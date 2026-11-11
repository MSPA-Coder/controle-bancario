"""Excluir um lançamento conciliado não pode travar sem feedback, nem levar
a linha de extrato junto com ele.

O DEFEITO (02/10/2026)

`BankStatementLine.matched_entry` usa `on_delete=PROTECT`: apagar um
`CashFlowEntry` ainda referenciado por uma linha de extrato conciliada
levantava `django.db.models.deletion.ProtectedError`. `delete_transaction_
or_operation` não tratava essa exceção, que subia crua até a view como erro
500 -- o modal "Confirmar exclusão" ficava sem nenhum retorno visível.

O QUE ESTE ARQUIVO FIXA

A exclusão passa a funcionar mesmo com o lançamento conciliado: a linha de
extrato volta para "novo" (não conciliada) em vez de bloquear o delete ou
desaparecer junto -- o extrato que ela representa continua existindo, só
sem lançamento vinculado, pronta para o usuário conciliar de novo, criar um
lançamento novo a partir dela, ou marcar como ignorada (decisão do usuário,
não do sistema).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from bank_statements.models import LINE_STATUS_NEW, BankStatementImport, BankStatementLine
from bank_statements.reconciliation import reconcile_line_with_entry
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import ENTRY_TYPE_EXPENSE, OPERATION_SCOPE_ALL, STATUS_PROJECTED
from transactions import services
from transactions.models import CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def cenario():
    user = AppUser.objects.create_user(username="operador-exclusao", password="senha-segura")
    owner = AccountOwner.objects.create(name="Titular")
    banco = FinancialInstitution.objects.create(
        institution_name="Banco dos testes", institution_type="Banco"
    )
    conta = FinancialAccount.objects.create(owner=owner, institution=banco, account_name="Corrente")
    UserOwnerAccess.objects.create(
        user=user, owner=owner, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    categoria = CashFlowCategory.objects.create(category_name="Mercado")
    return user, conta, categoria


def _lancamento(user, conta, categoria):
    return services.create_transaction_batch(
        services.TransactionRequest(
            account_id=conta.id,
            category_id=categoria.id,
            entry_type=ENTRY_TYPE_EXPENSE,
            description="Mercado",
            entry_amount=Decimal("100.00"),
            installments=1,
            due_date=date(2026, 9, 10),
            status=STATUS_PROJECTED,
        ),
        user=user,
    )[0]


def test_excluir_lancamento_conciliado_apaga_e_devolve_a_linha_para_novo(cenario):
    user, conta, categoria = cenario
    lancamento = _lancamento(user, conta, categoria)
    lote = BankStatementImport.objects.create(
        account=conta, source_filename="extrato.ofx", row_count=1
    )
    linha = BankStatementLine.objects.create(
        import_batch=lote, account=conta, statement_date=date(2026, 9, 10),
        description="Mercado", amount=Decimal("-100.00"), line_hash="hash-exclusao-teste",
    )
    reconcile_line_with_entry(user, line_id=linha.id, entry_id=lancamento.id)

    services.delete_transaction_or_operation(lancamento, OPERATION_SCOPE_ALL, user=user)

    assert not CashFlowEntry.objects.filter(id=lancamento.id).exists()
    linha.refresh_from_db()
    assert linha.status == LINE_STATUS_NEW
    assert linha.matched_entry_id is None


def test_excluir_lancamento_nao_conciliado_continua_funcionando(cenario):
    user, conta, categoria = cenario
    lancamento = _lancamento(user, conta, categoria)

    services.delete_transaction_or_operation(lancamento, OPERATION_SCOPE_ALL, user=user)

    assert not CashFlowEntry.objects.filter(id=lancamento.id).exists()


@pytest.mark.parametrize(
    ("tabela", "evento"),
    [("entry_attachment", "DELETE"), ("bank_statement_line", "UPDATE")],
)
def test_erro_de_banco_ao_limpar_vinculos_derruba_a_exclusao_com_a_causa(cenario, tabela, evento):
    """O erro real do banco chega a quem chamou, e o lançamento não é apagado.

    A exclusão engolia qualquer `Exception` nos dois comandos que limpam anexo
    e vínculo de extrato (`except Exception: pass`, com o comentário de que o
    app poderia não estar instalado, e `bank_statements` é app obrigatório).
    Um erro de banco (timeout de 55 s, trava de 10 s, gatilho) sumia, e o
    comando seguinte falhava com "transação abortada", que esconde a causa.
    O gatilho abaixo faz o comando recusar com uma mensagem própria, no banco
    real e dentro da transação do teste.
    """
    from django.db import DatabaseError, connection

    from bank_statements.models import EntryAttachment

    user, conta, categoria = cenario
    lancamento = _lancamento(user, conta, categoria)
    # O DELETE do anexo só é emitido se houver anexo a apagar.
    EntryAttachment.objects.create(
        entry=lancamento, original_filename="recibo.txt", stored_filename="recibo.txt",
        stored_path="attachments/recibo.txt", file_size=1,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE FUNCTION recusa_de_proposito() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'travado de proposito'; END $$"
        )
        cursor.execute(
            f"CREATE TRIGGER recusa_de_proposito BEFORE {evento} ON {tabela} "
            "FOR EACH STATEMENT EXECUTE FUNCTION recusa_de_proposito()"
        )

    with pytest.raises(DatabaseError, match="travado de proposito"):
        services.delete_transaction_or_operation(lancamento, OPERATION_SCOPE_ALL, user=user)

    assert CashFlowEntry.objects.filter(id=lancamento.id).exists()
