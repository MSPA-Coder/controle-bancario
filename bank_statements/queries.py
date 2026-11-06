"""Leituras de importação e conferência; não criam lançamentos nem lotes."""

from collections.abc import Iterable
from datetime import date, timedelta

from banking.models import FinancialAccount
from banking.services import accessible_account_ids

from .contracts import ConferenciaDeSaldo
from .models import BankStatementImport


def conferencia_de_saldo(lote: BankStatementImport) -> ConferenciaDeSaldo | None:
    """Confere o saldo do arquivo com o do CB, ou `None` se o arquivo não traz saldo.

    É o saldo absoluto da conta até a data (lançamentos realizados), não o do
    período importado: por isso uma diferença aponta linha faltando ou sobrando
    em qualquer ponto do histórico, e a conferência vale mesmo com o extrato
    parcial."""
    if lote.statement_balance is None or lote.statement_balance_date is None:
        return None
    from core.domain.finance import VIEW_REALIZED
    from reports.services import balance_available_by_account, decimal_balances_before_by_account

    if not balance_available_by_account([lote.account_id], lote.statement_balance_date).get(lote.account_id, False):
        return ConferenciaDeSaldo(
            saldo_do_extrato=lote.statement_balance,
            data=lote.statement_balance_date,
            saldo_no_cb=None,
        )

    saldos = decimal_balances_before_by_account(
        [lote.account_id], lote.statement_balance_date + timedelta(days=1), VIEW_REALIZED
    )
    return ConferenciaDeSaldo(
        saldo_do_extrato=lote.statement_balance,
        data=lote.statement_balance_date,
        saldo_no_cb=saldos.get(lote.account_id),
    )


def statement_imports_for_user(user, limit: int = 20) -> Iterable[BankStatementImport]:
    """Últimos lotes de importação visíveis para `user`, com a conferência de
    saldo (`.conferencia`) em cada um que traz saldo."""
    account_ids = accessible_account_ids(user, "view")
    if not account_ids:
        return BankStatementImport.objects.none()
    lotes = list(
        BankStatementImport.objects.select_related("account__owner", "account__institution").filter(
            account_id__in=account_ids
        )[:limit]
    )
    conferir_saldos(lotes)
    return lotes


def conferir_saldos(lotes: Iterable[BankStatementImport]) -> None:
    """Uma leitura por data distinta, reunindo as contas sem misturar moedas.

    O mesmo saldo pode conferir vários arquivos da mesma conta/data. Não há
    cache entre requisições: uma conciliação nova já aparece na próxima leitura.
    """
    from core.domain.finance import VIEW_REALIZED
    from reports.services import decimal_balances_before_by_account

    lotes = list(lotes)
    contas_por_data: dict[date, set[int]] = {}
    for lote in lotes:
        if lote.statement_balance is not None and lote.statement_balance_date is not None:
            contas_por_data.setdefault(lote.statement_balance_date, set()).add(lote.account_id)
    anchors = dict(
        FinancialAccount.objects.filter(id__in={account_id for ids in contas_por_data.values() for account_id in ids})
        .values_list("id", "initial_balance_date")
    )
    saldos_por_data = {}
    for dia, contas in contas_por_data.items():
        valid_ids = sorted(
            account_id for account_id in contas
            if anchors.get(account_id) is not None and anchors[account_id] <= dia
        )
        saldos_por_data[dia] = decimal_balances_before_by_account(
            valid_ids, dia + timedelta(days=1), VIEW_REALIZED
        ) if valid_ids else {}
    for lote in lotes:
        lote.conferencia = (
            ConferenciaDeSaldo(
                saldo_do_extrato=lote.statement_balance,
                data=lote.statement_balance_date,
                saldo_no_cb=saldos_por_data[lote.statement_balance_date].get(lote.account_id),
            )
            if lote.statement_balance is not None and lote.statement_balance_date is not None
            else None
        )
