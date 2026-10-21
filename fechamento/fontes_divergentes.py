"""Duas origens para o saldo da mesma conta no mesmo dia que não concordam.

A conta tem uma fonte declarada (`fechamento.fontes`) e só ela lança diferença.
Outra origem para o mesmo dia (um print numa conta do myProfit, por exemplo) fica
como conferência em `SaldoConferido`, uma linha por origem. Quando as origens
discordam além da tolerância, o que vale é decidir qual está certa, e não lançar
um segundo ajuste por cima do primeiro: o Roteiro de fechamento mostra a diferença.

A tolerância existe para não transformar arredondamento em pendência: o maior
entre `TOLERANCIA_FIXA` e `TOLERANCIA_PERCENTUAL` do maior saldo.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from banking.models import FinancialAccount
from banking.services import accessible_account_ids

from .models import SaldoConferido

TOLERANCIA_FIXA = Decimal("10.00")
TOLERANCIA_PERCENTUAL = Decimal("0.002")


@dataclass(frozen=True)
class Divergencia:
    conta: FinancialAccount
    data: date
    valores: dict[str, Decimal]  # origem -> saldo informado

    @property
    def diferenca(self) -> Decimal:
        return max(self.valores.values()) - min(self.valores.values())


def tolerancia(valores) -> Decimal:
    maior = max((abs(v) for v in valores), default=Decimal("0"))
    return max(TOLERANCIA_FIXA, (maior * TOLERANCIA_PERCENTUAL).quantize(Decimal("0.01")))


def divergentes(user, inicio: date, fim: date) -> list[Divergencia]:
    """Conta e dia, entre `inicio` e `fim`, em que duas origens informaram saldos que diferem além da tolerância."""
    ids = accessible_account_ids(user, "view")
    if not ids:
        return []
    registros = (
        SaldoConferido.objects.filter(account_id__in=ids, data__gte=inicio, data__lte=fim)
        .select_related("account__institution", "account__owner")
        .order_by("data", "account_id", "origem")
    )
    por_dia: dict[tuple[int, date], list[SaldoConferido]] = defaultdict(list)
    for registro in registros:
        por_dia[(registro.account_id, registro.data)].append(registro)
    achadas = []
    for (_, dia), linhas in por_dia.items():
        if len(linhas) < 2:
            continue
        valores = {linha.origem: linha.valor for linha in linhas}
        if max(valores.values()) - min(valores.values()) > tolerancia(valores.values()):
            achadas.append(Divergencia(conta=linhas[0].account, data=dia, valores=valores))
    return achadas
