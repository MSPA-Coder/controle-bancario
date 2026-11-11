"""A sessão da aplicação nasce com limite de consulta, de lock e de transação ociosa.

Os valores vêm de `DATABASES['default']['OPTIONS']['options']` e só valem se o
PostgreSQL os aceitar na conexão. A pergunta é feita ao servidor, numa conexão
nova: é ele quem cumpre o limite.
"""

from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


def _limites() -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT name, setting::int FROM pg_settings WHERE name IN "
            "('statement_timeout', 'lock_timeout', 'idle_in_transaction_session_timeout')"
        )
        return dict(cursor.fetchall())


def test_a_sessao_tem_os_tres_limites_ligados():
    limites = _limites()

    assert all(valor > 0 for valor in limites.values()), limites
    # A consulta tem de ser cortada antes de o Gunicorn desistir da requisição (60 s).
    assert limites["statement_timeout"] < 60_000
