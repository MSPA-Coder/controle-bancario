"""Processar a mesma fatura duas vezes ao mesmo tempo grava os lançamentos uma vez só.

A trava de linha em `fatura.processar` (`linhas_novas(lote).select_for_update()`) é a única coisa que impede a
segunda chamada de planejar sobre linhas já processadas: sem ela os lançamentos dobram.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import connections, transaction
from test_fatura_cartao import (
    FATURA_MARCO,
    _compra_anterior_no_mercado,
    _importar,
    _pagamento_de_300,
)
from test_fatura_cartao import cenario as cenario  # noqa: F401

from bank_statements import fatura
from transactions.models import CashFlowEntry

pytestmark = pytest.mark.django_db(transaction=True)


def _processar(c, lote_id, barreira):
    try:
        barreira.wait(timeout=10)
        fatura.processar(c["usuario"], lote_id, {})
        return None
    except ValueError as erro:
        return str(erro)
    finally:
        connections.close_all()


def test_fatura_processada_ao_mesmo_tempo_grava_uma_vez(cenario):
    _compra_anterior_no_mercado(cenario)
    _pagamento_de_300(cenario)
    lote, _, _ = _importar(cenario, FATURA_MARCO)
    cartao = cenario["cartao"]

    # Referência: o que um processamento sozinho grava. A transação é desfeita em seguida.
    with transaction.atomic():
        fatura.processar(cenario["usuario"], lote.id, {})
        esperado = CashFlowEntry.objects.filter(account=cartao).count()
        transaction.set_rollback(True)
    assert CashFlowEntry.objects.filter(account=cartao).count() < esperado

    barreira = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(_processar, cenario, lote.id, barreira) for _ in range(2)]
        resultados = [f.result(timeout=60) for f in futuros]

    assert CashFlowEntry.objects.filter(account=cartao).count() == esperado, resultados
