"""Candidato de conciliação não pode depender de a linha do extrato ter
chegado antes ou depois do vencimento.

O DEFEITO (02/10/2026)

`candidate_entries_for_line`/`candidate_entries_for_lines` limitavam a busca
a `due_date` entre o início do mês e a DATA DO EXTRATO. Um recebimento que
cai um ou mais dias antes do vencimento (comum: aluguel com vencimento dia
12, Pix recebido dia 11) ficava sem nenhum candidato, mesmo com conta, tipo e
valor idênticos -- o usuário acabava criando um lançamento duplicado em vez
de conciliar com o que já existia.

O QUE ESTE ARQUIVO FIXA

O teto da janela de busca é o mês inteiro do extrato, não mais a data da
linha.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from bank_statements.models import BankStatementImport, BankStatementLine
from bank_statements.reconciliation import candidate_entries_for_line, candidate_entries_for_lines
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import ENTRY_TYPE_INCOME, STATUS_PROJECTED
from transactions import services
from transactions.models import CashFlowCategory

pytestmark = pytest.mark.django_db


@pytest.fixture
def cenario():
    user = AppUser.objects.create_user(username="operador-conciliacao", password="senha-segura")
    owner = AccountOwner.objects.create(name="Titular")
    banco = FinancialInstitution.objects.create(
        institution_name="Banco dos testes", institution_type="Banco"
    )
    conta = FinancialAccount.objects.create(owner=owner, institution=banco, account_name="Corrente")
    UserOwnerAccess.objects.create(
        user=user, owner=owner, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    receita = CashFlowCategory.objects.create(category_name="Aluguel")
    return user, conta, receita


def _criar_receita(user, conta, categoria, *, vencimento):
    return services.create_transaction_batch(
        services.TransactionRequest(
            account_id=conta.id,
            category_id=categoria.id,
            entry_type=ENTRY_TYPE_INCOME,
            description="Aluguel casa 1",
            entry_amount=Decimal("990.00"),
            installments=1,
            due_date=vencimento,
            status=STATUS_PROJECTED,
        ),
        user=user,
    )[0]


def _linha_extrato(conta, *, data, valor):
    lote = BankStatementImport.objects.create(
        account=conta, source_filename="extrato.ofx", row_count=1
    )
    return BankStatementLine.objects.create(
        import_batch=lote, account=conta, statement_date=data, description="Pix recebido",
        amount=valor, line_hash=f"hash-{conta.id}-{data.isoformat()}-{valor}",
    )


def test_recebimento_um_dia_antes_do_vencimento_e_candidato(cenario):
    user, conta, receita = cenario
    lancamento = _criar_receita(user, conta, receita, vencimento=date(2026, 9, 12))
    linha = _linha_extrato(conta, data=date(2026, 9, 11), valor=Decimal("990.00"))

    candidatos = list(candidate_entries_for_line(linha))

    assert lancamento.id in {entry.id for entry in candidatos}


def test_recebimento_no_mesmo_mes_apos_o_vencimento_continua_candidato(cenario):
    """O comportamento antigo (vencimento <= data do extrato) não pode
    regredir: só a borda de cima da janela mudou."""
    user, conta, receita = cenario
    lancamento = _criar_receita(user, conta, receita, vencimento=date(2026, 9, 5))
    linha = _linha_extrato(conta, data=date(2026, 9, 20), valor=Decimal("990.00"))

    candidatos = list(candidate_entries_for_line(linha))

    assert lancamento.id in {entry.id for entry in candidatos}


def test_recebimento_de_vencimento_do_mes_seguinte_nao_e_candidato(cenario):
    """A janela é o mês do extrato, não indefinidamente pra frente."""
    user, conta, receita = cenario
    _criar_receita(user, conta, receita, vencimento=date(2026, 10, 1))
    linha = _linha_extrato(conta, data=date(2026, 9, 11), valor=Decimal("990.00"))

    candidatos = list(candidate_entries_for_line(linha))

    assert candidatos == []


def test_versao_em_lote_concorda_com_a_versao_de_uma_linha(cenario):
    user, conta, receita = cenario
    lancamento = _criar_receita(user, conta, receita, vencimento=date(2026, 9, 12))
    linha = _linha_extrato(conta, data=date(2026, 9, 11), valor=Decimal("990.00"))

    candidatos_por_linha = candidate_entries_for_lines([linha])

    assert lancamento.id in {entry.id for entry in candidatos_por_linha[linha.id]}


def test_lancamento_ja_conciliado_com_outra_linha_nao_e_candidato(cenario):
    """Um lançamento só tem uma linha ativa: oferecê-lo levaria ao erro
    "Movimento já está conciliado com outra linha de extrato"."""
    from bank_statements.reconciliation import reconcile_line_with_entry

    user, conta, receita = cenario
    lancamento = _criar_receita(user, conta, receita, vencimento=date(2026, 9, 11))
    primeira = _linha_extrato(conta, data=date(2026, 9, 11), valor=Decimal("990.00"))
    reconcile_line_with_entry(user, line_id=primeira.id, entry_id=lancamento.id)
    lote = BankStatementImport.objects.create(account=conta, source_filename="outro.ofx", row_count=1)
    segunda = BankStatementLine.objects.create(
        import_batch=lote, account=conta, statement_date=date(2026, 9, 11),
        description="Pix recebido * Prov *", amount=Decimal("990.00"), line_hash="hash-prov",
    )

    assert list(candidate_entries_for_line(segunda)) == []
    assert candidate_entries_for_lines([segunda])[segunda.id] == []


# --- virada do mês (10/11/2026) ----------------------------------------------
#
# A janela era só o mês do extrato: a conta que vence no sábado, 31/10, e é paga
# na segunda, 02/11, ficava sem candidato, e a linha virava um lançamento novo ao
# lado do previsto ainda em aberto.


def test_vencimento_no_fim_do_mes_pago_no_comeco_do_seguinte_e_candidato(cenario):
    user, conta, receita = cenario
    lancamento = _criar_receita(user, conta, receita, vencimento=date(2026, 10, 31))
    linha = _linha_extrato(conta, data=date(2026, 11, 2), valor=Decimal("990.00"))

    assert [entry.id for entry in candidate_entries_for_line(linha)] == [lancamento.id]
    assert [entry.id for entry in candidate_entries_for_lines([linha])[linha.id]] == [lancamento.id]


def test_recebido_no_fim_do_mes_com_vencimento_no_comeco_do_seguinte_e_candidato(cenario):
    user, conta, receita = cenario
    lancamento = _criar_receita(user, conta, receita, vencimento=date(2026, 11, 2))
    linha = _linha_extrato(conta, data=date(2026, 10, 30), valor=Decimal("990.00"))

    assert [entry.id for entry in candidate_entries_for_line(linha)] == [lancamento.id]
    assert [entry.id for entry in candidate_entries_for_lines([linha])[linha.id]] == [lancamento.id]


def test_virada_do_mes_tem_limite_de_dias_e_so_vale_para_lancamento_em_aberto(cenario):
    from transactions.services import realize_transaction

    user, conta, receita = cenario
    _criar_receita(user, conta, receita, vencimento=date(2026, 10, 20))  # 13 dias antes: longe demais
    realizado = _criar_receita(user, conta, receita, vencimento=date(2026, 10, 30))
    realize_transaction(realizado, realized_date=date(2026, 10, 30), realized_amount=Decimal("990.00"), user=user)
    linha = _linha_extrato(conta, data=date(2026, 11, 2), valor=Decimal("990.00"))

    assert list(candidate_entries_for_line(linha)) == []
    assert candidate_entries_for_lines([linha])[linha.id] == []


def test_recorrencia_na_virada_fica_com_o_vencimento_vizinho_e_nao_com_o_do_fim_do_mes(cenario):
    """O pagamento de 02/11 vê o vencimento de 31/10, em aberto, e o de 30/11, já
    projetado: vale o único que está a poucos dias da linha."""
    from bank_statements.reconciliation import desempatar_pelo_dia

    user, conta, receita = cenario
    de_outubro = _criar_receita(user, conta, receita, vencimento=date(2026, 10, 31))
    _criar_receita(user, conta, receita, vencimento=date(2026, 11, 30))
    linha = _linha_extrato(conta, data=date(2026, 11, 2), valor=Decimal("990.00"))

    candidatos = list(candidate_entries_for_line(linha))
    assert len(candidatos) == 2
    assert [entry.id for entry in desempatar_pelo_dia(linha, candidatos)] == [de_outubro.id]


def test_dois_em_aberto_perto_da_linha_continuam_para_escolha_manual(cenario):
    from bank_statements.reconciliation import desempatar_pelo_dia

    user, conta, receita = cenario
    _criar_receita(user, conta, receita, vencimento=date(2026, 10, 31))
    _criar_receita(user, conta, receita, vencimento=date(2026, 11, 5))
    linha = _linha_extrato(conta, data=date(2026, 11, 2), valor=Decimal("990.00"))

    candidatos = list(candidate_entries_for_line(linha))
    assert len(desempatar_pelo_dia(linha, candidatos)) == 2
