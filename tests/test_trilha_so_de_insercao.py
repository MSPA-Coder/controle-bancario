"""O papel da aplicação insere na trilha de auditoria e não a altera nem apaga.

A suíte conecta como superusuário, que o gatilho deixa passar de propósito. Para
ver a recusa, cada teste cria um papel comum com os mesmos privilégios de DML
que a aplicação tem e troca para ele dentro da transação do teste.
"""

from __future__ import annotations

import pytest
from django.db import DatabaseError, connection, transaction

from core.models import AuditLog

pytestmark = pytest.mark.django_db

PAPEL = "papel_comum_do_teste"


def _executar(sql: str, parametros=None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, parametros)


@pytest.fixture
def registro():
    return AuditLog.objects.create(entity_name="cash_flow_entry", entity_id="1", action="create")


@pytest.fixture
def como_papel_comum(registro):
    _executar(f"CREATE ROLE {PAPEL}")
    _executar(f"GRANT SELECT, INSERT, UPDATE, DELETE ON audit_log, app_user TO {PAPEL}")
    _executar(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {PAPEL}")
    _executar(f"SET LOCAL ROLE {PAPEL}")
    yield
    _executar("RESET ROLE")


def test_papel_comum_nao_altera_registro(registro, como_papel_comum):
    with pytest.raises(DatabaseError, match="apenas insercao"), transaction.atomic():
        _executar("UPDATE audit_log SET action = 'outra' WHERE id = %s", [registro.id])


def test_papel_comum_nao_apaga_registro(registro, como_papel_comum):
    with pytest.raises(DatabaseError, match="apenas insercao"), transaction.atomic():
        _executar("DELETE FROM audit_log WHERE id = %s", [registro.id])


def test_papel_comum_continua_inserindo(como_papel_comum):
    _executar(
        "INSERT INTO audit_log (entity_name, action, created_at, actor_name, request_id, result, summary) "
        "VALUES ('cash_flow_entry', 'create', now(), '', '', 'success', '')"
    )


def test_anular_o_usuario_do_registro_passa_e_mais_nada(registro, como_papel_comum):
    """É o que o `SET NULL` da chave faz quando um usuário é apagado."""
    _executar("UPDATE audit_log SET user_id = NULL WHERE id = %s", [registro.id])

    with pytest.raises(DatabaseError, match="apenas insercao"), transaction.atomic():
        _executar("UPDATE audit_log SET user_id = NULL, summary = 'mexido' WHERE id = %s", [registro.id])


def test_administrador_ainda_corrige_e_expurga(registro):
    AuditLog.objects.filter(id=registro.id).update(summary="corrigido pelo administrador")
    AuditLog.objects.filter(id=registro.id).delete()

    assert not AuditLog.objects.filter(id=registro.id).exists()
