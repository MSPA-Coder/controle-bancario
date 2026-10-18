"""O parser de investimentos lê ativo, tipo de renda, papel e liquidação da descrição.

As descrições são as reais de 2026 (Genial e SCP XP), sem valores. Parser puro:
roda sem banco.
"""
from __future__ import annotations

from datetime import date

import pytest

from bank_statements.investimentos import ativo_da_descricao, interpretar
from core.domain.finance import (
    INCOME_KIND_DIVIDEND,
    INCOME_KIND_JCP,
    INCOME_KIND_RENTAL,
    INCOME_ROLE_CREDIT,
    INCOME_ROLE_RENTAL_BROKERAGE,
    INCOME_ROLE_RENTAL_FEE,
    INCOME_ROLE_RENTAL_IRRF,
    INCOME_ROLE_REVERSAL,
)


@pytest.mark.parametrize(
    ("descricao", "ativo"),
    [
        ("Taxa de Remuneração Emprestimo Ações Brsmtoacnor3", "SMTO3"),
        ("Taxa de Remuneração Emprestimo Ações Braureacnor9", "AURE3"),
        ("Taxa de Remuneração Emprestimo Ações Brwegeacnor0", "WEGE3"),
        ("Taxa de Remuneração Emprestimo Ações Brraizacnpr6", "RAIZ4"),
        ("Taxa de Remuneração Emprestimo Ações Brazzaacnor9", "AZZA3"),
        ("Taxa de Remuneração Emprestimo Ações Brbbasacnor3", "BBAS3"),
        ("Taxa de Remuneração Emprestimo Ações Brhodlctf005", "HODL11"),
        ("Cred Reembolso Jcp-Btc Brbbasacnor3 0,00", "BBAS3"),
        ("Juros S/ Capital Prop Brbbasacnor3 1.300 13,57", "BBAS3"),
        ("Dividendos Brwegeacnor0", "WEGE3"),
        ("DIVIDENDOS DE CLIENTES EALT4 S/ 6,300", "EALT4"),
        ("JUROS S/ CAPITAL DE CLIENTES EALT4 S/ 6,300", "EALT4"),
        ("BRRAIZACNPR6", "RAIZ4"),
        # Sem regra: unit, BDR, texto sem código.
        ("Dividendos Brsantuntm05", None),
        ("Dividendos Brmeliddrn004", None),
        ("INSS benefício 01632823010", None),
        ("Atualização de saldo: rendimentos", None),
        ("S/ 6,300", None),
    ],
)
def test_o_ativo_vem_do_ticker_escrito_ou_do_codigo_impresso(descricao, ativo):
    assert ativo_da_descricao(descricao) == ativo


@pytest.mark.parametrize(
    ("descricao", "ativo", "tipo", "papel"),
    [
        ("Taxa de Remuneração Emprestimo Ações Brsmtoacnor3", "SMTO3", INCOME_KIND_RENTAL, INCOME_ROLE_CREDIT),
        ("Taxa de Remuneração Emprestimo Ações Brhodlctf005", "HODL11", INCOME_KIND_RENTAL, INCOME_ROLE_CREDIT),
        ("Cred Reembolso Jcp-Btc Brbbasacnor3 0,00", "BBAS3", INCOME_KIND_DIVIDEND, INCOME_ROLE_CREDIT),
        ("Cred Reembolso Jcp-Btc Brsmtoacnor3", "SMTO3", INCOME_KIND_DIVIDEND, INCOME_ROLE_CREDIT),
        ("Juros S/ Capital Prop Brbbasacnor3 1.300 13,57", "BBAS3", INCOME_KIND_JCP, INCOME_ROLE_CREDIT),
        ("Dividendos Brwegeacnor0", "WEGE3", INCOME_KIND_DIVIDEND, INCOME_ROLE_CREDIT),
        ("DIVIDENDOS DE CLIENTES EALT4 S/ 6,300", "EALT4", INCOME_KIND_DIVIDEND, INCOME_ROLE_CREDIT),
        ("JUROS S/ CAPITAL DE CLIENTES EALT4 S/ 6,300", "EALT4", INCOME_KIND_JCP, INCOME_ROLE_CREDIT),
        ("Irrf S/Rendimentos Empréstimos de Ações Ações Brraizacnpr6", "RAIZ4", INCOME_KIND_RENTAL,
         INCOME_ROLE_RENTAL_IRRF),
        ("Irrf S/Rendimentos Empréstimos de Ações Ações Brhodlctf005", "HODL11", INCOME_KIND_RENTAL,
         INCOME_ROLE_RENTAL_IRRF),
        ("Corretagem Executor - Btc", None, INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_BROKERAGE),
        ("Corretagem - Corretagem Executor - Btc", None, INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_BROKERAGE),
        ("Taxa de Remuneração Btc Ações da Brwegeacnor0", "WEGE3", INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_FEE),
        ("Tx de Liquidação de Emprest. de Ações Brwegeacnor0", "WEGE3", INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_FEE),
        # O estorno é tratado à parte, mas guarda o tipo da linha que desfaz.
        ("Estorno * Prov * Corretagem Executor - Btc", None, INCOME_KIND_RENTAL, INCOME_ROLE_REVERSAL),
        ("Estorno * Prov * Taxa de Remuneração Btc Ações da Brwegeacnor0", "WEGE3", INCOME_KIND_RENTAL,
         INCOME_ROLE_REVERSAL),
    ],
)
def test_tipo_de_renda_e_papel_da_linha(descricao, ativo, tipo, papel):
    detalhe = interpretar(descricao)
    assert detalhe is not None
    assert (detalhe.instrument_code, detalhe.income_kind, detalhe.income_role) == (ativo, tipo, papel)
    assert detalhe.settlement_pregao_date is None and detalhe.settlement_note is None


@pytest.mark.parametrize(
    ("descricao", "pregao", "nota"),
    [
        ("Operações Bolsa D+2 Pr 27/01/2026 Nc. 543216", date(2026, 1, 27), "543216"),
        ("Operações Bolsa D+1 Pr 28/01/2026 Nc. 556839", date(2026, 1, 28), "556839"),
        ("Operações Bolsa D+2 Pr 20/03/2026 Nc. *", date(2026, 3, 20), None),
        ("Liquidação - Operações Bolsa D+2 Pr 27/01/2026 Nc. 543216", date(2026, 1, 27), "543216"),
    ],
)
def test_liquidacao_de_pregao_traz_a_data_e_a_nota(descricao, pregao, nota):
    detalhe = interpretar(descricao)
    assert detalhe is not None
    assert detalhe.settlement_pregao_date == pregao
    assert detalhe.settlement_note == nota
    assert detalhe.instrument_code is None and detalhe.income_kind is None and detalhe.income_role is None


@pytest.mark.parametrize(
    "descricao",
    [
        # IRRF de pregão não é irrf_aluguel.
        "Irrf S/ Resultado Bolsa D+1 29/01/2026 Nc. 561118",
        "Nc. 543216 Irrf S/ Operações D+2 (Ações) Pr 27/01/2026",
        # Corretagem de mini-contrato: fora do escopo de renda.
        "Operações Bm&F Pr 06/01/2026 Nc. 126168",
        "Atualização de saldo: rendimentos",
        "Salário",
        "",
    ],
)
def test_o_que_nao_casa_fica_sem_campos(descricao):
    assert interpretar(descricao) is None


def test_palavra_inteira_nao_casa_pedaco_de_outra():
    assert interpretar("SUBDIVIDENDOS DIVERSOS") is None
    assert interpretar(None) is None


def test_data_impossivel_na_liquidacao_nao_vira_data():
    assert interpretar("Operações Bolsa D+2 Pr 31/02/2026 Nc. 1") is None
