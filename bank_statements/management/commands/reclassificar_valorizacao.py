"""Move a marcação a mercado antiga de "Rendimentos" para "Variação de mercado".

    python manage.py reclassificar_valorizacao --usuario NOME
    python manage.py reclassificar_valorizacao --usuario NOME --aplicar [--autorizar-meses]

Sem `--aplicar` é só a simulação: lista cada lançamento, a conta e os
meses-conta fechados que seriam reabertos. Com `--aplicar`, tudo ou nada; só a
categoria muda, e o saldo de fechamento é conferido antes de fechar de novo.
Faça o backup antes de aplicar em dados reais
(`python cli.py backup --projeto controle_bancario --tipos banco`).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts.models import AppUser
from bank_statements import valorizacao


class Command(BaseCommand):
    help = "Simula ou aplica a reclassificação da marcação a mercado como variação de mercado."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True, help="Usuário cujo acesso vale (e que assina a auditoria).")
        parser.add_argument("--aplicar", action="store_true", help="Grava; sem isto é só simulação.")
        parser.add_argument("--autorizar-meses", action="store_true", help="Permite reabrir e fechar de novo meses fechados.")

    def handle(self, *args, usuario, aplicar, autorizar_meses, **options):
        try:
            user = AppUser.objects.get(username=usuario)
        except AppUser.DoesNotExist as exc:
            raise CommandError(f"Usuário \"{usuario}\" não existe.") from exc

        efeito = valorizacao.simular(user)
        for entrada in efeito.entradas:
            sinal = "+" if entrada.entry_type == "receita" else "-"
            valor = entrada.realized_amount if entrada.realized_amount is not None else entrada.entry_amount
            self.stdout.write(
                f"{entrada.id}  {entrada.realized_date or entrada.due_date}  {entrada.account}  "
                f"{sinal}{valor}  {entrada.category.category_name} -> {valorizacao.CATEGORIA_DE_VARIACAO}"
            )
        extras = []
        if efeito.categoria_nova:
            extras.append(f"cria a categoria \"{valorizacao.CATEGORIA_DE_VARIACAO}\"")
        if efeito.meses_fechados:
            extras.append(f"reabre {len(efeito.meses_fechados)} mês(es)-conta fechado(s)")
        sufixo = f" ({'; '.join(extras)})" if extras else ""
        self.stdout.write(f"{len(efeito.entradas)} lançamento(s){sufixo}.")
        if not aplicar:
            self.stdout.write("Simulação: nada foi gravado. Use --aplicar para reclassificar.")
            return
        try:
            mudou = valorizacao.aplicar(user, autorizar_meses=autorizar_meses)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{mudou} lançamento(s) reclassificado(s).")
