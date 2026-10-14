"""Próximos movimentos é uma visão de caixa: o cartão não entra.

O que sai do caixa é o pagamento da fatura, uma transferência que já aparece na
conta pagadora. Compras, parcelas e "Gasto estimado" do cartão são dívida na
competência, e o saldo negativo dele não é alerta de caixa.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from accounts.models import AccountOwner
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import (
    ACCOUNT_KIND_CREDIT_CARD,
    CATEGORY_KIND_MANAGERIAL,
    ENTRY_TYPE_EXPENSE,
    STATUS_PROJECTED,
    VIEW_PROJECTED,
)
from reports.services import upcoming_movements_report
from transactions.models import CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db


def test_compras_do_cartao_nao_aparecem_mas_as_da_conta_sim():
    dono = AccountOwner.objects.create(name="Titular proximos")
    banco = FinancialInstitution.objects.create(institution_name="Banco proximos", institution_type="Banco")
    conta = FinancialAccount.objects.create(owner=dono, institution=banco, account_name="Corrente")
    cartao = FinancialAccount.objects.create(
        owner=dono, institution=banco, account_name="Cartão", account_kind=ACCOUNT_KIND_CREDIT_CARD,
        card_closing_day=19, card_due_day=25,
    )
    categoria = CashFlowCategory.objects.create(category_name="Mercado proximos", kind=CATEGORY_KIND_MANAGERIAL)
    amanha = date.today() + timedelta(days=1)
    for conta_do_lancamento, descricao in ((conta, "NA CONTA"), (cartao, "NO CARTAO")):
        CashFlowEntry.objects.create(
            account=conta_do_lancamento, category=categoria, entry_type=ENTRY_TYPE_EXPENSE,
            description=descricao, entry_amount=Decimal("50.00"), due_date=amanha, status=STATUS_PROJECTED,
        )

    relatorio = upcoming_movements_report(
        [conta.id, cartao.id], amanha, amanha + timedelta(days=5), VIEW_PROJECTED
    )

    assert [linha.description for linha in relatorio.movement_lines] == ["NA CONTA"]
    assert [linha.account_id for linha in relatorio.account_rows] == [conta.id]
