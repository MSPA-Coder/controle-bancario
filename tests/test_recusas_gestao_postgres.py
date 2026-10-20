"""Entradas inválidas, autorização e erros HTTP, com persistência real."""

from datetime import date

import pytest
from django.urls import reverse
from test_gestao_persistida import cenario as cenario
from test_gestao_persistida import lancamento

from accounts.models import UserOwnerAccess
from management import services
from management.models import (
    CashFlowEntryProject,
    CashFlowEntryTag,
    ManagementProject,
    ManagementTag,
    MonthlyBudget,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity", "1e9999", "10000000000.00", "9999999999.995", "-1", "abc"])
def test_orcamento_invalido_e_recusa_de_dominio_sem_escrita(cenario, valor):
    with pytest.raises(ValueError):
        services.save_budget(cenario.admin, owner_id=cenario.dono.id, category_id=cenario.categoria.id,
                             year=2026, month=12, planned_amount=valor)
    assert not MonthlyBudget.objects.exists()


@pytest.mark.parametrize("campo,valor", [("owner_id", None), ("category_id", "x"), ("year", "x"),
                                        ("year", 1999), ("month", 13), ("category_id", 2147483647)])
def test_referencias_e_periodo_invalidos_nao_criam_orcamento(cenario, campo, valor):
    dados = {"owner_id": cenario.dono.id, "category_id": cenario.categoria.id,
             "year": 2026, "month": 12, "planned_amount": "100"}
    dados[campo] = valor
    with pytest.raises(ValueError):
        services.save_budget(cenario.admin, **dados)
    assert not MonthlyBudget.objects.exists()


@pytest.mark.parametrize("tipo", ["tag", "project"])
@pytest.mark.parametrize("identificador", [None, "invalido", 2147483647])
def test_vinculo_com_referencia_inexistente_nao_deixa_associacao(cenario, tipo, identificador):
    entrada = lancamento(cenario, cenario.conta, date(2026, 12, 1), "15")
    atribuir = services.assign_tag_to_entry if tipo == "tag" else services.assign_project_to_entry
    with pytest.raises(ValueError):
        atribuir(cenario.admin, entrada.pk, identificador)
    assert not CashFlowEntryTag.objects.exists()
    assert not CashFlowEntryProject.objects.exists()


@pytest.mark.parametrize("tipo", ["tag", "project"])
def test_vinculo_recusa_lancamento_de_outro_titular_e_referencia_arquivada(cenario, tipo):
    entrada = lancamento(cenario, cenario.conta, date(2026, 12, 1), "15")
    criar = services.create_tag if tipo == "tag" else services.create_project
    atribuir = services.assign_tag_to_entry if tipo == "tag" else services.assign_project_to_entry
    referencia = criar("Histórico")
    with pytest.raises(ValueError):
        atribuir(cenario.restrito, entrada.pk, referencia.pk)
    referencia.active = False
    referencia.save()
    with pytest.raises(ValueError):
        atribuir(cenario.admin, entrada.pk, referencia.pk)
    assert not CashFlowEntryTag.objects.exists()
    assert not CashFlowEntryProject.objects.exists()


@pytest.mark.parametrize("htmx", [False, True])
def test_http_sem_permissao_funcional_nao_muda_catalogo(client, cenario, htmx):
    client.force_login(cenario.restrito)
    headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
    response = client.post(reverse("management:create_tag"), {"tag_name": "Negada"}, **headers)
    assert response.status_code == (200 if htmx else 302)
    if htmx:
        assert response.headers["HX-Redirect"]
    assert not ManagementTag.objects.exists()


@pytest.mark.parametrize("rota,formulario,modelo", [
    ("create_tag", {"tag_name": ""}, ManagementTag),
    ("create_project", {"project_name": "x" * 121}, ManagementProject),
    ("save_budget", {"budget_month": "invalido"}, MonthlyBudget),
])
def test_http_administrador_recebe_recusa_sem_erro_500(client, cenario, rota, formulario, modelo):
    client.force_login(cenario.admin)
    response = client.post(reverse("management:" + rota), formulario)
    assert response.status_code == 302
    assert not modelo.objects.exists()


def test_http_valor_nao_finito_recusado_preserva_orcamento_anterior(client, cenario):
    client.force_login(cenario.admin)
    form = {"owner_id": cenario.dono.id, "category_id": cenario.categoria.id,
            "budget_month": "2026-12", "planned_amount": "75.25"}
    url = reverse("management:save_budget")
    assert client.post(url, form).status_code == 302
    assert client.post(url, {**form, "planned_amount": "NaN"}).status_code == 302
    assert str(MonthlyBudget.objects.get().planned_amount) == "75.25"


def test_exclusao_orcamento_sem_historico_e_arquivamento_com_realizado(cenario):
    dados = {"owner_id": cenario.dono.id, "category_id": cenario.categoria.id, "year": 2026,
             "month": 12, "planned_amount": "100"}
    budget = services.save_budget(cenario.admin, **dados)
    assert services.retire_budget(cenario.admin, budget.id)[1] == "deleted"
    budget = services.save_budget(cenario.admin, **dados)
    lancamento(cenario, cenario.conta, date(2026, 12, 31), "30")
    assert services.retire_budget(cenario.admin, budget.id)[1] == "archived"
    budget.refresh_from_db()
    assert budget.active is False
    assert services.save_budget(cenario.admin, **dados).active is True


def test_escopo_leitura_nao_autoriza_remover_orcamento_http(client, cenario):
    budget = services.save_budget(cenario.admin, owner_id=cenario.dono.pk, category_id=cenario.categoria.pk,
                                  year=2026, month=12, planned_amount="100")
    UserOwnerAccess.objects.create(user=cenario.restrito, owner=cenario.dono, can_view=True, can_update=False, can_delete=False)
    with pytest.raises(ValueError):
        services.retire_budget(cenario.restrito, budget.pk)
    assert MonthlyBudget.objects.filter(pk=budget.pk, active=True).exists()


@pytest.mark.parametrize("valor", ["0", "0.01", "9999999999.99"])
def test_orcamento_aceita_limites_representaveis_sem_perder_centavos(cenario, valor):
    budget = services.save_budget(cenario.admin, owner_id=cenario.dono.id, category_id=cenario.categoria.id,
                                  year=2026, month=12, planned_amount=valor)
    budget.refresh_from_db()
    assert budget.planned_amount == services.Decimal(valor)
