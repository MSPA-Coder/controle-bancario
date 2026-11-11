"""Lista onde o banco conectado se afasta do esquema que os modelos declaram.

    python manage.py conferir_esquema
    python manage.py conferir_esquema --resumo

Só lê o catálogo do PostgreSQL; não altera nada. Sai com código 1 quando há
diferença. O motivo de existir e o que ele não confere estão em `core/esquema.py`.
"""

from __future__ import annotations

import sys
from collections import Counter

from django.core.management.base import BaseCommand

from core.esquema import diferencas


class Command(BaseCommand):
    help = "Compara o esquema do banco conectado com o que os modelos declaram (só leitura)."

    def add_arguments(self, parser):
        parser.add_argument("--resumo", action="store_true", help="Só a contagem por tipo de diferença.")

    def handle(self, *args, resumo, **options):
        achadas = diferencas()
        if not achadas:
            self.stdout.write("Nenhuma diferença: o banco tem o esquema dos modelos.")
            return

        if not resumo:
            for diferenca in achadas:
                self.stdout.write(str(diferenca))
            self.stdout.write("")
        for tipo, quantidade in sorted(Counter(d.tipo for d in achadas).items()):
            self.stdout.write(f"{quantidade:4d}  {tipo}")
        self.stdout.write(f"{len(achadas):4d}  no total")
        sys.exit(1)
