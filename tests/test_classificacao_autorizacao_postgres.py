"""Permissão funcional não concede escrita em titular somente para leitura."""

from datetime import date

import pytest
from django.urls import reverse
from test_gestao_persistida import cenario as cenario
from test_gestao_persistida import lancamento

from accounts.models import UserOwnerAccess
from accounts.services import save_function_permissions
from management import services
from management.models import CashFlowEntryProject, CashFlowEntryTag

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("tipo", ["tag", "project"])
@pytest.mark.parametrize("via", ["servico", "http"])
def test_classificacao_exige_escrita_do_titular_e_nao_apenas_leitura(cenario, client, tipo, via):
    entrada = lancamento(cenario, cenario.conta, date(2026, 12, 1), "15")
    UserOwnerAccess.objects.create(user=cenario.restrito, owner=cenario.dono,
                                   can_view=True, can_update=False, can_delete=False)
    save_function_permissions(cenario.restrito, {"management.manage"})
    criar = services.create_tag if tipo == "tag" else services.create_project
    atribuir = services.assign_tag_to_entry if tipo == "tag" else services.assign_project_to_entry
    referencia = criar("Classificação sintética")
    if via == "servico":
        with pytest.raises(ValueError):
            atribuir(cenario.restrito, entrada.pk, referencia.pk)
    else:
        client.force_login(cenario.restrito)
        response = client.post(reverse("management:assign_" + tipo),
                               {"entry_id": entrada.pk, tipo + "_id": referencia.pk})
        assert response.status_code == 302
    assert not CashFlowEntryTag.objects.exists()
    assert not CashFlowEntryProject.objects.exists()


@pytest.mark.parametrize("tipo", ["tag", "project"])
def test_classificacao_com_permissao_de_atualizar_continua_funcionando(cenario, tipo):
    entrada = lancamento(cenario, cenario.conta, date(2026, 12, 1), "15")
    UserOwnerAccess.objects.create(user=cenario.restrito, owner=cenario.dono,
                                   can_view=True, can_update=True, can_delete=False)
    criar = services.create_tag if tipo == "tag" else services.create_project
    atribuir = services.assign_tag_to_entry if tipo == "tag" else services.assign_project_to_entry
    referencia = criar("Permitida")
    assert atribuir(cenario.restrito, entrada.pk, referencia.pk).entry_id == entrada.pk
