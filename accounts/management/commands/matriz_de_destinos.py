"""Completa a matriz Usuário × conta destino a partir das transferências existentes.

    python manage.py matriz_de_destinos
    python manage.py matriz_de_destinos --aplicar

Sem `--aplicar` é só a simulação. Só acrescenta concessões (ver
`accounts.matriz_de_destinos`) e cada usuário alterado vai para a auditoria.
Faça o backup do banco antes de aplicar em dados reais
(`python cli.py backup --projeto controle_bancario --tipos banco`).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from accounts import matriz_de_destinos
from banking.models import FinancialAccount


class Command(BaseCommand):
    help = "Simula ou grava as concessões de destino de transferência que o histórico já pressupõe."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Grava; sem isto é só simulação.")

    def handle(self, *args, aplicar, **options):
        contas = {
            conta.id: f"{conta.owner.name} / {conta.institution.institution_name} / {conta.account_name}"
            for conta in FinancialAccount.objects.select_related("owner", "institution")
        }
        proposta = matriz_de_destinos.propor()
        for usuario, novos in proposta.items():
            self.stdout.write(f"{usuario.username}: +{len(novos)}")
            for conta_id in sorted(novos):
                self.stdout.write(f"    {conta_id:>3}  {contas[conta_id]}")
        if not proposta:
            self.stdout.write("A matriz já cobre todas as transferências existentes.")
            return
        if not aplicar:
            self.stdout.write("Simulação: nada foi gravado. Use --aplicar para conceder.")
            return
        total = matriz_de_destinos.aplicar(proposta)
        self.stdout.write(f"{total} concessão(ões) criada(s) para {len(proposta)} usuário(s).")
