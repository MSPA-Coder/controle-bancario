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
        ('bank_statements', '0001_initial'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='bankstatementimport',
            name='ck_bank_statement_import_filename_not_blank',
        ),
        migrations.AddConstraint(
            model_name='bankstatementimport',
            constraint=models.CheckConstraint(condition=models.Q(('source_filename__regex', '\\S')), name='ck_bank_statement_import_filename_not_blank'),
        ),
        migrations.RemoveConstraint(
            model_name='entryattachment',
            name='ck_entry_attachment_filename_not_blank',
        ),
        migrations.AddConstraint(
            model_name='entryattachment',
            constraint=models.CheckConstraint(condition=models.Q(('original_filename__regex', '\\S')), name='ck_entry_attachment_filename_not_blank'),
        ),
        migrations.RemoveConstraint(
            model_name='pendingstatementupload',
            name='ck_pending_statement_upload_filename_not_blank',
        ),
        migrations.AddConstraint(
            model_name='pendingstatementupload',
            constraint=models.CheckConstraint(condition=models.Q(('original_filename__regex', '\\S')), name='ck_pending_statement_upload_filename_not_blank'),
        ),
        migrations.RemoveIndex(
            model_name='bankstatementimport',
            name='bank_statem_account_9e538c_idx',
        ),
        migrations.RemoveIndex(
            model_name='bankstatementline',
            name='bank_statem_import__79616d_idx',
        ),
        migrations.RemoveIndex(
            model_name='bankstatementline',
            name='bank_statem_matched_eaa62f_idx',
        ),
        migrations.RemoveIndex(
            model_name='entryattachment',
            name='entry_attac_entry_i_bb47db_idx',
        ),
    ]
