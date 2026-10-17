"""Categoria sugerida para uma linha de extrato, aprendida do histórico.

Serve ao extrato de conta e à fatura de cartão: a mesma pergunta ("que
categoria o usuário deu a isto da última vez?") com a mesma resposta.

Ordem de precedência, da mais para a menos confiável:

1. **regra explícita** (`regras.regra_da_linha`): o usuário disse o que fazer
   com esta família de lançamentos, e vale mais que qualquer palpite;
2. **a mesma descrição já classificada**: a categoria mais frequente entre os
   lançamentos gerenciais de mesma chave (ver `chave_da_linha`), **sem contar
   "Outros"**. Antes valia o lançamento mais recente, e uma loja que caiu uma
   vez em "Outros" arrastava todas as compras seguintes para lá. A chave é
   comparada com a descrição do lançamento **e** com o texto da linha de
   extrato conciliada com ele: o usuário reescreve descrições ("Salário",
   "Aluguel Butantã"), e o texto que o banco manda continua sendo o mesmo.
   Descrição que só diz o meio de pagamento ("DEBIT", "Boleto") não conta;
3. **a categoria dominante da conta**, só para essa descrição genérica: na
   conta administrada do Jardim Iva, "Boleto" é quase sempre Jardim Iva;
4. **a categoria do banco** já escolhida antes (fatura de cartão e OFX com
   `NAME`): a escolha feita numa prévia vale para as linhas seguintes;
5. **o prefixo do PDF** ou a categoria do banco, quando têm o nome de uma
   categoria cadastrada;
6. **"Outros"**.

O prefixo do PDF fica depois do histórico de propósito: o PDF da Genial
rotula o aluguel de ações como "Rendimentos", mas durante nove meses o usuário
o classificou como "Aluguel de Ações / Dividendos / JCP". O histórico acerta;
o rótulo do banco, não.

Cada sugestão diz também o quanto se pode confiar nela (`Sugestao.confianca`).
O critério vem do teste retroativo de 17/10/2026 sobre os dados reais
(`medir_sugestoes`): regra, ou histórico com dois ou mais casos todos na mesma
categoria, acertou 99,4%; histórico dividido e categoria do banco ambígua
ficaram entre 55% e 89%. A prévia mostra primeiro o que é incerto.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date

from django.db.models import Count
from django.utils.translation import gettext_lazy

from core.domain.finance import (
    CATEGORY_KIND_MANAGERIAL,
    CATEGORY_KIND_MOVEMENT,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
)
from transactions.models import CashFlowCategory, CashFlowEntry

from .models import LINE_STATUS_RECONCILED, BankStatementLine
from .reclassificacao import chave_da_descricao

CATEGORIA_PADRAO = "Outros"
_LIMITE_DE_HISTORICO = 500

ORIGEM_REGRA = "regra"
ORIGEM_HISTORICO = "historico"
ORIGEM_CONTA = "conta"
ORIGEM_BANCO_APRENDIDA = "banco_aprendida"
ORIGEM_PREFIXO = "prefixo"
ORIGEM_BANCO = "banco"
ORIGEM_PADRAO = "padrao"

ROTULOS_DA_ORIGEM = {
    ORIGEM_REGRA: gettext_lazy("regra"),
    ORIGEM_HISTORICO: gettext_lazy("histórico"),
    ORIGEM_CONTA: gettext_lazy("categoria mais usada na conta"),
    ORIGEM_BANCO_APRENDIDA: gettext_lazy("categoria do banco (aprendida)"),
    ORIGEM_PREFIXO: gettext_lazy("prefixo do extrato"),
    ORIGEM_BANCO: gettext_lazy("categoria do banco"),
    ORIGEM_PADRAO: gettext_lazy("padrão"),
}

CONFIANCA_ALTA = "alta"
CONFIANCA_MEDIA = "media"
CONFIANCA_BAIXA = "baixa"
CONFIANCA_NENHUMA = "nenhuma"

ROTULOS_DA_CONFIANCA = {
    CONFIANCA_ALTA: gettext_lazy("confiança alta"),
    CONFIANCA_MEDIA: gettext_lazy("confiança média"),
    CONFIANCA_BAIXA: gettext_lazy("confiança baixa"),
    CONFIANCA_NENHUMA: gettext_lazy("sem sugestão"),
}

# A categoria dominante da conta só vale com base e maioria claras: no mínimo
# cinco lançamentos do mesmo tipo, 80% deles na mesma categoria.
_MINIMO_DA_CONTA = 5
_MAIORIA_DA_CONTA = (4, 5)

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

# Intermediadores: a mesma "loja" vende de tudo (Mercado Livre, Shopee, Amazon)
# ou repassa para qualquer vendedor (MP*, PayGo). O histórico deles nunca é
# confiança alta: dois dos três erros da confiança alta na medição de 17/10/2026
# eram do Mercado Livre. Os primeiros só valem como primeira palavra: "MP" ou
# "IFD" no meio da descrição é outra coisa.
_INTERMEDIADORES = frozenset(
    {
        "MERCADOLIVRE", "MERCADOPAGO", "SHOPEE", "AMAZON", "AMAZONMKTPLC", "PAYGO",
        "PAGSEGURO", "SUMUP", "PAYPAL", "EBANX",
    }
)
_INTERMEDIADORES_NO_INICIO = frozenset({"MP", "IFD", "STONE"})


@dataclass(frozen=True)
class Sugestao:
    categoria: CashFlowCategory | None
    origem: str
    # Quantos casos anteriores votaram e quantos deram a categoria sugerida.
    votos: int = 0
    iguais: int = 0
    intermediador: bool = False

    @property
    def rotulo(self) -> str:
        return str(ROTULOS_DA_ORIGEM.get(self.origem, self.origem))

    @property
    def confianca(self) -> str:
        if self.categoria is None or self.origem == ORIGEM_PADRAO:
            return CONFIANCA_NENHUMA
        if self.origem == ORIGEM_REGRA:
            return CONFIANCA_ALTA
        unanime = self.votos > 0 and self.iguais == self.votos
        quase = self.votos > 0 and self.iguais * 10 >= self.votos * 9
        if self.origem in (ORIGEM_HISTORICO, ORIGEM_CONTA):
            if unanime and self.votos >= 2 and not self.intermediador:
                return CONFIANCA_ALTA
            return CONFIANCA_MEDIA if quase else CONFIANCA_BAIXA
        if self.origem == ORIGEM_BANCO_APRENDIDA:
            return CONFIANCA_MEDIA if quase else CONFIANCA_BAIXA
        return CONFIANCA_BAIXA

    @property
    def rotulo_da_confianca(self) -> str:
        return str(ROTULOS_DA_CONFIANCA[self.confianca])

    @property
    def confiavel(self) -> bool:
        return self.confianca == CONFIANCA_ALTA


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


def eh_generica(descricao: str) -> bool:
    """Se a descrição só diz o meio de pagamento (ver `_PALAVRAS_GENERICAS`)."""
    chave = chave_da_linha(descricao)
    return not chave or not _termo_de_busca(descricao) or set(chave.split()) <= _PALAVRAS_GENERICAS


def eh_intermediador(descricao: str) -> bool:
    """Se a descrição é de um intermediador (ver `_INTERMEDIADORES`)."""
    palavras = chave_da_linha(descricao).split()
    return bool(palavras) and (
        palavras[0] in _INTERMEDIADORES_NO_INICIO or any(p in _INTERMEDIADORES for p in palavras)
    )


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


@dataclass(frozen=True)
class _Votacao:
    categoria: CashFlowCategory
    votos: int
    iguais: int


def _vencedora(votos: list[CashFlowCategory]) -> _Votacao | None:
    """A mais frequente; em empate, a que aparece primeiro (a mais recente)."""
    if not votos:
        return None
    contagem: Counter[int] = Counter(categoria.id for categoria in votos)
    ordem: dict[int, int] = {}
    por_id: dict[int, CashFlowCategory] = {}
    for posicao, categoria in enumerate(votos):
        ordem.setdefault(categoria.id, posicao)
        por_id.setdefault(categoria.id, categoria)
    melhor = min(contagem, key=lambda categoria_id: (-contagem[categoria_id], ordem[categoria_id]))
    return _Votacao(por_id[melhor], len(votos), contagem[melhor])


def _votacao_do_historico(
    descricao: str, *, apenas_gerenciais: bool, antes_de: date | None = None
) -> _Votacao | None:
    """Os lançamentos de mesma chave, cada um com um voto, sem "Outros".

    Um lançamento entra pela própria descrição ou pelo texto da linha de
    extrato conciliada com ele, e vota uma vez só. `antes_de` limita o
    histórico ao que existia antes daquela data (é o que `medir_sugestoes` usa
    para refazer o passado sem olhar o futuro)."""
    if eh_generica(descricao):
        return None
    chave = chave_da_linha(descricao)
    termo = _termo_de_busca(descricao)
    tipos = _tipos(apenas_gerenciais)
    lancamentos = (
        CashFlowEntry.objects.filter(category__kind__in=tipos, description__icontains=termo)
        .exclude(category__category_name__iexact=CATEGORIA_PADRAO)
        .select_related("category")
    )
    linhas = (
        BankStatementLine.objects.filter(
            status=LINE_STATUS_RECONCILED,
            matched_entry__category__kind__in=tipos,
            description__icontains=termo,
        )
        .exclude(matched_entry__category__category_name__iexact=CATEGORIA_PADRAO)
        .select_related("matched_entry__category")
    )
    if antes_de is not None:
        lancamentos = lancamentos.filter(due_date__lt=antes_de)
        linhas = linhas.filter(statement_date__lt=antes_de, matched_entry__due_date__lt=antes_de)
    achados: dict[int, CashFlowEntry] = {}
    for anterior in lancamentos.order_by("-due_date", "-id")[:_LIMITE_DE_HISTORICO]:
        if chave_da_linha(anterior.description) == chave:
            achados[anterior.id] = anterior
    for linha in linhas.order_by("-statement_date", "-id")[:_LIMITE_DE_HISTORICO]:
        if chave_da_linha(linha.description) == chave:
            achados.setdefault(linha.matched_entry_id, linha.matched_entry)
    recentes = sorted(achados.values(), key=lambda entrada: (entrada.due_date, entrada.id), reverse=True)
    return _vencedora([entrada.category for entrada in recentes])


def categoria_do_historico(
    descricao: str, *, apenas_gerenciais: bool = False, antes_de: date | None = None
) -> CashFlowCategory | None:
    """Categoria mais frequente dos lançamentos de mesma chave, sem "Outros".

    Em empate vence a que apareceu primeiro entre os mais recentes. Descrição
    genérica (ver `_PALAVRAS_GENERICAS`) não tem histórico."""
    votacao = _votacao_do_historico(descricao, apenas_gerenciais=apenas_gerenciais, antes_de=antes_de)
    return votacao.categoria if votacao else None


def _votacao_da_conta(conta, tipo: str, *, apenas_gerenciais: bool, antes_de: date | None = None) -> _Votacao | None:
    """A categoria que domina a conta naquele tipo, se a maioria for clara."""
    lancamentos = (
        CashFlowEntry.objects.filter(account=conta, entry_type=tipo, category__kind__in=_tipos(apenas_gerenciais))
        .exclude(category__category_name__iexact=CATEGORIA_PADRAO)
    )
    if antes_de is not None:
        lancamentos = lancamentos.filter(due_date__lt=antes_de)
    contagem = list(lancamentos.values("category_id").annotate(n=Count("id")).order_by("-n", "category_id")[:2])
    if not contagem:
        return None
    total = lancamentos.count()
    melhor = contagem[0]
    numerador, denominador = _MAIORIA_DA_CONTA
    if total < _MINIMO_DA_CONTA or melhor["n"] * denominador < total * numerador:
        return None
    return _Votacao(CashFlowCategory.objects.get(id=melhor["category_id"]), total, melhor["n"])


def _votacao_do_banco(
    bank_category: str, *, apenas_gerenciais: bool, antes_de: date | None = None
) -> _Votacao | None:
    if not bank_category:
        return None
    linhas = (
        BankStatementLine.objects.filter(
            bank_category=bank_category,
            status=LINE_STATUS_RECONCILED,
            matched_entry__category__kind__in=_tipos(apenas_gerenciais),
        )
        .exclude(matched_entry__category__category_name__iexact=CATEGORIA_PADRAO)
        .select_related("matched_entry__category")
    )
    if antes_de is not None:
        linhas = linhas.filter(statement_date__lt=antes_de)
    return _vencedora([linha.matched_entry.category for linha in linhas.order_by("-id")[:_LIMITE_DE_HISTORICO]])


def categoria_do_banco_aprendida(
    bank_category: str, *, apenas_gerenciais: bool = False
) -> CashFlowCategory | None:
    """A categoria que o usuário mais deu às linhas de mesma categoria do banco."""
    votacao = _votacao_do_banco(bank_category, apenas_gerenciais=apenas_gerenciais)
    return votacao.categoria if votacao else None


def _categoria_pelo_nome(nome: str | None, apenas_gerenciais: bool) -> CashFlowCategory | None:
    if not nome:
        return None
    return _categorias_validas(apenas_gerenciais).filter(category_name__iexact=nome.strip()).first()


def prefixo_de_categoria(descricao: str) -> str | None:
    """O rótulo de categoria que o PDF coloca na frente ("Corretagem - ...")."""
    prefixo, separador, _ = (descricao or "").partition(_SEPARADOR_DE_PREFIXO)
    return prefixo.strip() if separador else None


def sugerir_categoria(
    descricao: str,
    bank_category: str = "",
    *,
    regra=None,
    apenas_gerenciais: bool = False,
    conta=None,
    tipo: str | None = None,
    antes_de: date | None = None,
) -> Sugestao:
    """A categoria sugerida, de onde ela veio e o quanto confiar. Nunca grava nada.

    `regra` é a regra explícita já resolvida pelo chamador (`regras.Regras.da_linha`),
    para esta função não depender do contexto da linha (instituição). `conta` e
    `tipo` (receita ou despesa) servem só à descrição genérica, que cai na
    categoria dominante da conta. `antes_de` é para a medição (ver
    `_votacao_do_historico`)."""
    if regra is not None and regra.category_id:
        return Sugestao(regra.category, ORIGEM_REGRA)
    intermediador = eh_intermediador(descricao)
    historico = _votacao_do_historico(descricao, apenas_gerenciais=apenas_gerenciais, antes_de=antes_de)
    if historico is not None:
        return Sugestao(historico.categoria, ORIGEM_HISTORICO, historico.votos, historico.iguais, intermediador)
    if conta is not None and tipo is not None and eh_generica(descricao):
        da_conta = _votacao_da_conta(conta, tipo, apenas_gerenciais=apenas_gerenciais, antes_de=antes_de)
        if da_conta is not None:
            return Sugestao(da_conta.categoria, ORIGEM_CONTA, da_conta.votos, da_conta.iguais)
    aprendida = _votacao_do_banco(bank_category, apenas_gerenciais=apenas_gerenciais, antes_de=antes_de)
    if aprendida is not None:
        return Sugestao(aprendida.categoria, ORIGEM_BANCO_APRENDIDA, aprendida.votos, aprendida.iguais, intermediador)
    do_prefixo = _categoria_pelo_nome(prefixo_de_categoria(descricao), apenas_gerenciais)
    if do_prefixo is not None:
        return Sugestao(do_prefixo, ORIGEM_PREFIXO)
    do_banco = _categoria_pelo_nome(bank_category, apenas_gerenciais)
    if do_banco is not None:
        return Sugestao(do_banco, ORIGEM_BANCO)
    return Sugestao(_categoria_padrao(apenas_gerenciais), ORIGEM_PADRAO)


def tipo_da_linha(linha: BankStatementLine) -> str:
    return ENTRY_TYPE_INCOME if linha.amount > 0 else ENTRY_TYPE_EXPENSE


def sugerir_para_linha(
    linha: BankStatementLine, *, regra=None, apenas_gerenciais: bool = False, antes_de: date | None = None
) -> Sugestao:
    """`sugerir_categoria` com o que a própria linha diz: texto, categoria do banco,
    conta e sinal."""
    return sugerir_categoria(
        linha.description,
        linha.bank_category,
        regra=regra,
        apenas_gerenciais=apenas_gerenciais,
        conta=linha.account,
        tipo=tipo_da_linha(linha),
        antes_de=antes_de,
    )
