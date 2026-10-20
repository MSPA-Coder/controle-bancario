"""Conciliação: a categoria escolhida vale no lote, e a linha vira transferência.

Em 20/10/2026 o extrato da conta em real da Avenue foi conciliado com as
remessas de câmbio marcadas como transferência no seletor de cada linha, e tudo
virou "Outros": os botões em lote usavam a categoria sugerida e ignoravam o
seletor. E nem havia como dizer "isto foi para a conta em dólar" -- o "Criar"
com a categoria de transferência falhava pedindo a conta destino, e o plano do
extrato não faz transferência entre moedas.

Estes testes fixam o que mudou:

- o seletor da linha pertence ao formulário do lote, e "Criar selecionadas",
  "Aplicar sugestões" e o "Criar" da própria linha usam o que foi escolhido;
- "Transferir" lança a linha como transferência para (ou de) outra conta sua,
  com o valor da outra moeda quando ela é outra, e concilia a ponta desta conta;
- o par de transferência fica sempre na mesma orientação -- a despesa é a
  origem, a receita aponta para ela -- ao criar, converter e editar pela ponta
  que recebe. Editar pela ponta que recebe trocava as duas linhas de conta.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from accounts.services import save_transfer_destination_accesses
from bank_statements import extrato
from bank_statements.models import (
    LINE_STATUS_NEW,
    LINE_STATUS_RECONCILED,
    BankStatementImport,
    BankStatementLine,
)
from bank_statements.reconciliation import (
    bulk_create_entries_from_lines,
    create_entry_from_line,
    transfer_from_line,
)
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import (
    CATEGORY_KIND_TRANSFER,
    CURRENCY_BRL,
    CURRENCY_USD,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    OPERATION_INTERNAL_TRANSFER,
    OPERATION_SCOPE_ALL,
    STATUS_REALIZED,
)
from transactions import services
from transactions.models import CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db

DIA = date(2026, 10, 8)


@pytest.fixture
def cenario(client):
    user = AppUser.objects.create_user(username="operador-avenue", password="senha-segura")
    titular = AccountOwner.objects.create(name="Mariano")
    UserOwnerAccess.objects.create(
        user=user, owner=titular, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    avenue = FinancialInstitution.objects.create(institution_name="Avenue", institution_type="Corretora")
    banco = FinancialInstitution.objects.create(institution_name="Mercado Pago", institution_type="Banco")
    contas = {
        "real": FinancialAccount.objects.create(
            owner=titular, institution=avenue, account_name="Conta Brasileira", currency=CURRENCY_BRL
        ),
        "dolar": FinancialAccount.objects.create(
            owner=titular, institution=avenue, account_name="Conta em dólar", currency=CURRENCY_USD
        ),
        "mp": FinancialAccount.objects.create(
            owner=titular, institution=banco, account_name="Conta 01", currency=CURRENCY_BRL
        ),
    }
    save_transfer_destination_accesses(user, {conta.id for conta in contas.values()})
    categorias = {
        "outros": CashFlowCategory.objects.create(category_name="Outros"),
        "impostos": CashFlowCategory.objects.create(category_name="Impostos e Tributos"),
        "transferencia": CashFlowCategory.objects.create(
            category_name="Transferência Entre Contas", kind=CATEGORY_KIND_TRANSFER
        ),
    }
    client.force_login(user)
    return client, user, contas, categorias


def _linha(conta, descricao, valor, n, dia=DIA):
    lote, _ = BankStatementImport.objects.get_or_create(
        account=conta, source_filename="br_statement.pdf", defaults={"row_count": 0}
    )
    return BankStatementLine.objects.create(
        import_batch=lote, account=conta, statement_date=dia, description=descricao,
        amount=Decimal(valor), line_hash=f"h{conta.id}-{n}",
    )


def _transferencia(user, origem, destino, categoria, valor, *, tipo=ENTRY_TYPE_EXPENSE, valor_destino=None):
    return services.create_transaction_batch(
        services.TransactionRequest(
            account_id=origem.id, category_id=categoria.id, entry_type=tipo, description="",
            entry_amount=Decimal(valor), installments=1, due_date=DIA, status=STATUS_REALIZED,
            realized_date=DIA, realized_amount=Decimal(valor), counterparty_account_id=destino.id,
            counterparty_amount=Decimal(valor_destino) if valor_destino else None,
        ),
        user=user,
    )


def _mensagens(resposta) -> str:
    return " ".join(str(m) for m in resposta.context["messages"])


def _orientacao_canonica(a: CashFlowEntry, b: CashFlowEntry) -> None:
    a.refresh_from_db()
    b.refresh_from_db()
    despesa, receita = (a, b) if a.entry_type == ENTRY_TYPE_EXPENSE else (b, a)
    assert despesa.entry_type == ENTRY_TYPE_EXPENSE and receita.entry_type == ENTRY_TYPE_INCOME
    assert despesa.source_entry_id is None
    assert receita.source_entry_id == despesa.id
    assert despesa.description.startswith("Conta Destino: ")
    assert receita.description.startswith("Conta Origem: ")
    assert despesa.description.endswith(receita.account.account_name)
    assert receita.description.endswith(despesa.account.account_name)


# --- A categoria escolhida vale no lote ---------------------------------------


def test_criar_selecionadas_usa_a_categoria_escolhida_em_cada_linha(cenario):
    client, user, contas, cat = cenario
    remessa = _linha(contas["real"], "BI Remessa de Câmbio", "-2967.36", 1)
    iof = _linha(contas["real"], "BI IOF sob remessa", "-32.64", 2)

    resposta = client.post(
        reverse("bank_statements:bulk_action_lines"),
        {
            "bulk_action": "create",
            "line_ids": [remessa.id, iof.id],
            f"categoria_{remessa.id}": cat["outros"].id,
            f"categoria_{iof.id}": cat["impostos"].id,
        },
        follow=True,
    )

    assert "2 lançamentos criados" in _mensagens(resposta)
    remessa.refresh_from_db()
    iof.refresh_from_db()
    assert remessa.matched_entry.category == cat["outros"]
    assert iof.matched_entry.category == cat["impostos"]


def test_criar_selecionadas_sem_escolha_continua_usando_a_sugestao(cenario):
    _client, user, contas, cat = cenario
    linha = _linha(contas["real"], "Texto que nada sugere", "-10.00", 1)

    criadas, erros = bulk_create_entries_from_lines(user, line_ids=[linha.id])

    assert (criadas, erros) == (1, [])
    linha.refresh_from_db()
    assert linha.matched_entry.category == cat["outros"]


def test_o_criar_da_linha_passa_pelo_lote_com_a_categoria_dela(cenario):
    client, user, contas, cat = cenario
    linha = _linha(contas["real"], "BI IOF sob remessa", "-32.64", 1)
    outra = _linha(contas["real"], "Outra linha marcada", "-5.00", 2)

    client.post(
        reverse("bank_statements:bulk_action_lines"),
        {
            "bulk_action": f"criar:{linha.id}",
            # Uma linha marcada não entra: o "Criar" é só da linha do botão.
            "line_ids": [outra.id],
            f"categoria_{linha.id}": cat["impostos"].id,
            f"categoria_{outra.id}": cat["outros"].id,
        },
    )

    linha.refresh_from_db()
    outra.refresh_from_db()
    assert linha.status == LINE_STATUS_RECONCILED
    assert linha.matched_entry.category == cat["impostos"]
    assert outra.status == LINE_STATUS_NEW


def test_aplicar_sugestoes_usa_a_categoria_escolhida_na_linha_que_o_plano_cria(cenario):
    _client, user, contas, cat = cenario
    linha = _linha(contas["real"], "Texto que nada sugere", "-10.00", 1)

    feitas, erros = extrato.aplicar(user, [linha], categorias={linha.id: cat["impostos"].id})

    assert erros == []
    assert feitas[extrato.CRIA] == 1
    linha.refresh_from_db()
    assert linha.matched_entry.category == cat["impostos"]


def test_criar_com_categoria_de_transferencia_aponta_para_o_transferir(cenario):
    _client, user, contas, cat = cenario
    linha = _linha(contas["real"], "BI Remessa de Câmbio", "-2967.36", 1)

    with pytest.raises(ValueError, match="use “Transferir”"):
        create_entry_from_line(user, line_id=linha.id, category_id=cat["transferencia"].id)

    linha.refresh_from_db()
    assert linha.status == LINE_STATUS_NEW
    assert not CashFlowEntry.objects.exists()


def test_a_tela_liga_o_seletor_ao_lote_e_oferece_transferir(cenario):
    client, _user, contas, cat = cenario
    linha = _linha(contas["real"], "BI Remessa de Câmbio", "-2967.36", 1)

    html = client.get(reverse("bank_statements:reconciliation_view")).content.decode()

    assert f'name="categoria_{linha.id}" form="bulkPendingLinesForm"' in html
    assert f'value="criar:{linha.id}"' in html
    assert reverse("bank_statements:transfer_from_line") in html
    assert 'name="other_amount"' in html
    # Transferência não é categoria do "Criar": ela tem outra ponta.
    assert cat["transferencia"].category_name not in html
    assert "Conta em dólar (USD)" in html


# --- "Transferir" ---------------------------------------------------------------


def test_remessa_de_cambio_vira_transferencia_para_a_conta_em_dolar(cenario):
    client, _user, contas, cat = cenario
    linha = _linha(contas["real"], "BI Remessa de Câmbio Padrão Investimento BR-EUA", "-2967.36", 1)

    resposta = client.post(
        reverse("bank_statements:transfer_from_line"),
        {"line_id": linha.id, "other_account_id": contas["dolar"].id, "other_amount": "540.12"},
        follow=True,
    )

    assert "Transferência lançada e conciliada" in _mensagens(resposta)
    linha.refresh_from_db()
    assert linha.status == LINE_STATUS_RECONCILED
    saida = linha.matched_entry
    assert saida.account_id == contas["real"].id
    assert saida.entry_type == ENTRY_TYPE_EXPENSE
    assert saida.realized_amount == Decimal("2967.36")
    assert saida.category == cat["transferencia"]
    assert saida.operation_type == OPERATION_INTERNAL_TRANSFER
    entrada = CashFlowEntry.objects.get(account=contas["dolar"])
    assert entrada.entry_amount == entrada.realized_amount == Decimal("540.12")
    assert entrada.status == STATUS_REALIZED and entrada.realized_date == DIA
    _orientacao_canonica(saida, entrada)


def test_entre_moedas_sem_o_valor_da_outra_ponta_nada_e_gravado(cenario):
    _client, user, contas, _cat = cenario
    linha = _linha(contas["real"], "BI Remessa de Câmbio", "-2967.36", 1)

    with pytest.raises(ValueError, match="quanto foi creditado na conta destino"):
        transfer_from_line(user, line_id=linha.id, other_account_id=contas["dolar"].id)

    linha.refresh_from_db()
    assert linha.status == LINE_STATUS_NEW
    assert not CashFlowEntry.objects.exists()


def test_pix_recebido_vira_transferencia_vinda_da_outra_conta(cenario):
    _client, user, contas, _cat = cenario
    linha = _linha(contas["real"], "Recurso recebido via PIX", "3000.00", 1)

    transfer_from_line(user, line_id=linha.id, other_account_id=contas["mp"].id)

    linha.refresh_from_db()
    entrada = linha.matched_entry
    assert entrada.account_id == contas["real"].id and entrada.entry_type == ENTRY_TYPE_INCOME
    saida = CashFlowEntry.objects.get(account=contas["mp"])
    assert saida.entry_type == ENTRY_TYPE_EXPENSE
    assert saida.realized_amount == entrada.realized_amount == Decimal("3000.00")
    _orientacao_canonica(saida, entrada)


def test_credito_em_dolar_pede_quanto_saiu_da_conta_em_real(cenario):
    _client, user, contas, _cat = cenario
    linha = _linha(contas["dolar"], "Deposit", "540.12", 1)

    with pytest.raises(ValueError, match="Informe quanto saiu de Conta Brasileira"):
        transfer_from_line(user, line_id=linha.id, other_account_id=contas["real"].id)

    transfer_from_line(user, line_id=linha.id, other_account_id=contas["real"].id, other_amount=Decimal("2967.36"))

    linha.refresh_from_db()
    assert linha.matched_entry.realized_amount == Decimal("540.12")
    saida = CashFlowEntry.objects.get(account=contas["real"])
    assert saida.realized_amount == Decimal("2967.36")
    _orientacao_canonica(saida, linha.matched_entry)


def test_na_mesma_moeda_o_valor_da_outra_ponta_e_recusado(cenario):
    _client, user, contas, _cat = cenario
    linha = _linha(contas["real"], "Recurso recebido via PIX", "3000.00", 1)

    with pytest.raises(ValueError, match="mesma moeda"):
        transfer_from_line(
            user, line_id=linha.id, other_account_id=contas["mp"].id, other_amount=Decimal("3000.00")
        )
    assert not CashFlowEntry.objects.exists()


def test_transferir_para_conta_sem_concessao_de_destino_e_recusado(cenario):
    _client, user, contas, _cat = cenario
    save_transfer_destination_accesses(user, {contas["real"].id, contas["mp"].id})
    linha = _linha(contas["real"], "BI Remessa de Câmbio", "-2967.36", 1)

    with pytest.raises(ValueError, match="conta destino"):
        transfer_from_line(
            user, line_id=linha.id, other_account_id=contas["dolar"].id, other_amount=Decimal("540.12")
        )
    assert not CashFlowEntry.objects.exists()


@pytest.mark.parametrize("valor", ["abc", "NaN", "Infinity"])
def test_valor_da_outra_moeda_invalido_volta_como_mensagem(cenario, valor):
    client, _user, contas, _cat = cenario
    linha = _linha(contas["real"], "BI Remessa de Câmbio", "-2967.36", 1)

    resposta = client.post(
        reverse("bank_statements:transfer_from_line"),
        {"line_id": linha.id, "other_account_id": contas["dolar"].id, "other_amount": valor},
        follow=True,
    )

    assert resposta.status_code == 200
    assert "Valor monetário inválido" in _mensagens(resposta)
    assert not CashFlowEntry.objects.exists()


def test_transferir_linha_ja_conciliada_e_recusado(cenario):
    _client, user, contas, _cat = cenario
    linha = _linha(contas["real"], "Recurso recebido via PIX", "3000.00", 1)
    transfer_from_line(user, line_id=linha.id, other_account_id=contas["mp"].id)

    with pytest.raises(ValueError, match="já conciliada"):
        transfer_from_line(user, line_id=linha.id, other_account_id=contas["mp"].id)
    assert CashFlowEntry.objects.count() == 2


# --- Orientação do par: a despesa é a origem ------------------------------------


def test_transferencia_lancada_pela_conta_que_recebe_fica_com_a_despesa_como_origem(cenario):
    _client, user, contas, cat = cenario

    entrada, saida = _transferencia(user, contas["real"], contas["mp"], cat["transferencia"], "3000.00", tipo=ENTRY_TYPE_INCOME)

    assert entrada.account_id == contas["real"].id and saida.account_id == contas["mp"].id
    _orientacao_canonica(saida, entrada)


def test_converter_uma_receita_em_transferencia_orienta_o_par(cenario):
    _client, user, contas, cat = cenario
    receita = services.create_transaction_batch(
        services.TransactionRequest(
            account_id=contas["real"].id, category_id=cat["outros"].id, entry_type=ENTRY_TYPE_INCOME,
            description="Recurso recebido via PIX", entry_amount=Decimal("3000.00"), installments=1,
            due_date=DIA, status=STATUS_REALIZED, realized_date=DIA, realized_amount=Decimal("3000.00"),
        ),
        user=user,
    )[0]

    convertidas = services.update_transaction_operation(
        receita,
        services.TransactionRequest(
            account_id=contas["real"].id, category_id=cat["transferencia"].id, entry_type=ENTRY_TYPE_INCOME,
            description="", entry_amount=Decimal("3000.00"), installments=1, due_date=DIA,
            status=STATUS_REALIZED, realized_date=DIA, realized_amount=Decimal("3000.00"),
            counterparty_account_id=contas["mp"].id,
        ),
        OPERATION_SCOPE_ALL,
        user=user,
    )

    receita.refresh_from_db()
    assert receita.account_id == contas["real"].id and receita.entry_type == ENTRY_TYPE_INCOME
    saida = next(e for e in convertidas if e.id != receita.id)
    assert saida.account_id == contas["mp"].id
    _orientacao_canonica(saida, receita)


def test_editar_pela_ponta_que_recebe_nao_troca_as_linhas_de_conta(cenario):
    _client, user, contas, cat = cenario
    saida, entrada = _transferencia(
        user, contas["real"], contas["dolar"], cat["transferencia"], "2967.36", valor_destino="540.12"
    )
    linha = _linha(contas["dolar"], "Deposit", "540.12", 1)
    linha.matched_entry = entrada
    linha.status = LINE_STATUS_RECONCILED
    linha.save()

    # O formulário da ponta que recebe: a conta dela, o valor dela e, como
    # "valor creditado no destino", o da outra ponta (ver `_decorate_rows_for_editing`).
    services.update_transaction_operation(
        entrada,
        services.TransactionRequest(
            account_id=contas["dolar"].id, category_id=cat["transferencia"].id, entry_type=ENTRY_TYPE_INCOME,
            description="", entry_amount=Decimal("545.00"), installments=1, due_date=DIA,
            status=STATUS_REALIZED, realized_date=DIA, realized_amount=Decimal("545.00"),
            counterparty_account_id=contas["real"].id, counterparty_amount=Decimal("2967.36"),
        ),
        OPERATION_SCOPE_ALL,
        user=user,
    )

    entrada.refresh_from_db()
    saida.refresh_from_db()
    assert entrada.account_id == contas["dolar"].id and entrada.entry_type == ENTRY_TYPE_INCOME
    assert entrada.entry_amount == entrada.realized_amount == Decimal("545.00")
    assert saida.account_id == contas["real"].id and saida.entry_type == ENTRY_TYPE_EXPENSE
    assert saida.entry_amount == saida.realized_amount == Decimal("2967.36")
    linha.refresh_from_db()
    assert linha.matched_entry.account_id == linha.account_id
    _orientacao_canonica(saida, entrada)


def test_editar_pela_origem_continua_como_antes(cenario):
    _client, user, contas, cat = cenario
    saida, entrada = _transferencia(user, contas["real"], contas["mp"], cat["transferencia"], "100.00")

    services.update_transaction_operation(
        saida,
        services.TransactionRequest(
            account_id=contas["real"].id, category_id=cat["transferencia"].id, entry_type=ENTRY_TYPE_EXPENSE,
            description="", entry_amount=Decimal("120.00"), installments=1, due_date=DIA,
            status=STATUS_REALIZED, realized_date=DIA, realized_amount=Decimal("120.00"),
            counterparty_account_id=contas["mp"].id,
        ),
        OPERATION_SCOPE_ALL,
        user=user,
    )

    saida.refresh_from_db()
    entrada.refresh_from_db()
    assert saida.account_id == contas["real"].id and entrada.account_id == contas["mp"].id
    assert saida.realized_amount == entrada.realized_amount == Decimal("120.00")
    _orientacao_canonica(saida, entrada)
