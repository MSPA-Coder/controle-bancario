"""Roteiro de fechamento (`fechamento`).

Sem banco: a dedução da fonte de cada conta e o formato tirado do nome do arquivo.
Com banco: o estado de cada conta no corte (extrato que falta, linha pendente,
fatura, aplicação que espera a conta de movimento, conta sem fonte), o próximo
passo, a coleta do myProfit (marcação a mercado, caixa em dólar, remessa que falta,
reaplicar sem duplicar), as possíveis duplicatas, o cliente do CRV e as telas.
"""
from __future__ import annotations

import io
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.test import Client

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from accounts.services import save_function_permissions
from bank_statements.models import (
    LINE_STATUS_NEW,
    LINE_STATUS_RECONCILED,
    BankStatementImport,
    BankStatementLine,
)
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import (
    ACCOUNT_KIND_CREDIT_CARD,
    ACCOUNT_KIND_INVESTMENT,
    ENTRY_TYPE_INCOME,
    STATUS_REALIZED,
)
from core.domain.identity import USER_TYPE_ADMINISTRATOR, USER_TYPE_USER
from fechamento import crv, duplicatas, fontes, myprofit, roteiro
from fechamento.models import (
    CLASSE_CAIXA_USD,
    CLASSE_TESOURO,
    FONTE_ARQUIVO,
    FONTE_FATURA,
    FONTE_MYPROFIT,
    FONTE_NENHUMA,
    FONTE_PRINT,
    FREQUENCIA_MENSAL,
    ColetaMyProfit,
    FonteDaConta,
    SaldoConferido,
)
from transactions import services
from transactions.models import CashFlowCategory, CashFlowEntry

HOJE = date(2026, 10, 20)
CORTE = date(2026, 10, 20)


# --- sem banco ---------------------------------------------------------------------

def _conta(nome="Conta 01", instituicao="C6", tipo="conta", moeda="BRL"):
    return SimpleNamespace(
        account_name=nome, institution=SimpleNamespace(institution_name=instituicao), account_kind=tipo,
        currency=moeda, is_credit_card=tipo == ACCOUNT_KIND_CREDIT_CARD,
    )


@pytest.mark.parametrize(
    ("conta", "arquivo", "saldo", "esperado"),
    [
        (_conta(tipo=ACCOUNT_KIND_CREDIT_CARD, instituicao="XP"), "fatura.csv", False, (FONTE_FATURA, "CSV fatura XP", "", "corte")),
        (_conta("Tesouro Direto", "XP", ACCOUNT_KIND_INVESTMENT), None, True, (FONTE_MYPROFIT, "Posição do myProfit", CLASSE_TESOURO, "mensal")),
        (_conta("CDB", "C6", ACCOUNT_KIND_INVESTMENT), None, True, (FONTE_PRINT, "Print do app", "", "mensal")),
        (_conta(), "extrato-outubro.OFX", False, (FONTE_ARQUIVO, "OFX C6", "", "corte")),
        (_conta("Conta 03", "Genial"), "extrato.pdf", False, (FONTE_ARQUIVO, "PDF Genial", "", "corte")),
        (_conta("Conta em dólar", "Avenue", moeda="USD"), None, False, (FONTE_MYPROFIT, "Posição do myProfit", CLASSE_CAIXA_USD, "corte")),
        (_conta("Conta em dólar", "Nomad", moeda="USD"), None, True, (FONTE_PRINT, "Print do app", "", "corte")),
        (_conta("Conta em dólar", "Revolut", moeda="USD"), None, False, (FONTE_NENHUMA, "", "", "corte")),
    ],
)
def test_deduz_a_fonte_do_que_o_cb_ja_sabe(conta, arquivo, saldo, esperado):
    fonte = fontes.deduzir(conta, ultimo_arquivo=arquivo, teve_saldo_informado=saldo)
    assert (fonte.fonte, fonte.formato, fonte.classe_myprofit, fonte.frequencia) == esperado
    assert fonte.cadastrada is False


def test_formato_desconhecido_fica_vazio():
    assert fontes.formato_do_arquivo("extrato.xlsx", "Itaú") == ""


# --- com banco ---------------------------------------------------------------------

def _importar(conta, nome, linhas):
    lote = BankStatementImport.objects.create(account=conta, source_filename=nome, row_count=len(linhas))
    for indice, (dia, status, descricao, valor) in enumerate(linhas):
        BankStatementLine.objects.create(
            import_batch=lote, account=conta, statement_date=dia, description=descricao,
            amount=Decimal(valor), line_hash=f"{nome}-{indice}", status=status,
        )
    return lote


def _lancar(user, conta, categoria, dia, valor, tipo=ENTRY_TYPE_INCOME, descricao="Movimento"):
    return services.create_transaction_batch(
        services.TransactionRequest(
            account_id=conta.id, category_id=categoria.id, entry_type=tipo, description=descricao,
            entry_amount=Decimal(valor), installments=1, due_date=dia, status=STATUS_REALIZED,
            realized_date=dia, realized_amount=Decimal(valor),
        ),
        user=user,
    )[0]


@pytest.fixture
def cenario(db, monkeypatch):
    monkeypatch.delenv("CRV_FECHAMENTO_URL", raising=False)
    user = AppUser.objects.create_user(username="fechamento", password="troca-esta-senha", user_type=USER_TYPE_ADMINISTRATOR)
    titular = AccountOwner.objects.create(name="Titular")
    UserOwnerAccess.objects.create(user=user, owner=titular)
    banco = FinancialInstitution.objects.create(institution_name="C6", institution_type="Banco")
    xp = FinancialInstitution.objects.create(institution_name="XP", institution_type="Corretora")
    avenue = FinancialInstitution.objects.create(institution_name="Avenue", institution_type="Corretora")
    revolut = FinancialInstitution.objects.create(institution_name="Revolut", institution_type="Corretora")
    inicio = date(2025, 12, 31)

    def conta(nome, instituicao=banco, **extra):
        return FinancialAccount.objects.create(owner=titular, institution=instituicao, account_name=nome, initial_balance_date=inicio, **extra)

    atrasada = conta("Atrasada")
    _importar(atrasada, "atrasada.ofx", [(date(2026, 9, 25), LINE_STATUS_RECONCILED, "PIX", "-10"), (date(2026, 10, 10), LINE_STATUS_RECONCILED, "PIX", "-20")])
    pendente = conta("Pendente")
    _importar(pendente, "pendente.ofx", [(date(2026, 10, 19), LINE_STATUS_NEW, "TED", "30")])
    em_dia = conta("Em dia")
    _importar(em_dia, "em-dia.pdf", [(date(2026, 10, 19), LINE_STATUS_RECONCILED, "TED", "30")])
    cdb = conta("CDB", account_kind=ACCOUNT_KIND_INVESTMENT, movement_account=atrasada, initial_balance=Decimal("500.00"))
    cartao = conta("Carbon", account_kind=ACCOUNT_KIND_CREDIT_CARD, card_closing_day=5, card_due_day=12)
    _importar(cartao, "fatura.csv", [(date(2026, 10, 3), LINE_STATUS_RECONCILED, "LOJA", "-40")])
    cartao_sem_fatura = conta("Black", instituicao=xp, account_kind=ACCOUNT_KIND_CREDIT_CARD, card_closing_day=15, card_due_day=22)
    revolut_usd = conta("Conta em dólar", instituicao=revolut, currency="USD")
    avenue_usd = conta("Conta em dólar", instituicao=avenue, currency="USD")
    tesouro = conta("Tesouro Direto", instituicao=xp, account_kind=ACCOUNT_KIND_INVESTMENT, initial_balance=Decimal("900.00"))
    categorias = {
        nome: CashFlowCategory.objects.create(category_name=nome)
        for nome in ("Rendimentos", "Operações em Bolsa", "Outros", "Impostos e Tributos", "Ajustes de Saldo")
    }
    _lancar(user, revolut_usd, categorias["Outros"], date(2026, 10, 2), "5")
    client = Client()
    client.force_login(user)
    return SimpleNamespace(**locals())


def _itens(rot):
    return {item.chave: item for item in rot.itens}


@pytest.mark.django_db
def test_cada_conta_aparece_com_o_que_falta_no_corte(cenario):
    c = cenario
    rot = roteiro.montar(c.user, CORTE, HOJE)
    itens = _itens(rot)
    assert rot.alvo == date(2026, 10, 19)  # o extrato de hoje ainda não existe

    atrasada = itens[f"conta-{c.atrasada.id}"]
    assert (atrasada.estado, atrasada.texto) == (roteiro.FALTA, "Falta 11/10 a 19/10")
    assert atrasada.acao == "Importar OFX C6"
    assert atrasada.barra[9] == "c" and atrasada.barra[10] == "g" and atrasada.barra[19] == ""
    assert itens[f"conta-{c.pendente.id}"].estado == roteiro.PENDENTE
    assert itens[f"conta-{c.em_dia.id}"].estado == roteiro.EM_DIA
    # Cartão: a fatura que fechou em 05/10 já entrou; a que fechou em 15/10, não.
    assert itens[f"conta-{c.cartao.id}"].estado == roteiro.EM_DIA
    black = itens[f"conta-{c.cartao_sem_fatura.id}"]
    assert (black.estado, black.texto) == (roteiro.FALTA, "Falta a fatura que fechou em 15/10")
    # CDB: conferido só no fim do mês, então no dia 20 o que vale é o saldo de 30/09.
    cdb = itens[f"conta-{c.cdb.id}"]
    assert (cdb.estado, cdb.texto) == (roteiro.FALTA, "Informar o saldo de 30/09")
    assert f"conta={c.cdb.id}&data=2026-09-30" in cdb.url
    # Revolut teve movimento e não tem fonte; Avenue em dólar espera a coleta.
    assert itens[f"conta-{c.revolut_usd.id}"].estado == roteiro.SEM_FONTE
    assert itens[f"conta-{c.avenue_usd.id}"].estado == roteiro.ESPERA
    assert itens["coleta-myprofit"].estado == roteiro.FALTA
    assert itens["crv"].estado == roteiro.ESPERA
    assert itens["fechar-mes"].estado == roteiro.FORA
    # O próximo passo é o primeiro "a fazer" na ordem do roteiro.
    assert rot.proximo.etapa == roteiro.ETAPA_EXTRATOS
    assert rot.proximo.a_fazer
    assert not rot.concluivel


@pytest.mark.django_db
def test_saldo_informado_tira_a_aplicacao_da_lista_ate_o_fim_do_mes(cenario):
    c = cenario
    SaldoConferido.objects.create(account=c.cdb, data=date(2026, 9, 30), valor=Decimal("500"), origem="print")
    item = _itens(roteiro.montar(c.user, CORTE, HOJE))[f"conta-{c.cdb.id}"]
    assert (item.estado, item.texto) == (roteiro.FORA, "Só no fim do mês")
    # No corte do último dia, o CDB pede o saldo de 31/10.
    fim = _itens(roteiro.montar(c.user, date(2026, 10, 31), date(2026, 11, 3)))[f"conta-{c.cdb.id}"]
    assert (fim.estado, fim.texto) == (roteiro.FALTA, "Informar o saldo de 31/10")
    # Com uma linha pendente na conta de movimento, ele espera a conciliação.
    _importar(c.atrasada, "novo.ofx", [(date(2026, 10, 12), LINE_STATUS_NEW, "TED", "5")])
    fim = _itens(roteiro.montar(c.user, date(2026, 10, 31), date(2026, 11, 3)))[f"conta-{c.cdb.id}"]
    assert fim.estado == roteiro.ESPERA


@pytest.mark.django_db
def test_fonte_cadastrada_vence_a_deduzida(cenario):
    c = cenario
    fontes.salvar(c.user, c.revolut_usd, {"fonte": FONTE_PRINT, "formato": "Print do app", "frequencia": "corte"})
    item = _itens(roteiro.montar(c.user, CORTE, HOJE))[f"conta-{c.revolut_usd.id}"]
    assert (item.estado, item.texto) == (roteiro.FALTA, "Informar o saldo de 20/10")
    with pytest.raises(ValueError, match="myProfit"):
        fontes.salvar(c.user, c.revolut_usd, {"fonte": FONTE_MYPROFIT, "frequencia": "corte"})
    with pytest.raises(ValueError, match="fatura"):
        fontes.salvar(c.user, c.cartao, {"fonte": FONTE_PRINT, "frequencia": "corte"})


@pytest.mark.django_db
def test_corte_concluido_so_com_tudo_em_dia(cenario):
    c = cenario
    with pytest.raises(ValueError, match="tudo em dia"):
        roteiro.concluir(c.user, roteiro.montar(c.user, CORTE, HOJE))


# --- possíveis duplicatas ------------------------------------------------------------

@pytest.mark.django_db
def test_mesma_transacao_com_outra_cara_vira_possivel_duplicata(cenario):
    c = cenario
    _importar(c.em_dia, "primeiro.ofx", [(date(2026, 10, 3), LINE_STATUS_RECONCILED, "PIX ENVIADO JOAO", "-150")])
    _importar(c.em_dia, "segundo.ofx", [
        (date(2026, 10, 4), LINE_STATUS_NEW, "PIX JOAO SILVA", "-150"),
        # No mesmo lote, duas linhas parecidas são dois movimentos do banco.
        (date(2026, 10, 4), LINE_STATUS_NEW, "PIX MARIA", "-150"),
    ])
    pares = duplicatas.possiveis(c.user, date(2026, 10, 1), date(2026, 10, 19))
    descricoes = {(par.a.description, par.b.description) for par in pares}
    assert ("PIX ENVIADO JOAO", "PIX JOAO SILVA") in descricoes
    assert all(par.a.import_batch_id != par.b.import_batch_id for par in pares)

    for par in pares:
        duplicatas.descartar(c.user, par.chave)
    duplicatas.descartar(c.user, pares[0].chave)  # repetir não quebra
    assert duplicatas.possiveis(c.user, date(2026, 10, 1), date(2026, 10, 19)) == []
    with pytest.raises(ValueError):
        duplicatas.descartar(c.user, "abc")


# --- coleta do myProfit --------------------------------------------------------------

def _pacote(**extra) -> bytes:
    dados = {
        "formato": "myprofit-coleta/1", "de": "2026-09-01", "ate": "2026-10-19",
        "posicoes": {
            # No passado o myProfit não publica o caixa em dólar: a linha não vem.
            "2026-09-30": [
                {"ticker": "Tesouro IPCA+ 2032", "corretora": "XP", "classe": "TREASURY", "quantidade": "4.32", "valor_brl": "1000.00", "valor_usd": "180"},
            ],
            "2026-10-19": [
                {"ticker": "Tesouro IPCA+ 2032", "corretora": "XP", "classe": "TREASURY", "quantidade": "4.32", "valor_brl": "1100.00", "valor_usd": "200"},
                {"ticker": "Conta corrente em dólar Avenue", "corretora": "Avenue", "classe": "CASH_USD", "quantidade": "10.00", "valor_brl": "50.20", "valor_usd": "10.00"},
                {"ticker": "5CYTYK9", "corretora": "Avenue", "classe": "FIXED_INCOME_USA", "quantidade": "2000", "valor_brl": "8988.41", "valor_usd": "1790.52"},
            ],
        },
        "cambio": [{"data": "2026-10-07", "numero": "Int.1", "corretora": "Avenue", "de": "BRL", "para": "USD", "valor_de": "3000", "valor_para": "583.71"}],
        "proventos": [{"ticker": "Aluguel", "tipo": "ALUGUEL", "corretora": "Avenue", "data_pagamento": "2026-10-10", "valor_usd": "2.00"}],
    }
    dados.update(extra)
    return json.dumps(dados).encode()


@pytest.mark.django_db
def test_pacote_invalido_e_recusado():
    with pytest.raises(myprofit.PacoteInvalidoError):
        myprofit.ler(b"")
    with pytest.raises(myprofit.PacoteInvalidoError, match="pacote"):
        myprofit.ler(b'{"formato": "outro"}')
    with pytest.raises(myprofit.PacoteInvalidoError, match="depois da data"):
        myprofit.ler(_pacote(posicoes={"2026-11-01": []}))


@pytest.mark.django_db
def test_coleta_marca_o_tesouro_e_espera_a_remessa_que_falta(cenario):
    c = cenario
    plano = myprofit.planejar(c.user, myprofit.ler(_pacote()))
    por_conta = {(linha.conta.id, linha.data): linha for linha in plano.linhas}

    # Tesouro só no fim do mês: 30/09 entra, 19/10 não.
    tesouro = por_conta[(c.tesouro.id, date(2026, 9, 30))]
    assert (tesouro.acao, tesouro.destino, tesouro.diferenca) == ("lancar", "marcacao", Decimal("100.00"))
    assert (c.tesouro.id, date(2026, 10, 19)) not in por_conta
    # Caixa em dólar: sem a linha em 30/09, a data não entra (não é saldo zero);
    # e a remessa de 07/10 não está no CB, então 19/10 espera.
    assert (c.avenue_usd.id, date(2026, 9, 30)) not in por_conta
    assert por_conta[(c.avenue_usd.id, date(2026, 10, 19))].acao == "pular"
    assert any("Remessa de 07/10/2026" in p for p in plano.pendencias)
    assert any("Renda fixa EUA na Avenue" in p for p in plano.pendencias)


@pytest.mark.django_db
def test_coleta_aplicada_separa_proventos_de_investimentos_e_nao_duplica(cenario):
    c = cenario
    _lancar(c.user, c.avenue_usd, c.categorias["Outros"], date(2026, 10, 7), "583.71", descricao="Avenue - Compra US$")
    pacote = myprofit.ler(_pacote())
    plano = myprofit.planejar(c.user, pacote)
    assert plano.remessas_conferidas == 1
    caixa = next(linha for linha in plano.linhas if linha.conta == c.avenue_usd and linha.data == date(2026, 10, 19))
    assert (caixa.acao, caixa.rendimento, caixa.diferenca) == ("lancar", Decimal("2.00"), Decimal("-573.71"))

    coleta = myprofit.aplicar(c.user, plano)
    assert coleta.ate == date(2026, 10, 19)
    lancados = CashFlowEntry.objects.filter(account=c.avenue_usd, description__startswith="Atualização de saldo")
    assert sorted((e.category.category_name, e.entry_type, e.entry_amount) for e in lancados) == [
        ("Operações em Bolsa", "despesa", Decimal("575.71")),
        ("Rendimentos", "receita", Decimal("2.00")),
    ]
    assert SaldoConferido.objects.get(account=c.avenue_usd, data=date(2026, 10, 19)).valor == Decimal("10.00")
    assert SaldoConferido.objects.get(account=c.tesouro, data=date(2026, 9, 30)).origem == "myprofit"

    # O mesmo pacote de novo: tudo já bate, nada novo é lançado.
    total = CashFlowEntry.objects.count()
    replano = myprofit.planejar(c.user, pacote)
    assert replano.ja_aplicada == coleta
    assert {linha.acao for linha in replano.linhas} == {"conferir"}
    myprofit.aplicar(c.user, replano)
    assert CashFlowEntry.objects.count() == total
    assert ColetaMyProfit.objects.count() == 1

    item = _itens(roteiro.montar(c.user, CORTE, HOJE))["coleta-myprofit"]
    assert (item.estado, item.texto) == (roteiro.EM_DIA, "Coletado até 19/10")


@pytest.mark.django_db
def test_varias_datas_na_mesma_conta_entram_em_sequencia(cenario):
    """A prévia de setembro já desconta o que agosto vai lançar, e a gravação
    não esbarra no saldo que agosto mudou."""
    c = cenario
    posicoes = {
        data: [{"ticker": "Tesouro IPCA+ 2032", "corretora": "XP", "classe": "TREASURY", "quantidade": "4.32", "valor_brl": valor}]
        for data, valor in (("2026-08-31", "950.00"), ("2026-09-30", "1000.00"))
    }
    plano = myprofit.planejar(c.user, myprofit.ler(_pacote(posicoes=posicoes)))
    tesouro = [linha for linha in plano.linhas if linha.conta == c.tesouro]
    assert [(linha.data, linha.acao, linha.diferenca) for linha in tesouro] == [
        (date(2026, 8, 31), "lancar", Decimal("50.00")),
        (date(2026, 9, 30), "lancar", Decimal("50.00")),
    ]
    myprofit.aplicar(c.user, plano)
    lancados = CashFlowEntry.objects.filter(account=c.tesouro, description__startswith="Atualização de saldo")
    assert sorted(e.entry_amount for e in lancados) == [Decimal("50.00"), Decimal("50.00")]
    assert SaldoConferido.objects.get(account=c.tesouro, data=date(2026, 9, 30)).valor == Decimal("1000.00")


@pytest.mark.django_db
def test_coleta_nao_mexe_em_mes_fechado(cenario):
    c = cenario
    services.close_month(c.tesouro, 2026, 9, None, c.user)
    plano = myprofit.planejar(c.user, myprofit.ler(_pacote()))
    linha = next(linha for linha in plano.linhas if linha.conta == c.tesouro)
    assert (linha.acao, linha.motivo) == ("pular", "mês fechado")


# --- CRV ------------------------------------------------------------------------------

class _Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_crv_sem_configuracao_nao_derruba_o_roteiro(monkeypatch):
    monkeypatch.delenv("CRV_FECHAMENTO_URL", raising=False)
    assert crv.status(CORTE).erro == "CRV não configurado neste ambiente."


def test_crv_responde_itens_validos_e_o_resto_e_descartado(monkeypatch):
    monkeypatch.setenv("CRV_FECHAMENTO_URL", "http://crv-api:5003/fechamento/status")
    monkeypatch.setenv("CRV_PUBLIC_URL", "https://renda.exemplo")
    monkeypatch.setattr(crv, "_token_configurado", lambda: "x" * 40)
    corpo = {"contrato": "crv-fechamento/1", "itens": [
        {"chave": "b3", "etapa": "myprofit", "titulo": "Negócios da B3", "estado": "em_dia", "texto": "Aplicados até 16/10", "url": "/executions/reconciliation"},
        {"chave": "x", "etapa": "outra", "titulo": "?", "estado": "em_dia", "texto": "?"},
        {"chave": "y", "etapa": "conferencias", "titulo": "Pregões", "estado": "inventado", "texto": "?"},
    ]}
    pedidos = []

    def abrir(pedido, timeout):
        pedidos.append(pedido)
        return _Resposta(json.dumps(corpo).encode())

    monkeypatch.setattr(crv.urllib.request, "urlopen", abrir)
    status = crv.status(CORTE)
    assert status.erro == ""
    assert [item["chave"] for item in status.itens] == ["b3"]
    assert status.itens[0]["url"] == "https://renda.exemplo/executions/reconciliation"
    assert pedidos[0].full_url.endswith("?ate=2026-10-20")
    assert pedidos[0].get_header("Authorization") == "Bearer " + "x" * 40

    monkeypatch.setattr(crv.urllib.request, "urlopen", lambda pedido, timeout: _Resposta(b'{"contrato": "outro"}'))
    assert "formato" in crv.status(CORTE).erro


# --- telas ------------------------------------------------------------------------------

@pytest.mark.django_db
def test_telas_exigem_login_e_permissao(cenario):
    anonimo = Client()
    assert anonimo.get("/banking/closing/").status_code == 302
    comum = AppUser.objects.create_user(username="sem-permissao", password="troca-esta-senha", user_type=USER_TYPE_USER)
    save_function_permissions(comum, set())
    cliente = Client()
    cliente.force_login(comum)
    assert cliente.get("/banking/closing/").status_code == 302
    assert cliente.post(f"/banking/closing/sources/{cenario.revolut_usd.id}/", {"fonte": FONTE_PRINT}).status_code == 302
    assert not FonteDaConta.objects.exists()


@pytest.mark.django_db
def test_painel_fontes_e_cortes_respondem(cenario):
    c = cenario.client
    painel = c.get("/banking/closing/?corte=2026-10-20")
    assert painel.status_code == 200
    texto = painel.content.decode()
    assert "Próximo passo" in texto and "Coleta do myProfit" in texto
    assert c.get("/banking/closing/?corte=lixo&ver=tudo").status_code == 200
    assert c.get("/banking/closing/sources/").status_code == 200
    assert c.get("/banking/closing/cuts/").status_code == 200

    resposta = c.post(f"/banking/closing/sources/{cenario.revolut_usd.id}/", {"fonte": FONTE_PRINT, "frequencia": FREQUENCIA_MENSAL, "formato": "Print"})
    assert resposta.status_code == 302
    assert FonteDaConta.objects.get(account=cenario.revolut_usd).frequencia == FREQUENCIA_MENSAL


@pytest.mark.django_db
def test_coleta_pela_tela_mostra_a_previa_e_grava(cenario):
    c = cenario.client
    arquivo = io.BytesIO(_pacote())
    arquivo.name = "coleta.json"
    assert c.post("/banking/closing/myprofit/", {"acao": "previa", "corte": "2026-10-20", "pacote": arquivo}).status_code == 302
    painel = c.get("/banking/closing/?corte=2026-10-20").content.decode()
    assert "Lança como marcação a mercado" in painel
    assert c.post("/banking/closing/myprofit/", {"acao": "gravar", "corte": "2026-10-20"}).status_code == 302
    assert ColetaMyProfit.objects.count() == 1
    # Sem prévia na sessão, gravar não faz nada.
    c.post("/banking/closing/myprofit/", {"acao": "gravar", "corte": "2026-10-20"})
    assert ColetaMyProfit.objects.count() == 1
