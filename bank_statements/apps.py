from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class BankStatementsConfig(AppConfig):
    name = 'bank_statements'

    def ready(self):
        from .attachments import remover_arquivo_do_anexo
        from .investimentos_preenchimento import preencher_da_linha
        from .models import BankStatementLine, EntryAttachment

        # O arquivo do comprovante acompanha o registro: sem isto, excluir o
        # lançamento apaga a linha do anexo em cascata e deixa o arquivo no disco.
        post_delete.connect(
            remover_arquivo_do_anexo, sender=EntryAttachment, dispatch_uid="remover_arquivo_do_anexo"
        )

        # Lançamento que acaba de ser conciliado com uma linha de extrato ganha o
        # ativo e o tipo de renda lidos do texto (ver investimentos_preenchimento).
        post_save.connect(
            preencher_da_linha, sender=BankStatementLine, dispatch_uid="preencher_investimentos_da_linha"
        )
