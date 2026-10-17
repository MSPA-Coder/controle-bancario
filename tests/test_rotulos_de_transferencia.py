"""O rótulo "Conta Origem/Destino" das transferências acompanha o cadastro.

Em outubro de 2026 os titulares foram renomeados duas vezes, e cada vez cerca de
cem transferências ficaram com o nome antigo da outra ponta. Fica fixado aqui:

- renomear titular, instituição ou conta refaz o rótulo das duas pontas, também
  em mês fechado, sem mudar o saldo de fechamento;
- descrição que o usuário digitou numa transferência não é tocada;
- o comando `refazer_rotulos_de_transferencia` corrige o que ficou para trás.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from accounts.services import save_transfer_destination_accesses, update_owner
from banking.models import FinancialAccount, FinancialInstitution
from banking.services import update_account, update_institution
from core.domain.finance import CATEGORY_KIND_TRANSFER, ENTRY_TYPE_EXPENSE, STATUS_REALIZED
from core.models import AuditLog
from reports.services import VIEW_REALIZED, decimal_balance_before
from transactions.models import AccountMonthClose, CashFlowCategory, CashFlowEntry
from transactions.services import TransactionRequest, close_month, create_transaction_batch

pytestmark = pytest.mark.django_db

DIA = date(2026, 1, 15)


@pytest.fixture
def cenario():
    user = AppUser.objects.create_user(username="rotulos", password="senha-segura", user_type="administrator")
    titular = AccountOwner.objects.create(name="Maridito")
    UserOwnerAccess.objects.create(
        user=user, owner=titular, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    banco = FinancialInstitution.objects.create(institution_name="Banco Velho", institution_type="Banco")
    origem = FinancialAccount.objects.create(owner=titular, institution=banco, account_name="Conta 01")
    destino = FinancialAccount.objects.create(owner=titular, institution=banco, account_name="Conta 02")
    save_transfer_destination_accesses(user, {origem.id, destino.id})
    transferencia = CashFlowCategory.objects.create(category_name="Transferência", kind=CATEGORY_KIND_TRANSFER)
    saida, entrada = create_transaction_batch(
        TransactionRequest(
            account_id=origem.id, category_id=transferencia.id, entry_type=ENTRY_TYPE_EXPENSE,
            description="", entry_amount=Decimal("100.00"), installments=1, due_date=DIA,
            status=STATUS_REALIZED, realized_date=DIA, counterparty_account_id=destino.id,
        ),
        user=user,
    )
    return {"user": user, "titular": titular, "banco": banco, "origem": origem, "destino": destino,
            "saida": saida, "entrada": entrada}


def _descricoes(cenario) -> tuple[str, str]:
    return (
        CashFlowEntry.objects.get(id=cenario["saida"].id).description,
        CashFlowEntry.objects.get(id=cenario["entrada"].id).description,
    )


def test_a_transferencia_nasce_com_o_nome_da_outra_ponta(cenario):
    assert _descricoes(cenario) == (
        "Conta Destino: Maridito / Banco Velho / Conta 02",
        "Conta Origem: Maridito / Banco Velho / Conta 01",
    )


def test_renomear_o_titular_refaz_as_duas_pontas_mesmo_em_mes_fechado(cenario):
    origem = cenario["origem"]
    saldo = decimal_balance_before([origem.id], date(2026, 2, 1), VIEW_REALIZED)
    close_month(origem, 2026, 1, saldo, cenario["user"])

    update_owner(cenario["user"], cenario["titular"], "Mariano")

    assert _descricoes(cenario) == (
        "Conta Destino: Mariano / Banco Velho / Conta 02",
        "Conta Origem: Mariano / Banco Velho / Conta 01",
    )
    fechamento = AccountMonthClose.objects.get(account=origem, year=2026, month=1, active=True)
    assert fechamento.closing_balance == saldo
    assert AuditLog.objects.filter(summary__startswith="Rótulo de transferência").count() == 1


def test_renomear_a_instituicao_refaz_o_rotulo(cenario):
    update_institution(cenario["banco"], "Banco Novo", "Banco", user=cenario["user"])
    assert _descricoes(cenario) == (
        "Conta Destino: Maridito / Banco Novo / Conta 02",
        "Conta Origem: Maridito / Banco Novo / Conta 01",
    )


def test_renomear_a_conta_refaz_so_a_ponta_que_a_cita(cenario):
    destino = cenario["destino"]
    update_account(
        cenario["user"], destino, owner_id=str(destino.owner_id), institution_id=str(destino.institution_id),
        account_name="Poupança", initial_balance="0", currency=destino.currency,
    )
    assert _descricoes(cenario) == (
        "Conta Destino: Maridito / Banco Velho / Poupança",
        "Conta Origem: Maridito / Banco Velho / Conta 01",
    )


def test_editar_a_conta_sem_mudar_o_nome_nao_mexe_em_rotulo(cenario):
    destino = cenario["destino"]
    update_account(
        cenario["user"], destino, owner_id=str(destino.owner_id), institution_id=str(destino.institution_id),
        account_name="Conta 02", initial_balance="50", currency=destino.currency,
    )
    assert not AuditLog.objects.filter(summary__startswith="Rótulo de transferência").exists()


def test_descricao_digitada_pelo_usuario_fica_como_esta(cenario):
    CashFlowEntry.objects.filter(id=cenario["saida"].id).update(description="Presente para a mãe")
    update_owner(cenario["user"], cenario["titular"], "Mariano")
    assert _descricoes(cenario) == (
        "Presente para a mãe",
        "Conta Origem: Mariano / Banco Velho / Conta 01",
    )


def test_comando_corrige_o_rotulo_que_ficou_para_tras(cenario):
    CashFlowEntry.objects.filter(id=cenario["entrada"].id).update(description="Conta Origem: Mariano / Banco / ag 1")

    call_command("refazer_rotulos_de_transferencia", "--usuario", "rotulos")
    assert _descricoes(cenario)[1] == "Conta Origem: Mariano / Banco / ag 1"

    call_command("refazer_rotulos_de_transferencia", "--usuario", "rotulos", "--aplicar")
    assert _descricoes(cenario)[1] == "Conta Origem: Maridito / Banco Velho / Conta 01"
