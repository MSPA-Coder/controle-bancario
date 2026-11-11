"""A migração `transactions/0004` iguala o tipo da operação ao dos lançamentos.

Em produção havia uma operação `installment` (13/07/2026) cujos dez lançamentos
são todos `recurring`. O teste roda a função da migração sobre um banco com esse
estado e com os casos que ela não pode tocar, e confere o antes e o depois.
"""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps

from accounts.models import AccountOwner
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import (
    ENTRY_TYPE_EXPENSE,
    OPERATION_INSTALLMENT,
    OPERATION_INTERNAL_TRANSFER,
    OPERATION_RECURRING,
    OPERATION_SINGLE,
)
from transactions.models import BankOperation, CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db

MIGRACAO = importlib.import_module("transactions.migrations.0004_tipo_da_operacao_igual_ao_dos_lancamentos")


@pytest.fixture
def conta():
    dono = AccountOwner.objects.create(name="Mariano")
    banco = FinancialInstitution.objects.create(institution_name="C6", institution_type="Banco")
    return FinancialAccount.objects.create(
        owner=dono, institution=banco, account_name="Corrente", currency="BRL",
        initial_balance=Decimal("0"), initial_balance_date=date(2026, 1, 1),
    )


def _operacao(chave: str, tipo: str, *tipos_dos_lancamentos: str, conta=None) -> BankOperation:
    operacao = BankOperation.objects.create(operation_key=chave, operation_type=tipo)
    categoria, _ = CashFlowCategory.objects.get_or_create(category_name="Mercado")
    for numero, tipo_do_lancamento in enumerate(tipos_dos_lancamentos, start=1):
        CashFlowEntry.objects.create(
            account=conta, category=categoria, entry_type=ENTRY_TYPE_EXPENSE, description="Parcela",
            entry_amount=Decimal("10.00"), due_date=date(2026, 7, numero), bank_operation=operacao,
            operation_type=tipo_do_lancamento, is_recurring=tipo_do_lancamento == OPERATION_RECURRING,
        )
    return operacao


def _tipos() -> dict[str, str]:
    return dict(BankOperation.objects.values_list("operation_key", "operation_type"))


def test_operacao_cujos_lancamentos_tem_todos_outro_tipo_passa_a_ter_o_deles(conta):
    # O estado da produção: operação `installment`, dez lançamentos `recurring`.
    _operacao("op-297", OPERATION_INSTALLMENT, *[OPERATION_RECURRING] * 10, conta=conta)
    antes_dos_lancamentos = list(CashFlowEntry.objects.order_by("id").values())
    assert _tipos() == {"op-297": OPERATION_INSTALLMENT}

    MIGRACAO.alinhar_tipo_da_operacao(apps, None)

    assert _tipos() == {"op-297": OPERATION_RECURRING}
    # Só o rótulo da operação mudou: nenhum lançamento (valor, parcela, tipo, data) foi tocado.
    assert list(CashFlowEntry.objects.order_by("id").values()) == antes_dos_lancamentos


def test_o_que_ja_esta_certo_ou_e_ambiguo_nao_muda(conta):
    _operacao("certa", OPERATION_INSTALLMENT, OPERATION_INSTALLMENT, OPERATION_INSTALLMENT, conta=conta)
    _operacao("mista", OPERATION_SINGLE, OPERATION_INSTALLMENT, OPERATION_RECURRING, conta=conta)
    _operacao("vazia", OPERATION_INSTALLMENT)
    esperado = _tipos()

    MIGRACAO.alinhar_tipo_da_operacao(apps, None)

    assert _tipos() == esperado


def test_operacao_de_transferencia_fica_de_fora(conta):
    # Lançamentos `single` numa operação de transferência: o banco aceita (o gatilho
    # de integridade só olha lançamento `internal_transfer`), mas a operação de
    # transferência é publicada à parte no v4, e mudar o tipo dela não é rótulo.
    # O inverso (lançamento `internal_transfer` fora de operação de transferência)
    # o banco já recusa, e a migração também o deixa de fora.
    _operacao("transferencia", OPERATION_INTERNAL_TRANSFER, OPERATION_SINGLE, conta=conta)
    esperado = _tipos()

    MIGRACAO.alinhar_tipo_da_operacao(apps, None)

    assert _tipos() == esperado


def test_rodar_de_novo_nao_muda_mais_nada(conta):
    _operacao("op-297", OPERATION_INSTALLMENT, OPERATION_RECURRING, OPERATION_RECURRING, conta=conta)
    MIGRACAO.alinhar_tipo_da_operacao(apps, None)
    depois_da_primeira = _tipos()

    MIGRACAO.alinhar_tipo_da_operacao(apps, None)

    assert _tipos() == depois_da_primeira == {"op-297": OPERATION_RECURRING}
