"""Regras de extrato pela tela, e a Conciliação sem uma consulta por linha.

O QUE MOTIVOU (10/11/2026)

- A regra de extrato só existia por `manage.py regras_de_extrato`: para ensinar
  que "Boleto" de 1.234,56 é o condomínio era preciso entrar no servidor. A tela
  (Movimentação › Importação › Regras de extrato) cria, altera, desativa e
  exclui, e a Conciliação leva a ela com a linha já preenchida.
- A Conciliação com 100 linhas pendentes fazia 660 consultas, refeitas a cada
  clique: histórico, recorrências próximas e linhas repetidas eram lidos linha a
  linha. Agora são lidos uma vez, e o resultado tem de ser o mesmo.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from accounts.services import save_transfer_destination_accesses
from bank_statements import extrato
from bank_statements.classificacao import Contexto, sugerir_categoria
from bank_statements.models import (
    RULE_ACTION_CATEGORY,
    RULE_ACTION_IGNORE,
    RULE_ACTION_TRANSFER,
    RULE_SIGN_ANY,
    RULE_SIGN_DEBIT,
    BankStatementImport,
    BankStatementLine,
    StatementRule,
)
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import CATEGORY_KIND_TRANSFER, ENTRY_TYPE_EXPENSE, STATUS_REALIZED
from transactions import services
from transactions.models import CashFlowCategory

pytestmark = pytest.mark.django_db

URL = "/banking/rules/"


@pytest.fixture
def cenario(client):
    user = AppUser.objects.create_user(username="admin-regras", password="senha-segura")
    titular = AccountOwner.objects.create(name="Mariano")
    UserOwnerAccess.objects.create(
        user=user, owner=titular, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    c6 = FinancialInstitution.objects.create(institution_name="C6", institution_type="Banco")
    conta = FinancialAccount.objects.create(
        owner=titular, institution=c6, account_name="Conta 02", initial_balance_date=date(2026, 1, 1)
    )
    caixinha = FinancialAccount.objects.create(
        owner=titular, institution=c6, account_name="Caixinha", account_kind="aplicacao",
        initial_balance_date=date(2026, 1, 1),
    )
    save_transfer_destination_accesses(user, {conta.id, caixinha.id})
    categorias = {
        "outros": CashFlowCategory.objects.create(category_name="Outros"),
        "casa": CashFlowCategory.objects.create(category_name="Casa"),
        "mercado": CashFlowCategory.objects.create(category_name="Supermercado"),
        "transferencia": CashFlowCategory.objects.create(
            category_name="Transferência Entre Contas", kind=CATEGORY_KIND_TRANSFER
        ),
    }
    client.force_login(user)
    return client, user, {"conta": conta, "caixinha": caixinha, "c6": c6}, categorias


def _linha(conta, descricao, valor, dia, n=0):
    lote, _ = BankStatementImport.objects.get_or_create(
        account=conta, source_filename="out.ofx", defaults={"row_count": 0}
    )
    return BankStatementLine.objects.create(
        import_batch=lote, account=conta, statement_date=dia, description=descricao,
        amount=Decimal(valor), line_hash=f"h{conta.id}-{n}-{descricao}-{dia}-{valor}",
    )


def _lancar(user, conta, categoria, descricao, valor, dia):
    return services.create_transaction_batch(
        services.TransactionRequest(
            account_id=conta.id, category_id=categoria.id, entry_type=ENTRY_TYPE_EXPENSE, description=descricao,
            entry_amount=Decimal(valor), installments=1, due_date=dia, status=STATUS_REALIZED,
            realized_date=dia, realized_amount=Decimal(valor),
        ),
        user=user,
    )[0]


def _regra(cat, **campos):
    dados = {
        "acao": "salvar", "name": "Boleto do condomínio", "pattern": "condominio edificio",
        "institution": "", "sign": RULE_SIGN_DEBIT, "action": RULE_ACTION_CATEGORY,
        "category": str(cat["casa"].id), "destination_account_name": "", "destination_institution": "",
        "active": "1",
    }
    dados.update(campos)
    return dados


# --- a tela ------------------------------------------------------------------


def test_tela_cria_a_regra_e_o_plano_do_extrato_passa_a_usa_la(cenario):
    client, user, contas, cat = cenario
    linha = _linha(contas["conta"], "PAGTO CONDOMÍNIO EDIFÍCIO SOL", "-812.40", date(2026, 10, 5))
    (antes,) = extrato.planejar(user, [linha])
    assert antes.sugestao.categoria == cat["outros"]

    assert client.get(URL).status_code == 200
    resposta = client.post(URL, _regra(cat), follow=True)

    regra = StatementRule.objects.get()
    assert (regra.name, regra.pattern, regra.sign, regra.category) == (
        "Boleto do condomínio", "condominio edificio", RULE_SIGN_DEBIT, cat["casa"],
    )
    html = resposta.content.decode()
    assert "Ela decide 1 linha pendente agora" in html
    assert "Boleto do condomínio" in html
    (depois,) = extrato.planejar(user, [linha])
    assert depois.acao == extrato.CRIA and depois.sugestao.categoria == cat["casa"] and depois.confiavel


def test_tela_altera_desativa_e_exclui(cenario):
    client, _, _, cat = cenario
    client.post(URL, _regra(cat))
    regra = StatementRule.objects.get()

    edicao = client.get(URL, {"editar": regra.id})
    assert edicao.context["editando"] == regra.id and edicao.context["formulario"]["pattern"] == regra.pattern
    client.post(URL, _regra(cat, regra_id=regra.id, action=RULE_ACTION_IGNORE, category=str(cat["casa"].id)))
    regra.refresh_from_db()
    # A categoria some de uma regra que deixou de categorizar.
    assert (regra.action, regra.category) == (RULE_ACTION_IGNORE, None)
    assert StatementRule.objects.count() == 1

    client.post(URL, {"acao": "alternar", "regra_id": regra.id})
    regra.refresh_from_db()
    assert regra.active is False

    client.post(URL, {"acao": "excluir", "regra_id": regra.id})
    assert not StatementRule.objects.exists()


def test_regra_de_transferencia_pela_tela_leva_a_linha_para_a_conta_do_titular(cenario):
    client, user, contas, cat = cenario
    client.post(URL, _regra(
        cat, name="Caixinha do C6", pattern="aplicacao caixinha", sign=RULE_SIGN_ANY, action=RULE_ACTION_TRANSFER,
        category="", destination_account_name="caixinha", institution=str(contas["c6"].id),
    ))
    linha = _linha(contas["conta"], "APLICACAO CAIXINHA", "-300.00", date(2026, 10, 6))

    (plano,) = extrato.planejar(user, [linha])

    assert plano.acao == extrato.TRANSFERENCIA_REGRA and plano.conta_destino == contas["caixinha"]


@pytest.mark.parametrize(
    ("campos", "erro"),
    [
        ({"pattern": "ab"}, "pelo menos 3"),
        ({"name": "  "}, "nome"),
        ({"category": ""}, "Escolha a categoria"),
        ({"action": RULE_ACTION_TRANSFER, "category": ""}, "conta de destino"),
        ({"action": RULE_ACTION_TRANSFER, "destination_account_name": "Conta que não existe"}, "Não há conta"),
        ({"action": "apagar-tudo"}, "inválida"),
    ],
)
def test_tela_recusa_regra_que_nunca_valeria_e_mantem_o_que_foi_digitado(cenario, campos, erro):
    client, _, _, cat = cenario

    resposta = client.post(URL, _regra(cat, **campos))

    assert not StatementRule.objects.exists()
    assert erro in resposta.content.decode()
    assert resposta.context["formulario"]["pattern"] == _regra(cat, **campos)["pattern"]


def test_categoria_de_transferencia_e_recusada_na_regra_de_categorizar(cenario):
    client, _, _, cat = cenario

    resposta = client.post(URL, _regra(cat, category=str(cat["transferencia"].id)))

    assert not StatementRule.objects.exists()
    assert "outra ponta" in resposta.content.decode()


def test_conciliacao_leva_a_tela_de_regras_com_a_linha_preenchida(cenario):
    client, _, contas, _ = cenario
    linha = _linha(contas["conta"], "TRANSF ENVIADA PIX", "-90.00", date(2026, 10, 7))

    assert f"{URL}?linha={linha.id}" in client.get(reverse("bank_statements:reconciliation_view")).content.decode()
    formulario = client.get(URL, {"linha": linha.id}).context["formulario"]

    assert formulario["pattern"] == "TRANSF ENVIADA PIX"
    assert formulario["institution"] == str(contas["c6"].id)
    assert formulario["sign"] == RULE_SIGN_DEBIT


# --- a Conciliação sem uma consulta por linha ---------------------------------


def _popular(user, contas, cat, linhas: int, a_partir_de: int = 0):
    for k in range(a_partir_de, a_partir_de + linhas):
        _linha(contas["conta"], f"LOJA {chr(65 + k % 20)}{chr(65 + k % 7)} CENTRO", f"-{200 + k}.37",
               date(2026, 10, 1 + k % 28), k)


def test_conciliacao_nao_faz_mais_consultas_quando_ha_mais_linhas(cenario):
    client, user, contas, cat = cenario
    for k in range(40):
        _lancar(user, contas["conta"], cat["mercado"], f"LOJA {chr(65 + k % 20)}{chr(65 + k % 7)} CENTRO",
                f"{10 + k}.00", date(2026, 9, 1 + k % 28))
    url = reverse("bank_statements:reconciliation_view")
    _popular(user, contas, cat, 10)
    client.get(url)
    with CaptureQueriesContext(connection) as com_dez:
        client.get(url)
    _popular(user, contas, cat, 90, a_partir_de=10)
    with CaptureQueriesContext(connection) as com_cem:
        resposta = client.get(url)

    assert len(resposta.context["lines"]) == 100
    # Era proporcional às linhas (660 consultas para 100). O que sobra por linha
    # só existe em caso raro (regra de transferência, par sem permissão).
    assert len(com_cem) <= len(com_dez) + 3, (len(com_dez), len(com_cem))
    assert len(com_cem) < 80


def test_classificar_com_contexto_da_a_mesma_resposta_que_linha_a_linha(cenario):
    _, user, contas, cat = cenario
    dia = date(2026, 9, 10)
    _lancar(user, contas["conta"], cat["mercado"], "MERCADO BOM 0123", "50.00", dia)
    _lancar(user, contas["conta"], cat["mercado"], "Mercado Bom", "70.00", dia)
    _lancar(user, contas["conta"], cat["casa"], "Mercado Bom", "90.00", dia)
    _lancar(user, contas["conta"], cat["outros"], "Padaria Central", "9.00", dia)
    contexto = Contexto()

    for descricao, banco in [
        ("MERCADO BOM 9999", ""), ("PADARIA CENTRAL", ""), ("LOJA NUNCA VISTA", ""), ("Boleto", ""),
        ("Casa - Conserto", ""), ("ALGO", "Supermercado"),
    ]:
        isolada = sugerir_categoria(descricao, banco, conta=contas["conta"], tipo=ENTRY_TYPE_EXPENSE)
        em_lote = sugerir_categoria(descricao, banco, conta=contas["conta"], tipo=ENTRY_TYPE_EXPENSE, contexto=contexto)
        assert isolada == em_lote, descricao
        assert isolada.categoria is not None
    assert sugerir_categoria("MERCADO BOM 9999", contexto=contexto).categoria == cat["mercado"]
