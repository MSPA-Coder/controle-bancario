"""Entrada imutável dos comandos financeiros, sem dependência do ORM."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.domain.finance import CALC_REPEAT, STATUS_PROJECTED


@dataclass(frozen=True)
class TransactionRequest:
    """Payload validado de criação/edição de lançamento.

    Frozen de propósito: o caso de uso não deve reescrever a entrada enquanto
    a processa."""

    account_id: int
    category_id: int
    entry_type: str
    description: str
    entry_amount: Decimal
    installments: int
    due_date: date
    calc_mode: str = CALC_REPEAT
    is_recurring: bool = False
    status: str = STATUS_PROJECTED
    realized_date: date | None = None
    realized_amount: Decimal | None = None
    counterparty_account_id: int | None = None
    # Só existe quando a transferência atravessa moedas: é o que entra na conta
    # destino, em vez do espelho do valor que saiu da origem. Ver
    # `counterparty_amount_for_transfer`.
    counterparty_amount: Decimal | None = None
    # Parcelado que já vem andando: a fatura de cartão mostra a compra pela
    # primeira vez na parcela 10 de 12, e só as parcelas 10 a 12 são criadas,
    # numeradas como no banco. `due_date` é a da parcela `first_installment`.
    first_installment: int = 1
