"""Matriz Usuário × conta destino derivada do histórico (`accounts.matriz_de_destinos`).

Fixam-se: a concessão sai das transferências que já existem e do acesso de
criação à origem; só acrescenta; é idempotente; e quem não tem acesso à origem
não ganha nada.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command

from accounts import matriz_de_destinos
from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from accounts.services import save_transfer_destination_accesses, transfer_destination_access_ids
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import CATEGORY_KIND_TRANSFER, ENTRY_TYPE_EXPENSE, STATUS_PROJECTED
from core.models import AuditLog
from transactions.models import CashFlowCategory
from transactions.services import TransactionRequest, create_transaction_batch

pytestmark = pytest.mark.django_db


@pytest.fixture
def cenario():
    dono_a = AccountOwner.objects.create(name="Dono A")
    dono_b = AccountOwner.objects.create(name="Dono B")
    banco = FinancialInstitution.objects.create(institution_name="Banco matriz", institution_type="Banco")
    origem = FinancialAccount.objects.create(owner=dono_a, institution=banco, account_name="Origem A")
    destino = FinancialAccount.objects.create(owner=dono_b, institution=banco, account_name="Destino B")
    sem_uso = FinancialAccount.objects.create(owner=dono_b, institution=banco, account_name="Sem uso B")

    # Quem lançou a transferência histórica já tem o destino concedido.
    operador = AppUser.objects.create_user(username="operador-matriz", password="senha-segura-123")
    UserOwnerAccess.objects.create(user=operador, owner=dono_a, can_view=True, can_create=True)
    save_transfer_destination_accesses(operador, {destino.id})
    categoria = CashFlowCategory.objects.create(category_name="Interna matriz", kind=CATEGORY_KIND_TRANSFER)
    create_transaction_batch(
        TransactionRequest(
            account_id=origem.id, category_id=categoria.id, entry_type=ENTRY_TYPE_EXPENSE,
            description="x", entry_amount=Decimal("10.00"), installments=1,
            due_date=date(2026, 9, 10), status=STATUS_PROJECTED, counterparty_account_id=destino.id,
        ),
        user=operador,
    )
    return {"dono_a": dono_a, "origem": origem, "destino": destino, "sem_uso": sem_uso, "operador": operador}


def _usuario(nome):
    return AppUser.objects.create_user(username=nome, password="senha-segura-123")


def test_quem_cria_na_origem_recebe_o_destino_que_o_historico_ja_usa(cenario):
    colega = _usuario("colega-matriz")
    UserOwnerAccess.objects.create(user=colega, owner=cenario["dono_a"], can_view=True, can_create=True)
    sem_acesso = _usuario("sem-acesso-matriz")
    so_leitura = _usuario("so-leitura-matriz")
    UserOwnerAccess.objects.create(user=so_leitura, owner=cenario["dono_a"], can_view=True, can_create=False)

    proposta = matriz_de_destinos.propor()

    assert proposta == {colega: {cenario["destino"].id}}
    assert sem_acesso not in proposta and so_leitura not in proposta
    assert cenario["operador"] not in proposta  # já tem


def test_aplicar_so_acrescenta_audita_e_e_idempotente(cenario):
    colega = _usuario("colega-matriz")
    UserOwnerAccess.objects.create(user=colega, owner=cenario["dono_a"], can_view=True, can_create=True)
    save_transfer_destination_accesses(colega, {cenario["sem_uso"].id})  # concessão antiga, sem uso

    assert matriz_de_destinos.aplicar(matriz_de_destinos.propor()) == 1

    assert transfer_destination_access_ids(colega) == {cenario["destino"].id, cenario["sem_uso"].id}
    assert AuditLog.objects.filter(
        entity_name="app_user_transfer_destination_access", entity_id=str(colega.id)
    ).exists()
    assert matriz_de_destinos.propor() == {}


def test_comando_simula_sem_gravar_e_com_aplicar_grava(cenario, capsys):
    colega = _usuario("colega-matriz")
    UserOwnerAccess.objects.create(user=colega, owner=cenario["dono_a"], can_view=True, can_create=True)

    call_command("matriz_de_destinos")
    assert transfer_destination_access_ids(colega) == set()
    assert "Simulação" in capsys.readouterr().out

    call_command("matriz_de_destinos", "--aplicar")
    assert transfer_destination_access_ids(colega) == {cenario["destino"].id}
