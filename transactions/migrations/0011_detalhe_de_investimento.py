"""Dado estruturado de investimento do lançamento (aditiva).

Cria `cash_flow_entry_investment`, 1:1 com `cash_flow_entry`. Nenhuma coluna
existente muda, então as views do esquema `leitura` não são afetadas.

O gatilho reaproveita a função da outbox do patrimônio v4 (`core/0003`): gravar
ou alterar o detalhe muda o `cash_entry` publicado, e quem guarda a foto pelo
`high_watermark` precisa saber. Só INSERT e UPDATE: apagar o detalhe sozinho não
apaga o lançamento (o `delete` da outbox é um tombstone), e quando o lançamento é
apagado o próprio gatilho dele já emite o `delete`.
"""
import django.db.models.deletion
from django.db import migrations, models

TRIGGER = (
    "CREATE TRIGGER patrimonio_v4_outbox_cash_flow_entry_investment "
    "AFTER INSERT OR UPDATE ON cash_flow_entry_investment "
    "FOR EACH ROW EXECUTE FUNCTION patrimonio_v4_outbox_emit('cash_entry', 'entry_id')"
)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_patrimonio_v4_outbox"),
        ("transactions", "0010_envio_de_lancamento"),
    ]

    operations = [
        migrations.CreateModel(
            name="EntryInvestmentDetail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("instrument_code", models.CharField(blank=True, max_length=20, null=True)),
                ("income_kind", models.CharField(blank=True, max_length=20, null=True)),
                ("income_role", models.CharField(blank=True, max_length=30, null=True)),
                ("settlement_pregao_date", models.DateField(blank=True, null=True)),
                ("settlement_note", models.CharField(blank=True, max_length=40, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "entry",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="investment_detail",
                        to="transactions.cashflowentry",
                    ),
                ),
            ],
            options={
                "db_table": "cash_flow_entry_investment",
            },
        ),
        migrations.AddConstraint(
            model_name="entryinvestmentdetail",
            constraint=models.CheckConstraint(
                condition=models.Q(("income_kind__isnull", True), ("income_kind__in", ("aluguel", "jcp", "dividendo")), _connector="OR"),
                name="ck_entry_investment_income_kind_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="entryinvestmentdetail",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("income_role__isnull", True),
                    ("income_role__in", ("credito", "irrf_aluguel", "corretagem_aluguel", "taxa_aluguel", "estorno")),
                    _connector="OR",
                ),
                name="ck_entry_investment_income_role_valid",
            ),
        ),
        migrations.RunSQL(TRIGGER, "DROP TRIGGER patrimonio_v4_outbox_cash_flow_entry_investment ON cash_flow_entry_investment"),
    ]
