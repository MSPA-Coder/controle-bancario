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
        ('accounts', '0002_initial'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='accountowner',
            constraint=models.CheckConstraint(condition=models.Q(('name__regex', '\\S')), name='ck_account_owner_owner_name_not_blank'),
        ),
        migrations.RemoveIndex(
            model_name='userpermission',
            name='user_permis_user_id_281a2f_idx',
        ),
        migrations.RemoveIndex(
            model_name='userpermission',
            name='user_permis_permiss_0999ee_idx',
        ),
    ]
