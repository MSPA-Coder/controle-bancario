"""Travas de linha: cada teste segura o estado em outra transação.

Padrão: a "primeira operação" muda o estado e fica aberta (sem confirmar). A operação testada precisa
esperar por ela e então enxergar o estado confirmado. Sem a trava, a operação testada decide com o
estado antigo e o resultado final é errado. Não depende de sorte de tempo: a primeira operação só
libera quando a segunda já esperou ou terminou.
"""

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date
from decimal import Decimal
from threading import Event

import pytest
from django.db import connection, connections, transaction
from test_extrato_integridade_postgres import entrada, lote
from test_gestao_persistida import cenario as cenario  # noqa: F401

from accounts.login_lockout import register_failed_login_attempt
from accounts.models import LoginLockout
from bank_statements import reconciliation
from bank_statements.models import LINE_STATUS_IGNORED, BankStatementLine
from core.domain.finance import ENTRY_TYPE_EXPENSE, STATUS_PROJECTED, STATUS_REALIZED
from core.services import update_recurring_projection_settings
from transactions.models import CashFlowEntry
from transactions.services import TransactionRequest, create_transaction_batch, realize_transaction

pytestmark = pytest.mark.django_db(transaction=True)


def com_primeira_operacao_aberta(testada, mexer_no_estado):
    """Roda `testada` enquanto `mexer_no_estado()` segura o estado; devolve (resultado, erro) da testada."""
    preparada, liberar = Event(), Event()

    def primeira():
        try:
            with transaction.atomic():
                mexer_no_estado()
                preparada.set()
                assert liberar.wait(timeout=10)
        finally:
            connections.close_all()

    def segunda():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '12s'")
            try:
                return testada(), None
            except Exception as erro:  # noqa: BLE001 - o teste confere o tipo
                return None, erro
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(primeira)
        assert preparada.wait(timeout=10)
        b = pool.submit(segunda)
        # Com a trava a segunda continua esperando; sem ela já terminou.
        wait([b], timeout=1.5)
        liberar.set()
        a.result(timeout=10)
        return b.result(timeout=10)


def test_falha_de_login_espera_a_outra_e_nao_perde_a_contagem():
    register_failed_login_attempt("alvo", "10.0.0.1")
    linha = LoginLockout.objects.get()
    assert linha.failure_count == 1

    com_primeira_operacao_aberta(
        lambda: register_failed_login_attempt("alvo", "10.0.0.1"),
        lambda: LoginLockout.objects.filter(pk=linha.pk).update(failure_count=2),
    )

    linha.refresh_from_db()
    assert linha.failure_count == 3


def test_linha_ignorada_por_outra_transacao_nao_vira_lancamento(cenario):
    linha = BankStatementLine.objects.filter(import_batch=lote(cenario)).order_by("id").first()
    antes = CashFlowEntry.objects.count()

    _, erro = com_primeira_operacao_aberta(
        lambda: reconciliation.create_entry_from_line(
            cenario.admin, line_id=linha.pk, category_id=cenario.categoria.pk
        ),
        lambda: BankStatementLine.objects.filter(pk=linha.pk).update(status=LINE_STATUS_IGNORED),
    )

    assert isinstance(erro, ValueError)
    assert CashFlowEntry.objects.count() == antes
    linha.refresh_from_db()
    assert linha.status == LINE_STATUS_IGNORED


def test_desfazer_importacao_espera_a_conciliacao_em_andamento_e_a_desfaz(cenario):
    importacao = lote(cenario)
    linha = BankStatementLine.objects.filter(import_batch=importacao).order_by("id").first()
    lancamento = entrada(cenario)

    resultado, erro = com_primeira_operacao_aberta(
        lambda: reconciliation.undo_statement_import(cenario.admin, batch_id=importacao.pk),
        lambda: reconciliation.reconcile_line_with_entry(cenario.admin, line_id=linha.pk, entry_id=lancamento.pk),
    )

    assert erro is None
    total_de_linhas, desfeitas = resultado
    assert desfeitas == 1
    assert total_de_linhas == 2
    assert not BankStatementLine.objects.filter(pk=linha.pk).exists()


# --- projeção recorrente: a trava consultiva que serializa a extensão e o recolhimento --------------------------


def _segurar_a_trava_da_projecao():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(81288431)")


@pytest.mark.parametrize("rotina", ["extensao", "recolhimento"])
def test_projecao_recorrente_espera_a_outra_rotina_terminar(cenario, rotina):
    from transactions.recurring_projection import (
        ensure_recurring_projection_horizon,
        recolher_alem_do_horizonte,
    )

    testada = ensure_recurring_projection_horizon if rotina == "extensao" else recolher_alem_do_horizonte
    preparada, liberar = Event(), Event()

    def outra_rotina():
        try:
            with transaction.atomic():
                _segurar_a_trava_da_projecao()
                preparada.set()
                assert liberar.wait(timeout=10)
        finally:
            connections.close_all()

    def rotina_testada():
        try:
            testada()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(outra_rotina)
        assert preparada.wait(timeout=10)
        b = pool.submit(rotina_testada)
        terminou_sem_esperar = bool(wait([b], timeout=1.5).done)
        liberar.set()
        a.result(timeout=10)
        b.result(timeout=20)

    assert not terminou_sem_esperar


def test_linha_travada_do_extrato_espera_e_recusa_a_linha_ignorada_por_outra_transacao(cenario):
    from bank_statements import extrato

    linha = BankStatementLine.objects.filter(import_batch=lote(cenario)).order_by("id").first()

    _, erro = com_primeira_operacao_aberta(
        lambda: _em_transacao(extrato._linha_travada, cenario.admin, linha.pk),
        lambda: BankStatementLine.objects.filter(pk=linha.pk).update(status=LINE_STATUS_IGNORED),
    )

    assert isinstance(erro, ValueError)


def _em_transacao(funcao, *args):
    with transaction.atomic():
        return funcao(*args)


# --- lançamento: outro escritor (sem trava da conta) segura o lançamento; as rotinas precisam esperar -------------


def _realizar_por_fora(lancamento_id):
    """Outra transação marca o lançamento como realizado e não confirma (escritor que não toma a trava da conta)."""
    CashFlowEntry.objects.filter(pk=lancamento_id).update(
        status=STATUS_REALIZED, realized_date=date.today(), realized_amount=Decimal("10")
    )


def _realizar(lancamento_id, admin):
    return _em_transacao(
        lambda: realize_transaction(CashFlowEntry.objects.get(pk=lancamento_id), user=admin)
    )


def test_realizar_espera_o_lancamento_e_recusa_o_que_outra_transacao_realizou(cenario):
    lancamento = entrada(cenario)

    _, erro = com_primeira_operacao_aberta(
        lambda: _realizar(lancamento.pk, cenario.admin), lambda: _realizar_por_fora(lancamento.pk)
    )

    assert isinstance(erro, ValueError)
    assert "já está realizado" in str(erro)


def test_realizar_parcela_espera_os_lancamentos_da_operacao_e_recusa_a_ja_realizada(cenario):
    parcelas = create_transaction_batch(
        TransactionRequest(
            account_id=cenario.conta.pk, category_id=cenario.categoria.pk, entry_type=ENTRY_TYPE_EXPENSE,
            description="Parcelas sintéticas", entry_amount=Decimal("20"), installments=2,
            due_date=date(2026, 9, 10), status=STATUS_PROJECTED,
        ),
        user=cenario.admin,
    )
    primeira = parcelas[0]
    assert primeira.bank_operation_id

    _, erro = com_primeira_operacao_aberta(
        lambda: _realizar(primeira.pk, cenario.admin), lambda: _realizar_por_fora(primeira.pk)
    )

    assert isinstance(erro, ValueError)
    assert "já está realizado" in str(erro)


def test_recolhimento_espera_o_lancamento_e_nao_apaga_o_que_outra_transacao_realizou(cenario):
    from transactions.recurring_projection import recolher_alem_do_horizonte

    update_recurring_projection_settings(horizon_months=12, run_day=28)
    hoje = date.today()
    linhas = create_transaction_batch(
        TransactionRequest(
            account_id=cenario.conta.pk, category_id=cenario.categoria.pk, entry_type=ENTRY_TYPE_EXPENSE,
            description="Série sintética", entry_amount=Decimal("10"), installments=1,
            due_date=date(hoje.year, hoje.month, 10), is_recurring=True, status=STATUS_PROJECTED,
        ),
        user=cenario.admin,
    )
    operacao = linhas[0].bank_operation_id
    ultima = CashFlowEntry.objects.filter(bank_operation_id=operacao).order_by("-due_date").first()

    resultado, erro = com_primeira_operacao_aberta(
        lambda: recolher_alem_do_horizonte(today=hoje, horizon_months=3), lambda: _realizar_por_fora(ultima.pk)
    )

    assert erro is None
    assert resultado.removed_count >= 1
    sobrevivente = CashFlowEntry.objects.filter(pk=ultima.pk).first()
    assert sobrevivente is not None
    assert sobrevivente.status == STATUS_REALIZED


def test_transferir_com_lancamento_espera_o_lancamento_e_recusa_o_que_outra_transacao_mudou(cenario):
    from types import SimpleNamespace

    from bank_statements import extrato

    linha = BankStatementLine.objects.filter(import_batch=lote(cenario)).order_by("id").first()
    existente = CashFlowEntry.objects.create(
        account=cenario.conta, category=cenario.categoria, entry_type=ENTRY_TYPE_EXPENSE,
        description="Lançamento já gravado", entry_amount=abs(linha.amount), due_date=linha.statement_date,
        status=STATUS_REALIZED, realized_date=linha.statement_date, realized_amount=abs(linha.amount),
    )
    plano = SimpleNamespace(linha=linha, lancamento=existente)

    _, erro = com_primeira_operacao_aberta(
        lambda: _em_transacao(extrato._aplicar_com_lancamento, cenario.admin, plano, None, False),
        lambda: CashFlowEntry.objects.filter(pk=existente.pk).update(status=STATUS_PROJECTED, realized_amount=None),
    )

    assert isinstance(erro, ValueError)
    assert "mudou desde a prévia" in str(erro)
