"""Inclui a permissão de reclassificação em lote, que existia no código mas não no catálogo.

`banking.reclassify` está em `PERMISSION_DEFINITIONS`, no perfil Operador e protege a
tela de reclassificação, mas nenhuma migration criou a linha em `app_permission`.
Sem a linha, a matriz de permissões não a mostrava e `save_function_permissions` a
ignorava em silêncio: só administrador (que tem todas) conseguia usar a tela.

A migration só cria a linha. Ninguém ganha o acesso sozinho: quem já tem o perfil
Operador precisa que um administrador reaplique o perfil ou marque a permissão.
"""

from django.db import migrations


PERMISSION_NAME = "banking.reclassify"
PERMISSION_DESCRIPTION = "Reclassificar categorias de lançamentos em lote"


def add_permission(apps, _schema_editor):
    permission = apps.get_model("accounts", "AppPermission")
    permission.objects.update_or_create(
        name=PERMISSION_NAME,
        defaults={"description": PERMISSION_DESCRIPTION},
    )


def remove_permission(apps, _schema_editor):
    apps.get_model("accounts", "AppPermission").objects.filter(name=PERMISSION_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_appuser_language_regional_auto")]

    operations = [migrations.RunPython(add_permission, remove_permission)]
