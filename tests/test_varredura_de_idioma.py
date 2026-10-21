"""Varredura de português vazando na interface em inglês.

Risco que protege: texto que ninguém marcou (ou mensagem montada por concatenação) continua em
português para quem escolheu inglês, e nenhum teste de texto pega isso porque o português é
exatamente o que os outros testes esperam. Aqui o usuário usa `en`, os dados são todos em
ASCII e inglês; qualquer letra acentuada de português ou palavra de interface em português que
sobrar na tela é, por construção, texto da interface que escapou do catálogo.

Só olha o que a pessoa lê: texto da página e os atributos que a tela exibe (`title`,
`aria-label`, `placeholder`, `alt`, `data-sa-*`). Classes, ids e URLs ficam de fora.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from html.parser import HTMLParser

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import AccountOwner
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import (
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_PENDING,
    STATUS_PROJECTED,
    STATUS_REALIZED,
)
from core.models import AuditLog
from transactions.models import CashFlowCategory, CashFlowCategoryGroup
from transactions.services import TransactionRequest, create_transaction_batch

pytestmark = pytest.mark.django_db

ACENTOS = re.compile("[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]")
# Palavras de interface em português sem acento que nunca aparecem em inglês nem nos dados do teste.
PALAVRAS_PT = re.compile(
    r"\b(Salvar|Cancelar|Excluir|Editar|Voltar|Fechar|Filtrar|Limpar|Todos|Todas|Nenhum|Nenhuma|"
    r"Conta|Contas|Saldo|Receita|Receitas|Despesa|Despesas|Titular|Titulares|Senha|Entrar|Sair|"
    r"Lancamento|Lancamentos|Importar|Conciliar|Periodo|Mes|Ano|Valor|Categoria|Categorias|"
    r"Instituicao|Instituicoes|Gerenciar|Relatorios|Cadastros|Configuracoes)\b"
)
ATRIBUTOS_VISIVEIS = {
    "title", "aria-label", "placeholder", "alt", "data-sa-titulo", "data-sa-ok",
    "data-sa-cancelar", "data-sa-confirmar",
}


class _Visivel(HTMLParser):
    """Texto e atributos que o usuário lê; ignora script, style e comentários."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.trechos: list[str] = []
        self._ignorar = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._ignorar += 1
        for nome, valor in attrs:
            if nome in ATRIBUTOS_VISIVEIS and valor:
                self.trechos.append(valor)
        if tag == "input":
            tipo = dict(attrs).get("type")
            valor = dict(attrs).get("value")
            if tipo in {"submit", "button"} and valor:
                self.trechos.append(valor)

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._ignorar:
            self._ignorar -= 1

    def handle_data(self, data):
        if not self._ignorar and data.strip():
            self.trechos.append(data.strip())


def _vazamentos(html: str, dados: set[str]) -> list[str]:
    parser = _Visivel()
    parser.feed(html)
    achados = []
    for trecho in parser.trechos:
        for nome in dados:
            trecho = trecho.replace(nome, "")
        if ACENTOS.search(trecho) or PALAVRAS_PT.search(trecho):
            achados.append(trecho[:110])
    return achados


@pytest.fixture
def ambiente(client):
    usuario = get_user_model().objects.create_user(
        username="english-user", password="senha-segura", user_type="administrator", language="en",
    )
    titular = AccountOwner.objects.create(name="Test Holder")
    banco = FinancialInstitution.objects.create(institution_name="Test Bank", institution_type="Banco")
    corretora = FinancialInstitution.objects.create(institution_name="Test Broker", institution_type="Corretora")
    conta = FinancialAccount.objects.create(
        owner=titular, institution=banco, account_name="Test Checking",
        initial_balance=Decimal("1000.00"), initial_balance_date=date(2026, 1, 1),
    )
    FinancialAccount.objects.create(
        owner=titular, institution=corretora, account_name="Test Investment", account_kind="aplicacao",
        initial_balance=Decimal("0"), initial_balance_date=date(2026, 1, 1),
    )
    grupo = CashFlowCategoryGroup.objects.create(group_name="Test Group")
    despesa = CashFlowCategory.objects.create(category_name="Test Expense", group=grupo)
    receita = CashFlowCategory.objects.create(category_name="Test Income", group=grupo, kind="gerencial")
    hoje = date.today()
    for categoria, tipo, status, quando, parcelas in (
        (despesa, ENTRY_TYPE_EXPENSE, STATUS_REALIZED, hoje - timedelta(days=5), 1),
        (despesa, ENTRY_TYPE_EXPENSE, STATUS_PROJECTED, hoje + timedelta(days=5), 3),
        (receita, ENTRY_TYPE_INCOME, STATUS_PENDING, hoje - timedelta(days=3), 1),
    ):
        create_transaction_batch(
            TransactionRequest(
                account_id=conta.id, category_id=categoria.id, entry_type=tipo, description="Test entry",
                entry_amount=Decimal("100.00"), installments=parcelas, due_date=quando, status=status,
                realized_date=quando if status == STATUS_REALIZED else None,
            ),
            user=usuario,
        )
    client.force_login(usuario)
    nomes = {
        "Test Holder", "Test Bank", "Test Broker", "Test Checking", "Test Investment",
        "Test Group", "Test Expense", "Test Income", "Test entry", "english-user",
        # Nome do produto e nome do idioma no próprio idioma (o seletor mostra cada um na sua língua).
        "Controle Bancário", "Português (Brasil)", "English (US)",
        # Nome de categoria citado dentro de uma frase da tela de saldo.
        "Ajustes de Saldo",
    }
    # O log de auditoria exibe o resumo gravado no momento do fato: é registro, não texto de interface.
    nomes |= set(AuditLog.objects.values_list("summary", flat=True))
    # Dados semeados pelas migrações (grupos, categorias, permissões) são dado do usuário, não interface.
    nomes |= set(CashFlowCategory.objects.values_list("category_name", flat=True))
    nomes |= set(CashFlowCategoryGroup.objects.values_list("group_name", flat=True))
    return client, nomes


TELAS = [
    "core:inicio", "dashboard:dashboard", "transactions:transactions_view", "transactions:operations_view",
    "transactions:transaction_new", "transactions:categories_view", "transactions:category_groups_view",
    "banking:accounts_view", "banking:institutions_view", "accounts:owners_view", "accounts:change_password",
    "bank_statements:imports_view", "bank_statements:faturas", "bank_statements:extratos",
    "bank_statements:situacao_das_contas", "bank_statements:reconciliation_view",
    "bank_statements:reclassificacao", "bank_statements:atualizar_saldo", "bank_statements:attachments_view",
    "reports:projections_view", "reports:upcoming_movements_view", "reports:account_position_view",
    "reports:annual_planning_view", "management:management_view", "core:permissions",
    "core:settings_home", "core:settings_profile", "core:settings_monthly_close", "core:settings_database",
    "core:settings_audit_log", "fechamento:painel", "fechamento:fontes", "fechamento:cortes",
]


@pytest.mark.parametrize("rota", TELAS)
def test_tela_em_ingles_nao_traz_portugues(ambiente, rota):
    client, dados = ambiente
    resposta = client.get(reverse(rota), follow=True)
    assert resposta.status_code == 200, rota
    assert resposta.headers.get("Content-Language") == "en"
    assert '<html lang="en"' in resposta.content.decode()
    vazando = _vazamentos(resposta.content.decode(), dados)
    assert not vazando, f"{rota}: português na tela em inglês: {vazando[:12]}"


def test_login_em_ingles_pelo_idioma_do_navegador(client):
    resposta = client.get(reverse("login"), headers={"accept-language": "en-US,en;q=0.9"})
    assert resposta.status_code == 200
    assert '<html lang="en"' in resposta.content.decode()
    assert _vazamentos(resposta.content.decode(), set()) == []


def test_a_mesma_tela_em_portugues_continua_em_portugues(client):
    usuario = get_user_model().objects.create_user(
        username="usuario-pt", password="senha-segura", user_type="administrator", language="pt-br",
    )
    client.force_login(usuario)
    html = client.get(reverse("core:settings_profile")).content.decode()
    assert '<html lang="pt-br"' in html
    assert "Idioma e região" in html
