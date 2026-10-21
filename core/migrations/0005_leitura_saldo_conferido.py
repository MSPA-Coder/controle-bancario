"""Esquema `leitura`: os saldos informados por conta, dia e origem.

Quem audita o saldo de uma conta (o FinancasMCP) precisa ver de onde veio cada
valor e se duas origens discordaram no mesmo dia. A view só lê
`fechamento_saldo_conferido`; as regras de qual origem vale moram no CB. Como o
resto do esquema, o PostgreSQL recusa remover ou trocar o tipo de uma coluna que
ela lê: quem mexer lá depende desta migração e recria a view.
"""

from django.db import migrations

SQL = """
CREATE VIEW leitura.saldo_conferido AS
SELECT
    s.id,
    s.account_id AS conta_id,
    a.account_name AS conta,
    s.data,
    s.valor,
    s.origem,
    s.lancamento_id
FROM fechamento_saldo_conferido s
JOIN financial_account a ON a.id = s.account_id;

COMMENT ON VIEW leitura.saldo_conferido IS
    'Saldos informados por conta, dia e origem (manual, print ou myprofit). Mais de uma origem no mesmo dia é conferência; lancamento_id é o ajuste lançado, quando houve.';
"""

REVERSE_SQL = "DROP VIEW IF EXISTS leitura.saldo_conferido;"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_esquema_leitura"),
        ("fechamento", "0002_saldo_conferido_por_origem"),
    ]

    operations = [migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL)]
