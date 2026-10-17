from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bank_statements', '0007_fim_do_periodo_do_extrato'),
    ]

    operations = [
        migrations.AddField(
            model_name='pendingstatementupload',
            name='password_required',
            field=models.BooleanField(default=False),
        ),
    ]
