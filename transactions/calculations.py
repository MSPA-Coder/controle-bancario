"""Cálculos de parcelas, independentes de persistência e de requisição."""

from decimal import ROUND_HALF_UP, Decimal

from core.domain.finance import CALC_DIVIDE

MONEY_QUANT = Decimal("0.01")


def _monthly_amount_for(entry_amount: Decimal, installments: int, calc_mode: str) -> Decimal:
    """Valor-base de uma parcela, usado também para validar o payload."""
    amount = entry_amount if isinstance(entry_amount, Decimal) else Decimal(str(entry_amount))
    if calc_mode == CALC_DIVIDE and installments > 1:
        return (amount / Decimal(installments)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    return amount.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def installment_amount_for(entry_amount: Decimal, installments: int, calc_mode: str, installment: int) -> Decimal:
    """Devolve a parcela, concentrando na última o resíduo de arredondamento."""
    amount = entry_amount if isinstance(entry_amount, Decimal) else Decimal(str(entry_amount))
    base = _monthly_amount_for(amount, installments, calc_mode)
    if calc_mode != CALC_DIVIDE or installments <= 1 or installment < installments:
        return base
    return (amount - (base * (installments - 1))).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
