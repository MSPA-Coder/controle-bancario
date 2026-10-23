"""Migrations, dados sintéticos e servidor apenas no Compose de navegador."""

import os
from datetime import date
from decimal import Decimal


def main():
    if os.environ.get("BROWSER_TEST_SERVER") != "1" or os.environ.get("POSTGRES_DB") != "browser_tests":
        raise RuntimeError("Servidor de navegador exige banco descartável browser_tests.")
    import django

    django.setup()
    from django.core.management import call_command

    from accounts.models import AccountOwner, AppUser
    from banking.models import FinancialAccount, FinancialInstitution
    from transactions.models import CashFlowCategory, CashFlowEntry

    call_command("migrate", interactive=False, verbosity=0)
    if AppUser.objects.exists():
        raise RuntimeError("Banco do navegador deve nascer vazio; recrie a pilha de teste.")
    AppUser.objects.create_user(username="browser", password="Synthetic-browser-only-2026!", user_type="administrator")
    owner = AccountOwner.objects.create(name="Titular browser")
    institution = FinancialInstitution.objects.create(institution_name="Banco browser", institution_type="Banco")
    FinancialAccount.objects.create(
        owner=owner, institution=institution, account_name="Conta browser",
        initial_balance=Decimal("1000.00"), initial_balance_date=date.today().replace(day=1),
    )
    card = FinancialAccount.objects.create(
        owner=owner, institution=institution, account_name="Cartão browser",
        account_kind="cartao_credito", card_closing_day=25, card_due_day=5,
    )
    # Filtros em cascata: o titular browser tem conta em dois bancos, e um
    # segundo titular divide um deles. Saldo zero para não mexer nos totais.
    segundo_banco = FinancialInstitution.objects.create(institution_name="Banco dois", institution_type="Banco")
    FinancialAccount.objects.create(owner=owner, institution=segundo_banco, account_name="Conta dois")
    FinancialAccount.objects.create(
        owner=AccountOwner.objects.create(name="Titular dois"), institution=segundo_banco, account_name="Conta três",
    )
    category = CashFlowCategory.objects.create(category_name="Despesa browser")
    for description, amount in (("Compra browser A", "20.00"), ("Compra browser B", "30.00")):
        CashFlowEntry.objects.create(
            account=card, category=category, entry_type="despesa", description=description,
            entry_amount=Decimal(amount), due_date=date.today(), realized_date=date.today(),
            realized_amount=Decimal(amount), status="realizado",
        )
    call_command("runserver", "0.0.0.0:8000", use_reloader=False)


if __name__ == "__main__":
    main()
