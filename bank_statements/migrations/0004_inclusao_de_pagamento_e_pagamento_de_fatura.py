"""Remarca como pagamento de fatura as linhas "Inclusao de Pagamento" do C6.

O C6 exporta o boleto de fatura pago em partes com dois nomes: "Pag Fatura
Boleto" e "Inclusao de Pagamento". Só o primeiro era reconhecido, então a
parcela de "Inclusao de Pagamento" virava estorno (receita) em vez de casar com
a transferência que pagou a fatura. `fatura.eh_pagamento` passou a reconhecer
os dois; aqui se remarcam as linhas já importadas, com a mesma regra (cópia,
porque migração não importa código vivo). Sem volta: desmarcar não tem uso.
"""

import re

from django.db import migrations

_INCLUSAO = re.compile(r"^inclus[aã]o de pagamento\b", re.IGNORECASE)


def remarcar(apps, schema_editor):
    linha_modelo = apps.get_model("bank_statements", "BankStatementLine")
    ids = [
        linha.pk
        for linha in linha_modelo.objects.filter(amount__gt=0, is_card_payment=False).only("pk", "description")
        if _INCLUSAO.match(linha.description.strip())
    ]
    for inicio in range(0, len(ids), 1000):
        linha_modelo.objects.filter(pk__in=ids[inicio:inicio + 1000]).update(is_card_payment=True)


COMENTARIO = (
    "COMMENT ON COLUMN leitura.extrato_linha.pagamento_de_fatura IS "
    "'Verdadeiro quando a linha é pagamento de fatura de cartão: crédito (valor positivo) cuja descrição "
    "começa com \"pag\" ou \"pagamento(s)\" como palavra inteira, ou com \"inclusao de pagamento\". "
    "É a regra do CB (fatura.eh_pagamento), gravada na importação.'"
)


class Migration(migrations.Migration):
    dependencies = [("bank_statements", "0003_linha_de_extrato_pagamento_de_fatura")]

    operations = [
        migrations.RunPython(remarcar, migrations.RunPython.noop),
        migrations.RunSQL(COMENTARIO, migrations.RunSQL.noop),
    ]
