"""Vocabulário e normalizadores do domínio financeiro."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from django.utils.translation import gettext, gettext_lazy

ENTRY_TYPE_INCOME: Final = "receita"
ENTRY_TYPE_EXPENSE: Final = "despesa"
VALID_ENTRY_TYPES: Final = (
    ENTRY_TYPE_INCOME,
    ENTRY_TYPE_EXPENSE,
)

STATUS_PROJECTED: Final = "a_vencer"
STATUS_PENDING: Final = "vencidos"
STATUS_REALIZED: Final = "realizado"
# Este conjunto explicito e compartilhado por modelos, views e filtros.
VALID_STATUSES: Final = (
    STATUS_PROJECTED,
    STATUS_PENDING,
    STATUS_REALIZED,
)
STATUS_OPTIONS: Final = (
    (STATUS_PROJECTED, gettext_lazy("A vencer")),
    (STATUS_PENDING, gettext_lazy("Vencidos")),
    (STATUS_REALIZED, gettext_lazy("Realizado")),
)
# Os filtros oferecem explicitamente todas as opcoes validas. Evite fatias:
# uma nova ordenacao poderia retirar silenciosamente um status valido.
STATUS_FILTER_OPTIONS: Final = STATUS_OPTIONS

# O que uma categoria significa para o resultado. Eram dois casos (gerencial ou
# "interna"), e o terceiro faltava: dinheiro que sai da conta sem mudar de dono e
# sem ter uma conta de destino neste sistema -- a liquidação de bolsa, que vira
# ação, e é o Renda Variável quem avalia. Chamar isso de despesa é errado, e
# chamar de transferência exigiria uma contraparte que não existe aqui.
CATEGORY_KIND_MANAGERIAL: Final = "gerencial"
CATEGORY_KIND_TRANSFER: Final = "transferencia"
CATEGORY_KIND_MOVEMENT: Final = "movimentacao"
VALID_CATEGORY_KINDS: Final = (
    CATEGORY_KIND_MANAGERIAL,
    CATEGORY_KIND_TRANSFER,
    CATEGORY_KIND_MOVEMENT,
)
CATEGORY_KIND_OPTIONS: Final = (
    (CATEGORY_KIND_MANAGERIAL, gettext_lazy("Gerencial (receita ou despesa)")),
    (CATEGORY_KIND_TRANSFER, gettext_lazy("Transferência entre contas")),
    (CATEGORY_KIND_MOVEMENT, gettext_lazy("Movimentação (não é receita nem despesa)")),
)
# Os dois que não entram em receita nem em despesa gerencial.
NON_MANAGERIAL_CATEGORY_KINDS: Final = (
    CATEGORY_KIND_TRANSFER,
    CATEGORY_KIND_MOVEMENT,
)

OPERATION_SINGLE: Final = "single"
OPERATION_INSTALLMENT: Final = "installment"
OPERATION_RECURRING: Final = "recurring"
OPERATION_INTERNAL_TRANSFER: Final = "internal_transfer"
COMPOSITE_OPERATION_TYPES: Final = {
    OPERATION_INSTALLMENT,
    OPERATION_RECURRING,
    OPERATION_INTERNAL_TRANSFER,
}

OPERATION_SCOPE_ALL: Final = "all"
OPERATION_SCOPE_SINGLE: Final = "single"
OPERATION_SCOPE_CURRENT_FUTURE: Final = "current_future"
VALID_OPERATION_SCOPES: Final = (
    OPERATION_SCOPE_ALL,
    OPERATION_SCOPE_SINGLE,
    OPERATION_SCOPE_CURRENT_FUTURE,
)

CALC_REPEAT: Final = "repeat"
CALC_DIVIDE: Final = "divide"

# A moeda pertence a CONTA, nunca ao lançamento: um lançamento é sempre de uma
# conta, e moeda repetida no lançamento é moeda que um dia diverge da conta --
# aí nenhum relatório sabe qual das duas vale. Uma corretora que guardasse duas
# moedas vira duas contas, como o extrato dela mesma apresenta.
CURRENCY_BRL: Final = "BRL"
CURRENCY_USD: Final = "USD"
VALID_CURRENCIES: Final = (
    CURRENCY_BRL,
    CURRENCY_USD,
)
CURRENCY_OPTIONS: Final = (
    (CURRENCY_BRL, gettext_lazy("Real (R$)")),
    (CURRENCY_USD, gettext_lazy("Dólar (US$)")),
)
CURRENCY_SYMBOLS: Final = {
    CURRENCY_BRL: "R$",
    CURRENCY_USD: "US$",
}
# Moeda de quem não tem conta: o orçamento é por categoria e mês, não por
# conta. Converter de uma moeda para outra é apresentação e não acontece aqui.
BASE_CURRENCY: Final = CURRENCY_BRL


class MixedCurrencyError(ValueError):
    """Somar contas de moedas diferentes é erro, não arredondamento.

    Este sistema registra fato, não converte moeda: não existe aqui a taxa que
    transformaria dólar em real, e inventar uma na hora de somar produziria um
    número que ninguém consegue auditar depois. Quando a seleção de contas
    atravessa moedas, o certo é recusar e pedir um recorte -- nunca devolver um
    total que parece certo.
    """

    def __init__(self, currencies: Iterable[str]) -> None:
        self.currencies = tuple(sorted(currencies))
        super().__init__(
            gettext(
                "As contas selecionadas têm moedas diferentes (%(moedas)s), e este sistema não converte moeda. Filtre por uma conta, um titular ou uma instituição de uma moeda só."
            )
            % {"moedas": ", ".join(self.currencies)}
        )

MAX_TRANSACTION_INSTALLMENTS: Final = 48
MAX_TRANSACTION_DESCRIPTION_LENGTH: Final = 255
MAX_PROJECTION_RANGE_MONTHS: Final = 120

VIEW_PROJECTED: Final = STATUS_PROJECTED
VIEW_PENDING: Final = STATUS_PENDING
VIEW_REALIZED: Final = STATUS_REALIZED
VIEW_ALL: Final = "todos"
VIEW_MODE_OPTIONS: Final = (
    (VIEW_ALL, gettext_lazy("Todos os modos")),
    (VIEW_PROJECTED, gettext_lazy("A vencer")),
    (VIEW_PENDING, gettext_lazy("Vencidos")),
    (VIEW_REALIZED, gettext_lazy("Realizado")),
)
# O seletor de modo segue integralmente o vocabulario valido acima.
VIEW_FILTER_MODE_OPTIONS: Final = VIEW_MODE_OPTIONS
VALID_VIEW_MODES: Final = {mode for mode, _label in VIEW_MODE_OPTIONS}


def normalize_view_mode(value: str | None, default: str = VIEW_PROJECTED) -> str:
    return value if value in VALID_VIEW_MODES else default

# Tipo de conta. O cartão de crédito é uma conta como as outras -- compras são
# despesas nela, na data da compra e com a categoria real -- mas o saldo dele é
# dívida: fica negativo por natureza, e pagar a fatura é transferência de uma
# ou mais contas para ele, não despesa. Ver "Cartão de crédito" em docs/domain.md.
#
# Aplicação (CDB, caixinha, Tesouro) é uma conta comum para o saldo -- não tem
# dado de cartão nenhum --, mas é um tipo e não um marcador: uma conta não é
# cartão e aplicação ao mesmo tempo. Existe para que o filtro global de contas
# (`core/account_group_filter.py`) reparta toda conta em exatamente um grupo.
ACCOUNT_KIND_REGULAR: Final = "conta"
ACCOUNT_KIND_CREDIT_CARD: Final = "cartao_credito"
ACCOUNT_KIND_INVESTMENT: Final = "aplicacao"
ACCOUNT_KIND_OPTIONS: Final = (
    (ACCOUNT_KIND_REGULAR, gettext_lazy("Conta")),
    (ACCOUNT_KIND_CREDIT_CARD, gettext_lazy("Cartão de crédito")),
    (ACCOUNT_KIND_INVESTMENT, gettext_lazy("Aplicação")),
)
VALID_ACCOUNT_KINDS: Final = (ACCOUNT_KIND_REGULAR, ACCOUNT_KIND_CREDIT_CARD, ACCOUNT_KIND_INVESTMENT)
# Os tipos sem dado de cartão: tudo que não é cartão.
NON_CARD_ACCOUNT_KINDS: Final = (ACCOUNT_KIND_REGULAR, ACCOUNT_KIND_INVESTMENT)
# Finalidade da conta. "Administrada" é a conta que só recebe, gere e distribui
# dinheiro de outras pessoas (os aluguéis do Jardim Iva): fica fora do fluxo
# pessoal por padrão, em vez de entrar nele como se fosse do titular. A finalidade
# vence o tipo da conta no filtro global de grupos (`core/account_group_filter.py`),
# para cada conta continuar em exatamente um grupo. Dinheiro que cruza a fronteira
# entre administrada e pessoal não é transferência: é repasse e renda.
ACCOUNT_PURPOSE_PERSONAL: Final = "pessoal"
ACCOUNT_PURPOSE_ADMINISTERED: Final = "administrada"
ACCOUNT_PURPOSE_OPTIONS: Final = (
    (ACCOUNT_PURPOSE_PERSONAL, gettext_lazy("Pessoal")),
    (ACCOUNT_PURPOSE_ADMINISTERED, gettext_lazy("Administrada (de terceiros)")),
)
VALID_ACCOUNT_PURPOSES: Final = (ACCOUNT_PURPOSE_PERSONAL, ACCOUNT_PURPOSE_ADMINISTERED)
CARD_DAY_MIN: Final = 1
CARD_DAY_MAX: Final = 31

# Dado estruturado de investimento no lançamento (`EntryInvestmentDetail`),
# lido da descrição do extrato da corretora (`bank_statements/investimentos.py`)
# e publicado no contrato patrimonio/v4. Texto livre de máquina, nunca traduzido.
INCOME_KIND_RENTAL: Final = "aluguel"
INCOME_KIND_JCP: Final = "jcp"
INCOME_KIND_DIVIDEND: Final = "dividendo"
VALID_INCOME_KINDS: Final = (INCOME_KIND_RENTAL, INCOME_KIND_JCP, INCOME_KIND_DIVIDEND)
INCOME_ROLE_CREDIT: Final = "credito"
INCOME_ROLE_RENTAL_IRRF: Final = "irrf_aluguel"
INCOME_ROLE_RENTAL_BROKERAGE: Final = "corretagem_aluguel"
INCOME_ROLE_RENTAL_FEE: Final = "taxa_aluguel"
INCOME_ROLE_REVERSAL: Final = "estorno"
VALID_INCOME_ROLES: Final = (
    INCOME_ROLE_CREDIT,
    INCOME_ROLE_RENTAL_IRRF,
    INCOME_ROLE_RENTAL_BROKERAGE,
    INCOME_ROLE_RENTAL_FEE,
    INCOME_ROLE_REVERSAL,
)
