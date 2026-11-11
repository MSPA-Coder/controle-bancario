"""Guarda em `bank_statement_line.is_card_payment` se a linha é pagamento de fatura.

A regra mora em `bank_statements/fatura.py` (`eh_pagamento`): crédito (valor
positivo) cuja descrição começa com "pag" ou "pagamento(s)" como palavra
inteira. Quem lê o banco de fora (FinancasMCP) reescrevia a regra por regex; a
partir daqui lê a coluna `pagamento_de_fatura` de `leitura.extrato_linha`, que
repete o valor gravado. A regra não é duplicada em SQL: o serviço de importação
e `BankStatementLine.save` chamam `eh_pagamento` e gravam o resultado.

Passos: coluna (NOT NULL, falso para todas), preenchimento das linhas
existentes e a view. O critério do preenchimento é uma cópia de `eh_pagamento`
dentro desta migração (migração não importa código vivo, que pode mudar depois);
`tests/test_pagamento_de_fatura_leitura.py` prova a paridade com a função.

A view é substituída com `CREATE OR REPLACE VIEW`, que só aceita acrescentar a
coluna no fim e mantém dono, comentário e concessões (inclusive a de `SELECT`
ao papel `mcp_leitura`); o teste confere isso. Sem volta: tirar a coluna
exigiria recriar a view e repor as concessões.
"""

import re

from django.db import migrations, models

_PAGAMENTO = re.compile(r"^pag(amentos?)?\b", re.IGNORECASE)

VIEW = """
CREATE OR REPLACE VIEW leitura.extrato_linha AS
 SELECT id,
    import_id AS importacao_id,
    account_id AS conta_id,
    matched_entry_id AS lancamento_conciliado_id,
    statement_date AS data,
    description AS descricao,
    amount AS valor,
    status,
    bank_category AS categoria_do_banco,
    card_holder AS portador,
    installment_current AS parcela_atual,
    installment_total AS parcela_total,
    purchase_date AS data_da_compra,
    is_card_payment AS pagamento_de_fatura
   FROM public.bank_statement_line l;

COMMENT ON COLUMN leitura.extrato_linha.pagamento_de_fatura IS 'Verdadeiro quando a linha é pagamento de fatura de cartão: crédito (valor positivo) cuja descrição começa com "pag" ou "pagamento(s)" como palavra inteira. É a regra do CB (fatura.eh_pagamento), gravada na importação.';
"""


def preencher(apps, schema_editor):
    linha_modelo = apps.get_model("bank_statements", "BankStatementLine")
    ids = [
        linha.pk
        for linha in linha_modelo.objects.filter(amount__gt=0).only("id", "description", "amount").iterator(chunk_size=2000)
        if _PAGAMENTO.match(linha.description.strip())
    ]
    for inicio in range(0, len(ids), 1000):
        linha_modelo.objects.filter(pk__in=ids[inicio:inicio + 1000]).update(is_card_payment=True)


class Migration(migrations.Migration):

    dependencies = [
        ("bank_statements", "0002_checks_de_nome_e_indices_repetidos"),
        ("core", "0004_igualar_esquema_ao_das_migracoes"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankstatementline",
            name="is_card_payment",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(preencher, migrations.RunPython.noop),
        migrations.RunSQL(VIEW, migrations.RunSQL.noop),
    ]
