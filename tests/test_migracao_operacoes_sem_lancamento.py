"""A migração `transactions/0003` apaga só a operação que ficou sem lançamento.

Em produção havia 34 operações assim (resíduo de maio e junho de 2026). O teste
roda a função da migração sobre um banco com operações vazias e com lançamentos,
e confere o antes e o depois.
"""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps

from accounts.models import AccountOwner
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import ENTRY_TYPE_EXPENSE, OPERATION_INSTALLMENT, OPERATION_SINGLE
from transactions.models import BankOperation, CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db

MIGRACAO = importlib.import_module("transactions.migrations.0003_apagar_operacoes_sem_lancamento")


def _operacao(chave: str, tipo: str) -> BankOperation:
    return BankOperation.objects.create(operation_key=chave, operation_type=tipo)


def test_apaga_a_operacao_sem_lancamento_e_guarda_a_que_tem():
    dono = AccountOwner.objects.create(name="Mariano")
    banco = FinancialInstitution.objects.create(institution_name="C6", institution_type="Banco")
    conta = FinancialAccount.objects.create(
        owner=dono, institution=banco, account_name="Corrente", currency="BRL",
        initial_balance=Decimal("0"), initial_balance_date=date(2026, 1, 1),
    )
    categoria = CashFlowCategory.objects.create(category_name="Mercado")
    vazia_unica = _operacao("single-vazia", OPERATION_SINGLE)
    vazia_parcelada = _operacao("installment-vazia", OPERATION_INSTALLMENT)
    com_lancamento = _operacao("installment-cheia", OPERATION_INSTALLMENT)
    CashFlowEntry.objects.create(
        account=conta, category=categoria, entry_type=ENTRY_TYPE_EXPENSE, description="Parcela",
        entry_amount=Decimal("10.00"), due_date=date(2026, 7, 1), bank_operation=com_lancamento,
        operation_type=OPERATION_INSTALLMENT,
    )

    MIGRACAO.apagar_operacoes_sem_lancamento(apps, None)

    restantes = set(BankOperation.objects.values_list("id", flat=True))
    assert com_lancamento.id in restantes
    assert not {vazia_unica.id, vazia_parcelada.id} & restantes
    assert CashFlowEntry.objects.filter(bank_operation=com_lancamento).count() == 1
