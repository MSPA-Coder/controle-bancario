"""Refaz o rótulo "Conta Origem/Destino" de todas as transferências pelo nome atual das contas.

    python manage.py refazer_rotulos_de_transferencia --usuario NOME
    python manage.py refazer_rotulos_de_transferencia --usuario NOME --aplicar

Renomear titular, instituição ou conta já refaz os rótulos sozinho (ver
`transactions.rotulos`); este comando corrige o que ficou para trás antes disso.
Sem `--aplicar` é só a simulação: mostra quantos mudariam e alguns exemplos.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import AppUser
from core.models import AuditLog
from transactions.rotulos import atualizar_rotulos


class _SimulacaoError(Exception):
    pass


class Command(BaseCommand):
    help = "Refaz o rótulo das transferências pelo nome atual das contas."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True, help="Usuário que assina a auditoria.")
        parser.add_argument("--aplicar", action="store_true", help="Grava; sem isto é só simulação.")

    def handle(self, *args, usuario, aplicar, **options):
        try:
            user = AppUser.objects.get(username=usuario)
        except AppUser.DoesNotExist as exc:
            raise CommandError(f"Usuário \"{usuario}\" não existe.") from exc
        try:
            with transaction.atomic():
                n = atualizar_rotulos(None, user=user, motivo="Rótulos de transferência refeitos pelo nome atual das contas.")
                registro = AuditLog.objects.order_by("-id").first() if n else None
                if registro is not None:
                    for chave in list(registro.new_values_json)[:8]:
                        self.stdout.write(f"  {chave}: {registro.old_values_json[chave]!r} -> {registro.new_values_json[chave]!r}")
                self.stdout.write(f"{n} rótulo(s) de transferência {'refeito(s)' if aplicar else 'a refazer'}.")
                if not aplicar:
                    raise _SimulacaoError
        except _SimulacaoError:
            self.stdout.write("Simulação: nada foi gravado. Use --aplicar para gravar.")
