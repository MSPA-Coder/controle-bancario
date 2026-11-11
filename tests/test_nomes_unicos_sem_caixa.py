"""Nome de usuário, de categoria e de grupo é único sem diferenciar a caixa.

O login procura o usuário por `username__iexact`: "Ana" e "ana" juntos dariam
`MultipleObjectsReturned`, erro 500. O serviço de categoria e de grupo já
recusava nome que só difere na caixa, mas o banco só recusava o byte a byte, e
uma escrita fora do serviço criava a segunda. Aqui o banco real recusa, o
serviço diz por quê, e a migração que cria os índices se recusa a rodar sobre
duplicata, sem tocar em nada.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction

from accounts.models import AppUser
from accounts.services import create_managed_user, update_managed_user
from transactions.models import CashFlowCategory, CashFlowCategoryGroup

pytestmark = pytest.mark.django_db

SENHA = "senha-bastante-longa-123"


def test_banco_recusa_usuario_que_so_difere_na_caixa():
    AppUser.objects.create_user(username="Ana", password=SENHA)

    with pytest.raises(IntegrityError), transaction.atomic():
        AppUser.objects.create_user(username="ana", password=SENHA)


def test_banco_recusa_categoria_e_grupo_que_so_diferem_na_caixa():
    CashFlowCategory.objects.create(category_name="Mercado")
    CashFlowCategoryGroup.objects.create(group_name="Casa")

    with pytest.raises(IntegrityError), transaction.atomic():
        CashFlowCategory.objects.create(category_name="MERCADO")
    with pytest.raises(IntegrityError), transaction.atomic():
        CashFlowCategoryGroup.objects.create(group_name="casa")


def test_servico_recusa_novo_usuario_que_so_difere_na_caixa():
    AppUser.objects.create_user(username="Ana", password=SENHA)

    with pytest.raises(ValueError, match="Já existe um usuário"):
        create_managed_user("ANA", "user", SENHA, SENHA)

    assert AppUser.objects.filter(username__iexact="ana").count() == 1


def test_servico_recusa_renomear_para_nome_que_so_difere_na_caixa_mas_aceita_o_proprio():
    AppUser.objects.create_user(username="Ana", password=SENHA)
    bruno = AppUser.objects.create_user(username="Bruno", password=SENHA)

    with pytest.raises(ValueError, match="Já existe um usuário"):
        update_managed_user(bruno, "ana", "user", None, None, False)

    # Mudar só a caixa do próprio nome não é conflito com ele mesmo.
    atualizado = update_managed_user(bruno, "BRUNO", "user", None, None, False)
    assert atualizado.username == "BRUNO"


def test_login_acha_o_usuario_qualquer_que_seja_a_caixa_digitada(client):
    AppUser.objects.create_user(username="Ana", password=SENHA)

    resposta = client.post("/login", {"username": "aNa", "password": SENHA})

    assert resposta.status_code == 302
    assert client.session.get("_auth_user_id")


# --- a migração se recusa a rodar sobre duplicata ---------------------------

USUARIOS = importlib.import_module("accounts.migrations.0004_nome_de_usuario_unico_sem_caixa")
CATEGORIAS = importlib.import_module("transactions.migrations.0005_nome_de_categoria_e_grupo_unico_sem_caixa")


def _derrubar_indices(*nomes: str) -> None:
    """Devolve o banco ao estado anterior à migração, dentro da transação do teste."""
    with connection.cursor() as cursor:
        for nome in nomes:
            cursor.execute(f"DROP INDEX {nome}")


def test_migracao_de_usuario_recusa_duplicata_sem_alterar_nada():
    _derrubar_indices("uq_app_user_username_ci")
    ana = AppUser.objects.create_user(username="Ana", password=SENHA)
    outra = AppUser.objects.create_user(username="ana", password=SENHA)
    AppUser.objects.create_user(username="Bruno", password=SENHA)

    with pytest.raises(RuntimeError) as erro:
        USUARIOS.recusar_duplicata(apps, None)

    # Lista os ids (não os nomes) e nada foi apagado nem renomeado.
    assert str(ana.id) in str(erro.value) and str(outra.id) in str(erro.value)
    assert "Ana" not in str(erro.value)
    assert sorted(AppUser.objects.values_list("username", flat=True)) == ["Ana", "Bruno", "ana"]


def test_migracao_de_usuario_passa_quando_nao_ha_duplicata():
    _derrubar_indices("uq_app_user_username_ci")
    AppUser.objects.create_user(username="Ana", password=SENHA)
    AppUser.objects.create_user(username="Bruno", password=SENHA)

    USUARIOS.recusar_duplicata(apps, None)


@pytest.mark.parametrize(
    ("modelo", "campo", "esperado_no_erro"),
    [
        (CashFlowCategory, "category_name", "categoria"),
        (CashFlowCategoryGroup, "group_name", "grupo de categoria"),
    ],
)
def test_migracao_de_categoria_e_grupo_recusa_duplicata_sem_alterar_nada(modelo, campo, esperado_no_erro):
    _derrubar_indices("uq_cash_flow_category_name_ci", "uq_cash_flow_category_group_name_ci")
    primeira = modelo.objects.create(**{campo: "Mercado"})
    segunda = modelo.objects.create(**{campo: "MERCADO"})
    antes = list(modelo.objects.order_by("id").values_list("id", campo))

    with pytest.raises(RuntimeError) as erro:
        CATEGORIAS.recusar_duplicata(apps, None)

    assert esperado_no_erro in str(erro.value)
    assert str(primeira.id) in str(erro.value) and str(segunda.id) in str(erro.value)
    assert list(modelo.objects.order_by("id").values_list("id", campo)) == antes


def test_migracao_de_categoria_e_grupo_passa_quando_nao_ha_duplicata():
    _derrubar_indices("uq_cash_flow_category_name_ci", "uq_cash_flow_category_group_name_ci")
    CashFlowCategory.objects.create(category_name="Mercado")
    CashFlowCategoryGroup.objects.create(group_name="Casa")

    CATEGORIAS.recusar_duplicata(apps, None)


# --- quem cria por nome reaproveita o que já existe com outra caixa ---------


def test_estimativa_do_cartao_reaproveita_a_categoria_que_so_difere_na_caixa():
    """Antes criava a segunda; agora o banco a recusaria (erro 500 na atualização da fatura)."""
    from bank_statements.fatura_projetada import CATEGORIA_ESTIMATIVA, _categoria_da_estimativa

    existente = CashFlowCategory.objects.create(category_name=CATEGORIA_ESTIMATIVA.upper())

    assert _categoria_da_estimativa().id == existente.id


def test_familia_de_reclassificacao_reaproveita_o_grupo_que_so_difere_na_caixa():
    from bank_statements.familias import Familia, _garantir_categoria

    grupo = CashFlowCategoryGroup.objects.create(group_name="CASA DE TESTE")
    familia = Familia(
        nome="teste", padroes=("x",), de=(), tipo="despesa", para="Categoria de teste", grupo="Casa de Teste"
    )

    categoria = _garantir_categoria(familia)

    assert categoria.group_id == grupo.id
    assert CashFlowCategoryGroup.objects.filter(group_name__iexact="casa de teste").count() == 1
