"""Quarto tipo de categoria: variação de mercado (`valorizacao`), e a categoria dela.

A marcação a mercado de Tesouro, renda fixa e caixa em dólar mudava o saldo da
conta e entrava como "Rendimentos" gerencial: um papel que caiu 5% aparecia como
despesa do mês, e um que subiu, como renda. É variação não realizada do
patrimônio, não fluxo: muda o saldo, não é receita nem despesa.

Só acrescenta um valor permitido à restrição e cria a categoria "Variação de
mercado" (no grupo "Investimentos", se ele existir). Nenhuma coluna muda, então
as views do esquema `leitura` não são afetadas. Os lançamentos antigos de
marcação a mercado são reclassificados por `reclassificar_valorizacao`, com
simulação e backup, e não aqui.
"""
from django.db import migrations, models

GERENCIAL = "gerencial"
TRANSFERENCIA = "transferencia"
MOVIMENTACAO = "movimentacao"
VALORIZACAO = "valorizacao"
NOME = "Variação de mercado"
GRUPO = "Investimentos"


def criar_categoria(apps, schema_editor):
    categorias = apps.get_model("transactions", "CashFlowCategory").objects
    grupos = apps.get_model("transactions", "CashFlowCategoryGroup").objects
    if categorias.filter(category_name__iexact=NOME).exists():
        return
    categorias.create(category_name=NOME, kind=VALORIZACAO, group=grupos.filter(group_name=GRUPO).first())


def remover_categoria(apps, schema_editor):
    categorias = apps.get_model("transactions", "CashFlowCategory").objects
    lancamentos = apps.get_model("transactions", "CashFlowEntry").objects
    categoria = categorias.filter(category_name=NOME, kind=VALORIZACAO).first()
    if categoria is not None and not lancamentos.filter(category=categoria).exists():
        categoria.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0011_detalhe_de_investimento"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cashflowcategory",
            name="kind",
            field=models.CharField(
                choices=[
                    (GERENCIAL, "Gerencial (receita ou despesa)"),
                    (TRANSFERENCIA, "Transferência entre contas"),
                    (MOVIMENTACAO, "Movimentação (não é receita nem despesa)"),
                    (VALORIZACAO, "Variação de mercado (não é receita nem despesa)"),
                ],
                default=GERENCIAL,
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="cashflowcategory",
            name="ck_cash_flow_category_kind_valid",
        ),
        migrations.AddConstraint(
            model_name="cashflowcategory",
            constraint=models.CheckConstraint(
                condition=models.Q(kind__in=(GERENCIAL, TRANSFERENCIA, MOVIMENTACAO, VALORIZACAO)),
                name="ck_cash_flow_category_kind_valid",
            ),
        ),
        migrations.RunPython(criar_categoria, remover_categoria),
    ]
