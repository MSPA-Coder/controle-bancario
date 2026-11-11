"""O verificador de esquema não acusa o banco das migrações e acusa o que se afasta dele.

O banco de teste nasce das migrações, então é o esquema que os modelos
declaram: ali `diferencas()` tem de voltar vazia, senão o verificador inventa
diferença e a lista que ele dá em produção não vale nada. Os outros testes
reproduzem, dentro da transação do teste, os desvios que a produção tem de
verdade e conferem que cada um aparece.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.db import connection
from psycopg import sql
from psycopg.sql import Composable

from core.esquema import diferencas

pytestmark = pytest.mark.django_db


def _executar(comando: str | Composable, params: tuple[object, ...] | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(comando, params)


def _tipos_em(onde: str) -> set[str]:
    return {d.tipo for d in diferencas() if d.onde == onde}


def test_banco_das_migracoes_nao_tem_diferenca():
    assert diferencas() == []


def test_coluna_que_passou_a_aceitar_nulo_aparece():
    _executar("ALTER TABLE cash_flow_entry ALTER COLUMN status DROP NOT NULL")

    assert _tipos_em("cash_flow_entry.status") == {"aceita nulo"}


def test_chave_estrangeira_imediata_aparece():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT k.conname FROM pg_constraint k "
            "JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1] "
            "WHERE k.conrelid = 'cash_flow_entry'::regclass AND k.contype = 'f' "
            "AND a.attname = 'account_id'"
        )
        (nome,) = cursor.fetchone()
    _executar(
        sql.SQL("ALTER TABLE cash_flow_entry ALTER CONSTRAINT {} NOT DEFERRABLE").format(
            sql.Identifier(nome)
        )
    )

    assert _tipos_em("cash_flow_entry.account_id") == {"chave estrangeira imediata"}


def test_tipo_de_coluna_diferente_aparece():
    _executar("ALTER TABLE login_lockout ALTER COLUMN identity_key TYPE text")

    assert _tipos_em("login_lockout.identity_key") == {"tipo"}


def test_tabela_e_coluna_que_nenhum_modelo_usa_aparecem():
    _executar("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
    _executar("ALTER TABLE app_permission ADD COLUMN sobra_do_legado timestamptz")

    assert _tipos_em("alembic_version") == {"tabela a mais"}
    assert _tipos_em("app_permission.sobra_do_legado") == {"coluna a mais"}


def test_comando_sai_com_erro_so_quando_ha_diferenca(capsys):
    call_command("conferir_esquema")
    assert "Nenhuma diferença" in capsys.readouterr().out

    _executar("ALTER TABLE cash_flow_entry ALTER COLUMN status DROP NOT NULL")
    with pytest.raises(SystemExit) as saida:
        call_command("conferir_esquema", "--resumo")

    assert saida.value.code == 1
    assert "aceita nulo" in capsys.readouterr().out
