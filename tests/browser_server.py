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
    from transactions.models import CashFlowCategory

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
    CashFlowCategory.objects.create(category_name="Despesa browser")
    call_command("runserver", "0.0.0.0:8000", use_reloader=False)


if __name__ == "__main__":
    main()
