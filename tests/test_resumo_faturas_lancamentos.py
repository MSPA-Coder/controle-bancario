"""Resumo visual de cartões na tela de Lançamentos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounts.models import AccountOwner
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import (
    ACCOUNT_KIND_CREDIT_CARD,
    CATEGORY_KIND_MANAGERIAL,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_REALIZED,
)
from core.domain.identity import USER_TYPE_ADMINISTRATOR
from transactions.models import CashFlowCategory, CashFlowEntry
from transactions.services import (
    CARD_PRESENTATION_DETAILS,
    CARD_PRESENTATION_SUMMARY,
    CardStatementSummary,
    build_transactions_view_context,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def scenario():
    user = get_user_model().objects.create_user(
        username="resumo-faturas",
        password="troca-esta-senha",
        user_type=USER_TYPE_ADMINISTRATOR,
    )
    owner = AccountOwner.objects.create(name="Titular resumo")
    institution = FinancialInstitution.objects.create(institution_name="Banco resumo", institution_type="Banco")
    regular = FinancialAccount.objects.create(owner=owner, institution=institution, account_name="Conta corrente")
    card = FinancialAccount.objects.create(
        owner=owner,
        institution=institution,
        account_name="Cartão principal",
        account_kind=ACCOUNT_KIND_CREDIT_CARD,
        card_closing_day=19,
        card_due_day=25,
    )
    category = CashFlowCategory.objects.create(category_name="Mercado resumo", kind=CATEGORY_KIND_MANAGERIAL)

    def entry(account, description, amount, due_date, entry_type=ENTRY_TYPE_EXPENSE):
        return CashFlowEntry.objects.create(
            account=account,
            category=category,
            entry_type=entry_type,
            description=description,
            entry_amount=Decimal(amount),
            due_date=due_date,
            realized_date=due_date,
            realized_amount=Decimal(amount),
            status=STATUS_REALIZED,
        )

    entry(regular, "Débito em conta", "25.00", date(2026, 10, 10))
    entry(card, "Mercado no cartão", "100.00", date(2026, 10, 5))
    entry(card, "Estorno no cartão", "20.00", date(2026, 10, 12), ENTRY_TYPE_INCOME)
    return user, regular, card, category


def _context(user, **params):
    return build_transactions_view_context(
        user,
        {"period": "2026-10", "mode": "todos", "grupos": "bancos,cartoes", **params},
        {},
    )


def test_varias_compras_do_cartao_viram_uma_fatura_no_fechamento(scenario):
    user, regular, card, _category = scenario

    context = _context(user)

    summaries = [row for row in context["txs"] if isinstance(row, CardStatementSummary)]
    assert context["card_presentation"] == CARD_PRESENTATION_SUMMARY
    assert context["show_account_indicator"] is True
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.account_id == card.id
    assert summary.display_date == date(2026, 10, 19)
    assert summary.entry_count == 2
    assert summary.entry_type == ENTRY_TYPE_EXPENSE
    assert summary.entry_amount == Decimal("80.00")
    assert [row.description for row in context["txs"] if not isinstance(row, CardStatementSummary)] == ["Débito em conta"]
    assert context["blocos"][0]["total_despesas"] == Decimal("125.00")


def test_detalhe_e_filtros_de_categoria_preservam_lancamentos_originais(scenario):
    user, _regular, card, category = scenario

    explicit_detail = _context(user, card_presentation=CARD_PRESENTATION_DETAILS)
    category_filter = _context(user, filter_category=category.category_name)
    card_filter = _context(user, account_id=str(card.id))

    assert not any(isinstance(row, CardStatementSummary) for row in explicit_detail["txs"])
    assert category_filter["card_presentation"] == CARD_PRESENTATION_DETAILS
    assert not any(isinstance(row, CardStatementSummary) for row in category_filter["txs"])
    assert card_filter["card_presentation"] == CARD_PRESENTATION_DETAILS
    assert card_filter["show_account_indicator"] is False


def test_tabela_mostra_icones_de_conta_e_o_resumo_de_fechamento(client, scenario):
    user, _regular, _card, _category = scenario
    client.force_login(user)

    response = client.get("/transactions/?period=2026-10&mode=todos&grupos=bancos,cartoes")

    html = response.content.decode()
    assert response.status_code == 200
    assert 'value="resumo" selected' in html
    assert 'class="card-statement-summary"' in html
    assert 'class="account-indicator"' in html
    assert "Fatura fechada" in html
