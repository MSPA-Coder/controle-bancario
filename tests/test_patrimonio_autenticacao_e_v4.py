"""A autenticação das rotas de patrimônio e o contrato v4.

ESTE ARQUIVO PROTEGE UM CONTRATO, NÃO UMA TELA

O que sai destas rotas é lido por outro deployable, escrito em outro momento,
por alguém que não vai ler este código. Contrato quebrado não dá erro: dá número
errado do outro lado.

E as rotas carregam o saldo de todas as contas: os testes de autenticação são
sobre isso, não sobre formalidade. Os contratos v1 a v3 (resumo, fluxos,
atividades, categorias e metadata) foram retirados em 03/10/2026. A projeção
(`/patrimonio/v3/projection`) fica e usa o MESMO token do v4
(`PATRIMONIO_INTEGRATION_TOKEN`), então é por ela que os testes de configuração
do segredo passam. O corpo da projeção é coberto em `test_projecao_patrimonial.py`.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from accounts.models import AccountOwner
from banking.models import FinancialAccount, FinancialInstitution
from core import patrimonio
from core.domain.finance import (
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_PROJECTED,
    STATUS_REALIZED,
)
from transactions.models import CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db

TOKEN = "token-de-teste-com-mais-de-trinta-e-dois-caracteres"
TOKEN_V4 = "token-de-integracao-v4-com-mais-de-trinta-e-dois-caracteres"
TOKEN_V4_ROTACIONADO = "novo-token-de-integracao-v4-apos-rotacao-segura"
ROTA = "/patrimonio/v3/projection"


@pytest.fixture
def contas():
    owner = AccountOwner.objects.create(name="Mariano")
    banco = FinancialInstitution.objects.create(institution_name="C6", institution_type="Banco")
    corretora = FinancialInstitution.objects.create(
        institution_name="Avenue", institution_type="Corretora"
    )
    em_reais = FinancialAccount.objects.create(
        owner=owner, institution=banco, account_name="Conta corrente",
        initial_balance=Decimal("100.00"), currency="BRL",
        initial_balance_date=date(2025, 12, 31),
    )
    em_dolar = FinancialAccount.objects.create(
        owner=owner, institution=corretora, account_name="Conta em dólar",
        initial_balance=Decimal("1250.00"), currency="USD",
        initial_balance_date=date(2025, 12, 31),
    )
    categoria = CashFlowCategory.objects.create(category_name="Salário")
    CashFlowEntry.objects.create(
        account=em_reais, category=categoria, entry_type=ENTRY_TYPE_INCOME,
        description="Salário", entry_amount=Decimal("900.00"),
        due_date=date(2026, 1, 10), realized_date=date(2026, 1, 10),
        realized_amount=Decimal("900.00"), status=STATUS_REALIZED,
    )
    CashFlowEntry.objects.create(
        account=em_reais, category=categoria, entry_type=ENTRY_TYPE_EXPENSE,
        description="Conta de luz", entry_amount=Decimal("50.00"),
        due_date=date(2026, 2, 10), realized_date=date(2026, 2, 10),
        realized_amount=Decimal("50.00"), status=STATUS_REALIZED,
    )
    return {"em_reais": em_reais, "em_dolar": em_dolar}


@pytest.fixture
def com_token(monkeypatch, tmp_path):
    """Concede o token pela forma que vale em produção: arquivo montado.

    Sob o Compose, `REQUIRE_FILE_SECRETS=true` recusa a variável direta. Um
    teste que só exercitasse a variável passaria aqui e a rota responderia 503
    no servidor, que é o pior lugar para descobrir isso.
    """
    arquivo = tmp_path / "patrimonio_integration_token"
    arquivo.write_text(TOKEN, encoding="utf-8")
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_V4, raising=False)
    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", str(arquivo))
    return TOKEN


def pedir(token: str | None = TOKEN, **parametros):
    cabecalhos = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token is not None else {}
    return Client().get(ROTA, parametros, **cabecalhos)


def configurar_token_v4(monkeypatch, tmp_path, token: str = TOKEN_V4):
    arquivo = tmp_path / "patrimonio_integration_token"
    arquivo.write_text(token, encoding="utf-8")
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_V4, raising=False)
    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", str(arquivo))
    return token


def test_cursor_v4_usa_token_exclusivo_e_invalida_assinaturas_antigas(
    monkeypatch, tmp_path
):
    legado = tmp_path / "patrimonio_token"
    exclusivo = tmp_path / "patrimonio_integration_token"
    rotacionado = tmp_path / "patrimonio_integration_token_rotacionado"
    legado.write_text(TOKEN, encoding="utf-8")
    exclusivo.write_text(TOKEN_V4, encoding="utf-8")
    rotacionado.write_text(TOKEN_V4_ROTACIONADO, encoding="utf-8")
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_V4, raising=False)
    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", str(exclusivo))

    # O HMAC binário pode conter o ponto usado como separador. O parser deve
    # usar o tamanho fixo da assinatura, não procurar o último ponto.
    for position in range(200):
        cursor = patrimonio._cursor_v4(position)
        assert patrimonio._cursor_v4_ler(cursor) == position

    cursor_v4 = patrimonio._cursor_v4(41)
    assert patrimonio._cursor_v4_ler(cursor_v4) == 41

    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", str(rotacionado))
    with pytest.raises(ValueError, match="cursor inválido"):
        patrimonio._cursor_v4_ler(cursor_v4)

    # Simula um cursor emitido pela implementação anterior, assinada pelo
    # token legado. A chave exclusiva atual não deve aceitá-lo.
    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", str(legado))
    cursor_legado = patrimonio._cursor_v4(42)
    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", str(exclusivo))
    with pytest.raises(ValueError, match="cursor inválido"):
        patrimonio._cursor_v4_ler(cursor_legado)


# --- A chave é a permissão -------------------------------------------------


def test_sem_token_nao_ha_resposta(contas, com_token):
    resposta = pedir(token=None)

    assert resposta.status_code == 401
    assert "contas" not in resposta.json()


def test_token_errado_nao_ha_resposta(contas, com_token):
    resposta = pedir(token="token-errado-mas-do-mesmo-tamanho-que-o-certo")

    assert resposta.status_code == 401
    assert "contas" not in resposta.json()


def test_sem_segredo_configurado_a_rota_nao_atende(contas, monkeypatch):
    """"Não configurado" não é "não autorizado".

    Responder 401 aqui mandaria o operador procurar por horas um token errado
    que, na verdade, nunca foi concedido a este servidor.
    """
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_V4, raising=False)
    monkeypatch.delenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", raising=False)

    resposta = pedir()

    assert resposta.status_code == 503


def test_segredo_curto_demais_e_tratado_como_ausente(contas, monkeypatch, tmp_path):
    """Um token de oito letras não protege saldo de conta nenhuma."""
    arquivo = tmp_path / "patrimonio_integration_token"
    arquivo.write_text("curtinho", encoding="utf-8")
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_V4, raising=False)
    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", str(arquivo))

    resposta = pedir(token="curtinho")

    assert resposta.status_code == 503


def test_sob_o_compose_a_variavel_direta_nao_concede_o_token(contas, monkeypatch):
    """`REQUIRE_FILE_SECRETS=true` é o contrato do Compose, e vale aqui também.

    Sem esta trava, uma sobra de `PATRIMONIO_INTEGRATION_TOKEN` no ambiente do processo
    substituiria em silêncio o segredo montado como arquivo -- e ninguém
    descobriria qual dos dois está valendo.
    """
    monkeypatch.setenv("REQUIRE_FILE_SECRETS", "true")
    monkeypatch.setenv(patrimonio.NOME_DO_SEGREDO_V4, TOKEN)
    monkeypatch.delenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", raising=False)

    resposta = pedir()

    assert resposta.status_code == 503


def test_a_resposta_nao_pode_ser_guardada_por_intermediario(contas, com_token):
    resposta = pedir()

    assert resposta["Cache-Control"] == "no-store"


def test_a_rota_so_responde_a_get(contas, com_token):
    resposta = Client().post(ROTA, HTTP_AUTHORIZATION=f"Bearer {TOKEN}")

    assert resposta.status_code == 405


# --- O v4 tem token próprio ------------------------------------------------


def test_o_token_antigo_nao_concede_mais_nada(contas, monkeypatch, tmp_path):
    """`PATRIMONIO_TOKEN` foi retirado em 03/10/2026: nem configurado ele vale."""
    arquivo_antigo = tmp_path / "patrimonio_token"
    arquivo_antigo.write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv("PATRIMONIO_TOKEN_FILE", str(arquivo_antigo))
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_V4, raising=False)
    monkeypatch.delenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", raising=False)

    # Sem o token de integração, as duas rotas ficam fora do ar...
    assert pedir().status_code == 503
    assert Client().get("/patrimonio/v4/metadata", HTTP_AUTHORIZATION=f"Bearer {TOKEN}").status_code == 503

    # ...e, com ele configurado, o antigo é só um token errado.
    configurar_token_v4(monkeypatch, tmp_path)
    assert pedir().status_code == 401
    assert Client().get("/patrimonio/v4/metadata", HTTP_AUTHORIZATION=f"Bearer {TOKEN}").status_code == 401


@pytest.mark.django_db(transaction=True)
def test_v4_e_projecao_aceitam_o_mesmo_token_de_integracao(contas, monkeypatch, tmp_path):
    token_v4 = configurar_token_v4(monkeypatch, tmp_path)

    resposta_v4 = Client().get(
        "/patrimonio/v4/snapshot", HTTP_AUTHORIZATION=f"Bearer {token_v4}"
    )
    projecao = pedir(token=token_v4)

    assert resposta_v4.status_code == 200
    assert resposta_v4.json()["contrato"] == "patrimonio/v4"
    assert projecao.status_code == 200


# --- O vocabulário ---------------------------------------------------------


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("Mercado Pago", "mercado-pago"),
        ("mercado  pago", "mercado-pago"),
        ("Itaú", "itau"),
        ("Banco do Brasil", "banco-do-brasil"),
        ("C6", "c6"),
    ],
)
def test_identidade_normaliza_o_nome(nome, esperado):
    assert patrimonio.identidade(nome) == esperado


# --- O status efetivo ------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_v4_publica_o_status_efetivo_derivado_da_data_e_nao_do_gravado(
    contas, monkeypatch, tmp_path
):
    """O status gravado envelhece: em aberto com vencimento passado segue `a_vencer`
    até alguém gravar o lançamento. O contrato publica o que vale hoje, para que
    nenhum consumidor repita a conta (o FinancasMCP a repetia em SQL)."""
    hoje = timezone.localdate()
    categoria = CashFlowCategory.objects.create(category_name="Contas do mês")
    conta = contas["em_reais"]

    def lancar(descricao, dias, status, realizado=False):
        vencimento = hoje + timedelta(days=dias)
        return CashFlowEntry.objects.create(
            account=conta, category=categoria, entry_type=ENTRY_TYPE_EXPENSE,
            description=descricao, entry_amount=Decimal("10.00"), due_date=vencimento,
            status=status,
            realized_date=vencimento if realizado else None,
            realized_amount=Decimal("10.00") if realizado else None,
        )

    lancar("vencido que o banco ainda chama de a vencer", -1, STATUS_PROJECTED)
    lancar("vence hoje", 0, STATUS_PROJECTED)
    lancar("vence amanha", 1, STATUS_PROJECTED)
    lancar("vencido gravado como vencido", -5, patrimonio.STATUS_PENDING)
    lancar("gravado como vencido mas com prazo ainda por vir", 3, patrimonio.STATUS_PENDING)
    lancar("pago ha 30 dias", -30, STATUS_REALIZED, realizado=True)

    token_v4 = configurar_token_v4(monkeypatch, tmp_path)
    resposta = Client().get("/patrimonio/v4/snapshot", HTTP_AUTHORIZATION=f"Bearer {token_v4}")

    assert resposta.status_code == 200
    efetivo = {
        item["payload"]["description"]: (item["payload"]["status"], item["payload"]["effective_status"])
        for item in resposta.json()["items"]
        if item["resource"] == "cash_entry"
    }
    assert efetivo["vencido que o banco ainda chama de a vencer"] == (STATUS_PROJECTED, "vencidos")
    assert efetivo["vence hoje"] == (STATUS_PROJECTED, "a_vencer")
    assert efetivo["vence amanha"] == (STATUS_PROJECTED, "a_vencer")
    assert efetivo["vencido gravado como vencido"] == ("vencidos", "vencidos")
    assert efetivo["gravado como vencido mas com prazo ainda por vir"] == ("vencidos", "a_vencer")
    assert efetivo["pago ha 30 dias"] == (STATUS_REALIZED, "realizado")
    # Os lançamentos da fixture são realizados e continuam realizados.
    assert efetivo["Salário"] == (STATUS_REALIZED, "realizado")


@pytest.mark.django_db(transaction=True)
def test_v4_publica_ate_quando_o_extrato_da_conta_foi_importado(contas, monkeypatch, tmp_path):
    """A cobertura é o maior entre a última linha, o saldo do arquivo e o fim do
    período declarado; conta sem extrato não ganha o campo (nunca uma data inventada)."""
    from bank_statements.models import BankStatementImport, BankStatementLine

    conta = contas["em_reais"]
    lote = BankStatementImport.objects.create(
        account=conta, source_filename="setembro.pdf", statement_balance=Decimal("10.00"),
        statement_balance_date=date(2026, 9, 29),
    )
    BankStatementLine.objects.create(
        import_batch=lote, account=conta, statement_date=date(2026, 9, 26), description="Pix",
        amount=Decimal("5.00"), line_hash="cobertura-1",
    )
    # Mês parado: lote sem linha, só com o fim do período declarado.
    BankStatementImport.objects.create(account=conta, source_filename="outubro.ofx", statement_period_end=date(2026, 10, 31))

    assert patrimonio.coberturas_de_extrato([conta.id, contas["em_dolar"].id]) == {conta.id: date(2026, 10, 31)}

    token_v4 = configurar_token_v4(monkeypatch, tmp_path)
    resposta = Client().get("/patrimonio/v4/snapshot", HTTP_AUTHORIZATION=f"Bearer {token_v4}")

    assert resposta.status_code == 200
    contas_publicadas = {
        item["payload"]["name"]: item["payload"] for item in resposta.json()["items"] if item["resource"] == "account"
    }
    assert contas_publicadas["Conta corrente"]["statement_covered_until"] == "2026-10-31"
    assert "statement_covered_until" not in contas_publicadas["Conta em dólar"]


@pytest.mark.django_db
def test_v4_publica_a_carteira_de_cada_extrato_da_corretora(contas):
    """Uma entrada por data do saldo, em ordem; o extrato importado de novo vale pelo
    lote mais recente; mês sem ação sai com a carteira vazia (o extrato disse que não
    havia), e lote sem carteira não inventa uma."""
    from bank_statements.models import BankStatementImport

    conta = contas["em_dolar"]

    def lote(dia, carteira):
        BankStatementImport.objects.create(
            account=conta, source_filename=f"Stmt_{dia:%Y%m%d}.pdf", statement_balance=Decimal("1.00"),
            statement_balance_date=dia, statement_holdings=carteira,
        )

    lote(date(2026, 4, 30), [])
    lote(date(2026, 3, 31), [{"instrument": "CGC", "quantity": "3000"}])
    lote(date(2026, 3, 31), [{"instrument": "BRK.B", "quantity": "1.56365"}, {"instrument": "CGC", "quantity": "3367"}])
    lote(date(2026, 5, 31), None)

    assert patrimonio.carteiras_de_extrato([conta.id, contas["em_reais"].id]) == {
        conta.id: [
            {"date": "2026-03-31", "positions": [
                {"instrument": "BRK.B", "quantity": "1.56365"}, {"instrument": "CGC", "quantity": "3367"},
            ]},
            {"date": "2026-04-30", "positions": []},
        ]
    }


# --- O token do vínculo com o CRV -------------------------------------------

TOKEN_DO_VINCULO = "token-do-vinculo-cb-crv-com-mais-de-trinta-e-dois-caracteres"


def configurar_token_do_vinculo(monkeypatch, tmp_path, token: str = TOKEN_DO_VINCULO):
    arquivo = tmp_path / "crv_link_token"
    arquivo.write_text(token, encoding="utf-8")
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_DO_VINCULO, raising=False)
    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_DO_VINCULO}_FILE", str(arquivo))
    return token


def _snapshot_com(token: str):
    return Client().get("/patrimonio/v4/snapshot", HTTP_AUTHORIZATION=f"Bearer {token}")


@pytest.mark.django_db(transaction=True)
def test_token_do_vinculo_recebe_so_as_contas_de_corretora(contas, monkeypatch, tmp_path):
    """O CRV precisa do caixa das corretoras, e não do gasto da casa."""
    configurar_token_v4(monkeypatch, tmp_path)
    vinculo = configurar_token_do_vinculo(monkeypatch, tmp_path)
    CashFlowEntry.objects.create(
        account=contas["em_dolar"], category=CashFlowCategory.objects.get(category_name="Salário"),
        entry_type=ENTRY_TYPE_INCOME, description="Dividendo de CGC na Avenue", entry_amount=Decimal("3.00"),
        due_date=date(2026, 3, 2), realized_date=date(2026, 3, 2), realized_amount=Decimal("3.00"),
        status=STATUS_REALIZED,
    )

    corpo = _snapshot_com(vinculo).json()

    por_recurso = {}
    for item in corpo["items"]:
        por_recurso.setdefault(item["resource"], []).append(item["payload"])
    assert [conta["name"] for conta in por_recurso["account"]] == ["Conta em dólar"]
    assert [entry["description"] for entry in por_recurso["cash_entry"]] == ["Dividendo de CGC na Avenue"]
    assert [categoria["name"] for categoria in por_recurso["category"]] == ["Salário"]
    assert "transfer" not in por_recurso
    assert corpo["scope"] == {"institution_type": "Corretora", "resources": ["account", "category", "cash_entry"]}
    assert corpo["coverage"]["account"] == {"state": "partial", "count": 1}
    assert (corpo["coverage"]["cash_entry"]["state"], corpo["coverage"]["cash_entry"]["count"]) == ("partial", 1)
    assert corpo["coverage"]["transfer"]["state"] == "partial"
    assert corpo["capabilities"]["resources"]["transfer"] is False


@pytest.mark.django_db(transaction=True)
def test_token_de_integracao_continua_recebendo_a_foto_inteira(contas, monkeypatch, tmp_path):
    integracao = configurar_token_v4(monkeypatch, tmp_path)
    configurar_token_do_vinculo(monkeypatch, tmp_path)

    corpo = _snapshot_com(integracao).json()

    assert "scope" not in corpo
    assert corpo["coverage"]["account"] == {"state": "complete", "count": 2}
    assert len([item for item in corpo["items"] if item["resource"] == "cash_entry"]) == 2


@pytest.mark.django_db(transaction=True)
def test_token_do_vinculo_nao_abre_as_outras_rotas(contas, monkeypatch, tmp_path):
    configurar_token_v4(monkeypatch, tmp_path)
    vinculo = configurar_token_do_vinculo(monkeypatch, tmp_path)

    assert _snapshot_com(vinculo).status_code == 200
    for rota in ("/patrimonio/v4/metadata", "/patrimonio/v4/changes", ROTA):
        assert Client().get(rota, HTTP_AUTHORIZATION=f"Bearer {vinculo}").status_code == 401, rota
    assert _snapshot_com("outro-token-qualquer-com-mais-de-trinta-e-dois-chars").status_code == 401


@pytest.mark.django_db(transaction=True)
def test_dois_arquivos_com_o_mesmo_valor_valem_a_foto_inteira(contas, monkeypatch, tmp_path):
    """Recortar a foto do consolidador faria o patrimônio dele encolher sem aviso."""
    integracao = configurar_token_v4(monkeypatch, tmp_path)
    configurar_token_do_vinculo(monkeypatch, tmp_path, integracao)

    assert "scope" not in _snapshot_com(integracao).json()


def test_o_vinculo_usa_o_token_proprio_e_cai_no_de_integracao_sem_ele(monkeypatch, tmp_path):
    integracao = configurar_token_v4(monkeypatch, tmp_path)
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_DO_VINCULO, raising=False)
    monkeypatch.delenv(f"{patrimonio.NOME_DO_SEGREDO_DO_VINCULO}_FILE", raising=False)
    assert patrimonio.token_do_vinculo() == integracao

    vinculo = configurar_token_do_vinculo(monkeypatch, tmp_path)
    assert patrimonio.token_do_vinculo() == vinculo
