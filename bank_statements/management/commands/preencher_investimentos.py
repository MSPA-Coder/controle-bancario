"""Preenche o ativo e o tipo de renda dos lançamentos que já existem.

    python manage.py preencher_investimentos             # simula: só lista
    python manage.py preencher_investimentos --dry-run   # o mesmo, explícito
    python manage.py preencher_investimentos --aplicar   # grava

Lê a descrição de cada lançamento (e, na falta, a da linha de extrato conciliada
com ele) com `bank_statements.investimentos` e grava em `EntryInvestmentDetail`
o que ela diz: ativo, tipo de renda, papel da linha e a liquidação de pregão.
Qualquer conta entra; só quem casa com as regras ganha campos. Idempotente:
rodar de novo não muda nada. Não altera valor, data, categoria nem saldo.
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bank_statements.investimentos_preenchimento import preencher_existentes


def _resumo(detalhe) -> str:
    partes = [
        detalhe.instrument_code, detalhe.income_kind, detalhe.income_role,
        detalhe.settlement_pregao_date.isoformat() if detalhe.settlement_pregao_date else None,
        f"nota {detalhe.settlement_note}" if detalhe.settlement_note else None,
    ]
    return " | ".join(p for p in partes if p) or "-"


class Command(BaseCommand):
    help = "Preenche ativo, tipo de renda e liquidação de pregão dos lançamentos existentes (simula por padrão)."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Grava; sem isto só lista.")
        parser.add_argument("--dry-run", action="store_true", help="Só lista (é o padrão).")
        parser.add_argument("--silencioso", action="store_true", help="Só os totais, sem uma linha por lançamento.")

    def handle(self, *args, aplicar, dry_run, silencioso, **options):
        if aplicar and dry_run:
            raise CommandError("--aplicar e --dry-run se excluem.")
        contagem: Counter = Counter()
        papeis: Counter = Counter()
        with transaction.atomic():
            for mudanca in preencher_existentes(aplicar=aplicar):
                contagem[mudanca.acao] += 1
                papeis[mudanca.depois.income_role or ("liquidacao" if mudanca.depois.settlement_pregao_date else "-")] += 1
                if not silencioso:
                    self.stdout.write(
                        f"{mudanca.acao:9} #{mudanca.entry_id}  {_resumo(mudanca.depois)}  <-  {mudanca.descricao}"
                    )
        verbo = "gravados" if aplicar else "a gravar (nada foi gravado: simulação)"
        self.stdout.write(
            f"Lançamentos {verbo}: {sum(contagem.values())} "
            f"(criar {contagem['criar']}, atualizar {contagem['atualizar']})."
        )
        for papel, quantidade in sorted(papeis.items()):
            self.stdout.write(f"  {papel}: {quantidade}")
