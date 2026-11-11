"""Apaga as operações bancárias que não têm nenhum lançamento.

A produção tinha 34 (33 `single` e 1 `installment`), todas de maio e junho de
2026: resíduo de versões antigas, que criavam a operação também para o
lançamento único. O código atual só cria operação que não é `single` e, ao
excluir o último lançamento de uma operação, apaga a operação junto
(`delete_transaction_or_operation`, a projeção recorrente e a fatura projetada
fazem o mesmo). Nenhum fluxo depende de operação vazia.

Só a tabela `bank_operation` é tocada, e nada a referencia além dos lançamentos.
Não há como desfazer, nem o que desfazer: a operação vazia não guardava dado.
"""

from django.db import migrations


def apagar_operacoes_sem_lancamento(apps, schema_editor):
    BankOperation = apps.get_model('transactions', 'BankOperation')
    BankOperation.objects.filter(entries__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0002_checks_de_nome_e_indices_repetidos'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RunPython(apagar_operacoes_sem_lancamento, migrations.RunPython.noop),
    ]
