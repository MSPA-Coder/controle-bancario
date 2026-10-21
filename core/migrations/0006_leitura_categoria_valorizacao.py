"""Esquema `leitura`: `natureza` passa a ter um quarto valor, `valorizacao`.

Só o comentário da view muda (nenhuma coluna): quem lê pelo FinancasMCP precisa
saber que variação de mercado não é receita nem despesa, e que `natureza =
'gerencial'` já a deixa de fora. A migração depende da que cria o novo valor.
"""

from django.db import migrations

NOVO = (
    "Categorias. natureza: gerencial (receita/despesa de verdade), transferencia (entre contas próprias), "
    "movimentacao (aporte/resgate) ou valorizacao (variação de mercado do que está aplicado: muda o saldo, "
    "não é receita nem despesa)."
)
ANTIGO = (
    "Categorias. natureza: gerencial (receita/despesa de verdade), transferencia (entre contas próprias) "
    "ou movimentacao (aporte/resgate)."
)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_leitura_saldo_conferido"),
        ("transactions", "0012_categoria_valorizacao"),
    ]

    operations = [
        migrations.RunSQL(
            f"COMMENT ON VIEW leitura.categoria IS '{NOVO}';",
            reverse_sql=f"COMMENT ON VIEW leitura.categoria IS '{ANTIGO}';",
        ),
    ]
