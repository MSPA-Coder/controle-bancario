"""Saldos anteriores à data-base são indisponíveis, sem totais parciais."""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from bank_statements import painel_de_extratos, queries, saldo
from bank_statements.models import BankStatementImport
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import (
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_REALIZED,
    VIEW_REALIZED,
)
from core.domain.identity import USER_TYPE_ADMINISTRATOR
from core.templatetags.money_filters import money_signed
from reports import services
from transactions.models import CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def saldos():
    owner = AccountOwner.objects.create(name="Titular data-base")
    bank = FinancialInstitution.objects.create(institution_name="Banco data-base")
    category = CashFlowCategory.objects.create(category_name="Movimento data-base")
    first = FinancialAccount.objects.create(
        owner=owner, institution=bank, account_name="Conta A",
        initial_balance=Decimal("100.00"), initial_balance_date=date(2026, 10, 10),
    )
    second = FinancialAccount.objects.create(
        owner=owner, institution=bank, account_name="Conta B",
        initial_balance=Decimal("50.00"), initial_balance_date=date(2026, 10, 20),
    )
    for account, day, entry_type, amount in (
        (first, 5, ENTRY_TYPE_EXPENSE, "5.00"),
        (first, 15, ENTRY_TYPE_INCOME, "20.00"),
        (second, 12, ENTRY_TYPE_EXPENSE, "3.00"),
        (second, 25, ENTRY_TYPE_INCOME, "5.00"),
    ):
        CashFlowEntry.objects.create(
            account=account, category=category, entry_type=entry_type,
            description="Movimento sintético", entry_amount=Decimal(amount),
            due_date=date(2026, 10, day), realized_date=date(2026, 10, day),
            realized_amount=Decimal(amount), status=STATUS_REALIZED,
        )
    return first, second


def test_disponibilidade_tem_limite_inclusivo_na_data_do_saldo(saldos):
    first, second = saldos

    assert services.balance_available_by_account([first.id], date(2026, 10, 9)) == {first.id: False}
    assert services.balance_available_by_account([first.id], date(2026, 10, 10)) == {first.id: True}
    assert services.balance_available_by_account([second.id], date(2026, 10, 19)) == {second.id: False}
    assert services.balance_available_by_account([second.id], date(2026, 10, 20)) == {second.id: True}


def test_template_de_saldo_indisponivel_nao_formata_zero():
    assert money_signed(None) == "Indisponível"


def test_posicao_oculta_abertura_e_nao_soma_parcialmente(saldos):
    first, second = saldos
    rows = services.account_cash_report_rows(
        [first.id, second.id], date(2026, 10, 1), date(2026, 10, 1), VIEW_REALIZED
    )
    by_id = {row.account_id: row for row in rows}

    assert by_id[first.id].start_balance is None
    assert by_id[second.id].start_balance is None
    assert by_id[first.id].end_balance == Decimal("115.00")
    assert by_id[second.id].end_balance == Decimal("52.00")
    assert services.available_total(row.start_balance for row in rows) is None
    assert services.available_total(row.end_balance for row in rows) == Decimal("167.00")


def test_projecao_mascara_mes_anterior_e_preserva_saldo_apos_data_base(saldos):
    first, second = saldos
    rows = services.projection_months_between(
        [first.id, second.id], date(2026, 9, 1), date(2026, 11, 1), VIEW_REALIZED
    )

    assert rows[0]["saldo_inicial"] is None
    assert rows[0]["saldo"] is None
    assert rows[1]["saldo_inicial"] is None
    assert rows[1]["saldo"] == Decimal("167.00")
    assert rows[2]["saldo_inicial"] == Decimal("167.00")
    assert rows[2]["saldo"] == Decimal("167.00")


def test_movimentos_futuros_nao_apresentam_abertura_ou_minimo_parciais(saldos):
    first, second = saldos
    report = services.upcoming_movements_report(
        [first.id, second.id], date(2026, 10, 1), date(2026, 10, 31), VIEW_REALIZED
    )
    rows = {row.account_id: row for row in report.account_rows}

    assert rows[first.id].start_balance is None
    assert rows[second.id].start_balance is None
    assert rows[first.id].minimum_balance is None
    assert rows[second.id].minimum_balance is None
    assert rows[first.id].end_balance == Decimal("115.00")
    assert rows[second.id].end_balance == Decimal("52.00")
    assert all(
        line.balance_after is None
        for line in report.movement_lines
        if line.movement_date < (first.initial_balance_date if line.account_id == first.id else second.initial_balance_date)
    )
    assert all(
        line.balance_after is not None
        for line in report.movement_lines
        if line.movement_date >= (first.initial_balance_date if line.account_id == first.id else second.initial_balance_date)
    )
    assert report.summary.start_balance is None
    assert report.summary.minimum_balance is None
    assert report.summary.end_balance == Decimal("167.00")


def test_resumo_de_movimentos_considera_conta_sem_movimento_no_escopo(saldos):
    first, _ = saldos
    category = CashFlowEntry.objects.filter(account=first).first().category
    known = FinancialAccount.objects.create(
        owner=first.owner, institution=first.institution, account_name="Conta com movimento",
        initial_balance=Decimal("100.00"), initial_balance_date=date(2026, 9, 1),
    )
    future = FinancialAccount.objects.create(
        owner=first.owner, institution=first.institution, account_name="Conta sem movimento",
        initial_balance=Decimal("500.00"), initial_balance_date=date(2026, 11, 1),
    )
    CashFlowEntry.objects.create(
        account=known, category=category, entry_type=ENTRY_TYPE_EXPENSE,
        description="Movimento sintético", entry_amount=Decimal("10.00"),
        due_date=date(2026, 10, 15), realized_date=date(2026, 10, 15),
        realized_amount=Decimal("10.00"), status=STATUS_REALIZED,
    )

    report = services.upcoming_movements_report(
        [known.id, future.id], date(2026, 10, 1), date(2026, 10, 31), VIEW_REALIZED
    )
    only_future = services.upcoming_movements_report(
        [future.id], date(2026, 10, 1), date(2026, 10, 31), VIEW_REALIZED
    )

    # A tabela continua mostrando somente contas com movimento; o total resume
    # o escopo inteiro e fica indisponível se uma conta não tem base válida.
    assert [row.account_id for row in report.account_rows] == [known.id]
    assert report.account_rows[0].end_balance == Decimal("90.00")
    assert report.summary.start_balance is None
    assert report.summary.end_balance is None
    assert report.summary.minimum_balance is None
    assert only_future.account_rows == []
    assert only_future.summary.start_balance is None
    assert only_future.summary.end_balance is None
    assert only_future.summary.minimum_balance is None


def test_resumo_http_mostra_indisponivel_para_conta_sem_movimentos(saldos):
    first, _ = saldos
    user = AppUser.objects.create_user(
        username="data-base-resumo-http", password="local-test", user_type=USER_TYPE_ADMINISTRATOR
    )
    UserOwnerAccess.objects.create(user=user, owner=first.owner, can_view=True)
    future = FinancialAccount.objects.create(
        owner=first.owner, institution=first.institution, account_name="Conta futura sem movimento",
        initial_balance=Decimal("500.00"), initial_balance_date=date(2026, 11, 1),
    )
    client = Client()
    client.force_login(user)

    response = client.get(
        "/reports/upcoming-movements/",
        {
            "start_date": "2026-10-01", "end_date": "2026-10-31", "mode": VIEW_REALIZED,
            "account_id": future.id,
        },
    )

    html = response.content.decode()
    assert response.status_code == 200
    assert "Nenhuma conta com lançamentos no período." in html
    assert html.count("Indisponível") >= 4


def test_extrato_e_painel_mostram_saldo_indisponivel_antes_da_data_base(saldos):
    first, _ = saldos
    user = AppUser.objects.create_user(username="data-base-leitura", password="local-test")
    UserOwnerAccess.objects.create(user=user, owner=first.owner, can_view=True)
    lote = BankStatementImport.objects.create(
        account=first, source_filename="sintetico.ofx", row_count=0,
        statement_balance=Decimal("95.00"), statement_balance_date=date(2026, 10, 9),
    )

    conferencia = queries.conferencia_de_saldo(lote)
    painel = next(p for p in painel_de_extratos.paineis(user, hoje=date(2026, 10, 9)) if p.conta.id == first.id)

    assert conferencia.saldo_no_cb is None
    assert conferencia.diferenca is None
    assert conferencia.bate is None
    assert painel.saldo is None
    assert painel.extratos[0].conferencia.saldo_no_cb is None


def test_atualizacao_pre_data_base_falha_fechada_sem_registro_ou_lancamento(saldos):
    first, _ = saldos
    user = AppUser.objects.create_user(username="data-base-ajuste", password="local-test")
    UserOwnerAccess.objects.create(user=user, owner=first.owner, can_view=True, can_create=True)

    previa = saldo.previa(user, account_id=first.id, data=date(2026, 10, 9), saldo_informado="120.00")
    assert previa.saldo_no_cb is None
    assert previa.diferenca is None
    assert previa.tipo is None
    assert previa.destinos == []

    with pytest.raises(ValueError, match="indisponível"):
        saldo.confirmar(user, account_id=first.id, data=previa.data, saldo_informado="120.00")
    with pytest.raises(ValueError, match="indisponível"):
        saldo.aplicar(
            user, account_id=first.id, data=previa.data, saldo_informado="120.00",
            diferenca_esperada="20.00", destino=saldo.DESTINO_RENDIMENTOS,
        )

    assert not CashFlowEntry.objects.filter(account=first).exclude(description="Movimento sintético").exists()
    from fechamento.models import SaldoConferido
    assert not SaldoConferido.objects.filter(account=first, data=previa.data).exists()


def test_data_base_permite_confirmar_e_conferir_extrato_na_fronteira(saldos):
    first, _ = saldos
    user = AppUser.objects.create_user(username="data-base-limite", password="local-test")
    UserOwnerAccess.objects.create(user=user, owner=first.owner, can_view=True, can_create=True)
    lote = BankStatementImport.objects.create(
        account=first, source_filename="fronteira.ofx", row_count=0,
        statement_balance=Decimal("100.00"), statement_balance_date=first.initial_balance_date,
    )

    # Mantém a aritmética preexistente na fronteira: indisponibilidade mascara
    # somente datas anteriores, sem reescrever o histórico calculado.
    assert queries.conferencia_de_saldo(lote).saldo_no_cb == Decimal("95.00")
    assert saldo.previa(
        user, account_id=first.id, data=first.initial_balance_date, saldo_informado="100.00"
    ).saldo_no_cb == Decimal("95.00")
