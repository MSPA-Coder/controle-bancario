"""Disputas reais por lançamentos e fechamento, sem substituir os locks."""

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import suppress
from datetime import date
from decimal import Decimal
from threading import Barrier, Event

import pytest
import test_conciliacao_transferir
from django.db import connection, connections, transaction
from test_extrato_integridade_postgres import arquivo, entrada
from test_gestao_persistida import cenario as cenario

from bank_statements import reconciliation
from bank_statements import services as statement_services
from bank_statements.models import BankStatementLine
from bank_statements.reconciliation import reconcile_line_with_entry
from bank_statements.services import import_statement_file
from core.domain.finance import ENTRY_TYPE_EXPENSE, STATUS_PROJECTED, STATUS_REALIZED
from transactions import services as t
from transactions.models import CashFlowEntry
from transactions.recurring_projection import (
    recolher_alem_do_horizonte,
    recurring_projection_horizon_end,
)

pytestmark = pytest.mark.django_db(transaction=True)
cenario_transferencia = test_conciliacao_transferir.cenario


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


def test_reimportacoes_simultaneas_contam_duplicatas_sem_erro(cenario, monkeypatch):
    primeiro_leu, liberar = Event(), Event()
    ler = statement_services._existing_line_hashes

    def ler_com_pausa(*args):
        existentes = ler(*args)
        if not primeiro_leu.is_set():
            primeiro_leu.set()
            if not liberar.wait(10):
                raise AssertionError("primeira importação não foi liberada")
        return existentes

    monkeypatch.setattr(statement_services, "_existing_line_hashes", ler_com_pausa)

    def importar():
        try:
            _lote, inseridas, repetidas = import_statement_file(
                cenario.admin, account_id=cenario.conta.pk, uploaded_file=arquivo(),
            )
            return inseridas, repetidas
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        primeiro = pool.submit(importar)
        assert primeiro_leu.wait(10)
        segundo = pool.submit(importar)
        try:
            with suppress(TimeoutError):
                segundo.result(timeout=1)
        finally:
            liberar.set()
        assert sorted([primeiro.result(timeout=15), segundo.result(timeout=15)]) == [(0, 2), (2, 0)]
    assert BankStatementLine.objects.count() == 2


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


def test_transferencias_opostas_de_extratos_nao_travam_entre_si(cenario_transferencia, monkeypatch):
    _cliente, user, contas, _categorias = cenario_transferencia
    primeira = test_conciliacao_transferir._linha(contas["real"], "Transferência A", "-10", 1)
    segunda = test_conciliacao_transferir._linha(contas["mp"], "Transferência B", "-20", 1)
    barreira = Barrier(2)
    obter_linha = reconciliation._get_line_in_scope

    def obter_e_sincronizar(*args, **kwargs):
        linha = obter_linha(*args, **kwargs)
        barreira.wait(timeout=8)
        return linha

    monkeypatch.setattr(reconciliation, "_get_line_in_scope", obter_e_sincronizar)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [
            pool.submit(executar, lambda: reconciliation.transfer_from_line(
                user, line_id=primeira.id, other_account_id=contas["mp"].id)),
            pool.submit(executar, lambda: reconciliation.transfer_from_line(
                user, line_id=segunda.id, other_account_id=contas["real"].id)),
        ]
        assert [f.result(timeout=20) for f in futuros] == [None, None]
    assert CashFlowEntry.objects.count() == 4
    assert BankStatementLine.objects.filter(status="conciliado").count() == 2


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


def test_conta_alterada_antes_do_lock_nao_permite_realizacao_contra_fechamento(cenario, monkeypatch):
    lancamento = entrada(cenario)
    descobriu, prosseguir = Event(), Event()
    descobrir = t._entry_graph_ids

    def descobrir_com_pausa(item):
        resultado = descobrir(item)
        if not descobriu.is_set():
            descobriu.set()
            assert prosseguir.wait(10)
        return resultado

    monkeypatch.setattr(t, "_entry_graph_ids", descobrir_com_pausa)

    def realizar():
        t.realize_transaction(CashFlowEntry.objects.get(pk=lancamento.pk), date(2026, 9, 10), Decimal("10"), user=cenario.admin)

    with ThreadPoolExecutor(max_workers=1) as pool:
        futuro = pool.submit(executar, realizar)
        try:
            assert descobriu.wait(10)
            req = t.TransactionRequest(account_id=cenario.dolar.pk, category_id=cenario.categoria.pk,
                entry_type=ENTRY_TYPE_EXPENSE, description="Operação sintética", entry_amount=Decimal("10"),
                installments=1, due_date=date(2026, 9, 10), status=STATUS_PROJECTED)
            t.update_transaction_operation(CashFlowEntry.objects.get(pk=lancamento.pk), req, user=cenario.admin)
            with transaction.atomic():
                fechamento = t.close_month(cenario.dolar, 2026, 9, None, cenario.admin)
                prosseguir.set()
                with pytest.raises(TimeoutError):
                    futuro.result(timeout=1)
            erro = futuro.result(timeout=10)
            assert erro is not None
        finally:
            prosseguir.set()
    lancamento.refresh_from_db()
    assert lancamento.account_id == cenario.dolar.pk and lancamento.status != STATUS_REALIZED
    assert fechamento.closing_balance == Decimal("0")


def test_recolhimento_aguarda_fechamento_e_preserva_mes_fechado(cenario):
    from core.services import update_recurring_projection_settings

    hoje = date.today()
    update_recurring_projection_settings(horizon_months=12, run_day=28)
    linhas = t.create_transaction_batch(t.TransactionRequest(
        account_id=cenario.conta.pk, category_id=cenario.categoria.pk, entry_type=ENTRY_TYPE_EXPENSE,
        description="Recorrência sintética", entry_amount=Decimal("10"), installments=1,
        due_date=hoje, is_recurring=True, status=STATUS_PROJECTED), user=cenario.admin)
    fim = recurring_projection_horizon_end(hoje, 3)
    protegida = CashFlowEntry.objects.filter(bank_operation_id=linhas[0].bank_operation_id,
                                            due_date__gt=fim).order_by("-due_date").first()
    assert protegida is not None
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            t.close_month(cenario.conta, protegida.due_date.year, protegida.due_date.month, None, cenario.admin)
            futuro = pool.submit(executar, lambda: recolher_alem_do_horizonte(today=hoje, horizon_months=3))
            with pytest.raises(TimeoutError):
                futuro.result(timeout=1)
        assert futuro.result(timeout=15) is None
    assert CashFlowEntry.objects.filter(pk=protegida.pk).exists()
