"""Apaga da outbox do v4 o que passou da retenção (30 dias por padrão).

    python manage.py expurgar_outbox_v4
    python manage.py expurgar_outbox_v4 --dias 60

Roda a cada deploy, no serviço `migrate`, depois do `clearsessions`. A linha
mais nova nunca sai; o motivo de isso bastar para os consumidores do contrato
está em `core/outbox.py`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.outbox import DIAS_DE_RETENCAO, expurgar_outbox_v4


class Command(BaseCommand):
    help = "Apaga da outbox do contrato patrimônio v4 as linhas mais velhas que a retenção."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias", type=int, default=DIAS_DE_RETENCAO,
            help=f"Retenção em dias (padrão {DIAS_DE_RETENCAO}).",
        )

    def handle(self, *args, dias, **options):
        with transaction.atomic():
            apagadas = expurgar_outbox_v4(timezone.now(), dias)
        self.stdout.write(f"Outbox v4: {apagadas} linha(s) removida(s).")
