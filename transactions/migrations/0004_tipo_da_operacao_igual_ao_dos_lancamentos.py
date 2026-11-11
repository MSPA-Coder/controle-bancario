"""A operação passa a ter o tipo dos lançamentos, quando todos têm o mesmo.

A produção tinha uma operação `installment` (criada em 13/07/2026) cujos dez
lançamentos são todos `recurring` (`installments = 1`, `is_recurring`
verdadeiro): o código atual não produz esse estado, e o tipo da operação não
batia com o dos lançamentos. Todo fluxo decide pelo `operation_type` do
LANÇAMENTO (listagem de operações, projeção recorrente, saldo, parcela); o da
operação só aparece em `leitura.operacao.tipo` e no filtro por índice, de modo
que a troca não muda saldo, parcela nem projeção.

Regra, geral: a operação cujos lançamentos têm todos o mesmo `operation_type`,
diferente do dela, passa a ter o tipo dos lançamentos. Fica de fora, de
propósito, tudo o que envolve `internal_transfer` (do lado da operação ou dos
lançamentos): a transferência tem gatilho de integridade no banco
(`ck_internal_transfer_has_counterparty`) e é publicada à parte no contrato v4,
e mudar o tipo dela não é acerto de rótulo.

Idempotente: num banco já certo não há o que atualizar. Não há como desfazer
(a operação não guardava o tipo antigo em outro lugar), nem o que desfazer.
"""

from django.db import migrations
from django.db.models import Count, F, Max, Min

TRANSFERENCIA = 'internal_transfer'


def alinhar_tipo_da_operacao(apps, schema_editor):
    BankOperation = apps.get_model('transactions', 'BankOperation')
    divergentes = (
        BankOperation.objects
        .annotate(
            lancamentos=Count('entries'),
            menor=Min('entries__operation_type'),
            maior=Max('entries__operation_type'),
        )
        .filter(lancamentos__gt=0, menor=F('maior'))
        .exclude(menor=F('operation_type'))
        .exclude(operation_type=TRANSFERENCIA)
        .exclude(menor=TRANSFERENCIA)
    )
    for operacao in divergentes:
        BankOperation.objects.filter(pk=operacao.pk).update(operation_type=operacao.menor)


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0003_apagar_operacoes_sem_lancamento'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RunPython(alinhar_tipo_da_operacao, migrations.RunPython.noop),
    ]
