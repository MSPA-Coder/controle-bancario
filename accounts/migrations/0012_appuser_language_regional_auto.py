# Idioma por usuário e formato regional "auto" (acompanha o idioma).
#
# Só apresentação. Usuário existente fica como está: o idioma novo nasce em
# "pt-br" (o que o sistema sempre mostrou) e o formato regional que já estava
# gravado ("br" ou "us") continua valendo. Quem nasce daqui para a frente começa
# em "auto". A coluna `regional_format` cresce de 2 para 4 caracteres para caber
# "auto"; nenhuma view do esquema `leitura` lê esta coluna.
#
# Reverter volta a coluna para 2 caracteres e descarta o idioma. Quem estiver em
# "auto" ao reverter vira "br" antes, para a restrição antiga não recusar.

from django.db import migrations, models


def auto_para_br(apps, schema_editor):
    AppUser = apps.get_model('accounts', 'AppUser')
    AppUser.objects.filter(regional_format='auto').update(regional_format='br')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_appuser_regional_format'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='appuser',
            name='ck_app_user_regional_format_valid',
        ),
        migrations.AlterField(
            model_name='appuser',
            name='regional_format',
            field=models.CharField(
                choices=[('auto', 'auto'), ('br', 'br'), ('us', 'us')],
                default='auto',
                max_length=4,
            ),
        ),
        migrations.AddField(
            model_name='appuser',
            name='language',
            field=models.CharField(
                choices=[('pt-br', 'pt-br'), ('en', 'en')],
                default='pt-br',
                max_length=5,
            ),
        ),
        migrations.AddConstraint(
            model_name='appuser',
            constraint=models.CheckConstraint(
                condition=models.Q(('language__in', ('pt-br', 'en'))),
                name='ck_app_user_language_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='appuser',
            constraint=models.CheckConstraint(
                condition=models.Q(('regional_format__in', ('auto', 'br', 'us'))),
                name='ck_app_user_regional_format_valid',
            ),
        ),
        # Último na ida, primeiro na volta: antes de a coluna encolher e a
        # restrição antiga voltar, quem estiver em "auto" passa para "br".
        migrations.RunPython(migrations.RunPython.noop, auto_para_br),
    ]
