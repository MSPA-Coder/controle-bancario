"""Cartões separados do extrato misto na tela de Lançamentos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounts.models import AccountOwner
from bank_statements.models import BankStatementImport, BankStatementLine
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
    # Esta é a fonte da fatura fechada: ela é exibida pelo vencimento (25/10),
    # e não recomputada a partir dos lançamentos que por acaso caíram no mês.
    batch = BankStatementImport.objects.create(account=card, source_filename="fatura-outubro.csv", row_count=2)
    BankStatementLine.objects.create(
        import_batch=batch, account=card, statement_date=date(2026, 10, 5),
        description="Mercado", amount=Decimal("-100.00"), line_hash="fatura-out-1",
    )
    BankStatementLine.objects.create(
        import_batch=batch, account=card, statement_date=date(2026, 10, 12),
        description="Estorno", amount=Decimal("20.00"), line_hash="fatura-out-2",
    )
    return user, regular, card, category, batch


def _context(user, **params):
    return build_transactions_view_context(
        user,
        {"period": "2026-10", "mode": "todos", "grupos": "bancos,cartoes", **params},
        {},
    )


def test_modo_misto_separa_fatura_real_do_extrato_e_dos_totais(scenario):
    user, regular, card, _category, batch = scenario

    context = _context(user)

    assert context["card_presentation"] == CARD_PRESENTATION_SUMMARY
    assert [row.description for row in context["txs"]] == ["Débito em conta"]
    assert context["blocos"][0]["total_despesas"] == Decimal("25.00")
    assert context["show_card_invoices"] is True
    assert len(context["card_invoices"]) == 1
    invoice = context["card_invoices"][0]
    assert invoice.account.id == card.id
    assert invoice.closing_date == date(2026, 10, 19)
    assert invoice.due_date == date(2026, 10, 25)
    assert invoice.total == Decimal("80.00")
    assert invoice.import_batch_id == batch.id
    assert regular.id in context["blocos"][0]["account_ids"]
    assert card.id not in context["blocos"][0]["account_ids"]


def test_detalhe_e_filtros_preservam_lancamentos_originais_e_indicam_ciclo(scenario):
    user, _regular, card, category, _batch = scenario

    explicit_detail = _context(user, card_presentation=CARD_PRESENTATION_DETAILS)
    category_filter = _context(user, filter_category=category.category_name)
    card_filter = _context(user, account_id=str(card.id))

    detailed_card_entry = next(row for row in explicit_detail["txs"] if row.description == "Mercado no cartão")
    assert detailed_card_entry.card_invoice_closing_date == date(2026, 10, 19)
    assert detailed_card_entry.card_invoice_due_date == date(2026, 10, 25)
    assert explicit_detail["show_card_invoices"] is False
    assert category_filter["card_presentation"] == CARD_PRESENTATION_DETAILS
    assert card_filter["card_presentation"] == CARD_PRESENTATION_DETAILS
    assert card_filter["show_account_indicator"] is False


def test_tabela_mostra_painel_de_faturas_sem_linha_sintetica(client, scenario):
    user, _regular, _card, _category, _batch = scenario
    client.force_login(user)

    response = client.get("/transactions/?period=2026-10&mode=todos&grupos=bancos,cartoes")

    html = response.content.decode()
    assert response.status_code == 200
    assert 'value="resumo" selected' in html
    assert 'id="card-invoices-title"' in html
    assert "Faturas dos cartões" in html
    assert "fatura-outubro.csv" not in html
    assert 'class="card-statement-summary"' not in html
    assert "Débito em conta" in html
