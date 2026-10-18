"""Resultados financeiros imutáveis, independentes de upload, HTTP e ORM."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ParsedStatementLine:
    """Linha de extrato já normalizada para o domínio interno."""

    statement_date: date
    description: str
    amount: Decimal
    line_hash: str
    # Só a fatura de cartão preenche os campos abaixo (ver `fatura_csv`).
    purchase_date: date | None = None
    installment_current: int | None = None
    installment_total: int | None = None
    card_holder: str = ""
    bank_category: str = ""


@dataclass(frozen=True)
class ParsedStatement:
    lines: tuple[ParsedStatementLine, ...]
    balance: tuple[Decimal, date] | None = None
    period_end: date | None = None
    account_hint: str | None = None
    format_key: str = ""


@dataclass(frozen=True)
class ConferenciaDeSaldo:
    """O saldo que o extrato informa contra o saldo realizado do CB na mesma data."""

    saldo_do_extrato: Decimal
    data: date
    saldo_no_cb: Decimal

    @property
    def diferenca(self) -> Decimal:
        return (self.saldo_no_cb - self.saldo_do_extrato).quantize(Decimal("0.01"))

    @property
    def bate(self) -> bool:
        return self.diferenca == 0
