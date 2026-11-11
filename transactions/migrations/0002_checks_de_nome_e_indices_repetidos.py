"""Nome em branco passa a ser recusado de verdade e saem índices repetidos.

O check antigo (expressão regular com `.+` entre espaços opcionais) aceitava
texto só de espaços, porque o `.+` casa espaço; o novo exige ao menos um
caractere que não seja espaço (barra invertida e S maiúsculo). Os índices removidos
repetiam o que o Django já cria para a chave estrangeira (ou `db_index=True`)
na mesma coluna.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0001_initial'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='cashflowcategorygroup',
            name='ck_cash_flow_category_group_name_not_blank',
        ),
        migrations.AddConstraint(
            model_name='cashflowcategorygroup',
            constraint=models.CheckConstraint(condition=models.Q(('group_name__regex', '\\S')), name='ck_cash_flow_category_group_name_not_blank'),
        ),
        migrations.RemoveConstraint(
            model_name='cashflowcategory',
            name='ck_cash_flow_category_name_not_blank',
        ),
        migrations.AddConstraint(
            model_name='cashflowcategory',
            constraint=models.CheckConstraint(condition=models.Q(('category_name__regex', '\\S')), name='ck_cash_flow_category_name_not_blank'),
        ),
        migrations.RemoveConstraint(
            model_name='bankoperation',
            name='ck_bank_operation_key_not_blank',
        ),
        migrations.AddConstraint(
            model_name='bankoperation',
            constraint=models.CheckConstraint(condition=models.Q(('operation_key__regex', '\\S')), name='ck_bank_operation_key_not_blank'),
        ),
        migrations.RemoveIndex(
            model_name='cashflowentry',
            name='cash_flow_e_operati_60d3fd_idx',
        ),
        migrations.RemoveIndex(
            model_name='cashflowentry',
            name='cash_flow_e_bank_op_65cc45_idx',
        ),
        migrations.RemoveIndex(
            model_name='cashflowentry',
            name='cash_flow_e_source__2bb4eb_idx',
        ),
    ]
