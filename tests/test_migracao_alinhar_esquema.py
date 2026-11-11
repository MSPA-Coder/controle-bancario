"""A migração `core/0002` alinha um banco com os desvios da produção.

No banco de teste ela roda sem ter o que fazer, e isso não prova nada sobre o
banco para o qual foi escrita. Aqui os desvios da produção são reproduzidos
dentro da transação do teste (coluna que aceita nulo, timestamp nulo, chave
estrangeira imediata) e o SQL da migração é executado de novo por cima.
"""

from __future__ import annotations

import importlib

import pytest
from django.db import DatabaseError, connection, transaction
from psycopg import sql as psycopg_sql
from psycopg.sql import Composable

from banking.models import FinancialInstitution
from core.esquema import diferencas as todas_as_diferencas
from transactions.models import CashFlowCategory

pytestmark = pytest.mark.django_db

SQL = importlib.import_module("core.migrations.0002_alinhar_esquema_de_producao").SQL


def _executar(comando: str | Composable, params: tuple[object, ...] | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(comando, params)


@pytest.fixture(autouse=True)
def coluna_que_a_producao_tinha():
    """A `0002` foi escrita quando `financial_account.is_default` existia.

    A coluna saiu na `banking/0003`; como o SQL da `0002` ainda a nomeia, ela
    volta aqui, dentro da transação do teste, como estava no banco a que a
    migração se destinava.
    """
    _executar("ALTER TABLE financial_account ADD COLUMN is_default boolean NOT NULL DEFAULT false")


def diferencas():
    """As diferenças do esquema, sem a coluna que a fixture devolveu de propósito."""
    return [d for d in todas_as_diferencas() if "is_default" not in d.onde]


def _chave_de(tabela: str, coluna: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT k.conname FROM pg_constraint k "
            "JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1] "
            "WHERE k.conrelid = %s::regclass AND k.contype = 'f' AND a.attname = %s",
            [tabela, coluna],
        )
        (nome,) = cursor.fetchone()
    return nome


def test_alinha_coluna_anulavel_timestamp_nulo_e_chave_imediata():
    # O DDL vem antes do INSERT: o PostgreSQL recusa ALTER TABLE com evento de
    # chave adiada pendente, e a migração tem de dar conta dos que o INSERT deixa.
    _executar("ALTER TABLE cash_flow_category ALTER COLUMN created_at DROP NOT NULL")
    _executar("ALTER TABLE cash_flow_entry ALTER COLUMN status DROP NOT NULL")
    chave = _chave_de("cash_flow_entry", "account_id")
    _executar(
        psycopg_sql.SQL("ALTER TABLE cash_flow_entry ALTER CONSTRAINT {} NOT DEFERRABLE").format(
            psycopg_sql.Identifier(chave)
        )
    )
    categoria = CashFlowCategory.objects.create(category_name="Sem data de criação", kind="gerencial")
    _executar("UPDATE cash_flow_category SET created_at = NULL WHERE id = %s", (categoria.id,))
    assert {d.tipo for d in diferencas()} == {"aceita nulo", "chave estrangeira imediata"}

    _executar(SQL)

    assert diferencas() == []
    categoria.refresh_from_db()
    assert categoria.created_at == categoria.updated_at


def test_nulo_onde_nao_ha_o_que_inventar_faz_a_migracao_falhar():
    _executar("ALTER TABLE financial_institution ALTER COLUMN institution_type DROP NOT NULL")
    instituicao = FinancialInstitution.objects.create(
        institution_name="Sem tipo", institution_type="Banco"
    )
    _executar("UPDATE financial_institution SET institution_type = NULL WHERE id = %s", (instituicao.id,))

    with pytest.raises(DatabaseError, match="institution_type"), transaction.atomic():
        _executar(SQL)

    # Nada do que a migração faria ficou pela metade.
    assert "financial_institution.institution_type" in {d.onde for d in diferencas()}
