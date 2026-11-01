"""O tipo de renda `cupom` no detalhe de investimento (aditiva).

O extrato mensal em dólar da Avenue traz o cupom dos títulos de renda fixa, que
o CB passa a marcar como renda (`income_kind = cupom`) para o CRV mostrar como
provento. Só a restrição muda: nenhuma linha existente deixa de valer.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0012_categoria_valorizacao"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="entryinvestmentdetail",
            name="ck_entry_investment_income_kind_valid",
        ),
        migrations.AddConstraint(
            model_name="entryinvestmentdetail",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("income_kind__isnull", True),
                    ("income_kind__in", ("aluguel", "jcp", "dividendo", "cupom")),
                    _connector="OR",
                ),
                name="ck_entry_investment_income_kind_valid",
            ),
        ),
    ]
