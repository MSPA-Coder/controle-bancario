from django.apps import AppConfig
from django.db.models.signals import post_save


class BankStatementsConfig(AppConfig):
    name = 'bank_statements'

    def ready(self):
        from .investimentos_preenchimento import preencher_da_linha
        from .models import BankStatementLine

        # Lançamento que acaba de ser conciliado com uma linha de extrato ganha o
        # ativo e o tipo de renda lidos do texto (ver investimentos_preenchimento).
        post_save.connect(
            preencher_da_linha, sender=BankStatementLine, dispatch_uid="preencher_investimentos_da_linha"
        )
