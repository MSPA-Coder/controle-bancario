"""Conexão persistente que o PostgreSQL encerrou não derruba a requisição seguinte.

Com `CONN_MAX_AGE`, cada worker guarda a conexão entre requisições. Em
01/11/2026 um `run --rm web` no VPS passou pelo `db-provision`/`migrate`, o
servidor encerrou as conexões abertas e o `web` respondeu 500 (AdminShutdown)
até cada worker descartar a sua. `CONN_HEALTH_CHECKS` faz o Django testar a
conexão no início da requisição e reconectar.

O teste encerra a conexão de verdade, por `pg_terminate_backend` a partir de
outra conexão, e dispara `request_started` -- o que o handler WSGI faz no
início de toda requisição. O cliente de teste do Django desliga esse receptor
durante as próprias requisições, por isso o sinal vai à mão. O controle, com a
checagem desligada, mostra que sem ela a consulta seguinte falha: o teste não
passa por acaso.
"""

from __future__ import annotations

import pytest
from django.core.handlers.wsgi import WSGIHandler
from django.core.signals import request_started
from django.db import OperationalError, connections

pytestmark = pytest.mark.django_db(transaction=True)


def _encerrar_pelo_servidor(conexao) -> None:
    with conexao.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        pid = cursor.fetchone()[0]
    outra = connections.create_connection("default")
    try:
        with outra.cursor() as cursor:
            # O segundo argumento espera o processo sair; sem ele haveria
            # corrida entre o sinal e a consulta seguinte.
            cursor.execute("SELECT pg_terminate_backend(%s, 5000)", [pid])
            assert cursor.fetchone()[0] is True
    finally:
        outra.close()


def _consultar(conexao):
    with conexao.cursor() as cursor:
        cursor.execute("SELECT 1")
        return cursor.fetchone()


def test_configuracao_liga_a_checagem_e_mantem_a_persistencia():
    conexao = connections["default"]
    assert conexao.settings_dict["CONN_MAX_AGE"] > 0
    assert conexao.settings_dict["CONN_HEALTH_CHECKS"] is True


def test_requisicao_seguinte_reconecta_quando_o_servidor_encerrou_a_conexao():
    conexao = connections["default"]
    _consultar(conexao)
    assert conexao.health_check_enabled is True

    _encerrar_pelo_servidor(conexao)
    request_started.send(sender=WSGIHandler)

    assert _consultar(conexao) == (1,)


def test_sem_a_checagem_a_conexao_encerrada_falha():
    conexao = connections["default"]
    _consultar(conexao)
    conexao.health_check_enabled = False
    try:
        _encerrar_pelo_servidor(conexao)
        request_started.send(sender=WSGIHandler)

        with pytest.raises(OperationalError):
            _consultar(conexao)
    finally:
        conexao.close()
