"""Duas origens para o saldo da mesma conta no mesmo dia que não concordam.

A conta tem uma fonte declarada (`fechamento.fontes`) e só ela lança diferença.
Outra origem para o mesmo dia (um print numa conta do myProfit, por exemplo) fica
como conferência em `SaldoConferido`, uma linha por origem. Quando as origens
discordam além da tolerância, o que vale é decidir qual está certa, e não lançar
um segundo ajuste por cima do primeiro: o Roteiro de fechamento mostra a diferença.

A tolerância existe para não transformar arredondamento em pendência: o maior
entre `TOLERANCIA_FIXA` e `TOLERANCIA_PERCENTUAL` do maior saldo.

Aplicação em moeda estrangeira tem tolerância própria, `TOLERANCIA_PERCENTUAL_EXTERIOR`.
É onde estão os títulos de renda fixa do exterior, marcados a mercado pelo
extrato mensal da corretora, enquanto o myProfit os cota por outra fonte de
preço: em ago e set/2026 o myProfit ficou 0,49% e 0,51% abaixo do extrato, todo
mês, sem erro de nenhum lado. O extrato continua sendo a fonte; com 1% sobre
cerca de US$ 9.400, um título inteiro a mais ou a menos (US$ 1.150 a 1.800)
ainda aparece.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from banking.models import FinancialAccount
from banking.services import accessible_account_ids
from core.domain.finance import ACCOUNT_KIND_INVESTMENT, BASE_CURRENCY

from .models import SaldoConferido

TOLERANCIA_FIXA = Decimal("10.00")
TOLERANCIA_PERCENTUAL = Decimal("0.002")
TOLERANCIA_PERCENTUAL_EXTERIOR = Decimal("0.01")


@dataclass(frozen=True)
class Divergencia:
    conta: FinancialAccount
    data: date
    valores: dict[str, Decimal]  # origem -> saldo informado

    @property
    def diferenca(self) -> Decimal:
        return max(self.valores.values()) - min(self.valores.values())


def _aplicacao_no_exterior(conta: FinancialAccount | None) -> bool:
    return conta is not None and conta.account_kind == ACCOUNT_KIND_INVESTMENT and conta.currency != BASE_CURRENCY


def tolerancia(valores, conta: FinancialAccount | None = None) -> Decimal:
    maior = max((abs(v) for v in valores), default=Decimal("0"))
    percentual = TOLERANCIA_PERCENTUAL_EXTERIOR if _aplicacao_no_exterior(conta) else TOLERANCIA_PERCENTUAL
    return max(TOLERANCIA_FIXA, (maior * percentual).quantize(Decimal("0.01")))


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
        if max(valores.values()) - min(valores.values()) > tolerancia(valores.values(), linhas[0].account):
            achadas.append(Divergencia(conta=linhas[0].account, data=dia, valores=valores))
    return achadas
