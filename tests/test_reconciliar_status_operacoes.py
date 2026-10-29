"""Reparo auditado de status derivados, com simulação por padrão."""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from test_gestao_persistida import cenario as cenario

from core.domain.finance import ENTRY_TYPE_EXPENSE, STATUS_PROJECTED, STATUS_REALIZED
from core.models import AuditLog
from transactions import services
from transactions.models import BankOperation

pytestmark = pytest.mark.django_db


def test_simular_corrigir_e_repetir_sem_mexer_nas_ocorrencias(cenario):
    linhas = services.create_transaction_batch(services.TransactionRequest(
        account_id=cenario.conta.pk, category_id=cenario.categoria.pk, entry_type=ENTRY_TYPE_EXPENSE,
        description="Série sintética", entry_amount=Decimal("10"), installments=3,
        due_date=date.today(), status=STATUS_PROJECTED), user=cenario.admin)
    operacao = BankOperation.objects.get(pk=linhas[0].bank_operation_id)
    BankOperation.objects.filter(pk=operacao.pk).update(status=STATUS_REALIZED)
    antes = list(operacao.entries.order_by("id").values_list("id", "status", "entry_amount"))
    saida = StringIO()
    call_command("reconciliar_status_operacoes", usuario=cenario.admin.username, stdout=saida)
    operacao.refresh_from_db()
    assert operacao.status == STATUS_REALIZED
    assert "1 operação(ões) divergente(s)" in saida.getvalue()
    call_command("reconciliar_status_operacoes", usuario=cenario.admin.username, aplicar=True, stdout=StringIO())
    operacao.refresh_from_db()
    assert operacao.status == STATUS_PROJECTED
    assert list(operacao.entries.order_by("id").values_list("id", "status", "entry_amount")) == antes
    auditoria = AuditLog.objects.filter(entity_name="bank_operation", entity_id=str(operacao.id), action="update")
    assert auditoria.count() == 1
    assert auditoria.first().old_values_json == {"status": STATUS_REALIZED}
    assert auditoria.first().new_values_json == {"status": STATUS_PROJECTED}
    call_command("reconciliar_status_operacoes", usuario=cenario.admin.username, aplicar=True, stdout=StringIO())
    assert auditoria.count() == 1


def test_correcao_automatizada_nao_se_atribui_a_um_usuario(cenario):
    linhas = services.create_transaction_batch(services.TransactionRequest(
        account_id=cenario.conta.pk, category_id=cenario.categoria.pk, entry_type=ENTRY_TYPE_EXPENSE,
        description="Série sintética", entry_amount=Decimal("10"), installments=3,
        due_date=date.today(), status=STATUS_PROJECTED), user=cenario.admin)
    operacao = BankOperation.objects.get(pk=linhas[0].bank_operation_id)
    BankOperation.objects.filter(pk=operacao.pk).update(status=STATUS_REALIZED)
    call_command("reconciliar_status_operacoes", sistema=True, aplicar=True, stdout=StringIO())
    registro = AuditLog.objects.get(entity_name="bank_operation", entity_id=str(operacao.id), action="update")
    assert registro.user is None and "ação automatizada" in registro.summary
