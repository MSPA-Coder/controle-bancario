"""Extrato real: reprocessamento, conciliação, saldo e rollback no PostgreSQL."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from test_gestao_persistida import cenario as cenario

from accounts.models import UserOwnerAccess
from bank_statements import reconciliation as r
from bank_statements.models import BankStatementImport, BankStatementLine
from bank_statements.services import conferencia_de_saldo, import_statement_file
from core.domain.finance import (
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_PROJECTED,
    STATUS_REALIZED,
    VIEW_REALIZED,
)
from reports.services import decimal_balances_before_by_account
from transactions import services as t
from transactions.models import CashFlowEntry

pytestmark = pytest.mark.django_db


def arquivo(conteudo=None):
    return SimpleUploadedFile("extrato.csv", conteudo or b"data;descricao;valor\n2026-09-10;Compra;-10,00\n2026-09-11;Tarifa;-2,00\n", content_type="text/csv")


def entrada(c, *, valor="10", dia=date(2026, 9, 10), conta=None, tipo=ENTRY_TYPE_EXPENSE):
    return t.create_transaction_batch(t.TransactionRequest(
        account_id=(conta or c.conta).pk, category_id=c.categoria.pk, entry_type=tipo,
        description="Operação sintética", entry_amount=Decimal(valor), installments=1,
        due_date=dia, status=STATUS_PROJECTED), user=c.admin)[0]


def lote(c):
    return import_statement_file(c.admin, account_id=c.conta.pk, uploaded_file=arquivo())[0]


@contextmanager
def recusar_no_banco(tabela, expressao):
    nome = "qa_integridade_" + uuid4().hex
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(f"ALTER TABLE {tabela} ADD CONSTRAINT {nome} CHECK ({expressao}) NOT VALID")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {tabela} DROP CONSTRAINT {nome}")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def test_reimportar_depois_de_conciliar_preserva_vinculos_e_nao_duplica_caixa(cenario):
    batch = lote(cenario)
    linhas = list(BankStatementLine.objects.filter(import_batch=batch).order_by("statement_date"))
    lancamento = entrada(cenario)
    r.reconcile_line_with_entry(cenario.admin, line_id=linhas[0].pk, entry_id=lancamento.pk)
    novo, inseridas, duplicadas = import_statement_file(cenario.admin, account_id=cenario.conta.pk, uploaded_file=arquivo())
    assert (inseridas, duplicadas, novo.row_count) == (0, 2, 0)
    assert BankStatementLine.objects.count() == 2 and CashFlowEntry.objects.count() == 1
    linhas[0].refresh_from_db()
    lancamento.refresh_from_db()
    assert linhas[0].matched_entry_id == lancamento.pk and linhas[0].status == "conciliado"
    assert lancamento.realized_amount == Decimal("10")
    with pytest.raises(ValueError):
        r.reconcile_line_with_entry(cenario.admin, line_id=linhas[0].pk, entry_id=lancamento.pk)
    assert decimal_balances_before_by_account([cenario.conta.pk], date(2026, 10, 1), VIEW_REALIZED)[cenario.conta.pk] == Decimal("-10")


def test_erro_real_na_importacao_desfaz_lote_e_todas_as_linhas(cenario):
    with recusar_no_banco("bank_statement_line", "amount <> -2"), pytest.raises(IntegrityError):
        lote(cenario)
    assert BankStatementImport.objects.count() == BankStatementLine.objects.count() == 0
    assert lote(cenario).row_count == 2


def test_erro_ao_realizar_desfaz_vinculo_e_retry_concilia(cenario):
    batch = lote(cenario)
    linha = BankStatementLine.objects.get(import_batch=batch, amount=-10)
    lancamento = entrada(cenario)
    with (
        recusar_no_banco("cash_flow_entry", f"id <> {lancamento.pk} OR realized_amount IS NULL OR realized_amount < 10"),
        pytest.raises(IntegrityError),
    ):
        r.reconcile_line_with_entry(cenario.admin, line_id=linha.pk, entry_id=lancamento.pk)
    linha.refresh_from_db()
    lancamento.refresh_from_db()
    assert linha.status == "novo" and linha.matched_entry_id is None
    assert lancamento.status != STATUS_REALIZED and lancamento.realized_amount is None
    r.reconcile_line_with_entry(cenario.admin, line_id=linha.pk, entry_id=lancamento.pk)
    lancamento.refresh_from_db()
    assert lancamento.realized_amount == Decimal("10")


@pytest.mark.parametrize("erro", ["valor", "sinal", "conta", "titular_leitura"])
def test_recusa_de_conciliacao_preserva_linha_e_lancamento(cenario, erro):
    batch = lote(cenario)
    linha = BankStatementLine.objects.get(import_batch=batch, amount=-10)
    lancamento = entrada(cenario, valor="11" if erro == "valor" else "10",
                          conta=cenario.dolar if erro == "conta" else None,
                          tipo=ENTRY_TYPE_INCOME if erro == "sinal" else ENTRY_TYPE_EXPENSE)
    usuario = cenario.admin
    if erro == "titular_leitura":
        usuario = cenario.restrito
        UserOwnerAccess.objects.create(user=usuario, owner=cenario.dono, can_view=True, can_update=False)
    with pytest.raises(ValueError):
        r.reconcile_line_with_entry(usuario, line_id=linha.pk, entry_id=lancamento.pk)
    linha.refresh_from_db()
    lancamento.refresh_from_db()
    assert linha.status == "novo" and linha.matched_entry_id is None
    assert lancamento.status != STATUS_REALIZED and lancamento.realized_date is None


def test_lote_desfeito_preserva_lancamento_criado_e_permite_reimportar(cenario):
    batch = lote(cenario)
    linha = BankStatementLine.objects.get(import_batch=batch, amount=-10)
    reconciliada = r.create_entry_from_line(cenario.admin, line_id=linha.pk, category_id=cenario.categoria.pk)
    eid = reconciliada.matched_entry_id
    assert r.undo_statement_import(cenario.admin, batch_id=batch.pk) == (2, 1)
    assert not BankStatementImport.objects.exists() and not BankStatementLine.objects.exists()
    lancamento = CashFlowEntry.objects.get(pk=eid)
    assert lancamento.status != STATUS_REALIZED and lancamento.realized_amount is None
    novo = lote(cenario)
    nova_linha = BankStatementLine.objects.get(import_batch=novo, amount=-10)
    r.reconcile_line_with_entry(cenario.admin, line_id=nova_linha.pk, entry_id=eid)
    assert CashFlowEntry.objects.count() == 1


def test_desfazer_lote_em_mes_fechado_recusa_sem_perder_linhas(cenario):
    batch = lote(cenario)
    for linha in BankStatementLine.objects.filter(import_batch=batch):
        r.create_entry_from_line(cenario.admin, line_id=linha.pk, category_id=cenario.categoria.pk)
    t.close_month(cenario.conta, 2026, 9, None, cenario.admin)
    with pytest.raises(ValueError):
        r.undo_statement_import(cenario.admin, batch_id=batch.pk)
    assert BankStatementImport.objects.filter(pk=batch.pk).exists()
    assert BankStatementLine.objects.filter(status="conciliado").count() == 2
    assert CashFlowEntry.objects.filter(status=STATUS_REALIZED).count() == 2


def test_conferencia_detecta_divergencia_e_atualiza_apos_conciliar(cenario):
    batch = lote(cenario)
    batch.statement_balance = Decimal("-10")
    batch.statement_balance_date = date(2026, 9, 30)
    batch.save()
    antes = conferencia_de_saldo(batch)
    assert not antes.bate and antes.diferenca == Decimal("10")
    linha = BankStatementLine.objects.get(import_batch=batch, amount=-10)
    r.create_entry_from_line(cenario.admin, line_id=linha.pk, category_id=cenario.categoria.pk)
    depois = conferencia_de_saldo(batch)
    assert depois.bate and depois.saldo_no_cb == Decimal("-10")


@pytest.mark.parametrize("acao", ["importar", "criar", "ignorar", "desfazer_lote"])
def test_operacoes_exigem_permissao_adequada_sem_escrita(cenario, acao):
    batch = lote(cenario)
    linha = BankStatementLine.objects.get(import_batch=batch, amount=-10)
    UserOwnerAccess.objects.create(user=cenario.restrito, owner=cenario.dono, can_view=True,
                                   can_create=False, can_update=False, can_delete=False)
    operacoes = {
        "importar": lambda: import_statement_file(cenario.restrito, account_id=cenario.conta.pk, uploaded_file=arquivo()),
        "criar": lambda: r.create_entry_from_line(cenario.restrito, line_id=linha.pk, category_id=cenario.categoria.pk),
        "ignorar": lambda: r.ignore_statement_line(cenario.restrito, line_id=linha.pk),
        "desfazer_lote": lambda: r.undo_statement_import(cenario.restrito, batch_id=batch.pk),
    }
    with pytest.raises(ValueError):
        operacoes[acao]()
    assert CashFlowEntry.objects.count() == 0
    assert BankStatementImport.objects.count() == 1
    assert BankStatementLine.objects.filter(status="novo").count() == 2
