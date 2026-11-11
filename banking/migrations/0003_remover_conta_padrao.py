"""Sai `financial_account.is_default`, que nenhum código lia.

A coluna nunca foi usada pela aplicação, pelas views do esquema `leitura` nem
pelos consumidores (FinancasMCP, Wealthfolio). Seis contas de produção estavam
marcadas, sem efeito. Sai também o índice sobre ela.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('banking', '0002_checks_de_nome_e_indices_repetidos'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='financialaccount',
            name='financial_a_is_defa_1e20db_idx',
        ),
        migrations.RemoveField(
            model_name='financialaccount',
            name='is_default',
        ),
    ]
