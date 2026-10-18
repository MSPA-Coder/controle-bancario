"""Dado estruturado de investimento, lido da descrição do extrato da corretora.

A corretora imprime o ativo e o tipo de renda só como texto ("Taxa de
Remuneração Emprestimo Ações Brraizacnpr6"). O Controle de Renda Variável é o
dono dos papéis e precisa desses dados sem reinterpretar texto, então o CB os
extrai uma vez, aqui, e os publica no contrato `patrimonio/v4`.

Este módulo é puro: recebe uma descrição, devolve um `Detalhe` (ou `None`),
sem tocar o banco. Quem grava é `investimentos_preenchimento`.

O que se extrai:

* **ativo** (`instrument_code`): o ticker escrito (`EALT4`) ou o código tipo ISIN
  que a corretora imprime (`Brraizacnpr6` = RAIZ4). A classe do código dá o
  final do ticker: `ACNOR` = 3 (ordinária), `ACNPR` = 4 (preferencial) e `CTF` =
  11 (cota de fundo/ETF). Unit e BDR não têm regra: ficam sem ativo, e é melhor
  assim do que um ticker chutado. A regra do ticker é a de
  `ticker_from_description` do patch 0012 do Wealthfolio (ver o plano de
  18/10/2026), acrescida da classe CTF;
* **tipo de renda** (`income_kind`): `aluguel`, `jcp` ou `dividendo`;
* **papel da linha** (`income_role`): `credito` (a renda que entrou), as linhas
  que a acompanham no aluguel de ações (`irrf_aluguel`, `corretagem_aluguel`,
  `taxa_aluguel`) e `estorno` (o "Estorno * Prov *" de qualquer uma delas);
* **liquidação de pregão**: a data do pregão e o número da nota de
  "Operações Bolsa D+2 Pr 27/01/2026 Nc. 543216". Nota mascarada (`Nc. *`) fica
  sem número.

O IRRF de pregão ("Irrf S/ Resultado Bolsa ...") **não** é `irrf_aluguel`, e a
corretagem de mini-contrato ("Operações Bm&F") não é liquidação de pregão de
ações: ficam sem campos.

Palavra inteira e sem acento, como em `familias.py`: o texto é normalizado e
dividido em letras e números antes de casar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

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

from .regras import normalizar

# Letras e números são palavras separadas, como em `familias.py`.
_PALAVRAS = re.compile(r"[A-Z]+|[0-9]+")

# Cada regra é uma sequência de palavras que precisa aparecer, inteira e em
# ordem. A primeira que casar vale; a ordem importa (estorno antes de tudo).
_REGRAS: tuple[tuple[tuple[str, ...], str | None, str], ...] = (
    (("ESTORNO", "PROV"), None, INCOME_ROLE_REVERSAL),
    (("IRRF", "S", "RENDIMENTOS", "EMPRESTIMOS", "DE", "ACOES"), INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_IRRF),
    (("CORRETAGEM", "EXECUTOR", "BTC"), INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_BROKERAGE),
    (("TAXA", "DE", "REMUNERACAO", "EMPRESTIMO"), INCOME_KIND_RENTAL, INCOME_ROLE_CREDIT),
    (("TAXA", "DE", "REMUNERACAO", "BTC"), INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_FEE),
    (("TX", "DE", "LIQUIDACAO", "DE", "EMPREST"), INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_FEE),
    (("JUROS", "S", "CAPITAL"), INCOME_KIND_JCP, INCOME_ROLE_CREDIT),
    (("DIVIDENDOS",), INCOME_KIND_DIVIDEND, INCOME_ROLE_CREDIT),
    (("CRED", "REEMBOLSO", "JCP", "BTC"), INCOME_KIND_DIVIDEND, INCOME_ROLE_CREDIT),
)

# O estorno guarda o tipo da linha que ele desfaz, quando o texto a nomeia.
_REGRAS_DO_ESTORNADO = _REGRAS[1:]

_LIQUIDACAO = re.compile(r"\bOPERACOES\s+BOLSA\b.*?\bPR\s+(\d{2})/(\d{2})/(\d{4})(?:\s+NC\.?\s+(\d+))?")

_TICKER_ESCRITO = re.compile(r"^[A-Z]{4}[0-9]{1,2}$")
_CODIGO_ISIN = re.compile(r"^br([a-z]{4})([a-z]{3,5})([0-9]{1,3})$", re.IGNORECASE)
# Classe da ação no código impresso -> final do ticker.
_FINAL_DA_CLASSE = {"acnor": "3", "acnpr": "4", "ctf": "11"}


@dataclass(frozen=True)
class Detalhe:
    """O que se leu da descrição; todo campo é opcional."""

    instrument_code: str | None = None
    income_kind: str | None = None
    income_role: str | None = None
    settlement_pregao_date: date | None = None
    settlement_note: str | None = None

    @property
    def vazio(self) -> bool:
        return not any(
            (self.instrument_code, self.income_kind, self.income_role,
             self.settlement_pregao_date, self.settlement_note)
        )


def _palavras(texto: str) -> list[str]:
    return _PALAVRAS.findall(texto)


def _contem(palavras: list[str], alvo: tuple[str, ...]) -> bool:
    tamanho = len(alvo)
    return any(tuple(palavras[i:i + tamanho]) == alvo for i in range(len(palavras) - tamanho + 1))


def ativo_da_descricao(descricao: str) -> str | None:
    """O ticker escrito ou derivado do código que a corretora imprime."""
    tokens = (descricao or "").split()
    for token in tokens:
        if _TICKER_ESCRITO.match(token):
            return token
    for token in tokens:
        # BR + 4 letras do emissor + a classe + dígitos: "Brsmtoacnor3" (ACNOR,
        # dígito 3) e "Brhodlctf005" (CTF, 005). Classe sem regra (unit, BDR) não rende ativo.
        achado = _CODIGO_ISIN.match(token)
        final = _FINAL_DA_CLASSE.get(achado.group(2).lower()) if achado else None
        if final:
            return f"{achado.group(1).upper()}{final}"
    return None


def _liquidacao(normalizada: str) -> tuple[date, str | None] | None:
    achado = _LIQUIDACAO.search(normalizada)
    if not achado:
        return None
    dia, mes, ano, nota = achado.groups()
    try:
        return date(int(ano), int(mes), int(dia)), nota
    except ValueError:
        return None


def interpretar(descricao: str | None) -> Detalhe | None:
    """O `Detalhe` da descrição, ou `None` quando nenhuma regra casa."""
    normalizada = normalizar(descricao or "")
    if not normalizada:
        return None
    palavras = _palavras(normalizada)

    liquidacao = _liquidacao(normalizada)
    if liquidacao is not None:
        data, nota = liquidacao
        return Detalhe(settlement_pregao_date=data, settlement_note=nota)

    for alvo, tipo, papel in _REGRAS:
        if not _contem(palavras, alvo):
            continue
        if papel == INCOME_ROLE_REVERSAL:
            for alvo_estornado, tipo_estornado, _ in _REGRAS_DO_ESTORNADO:
                if _contem(palavras, alvo_estornado):
                    tipo = tipo_estornado
                    break
        return Detalhe(instrument_code=ativo_da_descricao(descricao or ""), income_kind=tipo, income_role=papel)
    return None
