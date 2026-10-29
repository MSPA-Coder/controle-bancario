"""Recalcula o status derivado das operações; simula por padrão."""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.domain.finance import STATUS_PENDING, STATUS_PROJECTED, STATUS_REALIZED
from core.services import log_audit_event
from transactions.models import BankOperation, CashFlowEntry
from transactions.services import _lock_accounts


class Command(BaseCommand):
    help = "Confere ou corrige o status resumido das operações a partir de suas ocorrências."

    def add_arguments(self, parser):
        identidade = parser.add_mutually_exclusive_group(required=True)
        identidade.add_argument("--usuario", help="Administrador responsável pela auditoria.")
        identidade.add_argument("--sistema", action="store_true", help="Registra a correção como ação automatizada.")
        parser.add_argument("--aplicar", action="store_true", help="Grava as correções; sem esta opção apenas confere.")

    def handle(self, *args, usuario, sistema, aplicar, **options):
        user = None if sistema else get_user_model().objects.filter(
            username=usuario, user_type="administrator", is_active=True,
        ).first()
        if not sistema and user is None:
            raise CommandError("Informe um administrador ativo para a auditoria.")
        with transaction.atomic():
            contas = set(CashFlowEntry.objects.filter(bank_operation__isnull=False).values_list("account_id", flat=True))
            _lock_accounts(contas)
            operacoes = list(BankOperation.objects.select_for_update().order_by("id"))
            estados = defaultdict(set)
            for operation_id, account_id, status in CashFlowEntry.objects.filter(
                bank_operation__isnull=False
            ).values_list("bank_operation_id", "account_id", "status"):
                if account_id not in contas:
                    raise CommandError("As contas mudaram durante a conferência; tente novamente.")
                estados[operation_id].add(status)
            alteradas = 0
            for operacao in operacoes:
                statuses = estados.get(operacao.pk)
                if not statuses:
                    continue
                esperado = (STATUS_REALIZED if statuses == {STATUS_REALIZED}
                            else STATUS_PENDING if STATUS_PENDING in statuses else STATUS_PROJECTED)
                if operacao.status == esperado:
                    continue
                alteradas += 1
                if aplicar:
                    anterior = operacao.status
                    operacao.status = esperado
                    operacao.updated_at = timezone.now()
                    operacao.save(update_fields=["status", "updated_at"])
                    log_audit_event("bank_operation", operacao.id, "update", user=user,
                                    old_values={"status": anterior}, new_values={"status": esperado},
                                    summary="Status da operação recalculado a partir das ocorrências"
                                            + (" (ação automatizada)." if sistema else "."))
        self.stdout.write(f"{alteradas} operação(ões) {'corrigida(s)' if aplicar else 'divergente(s)'}.")
        if not aplicar:
            self.stdout.write("Simulação: nada foi gravado.")
