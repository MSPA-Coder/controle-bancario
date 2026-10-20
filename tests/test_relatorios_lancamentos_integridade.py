"""Totais por moeda, limites operacionais e recusas antes de gravar caixa."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from test_extrato_integridade_postgres import entrada, recusar_no_banco
from test_gestao_persistida import cenario as cenario

from accounts.models import UserTransferDestinationAccess
from banking.models import FinancialAccount
from banking.services import MixedCurrencyError
from core.domain.finance import (
    CATEGORY_KIND_TRANSFER,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_REALIZED,
    VIEW_REALIZED,
)
from reports import services as relatorios
from transactions import services as t
from transactions.models import BankOperation, CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db


def requisicao(c):
    return t.TransactionRequest(account_id=c.conta.pk, category_id=c.categoria.pk,
                                entry_type=ENTRY_TYPE_EXPENSE, description="Teste de integridade",
                                entry_amount=Decimal("10"), installments=1, due_date=date(2026, 9, 10))


@pytest.mark.parametrize("campos", [
    {"entry_amount": Decimal("0")}, {"entry_amount": Decimal("-1")},
    {"entry_amount": Decimal("NaN")}, {"entry_amount": Decimal("Infinity")},
    {"installments": 10_000}, {"status": STATUS_REALIZED, "realized_date": None},
    {"status": STATUS_REALIZED, "realized_date": date(2026, 9, 10), "realized_amount": Decimal("0")},
])
def test_lancamento_invalido_nao_deixa_operacao_ou_parcelas(cenario, campos):
    with pytest.raises(ValueError):
        t.create_transaction_batch(replace(requisicao(cenario), **campos), user=cenario.admin)
    assert CashFlowEntry.objects.count() == BankOperation.objects.count() == 0


def test_falha_na_contraparte_desfaz_transferencia_e_operacao(cenario):
    from django.db import IntegrityError

    destino = FinancialAccount.objects.create(owner=cenario.dono, institution=cenario.conta.institution, account_name="Destino")
    UserTransferDestinationAccess.objects.create(user=cenario.admin, destination_account=destino)
    categoria = CashFlowCategory.objects.create(category_name="Transferência sintética", kind=CATEGORY_KIND_TRANSFER)
    pedido = replace(requisicao(cenario), category_id=categoria.pk, counterparty_account_id=destino.pk)
    with recusar_no_banco("cash_flow_entry", f"account_id <> {destino.pk}"), pytest.raises(IntegrityError):
        t.create_transaction_batch(pedido, user=cenario.admin)
    assert CashFlowEntry.objects.count() == BankOperation.objects.count() == 0
    assert len(t.create_transaction_batch(pedido, user=cenario.admin)) == 2


def test_relatorio_de_caixa_usa_valor_realizado_e_data_correta_por_conta(cenario):
    receita = entrada(cenario, valor="100", dia=date(2026, 8, 31), tipo=ENTRY_TYPE_INCOME)
    t.realize_transaction(receita, realized_date=date(2026, 9, 1), realized_amount=Decimal("90"), user=cenario.admin)
    despesa = entrada(cenario, valor="30", dia=date(2026, 9, 10))
    t.realize_transaction(despesa, realized_date=date(2026, 9, 11), realized_amount=Decimal("25"), user=cenario.admin)
    fora = entrada(cenario, valor="999", dia=date(2026, 10, 1))
    t.realize_transaction(fora, realized_date=date(2026, 10, 1), realized_amount=Decimal("999"), user=cenario.admin)
    usd = entrada(cenario, valor="7", conta=cenario.dolar)
    t.realize_transaction(usd, realized_date=date(2026, 9, 10), user=cenario.admin)
    linhas = relatorios.account_cash_report_rows([cenario.conta.pk, cenario.dolar.pk], date(2026, 9, 1), date(2026, 9, 1), VIEW_REALIZED)
    por_conta = {linha.account_id: linha for linha in linhas}
    assert por_conta[cenario.conta.pk].cash_generation == Decimal("65")
    assert por_conta[cenario.conta.pk].end_balance == Decimal("65")
    assert por_conta[cenario.dolar.pk].cash_generation == Decimal("-7")
    assert por_conta[cenario.dolar.pk].currency == "USD"


def test_relatorio_de_movimentos_nao_soma_moedas_diferentes(cenario):
    for conta in (cenario.conta, cenario.dolar):
        e = entrada(cenario, conta=conta)
        t.realize_transaction(e, realized_date=date(2026, 9, 10), user=cenario.admin)
    with pytest.raises(MixedCurrencyError):
        relatorios.upcoming_movements_report([cenario.conta.pk, cenario.dolar.pk], date(2026, 9, 1), date(2026, 9, 30), VIEW_REALIZED)


def test_relatorio_mostra_deficit_intermediario_mesmo_terminando_positivo(cenario):
    for dia, valor, tipo in [(10, "50", ENTRY_TYPE_EXPENSE), (20, "80", ENTRY_TYPE_INCOME)]:
        e = entrada(cenario, valor=valor, dia=date(2026, 9, dia), tipo=tipo)
        t.realize_transaction(e, realized_date=date(2026, 9, dia), user=cenario.admin)
    r = relatorios.upcoming_movements_report([cenario.conta.pk], date(2026, 9, 1), date(2026, 9, 30), VIEW_REALIZED)
    assert r.summary.end_balance == Decimal("30")
    assert r.summary.minimum_balance == Decimal("-50")
    assert r.summary.minimum_balance_date == date(2026, 9, 10)
    assert r.summary.action_amount == Decimal("50")


@pytest.mark.parametrize("limite", ["contas", "lancamentos"])
def test_teto_do_relatorio_recusa_em_vez_de_truncar_dinheiro(cenario, settings, limite):
    for i in (10, 11):
        e = entrada(cenario, dia=date(2026, 9, i))
        t.realize_transaction(e, realized_date=date(2026, 9, i), user=cenario.admin)
    ids = [cenario.conta.pk]
    if limite == "contas":
        settings.REPORT_MAX_ACCOUNTS = 1
        ids.append(cenario.dolar.pk)
    else:
        settings.REPORT_MAX_ENTRIES = 1
    with pytest.raises(relatorios.ReportSizeLimitError):
        relatorios.upcoming_movements_report(ids, date(2026, 9, 1), date(2026, 9, 30), VIEW_REALIZED)


def test_lancamento_parcelado_que_atravessa_mes_fechado_reverte_lote_inteiro(cenario):
    t.close_month(cenario.conta, 2026, 10, None, cenario.admin)
    with pytest.raises(ValueError):
        t.create_transaction_batch(replace(requisicao(cenario), installments=3), user=cenario.admin)
    assert CashFlowEntry.objects.count() == BankOperation.objects.count() == 0
