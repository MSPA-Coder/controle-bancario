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
        ('banking', '0001_initial'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='financialinstitution',
            name='ck_financial_institution_name_not_blank',
        ),
        migrations.AddConstraint(
            model_name='financialinstitution',
            constraint=models.CheckConstraint(condition=models.Q(('institution_name__regex', '\\S')), name='ck_financial_institution_name_not_blank'),
        ),
        migrations.RemoveConstraint(
            model_name='financialaccount',
            name='ck_financial_account_name_not_blank',
        ),
        migrations.AddConstraint(
            model_name='financialaccount',
            constraint=models.CheckConstraint(condition=models.Q(('account_name__regex', '\\S')), name='ck_financial_account_name_not_blank'),
        ),
        migrations.RemoveIndex(
            model_name='financialaccount',
            name='financial_a_owner_i_7633fc_idx',
        ),
        migrations.RemoveIndex(
            model_name='financialaccount',
            name='financial_a_institu_5cc945_idx',
        ),
    ]
