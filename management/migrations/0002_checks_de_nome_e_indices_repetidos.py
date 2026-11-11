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
        ('management', '0001_initial'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='managementtag',
            name='ck_management_tag_name_not_blank',
        ),
        migrations.AddConstraint(
            model_name='managementtag',
            constraint=models.CheckConstraint(condition=models.Q(('tag_name__regex', '\\S')), name='ck_management_tag_name_not_blank'),
        ),
        migrations.RemoveConstraint(
            model_name='managementproject',
            name='ck_management_project_name_not_blank',
        ),
        migrations.AddConstraint(
            model_name='managementproject',
            constraint=models.CheckConstraint(condition=models.Q(('project_name__regex', '\\S')), name='ck_management_project_name_not_blank'),
        ),
        migrations.RemoveIndex(
            model_name='cashflowentrytag',
            name='cash_flow_e_entry_i_6649ec_idx',
        ),
        migrations.RemoveIndex(
            model_name='cashflowentrytag',
            name='cash_flow_e_tag_id_ef71b8_idx',
        ),
        migrations.RemoveIndex(
            model_name='cashflowentryproject',
            name='cash_flow_e_entry_i_9d12cd_idx',
        ),
        migrations.RemoveIndex(
            model_name='cashflowentryproject',
            name='cash_flow_e_project_ce7689_idx',
        ),
    ]
