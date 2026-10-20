"""Disputas reais por lançamentos e fechamento, sem substituir os locks."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import connection, connections, transaction
from test_extrato_integridade_postgres import arquivo, entrada
from test_gestao_persistida import cenario as cenario

from bank_statements.models import BankStatementLine
from bank_statements.reconciliation import reconcile_line_with_entry
from bank_statements.services import import_statement_file
from core.domain.finance import STATUS_REALIZED
from transactions import services as t
from transactions.models import CashFlowEntry

pytestmark = pytest.mark.django_db(transaction=True)


def executar(acao, barreira=None):
    """Cada worker usa conexão própria, timeout e fechamento garantido."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '12s'")
            cursor.execute("SET lock_timeout = '10s'")
        if barreira:
            barreira.wait(timeout=10)
        try:
            acao()
        except ValueError as erro:
            return str(erro)
        return None
    finally:
        connections.close_all()


def disputar(acao_a, acao_b):
    barreira = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(executar, acao, barreira) for acao in (acao_a, acao_b)]
        resultados = [f.result(timeout=20) for f in futuros]
    assert resultados.count(None) == 1
    return next(r for r in resultados if r is not None)


def test_duas_linhas_concorrentes_nao_realizam_o_mesmo_lancamento_duas_vezes(cenario):
    batch = import_statement_file(cenario.admin, account_id=cenario.conta.pk, uploaded_file=arquivo(
        b"data;descricao;valor\n2026-09-10;Compra A;-10,00\n2026-09-10;Compra B;-10,00\n"))[0]
    linhas = list(BankStatementLine.objects.filter(import_batch=batch).order_by("id"))
    lancamento = entrada(cenario)
    erro = disputar(*[
        lambda lid=linha.pk: reconcile_line_with_entry(cenario.admin, line_id=lid, entry_id=lancamento.pk)
        for linha in linhas
    ])
    assert "conciliado" in erro
    lancamento.refresh_from_db()
    assert lancamento.status == STATUS_REALIZED and lancamento.realized_amount == Decimal("10")
    assert BankStatementLine.objects.filter(matched_entry=lancamento, status="conciliado").count() == 1
    assert BankStatementLine.objects.filter(status="novo", matched_entry=None).count() == 1
    assert CashFlowEntry.objects.count() == 1


def test_realizacao_simultanea_recusa_segunda_escrita(cenario):
    lancamento = entrada(cenario)

    def realizar():
        t.realize_transaction(CashFlowEntry.objects.get(pk=lancamento.pk), date(2026, 9, 10), Decimal("10"), user=cenario.admin)

    assert "já está realizado" in disputar(realizar, realizar)
    lancamento.refresh_from_db()
    assert lancamento.status == STATUS_REALIZED and lancamento.realized_amount == Decimal("10")


def test_fechamentos_simultaneos_criam_um_unico_registro(cenario):
    def fechar():
        t.close_month(cenario.conta, 2026, 9, None, cenario.admin)

    assert "já está fechado" in disputar(fechar, fechar)
    fechamento = cenario.conta.month_closes.get(year=2026, month=9)
    assert fechamento.active and fechamento.closing_balance == Decimal("0")


@pytest.mark.parametrize("fechar_primeiro", [False, True])
def test_fechamento_e_realizacao_serializam_saldo_e_bloqueio(cenario, fechar_primeiro):
    lancamento = entrada(cenario)
    status_inicial = lancamento.status

    def realizar():
        t.realize_transaction(CashFlowEntry.objects.get(pk=lancamento.pk), date(2026, 9, 10), Decimal("10"), user=cenario.admin)

    def fechar():
        t.close_month(cenario.conta, 2026, 9, None, cenario.admin)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pid = cursor.fetchone()[0]
            (fechar if fechar_primeiro else realizar)()
            futuro = pool.submit(executar, realizar if fechar_primeiro else fechar)
            bloqueada = False
            limite = time.monotonic() + 8
            while time.monotonic() < limite:
                with connection.cursor() as cursor:
                    # As estatísticas têm snapshot por transação; o worker
                    # pode ter conectado depois da primeira observação.
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid)))", [pid])
                    bloqueada = cursor.fetchone()[0]
                if bloqueada:
                    break
                time.sleep(0.02)
        erro = futuro.result(timeout=15)
    assert bloqueada, "O PostgreSQL precisa ter observado a disputa real pela conta."
    lancamento.refresh_from_db()
    fechamento = cenario.conta.month_closes.get(year=2026, month=9)
    if fechar_primeiro:
        assert erro and "fechado" in erro
        assert lancamento.status == status_inicial and lancamento.realized_amount is None
        assert fechamento.closing_balance == Decimal("0")
    else:
        assert erro is None and lancamento.status == STATUS_REALIZED
        assert fechamento.closing_balance == Decimal("-10")
