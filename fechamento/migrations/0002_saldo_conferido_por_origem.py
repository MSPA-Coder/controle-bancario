from django.db import migrations, models


class Migration(migrations.Migration):
    """Um saldo conferido por conta, data e origem.

    Antes era um por conta e data, e informar o mesmo dia por outra origem
    sobrescrevia valor, origem e lançamento do primeiro. Cada linha existente já
    tem uma origem só, então a nova restrição vale para todas sem mexer em dado.
    """

    dependencies = [
        ('fechamento', '0001_initial'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='saldoconferido',
            name='uq_fechamento_saldo_conta_data',
        ),
        migrations.AddConstraint(
            model_name='saldoconferido',
            constraint=models.UniqueConstraint(
                fields=('account', 'data', 'origem'), name='uq_fechamento_saldo_conta_data_origem',
            ),
        ),
    ]
