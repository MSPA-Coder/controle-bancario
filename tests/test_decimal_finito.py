"""`parse_finite_decimal`: a única leitura de "texto vira Decimal finito".

Existiam nove cópias (ARQ-A1 da auditoria de 10/11/2026), e a recusa de
NaN/Infinity foi corrigida à mão em rodadas separadas. Aqui ficam o contrato da
função e, por cada ponto de entrada que a usa, a recusa do que não é número
finito, com a exceção e a mensagem que cada um sempre deu.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from bank_statements import adapters, ajustes, saldo
from bank_statements.views import _valor_opcional
from banking.services import _parse_estimated_spend, _parse_initial_balance
from core.domain.finance import parse_finite_decimal
from fechamento.myprofit import PacoteInvalidoError
from fechamento.myprofit import _decimal as decimal_do_pacote
from transactions.views import _to_decimal as decimal_do_formulario

NAO_FINITOS = ["NaN", "nan", "sNaN", "Infinity", "-Infinity", "inf", "-inf", " NaN "]
LIXO = ["abc", "1,2,3", "1 000", "12abc", "--1", ""]


@pytest.mark.parametrize(
    ("bruto", "comma", "esperado"),
    [
        ("1234.56", None, Decimal("1234.56")),
        ("  12.5  ", None, Decimal("12.5")),
        ("-12.5", None, Decimal("-12.5")),
        ("+3", None, Decimal("3")),
        ("1e3", None, Decimal("1E+3")),
        ("1,5", "decimal", Decimal("1.5")),
        ("-1,50", "decimal", Decimal("-1.50")),
        ("1.5", "decimal", Decimal("1.5")),
        ("1.234,56", "milhar", Decimal("1234.56")),
        ("1234,56", "milhar", Decimal("1234.56")),
        ("-1.234,56", "milhar", Decimal("-1234.56")),
        ("1234.56", "milhar", Decimal("1234.56")),  # sem vírgula, o ponto é decimal
        ("0", None, Decimal("0")),
        (Decimal("7.10"), None, Decimal("7.10")),
        (5, None, Decimal("5")),
        (1.5, None, Decimal("1.5")),
    ],
)
def test_le_numero_finito(bruto, comma, esperado):
    resultado = parse_finite_decimal(bruto, comma=comma)
    assert resultado == esperado
    assert isinstance(resultado, Decimal)


@pytest.mark.parametrize("comma", [None, "decimal", "milhar"])
@pytest.mark.parametrize(
    "bruto", [*NAO_FINITOS, *LIXO, None, "   ", float("nan"), float("inf"), Decimal("NaN")]
)
def test_recusa_vazio_lixo_e_nao_finito(bruto, comma):
    assert parse_finite_decimal(bruto, comma=comma) is None


def test_formato_ambiguo_com_virgula_decimal_nao_adivinha():
    """`1.234,56` com `comma="decimal"` vira `1.234.56`, que não é número: recusa, não adivinha."""
    assert parse_finite_decimal("1.234,56", comma="decimal") is None
    assert parse_finite_decimal("1,234.56", comma="decimal") is None


def test_comma_desconhecido_e_erro_de_programacao():
    with pytest.raises(ValueError, match="comma"):
        parse_finite_decimal("1", comma="ponto")  # type: ignore[arg-type]


def test_nao_aplica_a_faixa_do_banco():
    """Quem chama decide a faixa (`assert_money_in_range`): 1e999 é finito."""
    assert parse_finite_decimal("1e999") == Decimal("1E+999")


# --- Cada ponto de entrada recusa o que não é finito, com a sua exceção e mensagem ---

@pytest.mark.parametrize("texto", [*NAO_FINITOS, "abc"])
def test_saldo_inicial_da_conta(texto):
    with pytest.raises(ValueError, match="Saldo inicial inválido"):
        _parse_initial_balance(texto)


def test_saldo_inicial_vazio_e_zero_e_virgula_decimal_vale():
    assert _parse_initial_balance(None) == Decimal("0.00")
    assert _parse_initial_balance("  ") == Decimal("0.00")
    assert _parse_initial_balance("12,50") == Decimal("12.50")


@pytest.mark.parametrize("texto", [*NAO_FINITOS, "abc", "1e999"])
def test_gasto_estimado_do_cartao(texto):
    with pytest.raises(ValueError, match="Gasto mensal estimado do cartão inválido"):
        _parse_estimated_spend(texto)


def test_gasto_estimado_vazio_deixa_a_mediana_decidir_e_milhar_vale():
    assert _parse_estimated_spend("") is None
    assert _parse_estimated_spend(None) is None
    assert _parse_estimated_spend("1.234,567") == Decimal("1234.57")


@pytest.mark.parametrize("texto", [*NAO_FINITOS, "abc"])
def test_valor_opcional_da_transferencia(texto):
    with pytest.raises(ValueError, match="Valor monetário inválido"):
        _valor_opcional(texto)


def test_valor_opcional_vazio_e_none():
    assert _valor_opcional("") is None
    assert _valor_opcional(None) is None
    assert _valor_opcional("1,5") == Decimal("1.5")


@pytest.mark.parametrize("texto", [*NAO_FINITOS, "abc"])
def test_valor_do_formulario_de_lancamento(texto):
    with pytest.raises(ValueError, match="Valor monetário inválido"):
        decimal_do_formulario(texto)


def test_valor_do_formulario_vazio_devolve_o_padrao():
    assert decimal_do_formulario("") is None
    assert decimal_do_formulario(None, default=Decimal("0")) == Decimal("0")
    assert decimal_do_formulario("1,5") == Decimal("1.5")


@pytest.mark.parametrize("texto", [*NAO_FINITOS, "abc"])
def test_valor_do_extrato_importado(texto):
    with pytest.raises(ValueError):
        adapters._to_decimal(texto)


def test_valor_do_extrato_fora_da_faixa_e_recusado():
    with pytest.raises(ValueError, match="limite"):
        adapters._to_decimal("99999999999.00")


@pytest.mark.parametrize("valor", [*NAO_FINITOS, "abc", float("nan")])
def test_valor_do_arquivo_de_ajustes(valor):
    with pytest.raises(ValueError, match="Valor inválido"):
        ajustes._decimal(valor, "Valor")


@pytest.mark.parametrize("valor", [*NAO_FINITOS, "abc", ""])
def test_saldo_informado(valor):
    with pytest.raises(ValueError, match="Saldo inválido"):
        saldo._decimal(valor, "Saldo")


def test_saldo_informado_aceita_formato_brasileiro_e_recusa_fora_da_faixa():
    assert saldo._decimal("1.234,56", "Saldo") == Decimal("1234.56")
    with pytest.raises(ValueError, match="limite"):
        saldo._decimal("99999999999,00", "Saldo")


@pytest.mark.parametrize("valor", [*NAO_FINITOS, "abc"])
def test_numero_do_pacote_myprofit(valor):
    with pytest.raises(PacoteInvalidoError, match="Número inválido em quantidade"):
        decimal_do_pacote(valor, "quantidade")


def test_numero_do_pacote_myprofit_vazio_e_zero():
    assert decimal_do_pacote(None, "quantidade") == Decimal("0")
    assert decimal_do_pacote("", "quantidade") == Decimal("0")
    assert decimal_do_pacote(1.5, "quantidade") == Decimal("1.5")
