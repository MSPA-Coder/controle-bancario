"""Uma fonte declarada por conta: só ela lança diferença; outra origem é conferência.

O que fica fixado: o mesmo dia por duas origens acrescenta um registro (e não
sobrescreve o primeiro); a conta do myProfit só lança pela origem myProfit; o
saldo de outra origem entra como conferência e não lança nada; as origens que
discordam além da tolerância viram pendência no Roteiro de fechamento, e as que
concordam (ou diferem em centavos) não; trocar a fonte fica na auditoria.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from bank_statements import saldo
from banking.models import FinancialAccount, FinancialInstitution
from core.models import AuditLog
from core.services import AuditRequestContext
from fechamento import fontes, fontes_divergentes, roteiro
from fechamento.models import (
    CLASSE_TESOURO,
    FONTE_MYPROFIT,
    FONTE_PRINT,
    ORIGEM_MANUAL,
    ORIGEM_MYPROFIT,
    ORIGEM_PRINT,
    SaldoConferido,
)
from transactions.models import CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db

DIA = date(2026, 9, 30)
HOJE = date(2026, 10, 20)


@pytest.fixture
def cenario():
    user = AppUser.objects.create_user(username="operador-fonte-unica", password="senha-segura")
    titular = AccountOwner.objects.create(name="Titular")
    UserOwnerAccess.objects.create(
        user=user, owner=titular, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    banco = FinancialInstitution.objects.create(institution_name="XP", institution_type="Corretora")
    tesouro = FinancialAccount.objects.create(
        owner=titular, institution=banco, account_name="Tesouro Direto", account_kind="aplicacao",
        initial_balance=Decimal("1000.00"), initial_balance_date=date(2025, 12, 31),
    )
    cdb = FinancialAccount.objects.create(
        owner=titular, institution=banco, account_name="CDB", account_kind="aplicacao",
        initial_balance=Decimal("1000.00"), initial_balance_date=date(2025, 12, 31),
    )
    for nome in ("Rendimentos", "Ajustes de Saldo"):
        CashFlowCategory.objects.create(category_name=nome)
    # A dedução já diz: Tesouro = myProfit; o resto das aplicações = print.
    return user, tesouro, cdb


def test_a_conta_de_tesouro_tem_o_myprofit_como_fonte_deduzida(cenario):
    _, tesouro, cdb = cenario
    efetivas = fontes.fontes_das_contas([tesouro, cdb])
    assert efetivas[tesouro.id].fonte == FONTE_MYPROFIT
    assert efetivas[cdb.id].fonte == FONTE_PRINT


def test_conta_do_myprofit_nao_lanca_diferenca_por_origem_digitada(cenario):
    user, tesouro, _ = cenario
    with pytest.raises(ValueError, match="fonte desta conta é outra"):
        saldo.aplicar(
            user, account_id=tesouro.id, data=DIA, saldo_informado="1100,00", diferenca_esperada="100,00",
            destino=saldo.DESTINO_MARCACAO, origem=ORIGEM_MANUAL,
        )
    assert not CashFlowEntry.objects.filter(account=tesouro).exists()
    lancada = saldo.aplicar(
        user, account_id=tesouro.id, data=DIA, saldo_informado="1100,00", diferenca_esperada="100,00",
        destino=saldo.DESTINO_MARCACAO, origem=ORIGEM_MYPROFIT,
    )
    assert lancada.entry_amount == Decimal("100.00")


def test_conta_de_print_aceita_print_ou_digitado_e_recusa_myprofit(cenario):
    user, _, cdb = cenario
    for origem in (ORIGEM_PRINT, ORIGEM_MANUAL):
        previa = saldo.previa(user, account_id=cdb.id, data=DIA, saldo_informado="1000", origem=origem)
        assert previa.origem_vale
    previa = saldo.previa(user, account_id=cdb.id, data=DIA, saldo_informado="1000", origem=ORIGEM_MYPROFIT)
    assert not previa.origem_vale


def test_outra_origem_no_mesmo_dia_acrescenta_um_registro_e_nao_sobrescreve(cenario):
    user, tesouro, _ = cenario
    lancada = saldo.aplicar(
        user, account_id=tesouro.id, data=DIA, saldo_informado="1100,00", diferenca_esperada="100,00",
        destino=saldo.DESTINO_MARCACAO, origem=ORIGEM_MYPROFIT,
    )
    saldo.conferir(user, account_id=tesouro.id, data=DIA, saldo_informado="1090,00", origem=ORIGEM_MANUAL)
    registros = {r.origem: r for r in SaldoConferido.objects.filter(account=tesouro, data=DIA)}
    assert set(registros) == {ORIGEM_MYPROFIT, ORIGEM_MANUAL}
    # O primeiro continua com o valor e com o vínculo ao lançamento que fez.
    assert registros[ORIGEM_MYPROFIT].valor == Decimal("1100.00")
    assert registros[ORIGEM_MYPROFIT].lancamento_id == lancada.id
    assert registros[ORIGEM_MANUAL].valor == Decimal("1090.00")
    assert registros[ORIGEM_MANUAL].lancamento_id is None


def test_conferir_nao_lanca_nada(cenario):
    user, tesouro, _ = cenario
    saldo.conferir(user, account_id=tesouro.id, data=DIA, saldo_informado="5000,00", origem=ORIGEM_MANUAL)
    assert not CashFlowEntry.objects.filter(account=tesouro).exists()


def test_mesma_origem_substitui_e_nao_duplica(cenario):
    user, tesouro, _ = cenario
    saldo.conferir(user, account_id=tesouro.id, data=DIA, saldo_informado="1000,00", origem=ORIGEM_MANUAL)
    saldo.conferir(user, account_id=tesouro.id, data=DIA, saldo_informado="1001,00", origem=ORIGEM_MANUAL)
    assert SaldoConferido.objects.filter(account=tesouro, data=DIA).count() == 1
    assert SaldoConferido.objects.get(account=tesouro, data=DIA).valor == Decimal("1001.00")


@pytest.mark.parametrize(("segundo", "diverge"), [
    ("1100.00", False),   # igual
    ("1105.00", False),   # R$ 5: abaixo da tolerância fixa de R$ 10
    ("1500.00", True),    # R$ 400: bem acima
])
def test_origens_que_discordam_alem_da_tolerancia_sao_divergencia(cenario, segundo, diverge):
    user, tesouro, _ = cenario
    SaldoConferido.objects.create(account=tesouro, data=DIA, valor=Decimal("1100.00"), origem=ORIGEM_MYPROFIT)
    SaldoConferido.objects.create(account=tesouro, data=DIA, valor=Decimal(segundo), origem=ORIGEM_MANUAL)
    achadas = fontes_divergentes.divergentes(user, date(2026, 9, 1), HOJE)
    assert bool(achadas) is diverge
    if diverge:
        assert achadas[0].diferenca == Decimal(segundo) - Decimal("1100.00")


def test_tolerancia_cresce_com_o_saldo_para_nao_acusar_arredondamento():
    assert fontes_divergentes.tolerancia([Decimal("100.00"), Decimal("101.00")]) == Decimal("10.00")
    assert fontes_divergentes.tolerancia([Decimal("100000.00")]) == Decimal("200.00")


def test_um_so_registro_no_dia_nao_e_divergencia(cenario):
    user, tesouro, _ = cenario
    SaldoConferido.objects.create(account=tesouro, data=DIA, valor=Decimal("1100.00"), origem=ORIGEM_MYPROFIT)
    assert fontes_divergentes.divergentes(user, date(2026, 9, 1), HOJE) == []


def test_o_roteiro_mostra_a_divergencia_e_some_quando_nao_ha(cenario):
    user, tesouro, _ = cenario
    em_dia = {i.chave: i for e in roteiro.montar(user, HOJE, HOJE).etapas for i in e.itens}
    assert em_dia["fontes-divergentes"].estado == roteiro.EM_DIA
    SaldoConferido.objects.create(account=tesouro, data=DIA, valor=Decimal("1100.00"), origem=ORIGEM_MYPROFIT)
    SaldoConferido.objects.create(account=tesouro, data=DIA, valor=Decimal("1500.00"), origem=ORIGEM_MANUAL)
    pendente = {i.chave: i for e in roteiro.montar(user, HOJE, HOJE).etapas for i in e.itens}["fontes-divergentes"]
    assert pendente.estado == roteiro.PENDENTE
    assert "Tesouro Direto" in pendente.detalhe and "myProfit" in pendente.detalhe


def test_trocar_a_fonte_fica_na_auditoria_e_repetir_nao(cenario):
    user, tesouro, _ = cenario
    contexto = AuditRequestContext(user=user, client_ip=None, proxy_ip=None, request_id="r1")
    dados = {"fonte": FONTE_MYPROFIT, "frequencia": "mensal", "classe_myprofit": CLASSE_TESOURO, "corretora_myprofit": "XP"}
    # Já era myProfit por dedução, mas ainda sem cadastro: gravar o mesmo não muda a fonte.
    fontes.salvar(user, tesouro, dados, audit_context=contexto)
    assert not AuditLog.objects.filter(entity_name="account_source").exists()
    fontes.salvar(user, tesouro, {**dados, "fonte": FONTE_PRINT, "classe_myprofit": "", "corretora_myprofit": ""}, audit_context=contexto)
    registro = AuditLog.objects.get(entity_name="account_source")
    assert registro.old_values_json["fonte"] == FONTE_MYPROFIT
    assert registro.new_values_json["fonte"] == FONTE_PRINT
    fontes.salvar(user, tesouro, {**dados, "fonte": FONTE_PRINT, "classe_myprofit": "", "corretora_myprofit": ""}, audit_context=contexto)
    assert AuditLog.objects.filter(entity_name="account_source").count() == 1
