"""Mede a sugestão de categoria contra o que o usuário decidiu (ver `bank_statements.medicao`).

    python manage.py medir_sugestoes
    python manage.py medir_sugestoes --desde 2026-11-01 [--ate 2026-11-30] [--suspeitos 50]

Cada linha conciliada recebe a sugestão que teria tido com o histórico de antes
do mês dela; o relatório mostra o acerto, o acerto por nível de confiança,
quanto o usuário confere e os lançamentos suspeitos de classificação errada.
Só lê: a medição roda numa transação desfeita no fim.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from bank_statements import medicao
from bank_statements.classificacao import (
    CONFIANCA_ALTA,
    CONFIANCA_BAIXA,
    CONFIANCA_MEDIA,
    CONFIANCA_NENHUMA,
    ROTULOS_DA_CONFIANCA,
)


def _data(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"data inválida: \"{texto}\" (use AAAA-MM-DD)") from exc


def _pct(taxa: medicao.Taxa) -> str:
    if taxa.fracao is None:
        return "-"
    return f"{taxa.fracao:.1%}".replace(".", ",")


class Command(BaseCommand):
    help = "Mede o acerto da sugestão de categoria e lista classificações suspeitas."

    def add_arguments(self, parser):
        parser.add_argument("--desde", type=_data, help="Primeira data de linha avaliada (AAAA-MM-DD).")
        parser.add_argument("--ate", type=_data, help="Última data de linha avaliada (AAAA-MM-DD).")
        parser.add_argument("--suspeitos", type=int, default=30, help="Quantos suspeitos listar (padrão 30).")

    def handle(self, *args, desde, ate, suspeitos, **options):
        with transaction.atomic():
            casos = medicao.casos(desde=desde, ate=ate)
            achados = medicao.suspeitos(limite=suspeitos)
            transaction.set_rollback(True)
        escrever = self.stdout.write
        if not casos:
            escrever("Nenhuma linha conciliada para avaliar no período.")
        else:
            self._relatorio(casos)
        escrever("")
        escrever(f"Suspeitos de classificação errada ({len(achados)}; corrija em Bancos > Reclassificação):")
        for suspeito in achados:
            entrada = suspeito.lancamento
            if suspeito.motivo == "loja":
                porque = (f"a mesma loja é \"{suspeito.esperada.category_name}\" "
                          f"em {suspeito.iguais} de {suspeito.total} compras")
            else:
                porque = (f"\"{suspeito.bank_category}\" é \"{suspeito.esperada.category_name}\" "
                          f"em {suspeito.iguais} de {suspeito.total} linhas")
            escrever(f"  #{entrada.id} {entrada.due_date} {suspeito.texto[:45]}: "
                     f"\"{entrada.category.category_name}\"; {porque}")

    def _relatorio(self, casos):
        escrever = self.stdout.write
        novos = [caso for caso in casos if caso.lancamento_novo]
        escrever("Sugestão de categoria, refeita com o histórico de antes do mês de cada linha.")
        escrever(f"Linhas avaliadas: {len(casos)}; com lançamento novo (onde a sugestão é usada): {len(novos)}.")
        escrever("")
        escrever(f"{'':34}{'todas':>10}{'lançamento novo':>18}")
        for rotulo, filtro in (
            ("Acerto", lambda caso: True),
            ("  cartão", lambda caso: caso.cartao),
            ("  conta", lambda caso: not caso.cartao),
        ):
            escrever(f"{rotulo:34}{_pct(medicao.taxa(filter(filtro, casos))):>10}"
                     f"{_pct(medicao.taxa(filter(filtro, novos))):>18}")
        escrever("")
        escrever("Por nível de confiança (lançamento novo):")
        for nivel in (CONFIANCA_ALTA, CONFIANCA_MEDIA, CONFIANCA_BAIXA, CONFIANCA_NENHUMA):
            taxa = medicao.taxa(caso for caso in novos if caso.sugestao.confianca == nivel)
            escrever(f"  {str(ROTULOS_DA_CONFIANCA[nivel]):20}{taxa.total:>6} linhas  acerto {_pct(taxa)}")
        esforco = medicao.esforco(novos)
        escrever("")
        escrever(f"Para conferir: {esforco.a_conferir} de {esforco.pedem_categoria} linhas, "
                 f"{esforco.decisoes} decisões com o agrupamento da fatura.")
        escrever("")
        escrever("Por mês (lançamento novo):")
        por_mes = defaultdict(list)
        for caso in novos:
            por_mes[caso.linha.statement_date.strftime("%Y-%m")].append(caso)
        for mes in sorted(por_mes):
            taxa = medicao.taxa(por_mes[mes])
            escrever(f"  {mes}{taxa.total:>6} linhas  acerto {_pct(taxa)}")
