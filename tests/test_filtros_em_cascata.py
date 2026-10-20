"""Filtros que dependem uns dos outros: cada lista só é recortada pelos de cima.

Relato de 19/10/2026: com um titular e uma conta escolhidos, as listas de
Instituição e Conta passavam a mostrar só aquela conta, e voltar para "Todas as
instituições" não reabria as outras contas do titular. A regra que estes testes
fixam: Titular > Instituição > Conta, e nenhuma lista é recortada pela própria
escolha nem pelas de baixo. Os filtros de coluna da tabela de Lançamentos são
pares (Tipo e Data): cada um é recortado pelo outro, nunca por si.

O lado do navegador -- trocar Titular ou Instituição limpa a Conta -- está em
`tests/browser/critical.test.mjs`.
"""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from accounts.models import AccountOwner
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import ENTRY_TYPE_EXPENSE, ENTRY_TYPE_INCOME, STATUS_PROJECTED
from reports.services import context_options, selected_context


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user(
        username="filtros-cascata", password="senha-segura", user_type="administrator",
    )


@pytest.fixture
def contas(db):
    """Titular A com conta no Banco 1 e no Banco 2; titular B no Banco 2 e no Banco 3."""
    titular_a = AccountOwner.objects.create(name="Titular A")
    titular_b = AccountOwner.objects.create(name="Titular B")
    bancos = {
        numero: FinancialInstitution.objects.create(institution_name=f"Banco {numero}", institution_type="Banco")
        for numero in (1, 2, 3)
    }

    def conta(nome, titular, banco):
        return FinancialAccount.objects.create(
            owner=titular, institution=bancos[banco], account_name=nome,
            initial_balance=Decimal("0.00"), initial_balance_date=date(2025, 12, 31),
        )

    return {
        "a1": conta("A no 1", titular_a, 1),
        "a2": conta("A no 2", titular_a, 2),
        "b2": conta("B no 2", titular_b, 2),
        "b3": conta("B no 3", titular_b, 3),
    }


def _seletores(usuario, params, request=None):
    ctx = selected_context(usuario, params, request=request)
    opcoes = context_options(usuario, ctx)
    return (
        ctx,
        {instituicao.institution_name for instituicao in opcoes.institutions},
        {conta.account_name for conta in opcoes.accounts},
        opcoes.account_ids,
    )


@pytest.mark.django_db
def test_conta_escolhida_nao_recorta_instituicoes_nem_contas(usuario, contas):
    """O caso relatado: titular + conta, e a lista de contas continua inteira."""
    a1 = contas["a1"]
    _ctx, instituicoes, nomes, account_ids = _seletores(
        usuario, {"owner_id": str(a1.owner_id), "account_id": str(a1.id)}
    )

    assert instituicoes == {"Banco 1", "Banco 2"}
    assert nomes == {"A no 1", "A no 2"}
    # O recorte dos dados continua sendo a conta escolhida.
    assert account_ids == [a1.id]


@pytest.mark.django_db
def test_conta_escolhida_sem_titular_mantem_todas_as_opcoes(usuario, contas):
    _ctx, instituicoes, nomes, account_ids = _seletores(usuario, {"account_id": str(contas["b3"].id)})

    assert instituicoes == {"Banco 1", "Banco 2", "Banco 3"}
    assert nomes == {"A no 1", "A no 2", "B no 2", "B no 3"}
    assert account_ids == [contas["b3"].id]


@pytest.mark.django_db
def test_instituicao_recorta_as_contas_mas_nao_a_propria_lista(usuario, contas):
    a2 = contas["a2"]
    _ctx, instituicoes, nomes, _ids = _seletores(
        usuario, {"owner_id": str(a2.owner_id), "institution_id": str(a2.institution_id)}
    )

    assert instituicoes == {"Banco 1", "Banco 2"}
    assert nomes == {"A no 2"}


@pytest.mark.django_db
def test_instituicao_sem_conta_do_titular_cai_e_sai_da_barra(usuario, contas):
    """Trocar o titular deixava a instituição anterior valendo e a tela vazia."""
    titular_a = contas["a1"].owner_id
    banco_3 = contas["b3"].institution_id
    request = RequestFactory().get("/transactions/")

    ctx, instituicoes, nomes, _ids = _seletores(
        usuario, {"owner_id": str(titular_a), "institution_id": str(banco_3)}, request=request,
    )

    assert ctx.institution_id is None
    assert request.filtros_descartados == {"institution_id"}
    assert instituicoes == {"Banco 1", "Banco 2"}
    assert nomes == {"A no 1", "A no 2"}


@pytest.mark.django_db
def test_instituicao_compartilhada_continua_ao_trocar_de_titular(usuario, contas):
    banco_2 = contas["a2"].institution_id
    request = RequestFactory().get("/transactions/")

    ctx, _instituicoes, nomes, _ids = _seletores(
        usuario, {"owner_id": str(contas["b2"].owner_id), "institution_id": str(banco_2)}, request=request,
    )

    assert ctx.institution_id == banco_2
    assert not getattr(request, "filtros_descartados", set())
    assert nomes == {"B no 2"}


# ---------------------------------------------------------------------------
# Filtros de coluna da tabela de Lançamentos
# ---------------------------------------------------------------------------

@pytest.fixture
def lancamentos(usuario, contas):
    from transactions.models import CashFlowCategory
    from transactions.services import TransactionRequest, create_transaction_batch

    categoria = CashFlowCategory.objects.create(category_name="Categoria cascata")
    hoje = date.today()
    dias = {ENTRY_TYPE_EXPENSE: hoje.replace(day=1), ENTRY_TYPE_INCOME: hoje.replace(day=2)}
    for tipo, dia in dias.items():
        create_transaction_batch(TransactionRequest(
            account_id=contas["a1"].id, category_id=categoria.id, entry_type=tipo,
            description=f"Lançamento {tipo}", entry_amount=Decimal("10.00"), installments=1,
            due_date=dia, status=STATUS_PROJECTED,
        ), user=usuario)
    return dias


def _opcoes_da_coluna(html, nome):
    seletor = re.search(rf'<select data-table-filter name="{nome}".*?</select>', html, re.S)
    assert seletor, nome
    return set(re.findall(r'<option value="([^"]+)"', seletor.group(0)))


@pytest.mark.django_db
def test_tipo_escolhido_nao_esconde_os_outros_tipos(client, usuario, lancamentos):
    client.force_login(usuario)
    periodo = lancamentos[ENTRY_TYPE_EXPENSE].strftime("%Y-%m")

    html = client.get(f"/transactions/?period={periodo}&mode=todos&filter_type=despesa").content.decode()

    assert _opcoes_da_coluna(html, "filter_type") == {ENTRY_TYPE_EXPENSE, ENTRY_TYPE_INCOME}
    # A data é recortada pelo tipo: o dia da receita não aparece com "Despesa".
    assert _opcoes_da_coluna(html, "filter_date") == {lancamentos[ENTRY_TYPE_EXPENSE].isoformat()}


@pytest.mark.django_db
def test_data_escolhida_nao_esconde_as_outras_datas(client, usuario, lancamentos):
    client.force_login(usuario)
    dia_da_despesa = lancamentos[ENTRY_TYPE_EXPENSE]

    html = client.get(
        f"/transactions/?period={dia_da_despesa:%Y-%m}&mode=todos&filter_date={dia_da_despesa.isoformat()}"
    ).content.decode()

    assert _opcoes_da_coluna(html, "filter_date") == {dia.isoformat() for dia in lancamentos.values()}
    # O tipo é recortado pela data: nesse dia só há despesa.
    assert _opcoes_da_coluna(html, "filter_type") == {ENTRY_TYPE_EXPENSE}
