"""`leitura.extrato_linha.pagamento_de_fatura`: a regra do CB, gravada na linha.

O FinancasMCP reconhecia pagamento de fatura por regex na descrição. A regra é
`fatura.eh_pagamento`; a coluna `bank_statement_line.is_card_payment` guarda o
resultado e a view o publica. Aqui se prova: a importação marca a linha, a
edição de descrição ou valor remarca, a view devolve a coluna, a migração
preenche as linhas existentes com o mesmo critério e preserva as concessões.
"""

from __future__ import annotations

import importlib
import itertools
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection

from accounts.models import AccountOwner
from bank_statements import fatura
from bank_statements.models import BankStatementImport, BankStatementLine
from banking.models import FinancialAccount, FinancialInstitution

pytestmark = pytest.mark.django_db

DESCRICOES = [
    "Pag Fatura Boleto",
    "Pagamentos Validos Normais",
    "PAGAMENTO",
    "  pagamento recebido",
    "PAGUE MENOS",
    "Compra Pag Seguro",
    "Estorno",
    "",
    "Pagção",
    "Pag_x",
    "Pág Fatura",
]
VALORES = [Decimal("300.00"), Decimal("-300.00")]


@pytest.fixture
def lote():
    titular = AccountOwner.objects.create(name="Titular do pagamento")
    instituicao = FinancialInstitution.objects.create(institution_name="Banco", institution_type="Banco")
    conta = FinancialAccount.objects.create(
        owner=titular, institution=instituicao, account_name="Cartao", initial_balance=Decimal("0.00")
    )
    return BankStatementImport.objects.create(account=conta, source_filename="f.csv", row_count=0)


_contador = itertools.count(1)


def _linha(lote, descricao, valor):
    return BankStatementLine.objects.create(
        import_batch=lote,
        account=lote.account,
        statement_date=date(2026, 11, 1),
        description=descricao,
        amount=valor,
        line_hash=f"h{next(_contador)}",
    )


def _da_view(linha_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pagamento_de_fatura FROM leitura.extrato_linha WHERE id = %s", [linha_id])
        return cursor.fetchone()[0]


def test_a_view_devolve_o_que_eh_pagamento_decide(lote):
    for descricao in DESCRICOES:
        for valor in VALORES:
            linha = _linha(lote, descricao, valor)
            esperado = fatura.eh_pagamento(linha)
            assert linha.is_card_payment is esperado
            assert _da_view(linha.id) is esperado, (descricao, valor)
    assert _da_view(BankStatementLine.objects.get(description="Pag Fatura Boleto", amount=300).id) is True
    assert _da_view(BankStatementLine.objects.get(description="Pag Fatura Boleto", amount=-300).id) is False


def test_editar_descricao_ou_valor_remarca_a_linha(lote):
    linha = _linha(lote, "Compra", Decimal("50.00"))
    assert _da_view(linha.id) is False

    linha.description = "Pagamento recebido"
    linha.save(update_fields=["description"])
    assert _da_view(linha.id) is True

    linha.amount = Decimal("-50.00")
    linha.save(update_fields=["amount"])
    assert _da_view(linha.id) is False

    linha.amount = Decimal("50.00")
    linha.save()
    assert _da_view(linha.id) is True

    linha.description = "Pague Menos"
    linha.save()
    assert _da_view(linha.id) is False


def test_migracao_preenche_com_o_mesmo_criterio_da_funcao(lote):
    migracao = importlib.import_module("bank_statements.migrations.0003_linha_de_extrato_pagamento_de_fatura")
    linhas = [_linha(lote, d, v) for d in DESCRICOES for v in VALORES]
    BankStatementLine.objects.update(is_card_payment=False)

    migracao.preencher(_Apps(), None)

    for linha in linhas:
        linha.refresh_from_db()
        assert linha.is_card_payment is fatura.eh_pagamento(linha), (linha.description, linha.amount)


class _Apps:
    @staticmethod
    def get_model(app, nome):
        return BankStatementLine


def test_recriar_a_view_preserva_dono_comentario_e_concessao():
    migracao = importlib.import_module("bank_statements.migrations.0003_linha_de_extrato_pagamento_de_fatura")
    with connection.cursor() as cursor:
        cursor.execute("CREATE ROLE leitor_de_teste_pagamento")
        cursor.execute("GRANT SELECT ON leitura.extrato_linha TO leitor_de_teste_pagamento")
        cursor.execute(
            "SELECT relowner, relacl::text, obj_description(oid, 'pg_class') FROM pg_class WHERE oid = 'leitura.extrato_linha'::regclass"
        )
        antes = cursor.fetchone()

        cursor.execute(migracao.VIEW)

        cursor.execute(
            "SELECT relowner, relacl::text, obj_description(oid, 'pg_class') FROM pg_class WHERE oid = 'leitura.extrato_linha'::regclass"
        )
        depois = cursor.fetchone()
        cursor.execute("SELECT has_table_privilege('leitor_de_teste_pagamento', 'leitura.extrato_linha', 'SELECT')")
        pode = cursor.fetchone()[0]
    assert depois == antes
    assert pode is True
