from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bank_statements', '0008_pdf_com_senha'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankstatementimport',
            name='statement_holdings',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
