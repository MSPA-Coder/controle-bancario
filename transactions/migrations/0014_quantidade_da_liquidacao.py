from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0013_cupom_no_detalhe_de_investimento"),
    ]

    operations = [
        migrations.AddField(
            model_name="entryinvestmentdetail",
            name="settlement_quantity",
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=20, null=True),
        ),
        migrations.AddConstraint(
            model_name="entryinvestmentdetail",
            constraint=models.CheckConstraint(
                condition=models.Q(("settlement_quantity__isnull", True), ("settlement_quantity__gt", 0), _connector="OR"),
                name="ck_entry_investment_settlement_quantity_positive",
            ),
        ),
    ]
