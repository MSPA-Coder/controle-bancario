"""Correções que saíram da varredura de idioma: dado de máquina, catálogo de permissões e filtro de exibição.

Riscos que protege:
- o JSON de status do lote devolver a data formatada pela região de quem pediu (o consumidor
  de máquina precisa de ISO, igual para todos);
- uma permissão existir no código e no perfil Operador sem linha em `app_permission`, o que a
  esconde da matriz e faz `save_function_permissions` ignorá-la sem aviso;
- o filtro `traduzido` devolver o cabeçalho do catálogo para texto vazio.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.urls import reverse
from django.utils import translation

from accounts.models import AccountOwner, AppPermission
from accounts.services import PERMISSION_DEFINITIONS, PROFILE_DEFINITIONS
from bank_statements.models import BankStatementImport
from banking.models import FinancialAccount, FinancialInstitution


@pytest.mark.django_db
def test_status_do_lote_devolve_a_data_em_iso_qualquer_que_seja_a_regiao(client):
    usuario = get_user_model().objects.create_user(
        username="status-lote", password="senha-segura", user_type="administrator",
        language="en", regional_format="us",
    )
    titular = AccountOwner.objects.create(name="Titular")
    banco = FinancialInstitution.objects.create(institution_name="Banco", institution_type="Banco")
    conta = FinancialAccount.objects.create(
        owner=titular, institution=banco, account_name="Corrente",
        initial_balance=Decimal("0"), initial_balance_date=date(2026, 1, 1),
    )
    lote = BankStatementImport.objects.create(account=conta, source_filename="extrato.ofx", row_count=1)
    client.force_login(usuario)

    corpo = client.get(reverse("bank_statements:import_status", args=[lote.id])).json()

    # ISO 8601 lê de volta no mesmo instante; "10/11/2026 08:05" (região EUA) não leria.
    assert datetime.fromisoformat(corpo["created_at"]) == lote.created_at


@pytest.mark.django_db
def test_toda_permissao_definida_no_codigo_tem_linha_no_catalogo():
    sem_linha = set(PERMISSION_DEFINITIONS) - set(AppPermission.objects.values_list("name", flat=True))
    assert not sem_linha, f"permissão sem linha em app_permission (nenhuma migration a criou): {sorted(sem_linha)}"


def test_perfis_so_citam_permissoes_definidas():
    citadas = {nome for perfil in PROFILE_DEFINITIONS.values() for nome in perfil["permissions"]}
    assert citadas <= set(PERMISSION_DEFINITIONS)


def _filtrar(valor) -> str:
    return Template("{% load regional_filters %}{{ v|traduzido }}").render(Context({"v": valor}))


def test_traduzido_nao_vira_o_cabecalho_do_catalogo_quando_vazio():
    with translation.override("en"):
        assert _filtrar("") == ""
        assert _filtrar(None) == ""


def test_traduzido_deixa_passar_o_que_nao_esta_no_catalogo():
    with translation.override("en"):
        assert _filtrar("Texto que nenhum catálogo conhece 41861-7") == "Texto que nenhum catálogo conhece 41861-7"
