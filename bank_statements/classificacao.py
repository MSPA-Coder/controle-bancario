"""Categoria sugerida para uma linha de extrato, aprendida do histórico.

Serve ao extrato de conta e à fatura de cartão: a mesma pergunta ("que
categoria o usuário deu a isto da última vez?") com a mesma resposta.

Ordem de precedência, da mais para a menos confiável:

1. **regra explícita** (`regras.regra_da_linha`): o usuário disse o que fazer
   com esta família de lançamentos, e vale mais que qualquer palpite;
2. **a mesma descrição já classificada**: a categoria mais frequente entre os
   lançamentos gerenciais de mesma chave (ver `chave_da_linha`), **sem contar
   "Outros"**. Antes valia o lançamento mais recente, e uma loja que caiu uma
   vez em "Outros" arrastava todas as compras seguintes para lá. Descrição
   que só diz o meio de pagamento ("DEBIT", "Boleto") não conta;
3. **a categoria do banco** já escolhida antes (fatura de cartão e OFX com
   `NAME`): a escolha feita numa prévia vale para as linhas seguintes;
4. **o prefixo do PDF** ou a categoria do banco, quando têm o nome de uma
   categoria cadastrada;
5. **"Outros"**.

O prefixo do PDF fica depois do histórico de propósito: o PDF da Genial
rotula o aluguel de ações como "Rendimentos", mas durante nove meses o usuário
o classificou como "Aluguel de Ações / Dividendos / JCP". O histórico acerta;
o rótulo do banco, não.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from django.utils.translation import gettext_lazy

from core.domain.finance import CATEGORY_KIND_MANAGERIAL, CATEGORY_KIND_MOVEMENT
from transactions.models import CashFlowCategory, CashFlowEntry

from .models import LINE_STATUS_RECONCILED, BankStatementLine
from .reclassificacao import chave_da_descricao

CATEGORIA_PADRAO = "Outros"
_LIMITE_DE_HISTORICO = 500

ORIGEM_REGRA = "regra"
ORIGEM_HISTORICO = "historico"
ORIGEM_BANCO_APRENDIDA = "banco_aprendida"
ORIGEM_PREFIXO = "prefixo"
ORIGEM_BANCO = "banco"
ORIGEM_PADRAO = "padrao"

ROTULOS_DA_ORIGEM = {
    ORIGEM_REGRA: gettext_lazy("regra"),
    ORIGEM_HISTORICO: gettext_lazy("histórico"),
    ORIGEM_BANCO_APRENDIDA: gettext_lazy("categoria do banco (aprendida)"),
    ORIGEM_PREFIXO: gettext_lazy("prefixo do extrato"),
    ORIGEM_BANCO: gettext_lazy("categoria do banco"),
    ORIGEM_PADRAO: gettext_lazy("padrão"),
}

# Rótulos que o PDF coloca antes da descrição ("Rendimentos - Taxa de ...").
# Ficam fora da chave, porque ao criar o lançamento o sistema tira o prefixo
# quando ele coincide com a categoria escolhida, e o lançamento antigo e a linha
# nova precisam gerar a mesma chave.
_PREFIXOS_DE_EXTRATO = frozenset(
    {
        "CORRETAGEM",
        "IMPOSTOS E TRIBUTOS",
        "RENDIMENTOS",
        "OPERACOES EM BOLSA",
        "PIX",
        "TED",
        "DOC",
        "TRANSFERENCIA",
        "TRANSFERENCIAS",
        "TARIFAS",
        "TAXAS",
        "PAGAMENTOS",
        "COMPRAS",
        "SAQUES",
        "DEPOSITOS",
        "OUTROS",
    }
)
_SEPARADOR_DE_PREFIXO = " - "
_PALAVRA = re.compile(r"[^\W\d_]{3,}", re.UNICODE)

# Palavras que dizem o meio de pagamento, não o que foi pago. O OFX do C6 traz
# linhas só com "DEBIT", "CREDIT", "Boleto" ou "TRANSF ENVIADA PIX": aprendidas
# na conta do Jardim Iva, elas mandavam para "Jardim Iva" qualquer linha igual de
# qualquer conta. Descrição feita só delas não ensina categoria nenhuma.
_PALAVRAS_GENERICAS = frozenset(
    {
        "DEBIT", "CREDIT", "DEBITO", "CREDITO", "BOLETO", "PIX", "TED", "DOC", "TEF",
        "TRANSF", "TRANSFERENCIA", "ENVIADA", "ENVIADO", "RECEBIDA", "RECEBIDO",
        "RECORRENTE", "PAGAMENTO", "PAGTO", "PGTO", "COMPRA", "CARTAO", "CONTA",
        "DE", "DA", "DO", "PARA", "EM",
    }
)


@dataclass(frozen=True)
class Sugestao:
    categoria: CashFlowCategory | None
    origem: str

    @property
    def rotulo(self) -> str:
        return str(ROTULOS_DA_ORIGEM.get(self.origem, self.origem))


def _ascii_maiusculo(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").upper().strip()


def sem_prefixo_de_extrato(descricao: str) -> str:
    """A descrição sem o rótulo de categoria que o PDF coloca na frente."""
    prefixo, separador, resto = (descricao or "").partition(_SEPARADOR_DE_PREFIXO)
    if separador and _ascii_maiusculo(prefixo) in _PREFIXOS_DE_EXTRATO:
        return resto.strip()
    return (descricao or "").strip()


def chave_da_linha(descricao: str) -> str:
    """Chave de comparação entre linha de extrato e lançamento já classificado."""
    return chave_da_descricao(sem_prefixo_de_extrato(descricao))


def _termo_de_busca(descricao: str) -> str | None:
    """Primeira palavra com acento preservado, para o `icontains` do banco.

    Vem do texto original, não da chave: a chave tem os acentos removidos e
    não encontraria "Remuneração" por "REMUNERACAO"."""
    for palavra in _PALAVRA.findall(sem_prefixo_de_extrato(descricao)):
        return palavra
    return None


def _tipos(apenas_gerenciais: bool) -> tuple[str, ...]:
    """Natureza das categorias que podem ser sugeridas.

    Extrato de conta também sugere movimentação ("Operações em Bolsa": o caixa
    vira posição); a fatura de cartão só aceita receita e despesa. Transferência
    nunca é sugerida por categoria: tem outra ponta e passa por `extrato`."""
    if apenas_gerenciais:
        return (CATEGORY_KIND_MANAGERIAL,)
    return (CATEGORY_KIND_MANAGERIAL, CATEGORY_KIND_MOVEMENT)


def _categorias_validas(apenas_gerenciais: bool):
    return CashFlowCategory.objects.filter(kind__in=_tipos(apenas_gerenciais))


def _categoria_padrao(apenas_gerenciais: bool) -> CashFlowCategory | None:
    return _categorias_validas(apenas_gerenciais).filter(category_name__iexact=CATEGORIA_PADRAO).first()


def categoria_do_historico(descricao: str, *, apenas_gerenciais: bool = False) -> CashFlowCategory | None:
    """Categoria mais frequente dos lançamentos de mesma chave, sem "Outros".

    Em empate vence a que apareceu primeiro entre os mais recentes. Descrição
    genérica (ver `_PALAVRAS_GENERICAS`) não tem histórico."""
    chave = chave_da_linha(descricao)
    termo = _termo_de_busca(descricao)
    if not chave or not termo or set(chave.split()) <= _PALAVRAS_GENERICAS:
        return None
    anteriores = (
        CashFlowEntry.objects.filter(
            category__kind__in=_tipos(apenas_gerenciais), description__icontains=termo
        )
        .exclude(category__category_name__iexact=CATEGORIA_PADRAO)
        .select_related("category")
        .order_by("-due_date", "-id")[:_LIMITE_DE_HISTORICO]
    )
    contagem: Counter[int] = Counter()
    por_id: dict[int, CashFlowCategory] = {}
    ordem: dict[int, int] = {}
    for posicao, anterior in enumerate(anteriores):
        if chave_da_linha(anterior.description) != chave:
            continue
        categoria = anterior.category
        contagem[categoria.id] += 1
        por_id.setdefault(categoria.id, categoria)
        ordem.setdefault(categoria.id, posicao)
    if not contagem:
        return None
    melhor = min(contagem, key=lambda categoria_id: (-contagem[categoria_id], ordem[categoria_id]))
    return por_id[melhor]


def categoria_do_banco_aprendida(
    bank_category: str, *, apenas_gerenciais: bool = False
) -> CashFlowCategory | None:
    """A categoria que o usuário mais deu às linhas de mesma categoria do banco."""
    if not bank_category:
        return None
    categorias = (
        BankStatementLine.objects.filter(
            bank_category=bank_category,
            status=LINE_STATUS_RECONCILED,
            matched_entry__category__kind__in=_tipos(apenas_gerenciais),
        )
        .exclude(matched_entry__category__category_name__iexact=CATEGORIA_PADRAO)
        .select_related("matched_entry__category")
        .order_by("-id")[:_LIMITE_DE_HISTORICO]
    )
    contagem: Counter[int] = Counter()
    por_id: dict[int, CashFlowCategory] = {}
    ordem: dict[int, int] = {}
    for posicao, linha in enumerate(categorias):
        categoria = linha.matched_entry.category
        contagem[categoria.id] += 1
        por_id.setdefault(categoria.id, categoria)
        ordem.setdefault(categoria.id, posicao)
    if not contagem:
        return None
    melhor = min(contagem, key=lambda categoria_id: (-contagem[categoria_id], ordem[categoria_id]))
    return por_id[melhor]


def _categoria_pelo_nome(nome: str | None, apenas_gerenciais: bool) -> CashFlowCategory | None:
    if not nome:
        return None
    return _categorias_validas(apenas_gerenciais).filter(category_name__iexact=nome.strip()).first()


def prefixo_de_categoria(descricao: str) -> str | None:
    """O rótulo de categoria que o PDF coloca na frente ("Corretagem - ...")."""
    prefixo, separador, _ = (descricao or "").partition(_SEPARADOR_DE_PREFIXO)
    return prefixo.strip() if separador else None


def sugerir_categoria(
    descricao: str, bank_category: str = "", *, regra=None, apenas_gerenciais: bool = False
) -> Sugestao:
    """A categoria sugerida e de onde ela veio. Nunca grava nada.

    `regra` é a regra explícita já resolvida pelo chamador (`regras.Regras.da_linha`),
    para esta função não depender do contexto da linha (conta, instituição)."""
    if regra is not None and regra.category_id:
        return Sugestao(regra.category, ORIGEM_REGRA)
    historico = categoria_do_historico(descricao, apenas_gerenciais=apenas_gerenciais)
    if historico is not None:
        return Sugestao(historico, ORIGEM_HISTORICO)
    aprendida = categoria_do_banco_aprendida(bank_category, apenas_gerenciais=apenas_gerenciais)
    if aprendida is not None:
        return Sugestao(aprendida, ORIGEM_BANCO_APRENDIDA)
    do_prefixo = _categoria_pelo_nome(prefixo_de_categoria(descricao), apenas_gerenciais)
    if do_prefixo is not None:
        return Sugestao(do_prefixo, ORIGEM_PREFIXO)
    do_banco = _categoria_pelo_nome(bank_category, apenas_gerenciais)
    if do_banco is not None:
        return Sugestao(do_banco, ORIGEM_BANCO)
    return Sugestao(_categoria_padrao(apenas_gerenciais), ORIGEM_PADRAO)
