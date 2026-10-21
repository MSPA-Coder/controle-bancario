"""Variação de mercado: muda o saldo, não é receita nem despesa.

O que fica fixado: a categoria `valorizacao` existe (criada pela migração) e é
"interna" para o resultado; a projeção mensal a mostra numa coluna própria, com
sinal, fora de receita, despesa e créditos/débitos internos, e o saldo a
inclui; o contrato v4 a publica como `gerencial` com a marca `valuation`; a
reclassificação da marcação antiga só toca "Rendimentos" com o texto da
atualização de saldo, mantém valor e saldo, e reabre mês fechado só com
autorização.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from bank_statements import valorizacao
from banking.models import FinancialAccount, FinancialInstitution
from core import patrimonio
from core.domain.finance import (
    CATEGORY_KIND_MANAGERIAL,
    CATEGORY_KIND_VALUATION,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_REALIZED,
    VIEW_ALL,
)
from reports import services as reports_services
from transactions import services
from transactions.models import AccountMonthClose, CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db

MARCACAO = "Atualização de saldo: marcação a mercado (posição do myProfit)"


@pytest.fixture
def cenario():
    user = AppUser.objects.create_user(username="operador-valorizacao", password="senha-segura")
    owner = AccountOwner.objects.create(name="Titular")
    UserOwnerAccess.objects.create(
        user=user, owner=owner, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    banco = FinancialInstitution.objects.create(institution_name="XP", institution_type="Corretora")
    conta = FinancialAccount.objects.create(
        owner=owner, institution=banco, account_name="Tesouro Direto", account_kind="aplicacao",
        initial_balance=Decimal("1000.00"), initial_balance_date=date(2025, 12, 31),
    )
    rendimentos, _ = CashFlowCategory.objects.get_or_create(
        category_name="Rendimentos", defaults={"kind": CATEGORY_KIND_MANAGERIAL}
    )
    variacao = CashFlowCategory.objects.get(category_name="Variação de mercado")
    return user, conta, rendimentos, variacao


def _lancar(conta, categoria, tipo, valor, descricao, dia=date(2026, 9, 30)):
    return CashFlowEntry.objects.create(
        account=conta, category=categoria, entry_type=tipo, description=descricao,
        entry_amount=Decimal(valor), due_date=dia, status=STATUS_REALIZED,
        realized_date=dia, realized_amount=Decimal(valor),
    )


def test_a_migracao_cria_a_categoria_e_ela_nao_e_receita_nem_despesa(cenario):
    _, _, _, variacao = cenario
    assert variacao.kind == CATEGORY_KIND_VALUATION
    assert variacao.is_internal
    assert not variacao.requires_counterparty
    assert variacao.group is None or variacao.group.group_name == "Investimentos"


def test_a_projecao_mensal_tem_coluna_propria_com_sinal_e_o_saldo_a_inclui(cenario):
    _, conta, rendimentos, variacao = cenario
    _lancar(conta, rendimentos, ENTRY_TYPE_INCOME, "50.00", "Juros do CDB")
    _lancar(conta, variacao, ENTRY_TYPE_INCOME, "300.00", MARCACAO)
    _lancar(conta, variacao, ENTRY_TYPE_EXPENSE, "120.00", MARCACAO)

    mes = reports_services.projection_months_between(
        [conta.id], date(2026, 9, 1), date(2026, 9, 1), VIEW_ALL
    )[0]

    assert mes["valorizacao"] == Decimal("180.00")
    assert (mes["receita"], mes["despesa"], mes["geracao"]) == (Decimal("50.00"), Decimal("0.00"), Decimal("50.00"))
    assert (mes["rec_int"], mes["desp_int"]) == (Decimal("0.00"), Decimal("0.00"))
    # O saldo é o da conta: inicial + juros + variação líquida.
    assert mes["saldo"] == Decimal("1230.00")
    assert reports_services.projection_period_totals([mes])["valorizacao"] == Decimal("180.00")


def test_a_posicao_por_conta_separa_a_variacao_das_transferencias(cenario):
    _, conta, rendimentos, variacao = cenario
    _lancar(conta, rendimentos, ENTRY_TYPE_INCOME, "50.00", "Juros do CDB")
    _lancar(conta, variacao, ENTRY_TYPE_INCOME, "300.00", MARCACAO)
    _lancar(conta, variacao, ENTRY_TYPE_EXPENSE, "120.00", MARCACAO)

    linha = reports_services.account_cash_report_rows(
        [conta.id], date(2026, 9, 1), date(2026, 9, 1), VIEW_ALL
    )[0]

    assert (linha.cash_generation, linha.internal_transfers, linha.market_change) == (
        Decimal("50.00"), Decimal("0.00"), Decimal("180.00"),
    )
    assert linha.end_balance == Decimal("1230.00")


def test_o_planejamento_anual_tem_linha_propria_e_nao_a_mistura_com_transferencias(cenario):
    user, conta, rendimentos, variacao = cenario
    _lancar(conta, rendimentos, ENTRY_TYPE_INCOME, "50.00", "Juros do CDB")
    _lancar(conta, variacao, ENTRY_TYPE_INCOME, "300.00", MARCACAO)
    _lancar(conta, variacao, ENTRY_TYPE_EXPENSE, "120.00", MARCACAO)

    grade = reports_services.annual_planning_presentation(
        user, date(2026, 9, 1), view_mode=reports_services.VIEW_REALIZED
    )
    linhas = {linha["label"]: linha for linha in grade["summary_rows"]}

    setembro = next(i for i, mes in enumerate(grade["months"]) if mes["key"] == "2026-09")
    assert linhas["Variação de mercado"]["months"][setembro]["value"] == Decimal("180.00")
    assert linhas["Transferências internas"]["months"][setembro]["value"] == Decimal("0.00")
    assert linhas["Geração de caixa"]["months"][setembro]["value"] == Decimal("50.00")

    # Sem nenhuma variação no período, a linha nem aparece.
    sem = reports_services.annual_planning_presentation(
        user, date(2025, 1, 1), view_mode=reports_services.VIEW_REALIZED
    )
    assert "Variação de mercado" not in {linha["label"] for linha in sem["summary_rows"]}


def test_o_contrato_v4_publica_como_gerencial_e_marca_a_valorizacao(cenario):
    _, conta, rendimentos, variacao = cenario
    assert patrimonio._categoria_v4(variacao)["kind"] == "gerencial"
    assert patrimonio._categoria_v4(variacao)["valuation"] is True
    assert "valuation" not in patrimonio._categoria_v4(rendimentos)

    entrada = _lancar(conta, variacao, ENTRY_TYPE_INCOME, "10.00", MARCACAO)
    carregada = CashFlowEntry.objects.select_related("account", "category").get(id=entrada.id)
    assert patrimonio._lancamento_v4(carregada, date(2026, 10, 20))["category_kind"] == "gerencial"


def test_so_a_marcacao_em_rendimentos_e_reclassificada(cenario):
    user, conta, rendimentos, variacao = cenario
    marcacao = _lancar(conta, rendimentos, ENTRY_TYPE_EXPENSE, "40.00", MARCACAO)
    juros = _lancar(conta, rendimentos, ENTRY_TYPE_INCOME, "9.00", "Atualização de saldo: rendimentos")
    ja_certa = _lancar(conta, variacao, ENTRY_TYPE_INCOME, "5.00", MARCACAO)
    saldo_antes = reports_services.decimal_balance_before([conta.id], date(2026, 10, 1), VIEW_ALL)

    efeito = valorizacao.simular(user)
    assert [e.id for e in efeito.entradas] == [marcacao.id]
    assert valorizacao.aplicar(user) == 1

    marcacao.refresh_from_db()
    juros.refresh_from_db()
    ja_certa.refresh_from_db()
    assert marcacao.category == variacao
    assert (marcacao.entry_type, marcacao.entry_amount, marcacao.realized_date) == (
        ENTRY_TYPE_EXPENSE, Decimal("40.00"), date(2026, 9, 30),
    )
    assert juros.category == rendimentos and ja_certa.category == variacao
    assert reports_services.decimal_balance_before([conta.id], date(2026, 10, 1), VIEW_ALL) == saldo_antes
    # Rodar de novo não acha mais nada.
    assert valorizacao.simular(user).entradas == []
    assert valorizacao.aplicar(user) == 0


def test_mes_fechado_so_e_reaberto_com_autorizacao_e_fecha_de_novo_igual(cenario):
    user, conta, rendimentos, variacao = cenario
    entrada = _lancar(conta, rendimentos, ENTRY_TYPE_INCOME, "70.00", MARCACAO)
    services.close_month(conta, 2026, 9, None, user)

    assert len(valorizacao.simular(user).meses_fechados) == 1
    with pytest.raises(ValueError, match="meses fechados"):
        valorizacao.aplicar(user)
    entrada.refresh_from_db()
    assert entrada.category == rendimentos

    assert valorizacao.aplicar(user, autorizar_meses=True) == 1
    entrada.refresh_from_db()
    assert entrada.category == variacao
    fechamento = AccountMonthClose.objects.get(account=conta, year=2026, month=9, active=True)
    assert fechamento.closing_balance == Decimal("1070.00")


def test_o_comando_simula_por_padrao_e_so_grava_com_aplicar(cenario):
    user, conta, rendimentos, variacao = cenario
    entrada = _lancar(conta, rendimentos, ENTRY_TYPE_INCOME, "10.00", MARCACAO)

    saida = StringIO()
    call_command("reclassificar_valorizacao", "--usuario", user.username, stdout=saida)
    assert "Simulação: nada foi gravado" in saida.getvalue()
    entrada.refresh_from_db()
    assert entrada.category == rendimentos

    saida = StringIO()
    call_command("reclassificar_valorizacao", "--usuario", user.username, "--aplicar", stdout=saida)
    assert "1 lançamento(s) reclassificado(s)" in saida.getvalue()
    entrada.refresh_from_db()
    assert entrada.category == variacao
