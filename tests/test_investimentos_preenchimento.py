"""O dado de investimento chega ao lançamento: ao conciliar e pelo comando.

Cobre o gancho (qualquer caminho que concilia uma linha de extrato com um
lançamento preenche o detalhe), o preenchimento dos lançamentos existentes
(idempotente, com simulação que não grava) e a publicação no contrato v4.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from bank_statements.models import BankStatementImport, BankStatementLine
from bank_statements.reconciliation import create_entry_from_line, reconcile_line_with_entry
from banking.models import FinancialAccount, FinancialInstitution
from core import patrimonio
from core.domain.finance import (
    CATEGORY_KIND_MANAGERIAL,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_REALIZED,
)
from core.domain.identity import USER_TYPE_ADMINISTRATOR
from transactions.models import CashFlowCategory, CashFlowEntry, EntryInvestmentDetail

pytestmark = pytest.mark.django_db


@pytest.fixture
def cenario():
    user = AppUser.objects.create_user(
        username="operador-investimentos", password="senha-segura", user_type=USER_TYPE_ADMINISTRATOR
    )
    owner = AccountOwner.objects.create(name="Titular")
    corretora = FinancialInstitution.objects.create(institution_name="Genial", institution_type="Corretora")
    banco = FinancialInstitution.objects.create(institution_name="Banco", institution_type="Banco")
    conta = FinancialAccount.objects.create(owner=owner, institution=corretora, account_name="Genial")
    corrente = FinancialAccount.objects.create(owner=owner, institution=banco, account_name="Corrente")
    UserOwnerAccess.objects.create(
        user=user, owner=owner, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    categoria = CashFlowCategory.objects.create(category_name="Proventos", kind=CATEGORY_KIND_MANAGERIAL)
    return user, conta, corrente, categoria


def _linha(conta, descricao, valor, *, dia=date(2026, 1, 27), numero=1):
    lote = BankStatementImport.objects.create(account=conta, source_filename="extrato.pdf", row_count=1)
    return BankStatementLine.objects.create(
        import_batch=lote, account=conta, statement_date=dia, description=descricao,
        amount=Decimal(valor), line_hash=f"h-{conta.id}-{numero}",
    )


def _lancamento(conta, categoria, descricao, *, tipo=ENTRY_TYPE_INCOME, valor="10.00", dia=date(2026, 1, 27)):
    return CashFlowEntry.objects.create(
        account=conta, category=categoria, entry_type=tipo, description=descricao, entry_amount=Decimal(valor),
        due_date=dia, status=STATUS_REALIZED, realized_date=dia, realized_amount=Decimal(valor),
    )


def _comando(*argumentos):
    saida = StringIO()
    call_command("preencher_investimentos", *argumentos, stdout=saida)
    return saida.getvalue()


def _publicado(entry):
    carregado = CashFlowEntry.objects.select_related("account", "category", "investment_detail").get(id=entry.id)
    return patrimonio._lancamento_v4(carregado, date(2026, 10, 18))


def test_criar_lancamento_a_partir_da_linha_preenche_o_detalhe(cenario):
    user, conta, _, categoria = cenario
    linha = _linha(conta, "Taxa de Remuneração Emprestimo Ações Brraizacnpr6", "7.31")

    create_entry_from_line(user, line_id=linha.id, category_id=categoria.id)

    detalhe = EntryInvestmentDetail.objects.get()
    assert detalhe.entry_id == BankStatementLine.objects.get(id=linha.id).matched_entry_id
    assert (detalhe.instrument_code, detalhe.income_kind, detalhe.income_role) == ("RAIZ4", "aluguel", "credito")


def test_liquidacao_de_pregao_guarda_a_data_e_a_nota(cenario):
    user, conta, _, categoria = cenario
    linha = _linha(conta, "Operações Bolsa D+2 Pr 27/01/2026 Nc. 543216", "-500.00", dia=date(2026, 1, 29))

    create_entry_from_line(user, line_id=linha.id, category_id=categoria.id)

    detalhe = EntryInvestmentDetail.objects.get()
    assert detalhe.settlement_pregao_date == date(2026, 1, 27)
    assert detalhe.settlement_note == "543216"
    assert detalhe.instrument_code is None and detalhe.income_kind is None


def test_conciliar_com_lancamento_existente_preenche_pelo_texto_do_extrato(cenario):
    user, conta, _, categoria = cenario
    # O lançamento foi digitado à mão, sem o texto da corretora.
    entry = _lancamento(conta, categoria, "Dividendo da WEGE")
    linha = _linha(conta, "Dividendos Brwegeacnor0", "10.00")

    reconcile_line_with_entry(user, line_id=linha.id, entry_id=entry.id)

    detalhe = EntryInvestmentDetail.objects.get(entry=entry)
    assert (detalhe.instrument_code, detalhe.income_kind) == ("WEGE3", "dividendo")


def test_linha_que_nao_casa_nao_cria_detalhe(cenario):
    user, conta, _, categoria = cenario
    linha = _linha(conta, "Atualização de saldo: rendimentos", "1.00")

    create_entry_from_line(user, line_id=linha.id, category_id=categoria.id)

    assert not EntryInvestmentDetail.objects.exists()


def test_comando_simula_por_padrao_e_nao_grava(cenario):
    _, conta, _, categoria = cenario
    _lancamento(conta, categoria, "Dividendos Brwegeacnor0")

    saida = _comando()
    assert "criar" in saida and "WEGE3" in saida and "simulação" in saida
    assert not EntryInvestmentDetail.objects.exists()

    _comando("--dry-run")
    assert not EntryInvestmentDetail.objects.exists()


def test_comando_aplicar_e_idempotente(cenario):
    _, conta, corrente, categoria = cenario
    _lancamento(conta, categoria, "Dividendos Brwegeacnor0")
    _lancamento(conta, categoria, "Corretagem Executor - Btc", tipo=ENTRY_TYPE_EXPENSE, valor="0.50")
    _lancamento(corrente, categoria, "JUROS S/ CAPITAL DE CLIENTES EALT4 S/ 6,300")
    _lancamento(corrente, categoria, "Salário")

    primeira = _comando("--aplicar")
    assert EntryInvestmentDetail.objects.count() == 3
    assert "gravados: 3" in primeira
    marcas = list(EntryInvestmentDetail.objects.order_by("id").values_list("id", "updated_at"))

    segunda = _comando("--aplicar")
    assert "gravados: 0" in segunda
    assert list(EntryInvestmentDetail.objects.order_by("id").values_list("id", "updated_at")) == marcas
    assert "(nada foi gravado: simulação): 0" in _comando()


def test_comando_atualiza_o_que_mudou_e_nunca_apaga(cenario):
    _, conta, _, categoria = cenario
    entry = _lancamento(conta, categoria, "Dividendos Brwegeacnor0")
    EntryInvestmentDetail.objects.create(entry=entry, income_kind="jcp")

    saida = _comando("--aplicar")

    assert "atualizar" in saida
    assert EntryInvestmentDetail.objects.get(entry=entry).income_kind == "dividendo"
    entry.description = "Texto que não casa"
    entry.save(update_fields=["description"])
    _comando("--aplicar")
    assert EntryInvestmentDetail.objects.get(entry=entry).income_kind == "dividendo"


def test_comando_recusa_aplicar_com_dry_run(cenario):
    with pytest.raises(CommandError):
        _comando("--aplicar", "--dry-run")


def test_o_contrato_v4_publica_so_o_que_esta_preenchido(cenario):
    _, conta, _, categoria = cenario
    com_ativo = _lancamento(conta, categoria, "Dividendos Brwegeacnor0")
    liquidacao = _lancamento(conta, categoria, "Operações Bolsa D+2 Pr 20/03/2026 Nc. *", tipo=ENTRY_TYPE_EXPENSE)
    comum = _lancamento(conta, categoria, "Salário")
    _comando("--aplicar")

    publicado = _publicado(com_ativo)
    assert publicado["instrument"] == "WEGE3"
    assert publicado["income_kind"] == "dividendo" and publicado["income_role"] == "credito"
    assert "settlement" not in publicado

    pregao = _publicado(liquidacao)
    assert pregao["settlement"] == {"pregao_date": "2026-03-20"}
    assert "instrument" not in pregao and "income_kind" not in pregao

    assert not {"instrument", "income_kind", "income_role", "settlement"} & set(_publicado(comum))
