"""Orçamento e classificações precisam conservar dinheiro, histórico e escopo."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import ENTRY_TYPE_EXPENSE, STATUS_REALIZED
from core.domain.identity import USER_TYPE_ADMINISTRATOR, USER_TYPE_USER
from management import services
from management.models import CashFlowEntryProject, CashFlowEntryTag, MonthlyBudget
from transactions.models import CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def cenario():
    admin = AppUser.objects.create(username="gestao-admin", user_type=USER_TYPE_ADMINISTRATOR)
    restrito = AppUser.objects.create(username="gestao-restrito", user_type=USER_TYPE_USER)
    dono = AccountOwner.objects.create(name="Titular gestão")
    banco = FinancialInstitution.objects.create(institution_name="Instituição gestão")
    conta = FinancialAccount.objects.create(owner=dono, institution=banco, account_name="Real", currency="BRL")
    dolar = FinancialAccount.objects.create(owner=dono, institution=banco, account_name="Dólar", currency="USD")
    categoria = CashFlowCategory.objects.create(category_name="Pesquisa gestão")
    return SimpleNamespace(admin=admin, restrito=restrito, dono=dono, conta=conta, dolar=dolar, categoria=categoria)


def lancamento(cenario, conta, dia, valor):
    return CashFlowEntry.objects.create(
        account=conta, category=cenario.categoria, entry_type=ENTRY_TYPE_EXPENSE,
        description="Despesa de pesquisa", entry_amount=Decimal(valor), due_date=dia,
        status=STATUS_REALIZED, realized_date=dia, realized_amount=Decimal(valor),
    )


def salvar(cenario, user=None, **campos):
    return services.save_budget(
        user or cenario.admin, owner_id=cenario.dono.id, category_id=cenario.categoria.id,
        year=2026, month=12, planned_amount=campos.get("valor", "150,25"),
    )


def test_orcamento_recalcula_realizado_sem_misturar_moedas_ou_virada_do_ano(cenario):
    orcamento = salvar(cenario)
    lancamento(cenario, cenario.conta, date(2026, 12, 1), "10.10")
    ultimo = lancamento(cenario, cenario.conta, date(2026, 12, 31), "20.20")
    lancamento(cenario, cenario.conta, date(2027, 1, 1), "999.99")
    lancamento(cenario, cenario.dolar, date(2026, 12, 15), "888.88")
    linhas = services.budget_rows_for_period([cenario.dono.id], 2026, 12)
    assert len(linhas) == 1
    assert linhas[0].budget.pk == orcamento.pk
    assert linhas[0].actual_amount == Decimal("30.30")
    assert linhas[0].difference == Decimal("119.95")
    ultimo.realized_amount = Decimal("25.20")
    ultimo.save(update_fields=["realized_amount"])
    assert services.actual_amount_for_budget(cenario.dono.id, cenario.categoria.id, 2026, 12) == Decimal("35.30")


def test_salvar_de_novo_atualiza_mesma_meta_e_preserva_categorias(cenario):
    primeiro = salvar(cenario)
    segundo = salvar(cenario, valor="200.50")
    assert segundo.pk == primeiro.pk
    assert MonthlyBudget.objects.count() == 1
    assert segundo.planned_amount == Decimal("200.50")


def test_titular_sem_permissao_de_escrita_nao_recebe_orcamento(cenario):
    UserOwnerAccess.objects.create(
        user=cenario.restrito, owner=cenario.dono, can_view=True,
        can_update=False, can_delete=False,
    )
    with pytest.raises(ValueError):
        salvar(cenario, user=cenario.restrito)
    assert not MonthlyBudget.objects.exists()


def test_tag_repetida_nao_duplica_e_arquivamento_preserva_historico(cenario):
    entrada = lancamento(cenario, cenario.conta, date(2026, 12, 1), "10.00")
    tag = services.create_tag(" Pesquisa ")
    primeiro = services.assign_tag_to_entry(cenario.admin, entrada.pk, tag.pk)
    segundo = services.assign_tag_to_entry(cenario.admin, entrada.pk, tag.pk)
    assert primeiro.pk == segundo.pk
    assert CashFlowEntryTag.objects.count() == 1
    arquivada, acao = services.retire_tag(tag.pk)
    assert acao == "archived"
    assert not arquivada.active
    assert CashFlowEntryTag.objects.get(pk=primeiro.pk).tag_id == tag.pk
    with pytest.raises(ValueError):
        services.assign_tag_to_entry(cenario.admin, entrada.pk, tag.pk)


def test_troca_de_projeto_move_vinculo_sem_duplicar_lancamento(cenario):
    entrada = lancamento(cenario, cenario.conta, date(2026, 12, 1), "10.00")
    antigo = services.create_project("Antigo")
    novo = services.create_project("Novo")
    services.assign_project_to_entry(cenario.admin, entrada.pk, antigo.pk)
    services.assign_project_to_entry(cenario.admin, entrada.pk, novo.pk)
    assert CashFlowEntryProject.objects.get(entry=entrada).project_id == novo.pk
    assert CashFlowEntryProject.objects.count() == 1
    assert CashFlowEntry.objects.count() == 1


def test_permissao_de_atualizar_nao_autoriza_excluir_meta(cenario):
    UserOwnerAccess.objects.create(
        user=cenario.restrito, owner=cenario.dono, can_view=True,
        can_update=True, can_delete=False,
    )
    orcamento = salvar(cenario, user=cenario.restrito)
    with pytest.raises(ValueError):
        services.retire_budget(cenario.restrito, orcamento.pk)
    assert MonthlyBudget.objects.filter(pk=orcamento.pk, active=True).exists()
