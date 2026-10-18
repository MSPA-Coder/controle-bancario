"""A mesma conferência não relê o saldo a cada arquivo listado.

Na auditoria de 17/10/2026, 20 lotes da mesma conta/data custaram 63 consultas,
contra 6 para um lote. A comparação roda fora do memo de uma requisição HTTP.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from bank_statements.models import BankStatementImport
from bank_statements.services import conferencia_de_saldo, statement_imports_for_user
from tests.test_teto_consultas import cenario as cenario

pytestmark = pytest.mark.django_db


def test_same_balance_date_does_not_grow_queries_with_number_of_imports(cenario):
    def create_batch(index):
        return BankStatementImport.objects.create(
            account=cenario.conta, source_filename=f"synthetic-{index}.ofx",
            statement_balance=Decimal("1000"), statement_balance_date=date(2026, 8, 31),
        )

    batch = create_batch(0)
    expected = conferencia_de_saldo(batch)
    statement_imports_for_user(cenario.user)
    with CaptureQueriesContext(connection) as single:
        first = list(statement_imports_for_user(cenario.user))
    for index in range(1, 20):
        create_batch(index)
    with CaptureQueriesContext(connection) as twenty:
        second = list(statement_imports_for_user(cenario.user))
    assert (len(first), len(second)) == (1, 20)
    assert len(twenty) == len(single)
    assert all(batch.conferencia == expected for batch in second)


def test_grouped_comparison_preserves_each_account_date_and_missing_balance(cenario):
    for index, (account, day, balance) in enumerate([
        (cenario.conta, date(2026, 8, 31), Decimal("1000")),
        (cenario.conta, date(2026, 9, 30), Decimal("999")),
        (cenario.reserva, date(2026, 8, 31), Decimal("0")),
        (cenario.reserva, None, None),
    ]):
        BankStatementImport.objects.create(
            account=account, source_filename=f"synthetic-{index}.ofx",
            statement_balance=balance, statement_balance_date=day,
        )
    batches = list(statement_imports_for_user(cenario.user))
    assert len(batches) == 4
    for batch in batches:
        assert batch.conferencia == conferencia_de_saldo(batch)
