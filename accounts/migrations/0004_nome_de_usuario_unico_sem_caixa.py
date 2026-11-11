"""Nome de usuário único sem diferenciar maiúsculas e minúsculas.

O login procura por `username__iexact`: dois usuários que só diferem na caixa
("Ana" e "ana") dariam `MultipleObjectsReturned`, erro 500 para os dois. Antes
só o byte a byte era único. Em produção havia 0 duplicatas (medido em
10/11/2026).

A conferência abaixo roda antes do índice e **recusa** a migração, inteira e sem
alterar nada, se houver duplicata: o nome de uma conta não se apaga nem se
renomeia por migração. Quem decide é o mantenedor, olhando os ids que a
mensagem lista. Consulta para ver antes:

    SELECT lower(username), count(*), array_agg(id) FROM app_user
    GROUP BY 1 HAVING count(*) > 1;
"""

from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def recusar_duplicata(apps, schema_editor):
    AppUser = apps.get_model('accounts', 'AppUser')
    repetidos = (
        AppUser.objects.annotate(chave=Lower('username'))
        .values('chave')
        .annotate(total=Count('id'))
        .filter(total__gt=1)
    )
    if repetidos:
        ids = sorted(
            AppUser.objects.annotate(chave=Lower('username'))
            .filter(chave__in=[r['chave'] for r in repetidos])
            .values_list('id', flat=True)
        )
        raise RuntimeError(
            'Há usuários cujo nome só difere na caixa (ids: '
            + ', '.join(map(str, ids))
            + '). Nada foi alterado: resolva à mão e rode a migração de novo.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_checks_de_nome_e_indices_repetidos'),
        ('core', '0004_igualar_esquema_ao_das_migracoes'),
    ]

    operations = [
        migrations.RunPython(recusar_duplicata, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='appuser',
            constraint=models.UniqueConstraint(Lower('username'), name='uq_app_user_username_ci'),
        ),
    ]
