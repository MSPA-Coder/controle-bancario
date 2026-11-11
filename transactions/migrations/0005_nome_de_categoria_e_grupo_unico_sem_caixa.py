"""Nome de categoria e de grupo de categoria único sem diferenciar a caixa.

O serviço já recusa "Saúde" e "saude" como o mesmo nome (`_assert_nome_livre`),
mas o banco só recusava o byte a byte: uma escrita que não passe pelo serviço
(importação, comando, concorrência) criava a segunda categoria. Em produção
havia 0 duplicatas de usuário e de categoria (medido em 10/11/2026); a de grupo
não foi medida.

A conferência abaixo roda antes dos índices e **recusa** a migração, inteira e
sem alterar nada, se houver duplicata: nome de categoria ou de grupo não se
apaga nem se renomeia por migração, porque lançamentos apontam para eles. Quem
decide é o mantenedor, olhando os ids que a mensagem lista. Consultas para ver
antes:

    SELECT lower(category_name), count(*), array_agg(id)
    FROM cash_flow_category GROUP BY 1 HAVING count(*) > 1;

    SELECT lower(group_name), count(*), array_agg(id)
    FROM cash_flow_category_group GROUP BY 1 HAVING count(*) > 1;
"""

from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def _repetidos(modelo, campo):
    chaves = [
        linha['chave']
        for linha in modelo.objects.annotate(chave=Lower(campo))
        .values('chave')
        .annotate(total=Count('id'))
        .filter(total__gt=1)
    ]
    return sorted(
        modelo.objects.annotate(chave=Lower(campo)).filter(chave__in=chaves).values_list('id', flat=True)
    )


def recusar_duplicata(apps, schema_editor):
    problemas = []
    for rotulo, nome_do_modelo, campo in (
        ('categoria', 'CashFlowCategory', 'category_name'),
        ('grupo de categoria', 'CashFlowCategoryGroup', 'group_name'),
    ):
        ids = _repetidos(apps.get_model('transactions', nome_do_modelo), campo)
        if ids:
            problemas.append(f"{rotulo} (ids: {', '.join(map(str, ids))})")
    if problemas:
        raise RuntimeError(
            'Há nomes que só diferem na caixa em: ' + '; '.join(problemas)
            + '. Nada foi alterado: resolva à mão e rode a migração de novo.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0004_tipo_da_operacao_igual_ao_dos_lancamentos'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RunPython(recusar_duplicata, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='cashflowcategorygroup',
            constraint=models.UniqueConstraint(Lower('group_name'), name='uq_cash_flow_category_group_name_ci'),
        ),
        migrations.AddConstraint(
            model_name='cashflowcategory',
            constraint=models.UniqueConstraint(Lower('category_name'), name='uq_cash_flow_category_name_ci'),
        ),
    ]
