"""Piso de senha de 10 caracteres, igual ao do SharedAuth (D6, 11/11/2026).

O piso vale para senha nova ou trocada. Quem ainda tem senha de 8 caracteres
continua entrando: o login não revalida o tamanho. O valor gravado em
`app_setting` abaixo do piso (o 8 antigo) não derruba nada: vale o piso.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from sharedauth.passwords import MIN_PASSWORD_LENGTH

from accounts import services as accounts_services
from accounts.password_validators import current_min_length
from core import services as core_services
from core.domain.settings import APP_SETTING_PASSWORD_MIN_LENGTH
from core.services import get_password_policy_settings, upsert_app_setting

pytestmark = pytest.mark.django_db

SENHA_DE_8 = "xq7Lm2Zk"
SENHA_DE_9 = "xq7Lm2Zk9"
SENHA_DE_10 = "xq7Lm2Zk9R"


def test_o_piso_e_o_do_sharedauth():
    assert MIN_PASSWORD_LENGTH == 10
    assert current_min_length() == 10
    assert get_password_policy_settings().min_length == 10


def test_valor_antigo_8_gravado_no_banco_vale_o_piso():
    upsert_app_setting(APP_SETTING_PASSWORD_MIN_LENGTH, "8")

    assert current_min_length() == 10
    assert get_password_policy_settings().min_length == 10


def test_valor_acima_do_piso_gravado_continua_valendo():
    upsert_app_setting(APP_SETTING_PASSWORD_MIN_LENGTH, "14")

    assert current_min_length() == 14


def test_parametros_recusam_minimo_abaixo_do_piso():
    with pytest.raises(ValueError):
        core_services.update_password_policy_settings(
            min_length="9", min_uppercase="0", min_numbers="0", min_special="0"
        )


def test_tela_de_parametros_anuncia_o_piso(client):
    admin = get_user_model().objects.create_superuser(username="piso-admin", password=SENHA_DE_10)
    client.force_login(admin)

    html = client.get(reverse("core:settings_home")).content.decode()

    # O que importa é o campo do tamanho mínimo anunciar o piso, não a ordem
    # dos atributos da tag.
    campo = re.search(r'<input[^>]*name="min_length"[^>]*>', html)
    assert campo is not None
    assert ' min="10"' in campo.group(0)


def test_senha_nova_de_9_caracteres_e_recusada_e_de_10_passa():
    with pytest.raises(ValueError, match="10"):
        accounts_services.create_managed_user("novo-9", "user", SENHA_DE_9, SENHA_DE_9)

    criado = accounts_services.create_managed_user("novo-10", "user", SENHA_DE_10, SENHA_DE_10)

    assert criado.check_password(SENHA_DE_10)


def test_troca_de_senha_exige_o_piso():
    usuario = get_user_model().objects.create_user(username="troca", password=SENHA_DE_8)

    with pytest.raises(ValueError, match="10"):
        accounts_services.change_user_password(usuario, SENHA_DE_8, SENHA_DE_9, SENHA_DE_9)

    accounts_services.change_user_password(usuario, SENHA_DE_8, SENHA_DE_10, SENHA_DE_10)
    usuario.refresh_from_db()
    assert usuario.check_password(SENHA_DE_10)


def test_quem_tem_senha_de_8_continua_entrando(client):
    get_user_model().objects.create_user(username="antigo", password=SENHA_DE_8)

    resposta = client.post(reverse("login"), {"username": "antigo", "password": SENHA_DE_8})

    assert resposta.status_code == 302
    assert "_auth_user_id" in client.session
