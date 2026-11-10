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


@dataclass(frozen=True)
class _Voto:
    vencimento: date
    lancamento_id: int
    categoria_id: int
    # Preenchida quando o lançamento entrou pelo texto da linha conciliada com ele.
    data_da_linha: date | None = None


class Historico:
    """Os lançamentos já classificados, por chave: cada um vota uma vez, sem "Outros".

    Um lançamento entra pela própria descrição ou pelo texto da linha de extrato
    conciliada com ele. Com `termo`, lê só o que contém aquela palavra, até
    `_LIMITE_DE_HISTORICO` de cada (é o que serve a uma linha só). Sem ele, lê
    tudo de uma vez e responde por qualquer linha: é o que um plano inteiro usa,
    em vez de duas consultas por linha."""

    def __init__(self, *, apenas_gerenciais: bool, termo: str | None = None) -> None:
        tipos = _tipos(apenas_gerenciais)
        lancamentos = CashFlowEntry.objects.filter(category__kind__in=tipos).exclude(
            category__category_name__iexact=CATEGORIA_PADRAO
        )
        linhas = BankStatementLine.objects.filter(
            status=LINE_STATUS_RECONCILED, matched_entry__category__kind__in=tipos
        ).exclude(matched_entry__category__category_name__iexact=CATEGORIA_PADRAO)
        if termo is not None:
            lancamentos = lancamentos.filter(description__icontains=termo).order_by("-due_date", "-id")
            lancamentos = lancamentos[:_LIMITE_DE_HISTORICO]
            linhas = linhas.filter(description__icontains=termo).order_by("-statement_date", "-id")
            linhas = linhas[:_LIMITE_DE_HISTORICO]
        self._por_chave: dict[str, dict[int, _Voto]] = {}
        for lancamento_id, descricao, vencimento, categoria_id in lancamentos.values_list(
            "id", "description", "due_date", "category_id"
        ):
            self._por_chave.setdefault(chave_da_linha(descricao), {})[lancamento_id] = _Voto(
                vencimento, lancamento_id, categoria_id
            )
        for descricao, data, lancamento_id, vencimento, categoria_id in linhas.values_list(
            "description", "statement_date", "matched_entry_id", "matched_entry__due_date",
            "matched_entry__category_id",
        ):
            self._por_chave.setdefault(chave_da_linha(descricao), {}).setdefault(
                lancamento_id, _Voto(vencimento, lancamento_id, categoria_id, data)
            )
        self._categorias: dict[int, CashFlowCategory] | None = None

    def _categoria(self, categoria_id: int) -> CashFlowCategory:
        if self._categorias is None:
            ids = {voto.categoria_id for votos in self._por_chave.values() for voto in votos.values()}
            self._categorias = CashFlowCategory.objects.in_bulk(ids)
        return self._categorias[categoria_id]

    def votacao(self, descricao: str, *, antes_de: date | None = None) -> _Votacao | None:
        """A votação da descrição. `antes_de` limita o histórico ao que existia
        antes daquela data (é o que `medir_sugestoes` usa para refazer o passado
        sem olhar o futuro). Descrição genérica não tem histórico."""
        if eh_generica(descricao):
            return None
        votos = self._por_chave.get(chave_da_linha(descricao), {}).values()
        if antes_de is not None:
            votos = [
                voto for voto in votos
                if voto.vencimento < antes_de and (voto.data_da_linha is None or voto.data_da_linha < antes_de)
            ]
        recentes = sorted(votos, key=lambda voto: (voto.vencimento, voto.lancamento_id), reverse=True)
        return _vencedora([self._categoria(voto.categoria_id) for voto in recentes])


class Contexto:
    """O que a classificação de várias linhas lê uma vez só.

    A tela de Conciliação e a prévia da fatura classificam dezenas de linhas de
    uma vez; sem isto cada linha refazia as mesmas consultas (histórico,
    categoria do banco, categoria da conta, categoria pelo nome), e a tela de
    100 linhas custava centenas de consultas a cada clique."""

    def __init__(self, *, apenas_gerenciais: bool = False) -> None:
        self.apenas_gerenciais = apenas_gerenciais
        self._historico: Historico | None = None
        self._do_banco: dict[tuple, _Votacao | None] = {}
        self._da_conta: dict[tuple, _Votacao | None] = {}
        self._pelo_nome: dict[str, CashFlowCategory] | None = None

    @property
    def historico(self) -> Historico:
        if self._historico is None:
            self._historico = Historico(apenas_gerenciais=self.apenas_gerenciais)
        return self._historico

    def do_banco(self, bank_category: str, antes_de: date | None) -> _Votacao | None:
        chave = (bank_category, antes_de)
        if chave not in self._do_banco:
            self._do_banco[chave] = _votacao_do_banco(
                bank_category, apenas_gerenciais=self.apenas_gerenciais, antes_de=antes_de
            )
        return self._do_banco[chave]

    def da_conta(self, conta, tipo: str, antes_de: date | None) -> _Votacao | None:
        chave = (conta.id, tipo, antes_de)
        if chave not in self._da_conta:
            self._da_conta[chave] = _votacao_da_conta(
                conta, tipo, apenas_gerenciais=self.apenas_gerenciais, antes_de=antes_de
            )
        return self._da_conta[chave]

    def categoria_pelo_nome(self, nome: str | None) -> CashFlowCategory | None:
        if not nome:
            return None
        if self._pelo_nome is None:
            self._pelo_nome = {}
            for categoria in _categorias_validas(self.apenas_gerenciais):
                self._pelo_nome.setdefault(categoria.category_name.upper(), categoria)
        return self._pelo_nome.get(nome.strip().upper())


def _votacao_do_historico(
    descricao: str, *, apenas_gerenciais: bool, antes_de: date | None = None
) -> _Votacao | None:
    """A votação do histórico para uma descrição só (ver `Historico`)."""
    if eh_generica(descricao):
        return None
    historico = Historico(apenas_gerenciais=apenas_gerenciais, termo=_termo_de_busca(descricao))
    return historico.votacao(descricao, antes_de=antes_de)


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
    contexto: Contexto | None = None,
) -> Sugestao:
    """A categoria sugerida, de onde ela veio e o quanto confiar. Nunca grava nada.

    `regra` é a regra explícita já resolvida pelo chamador (`regras.Regras.da_linha`),
    para esta função não depender do contexto da linha (instituição). `conta` e
    `tipo` (receita ou despesa) servem só à descrição genérica, que cai na
    categoria dominante da conta. `antes_de` é para a medição (ver
    `Historico.votacao`). `contexto` é de quem classifica várias linhas (ver
    `Contexto`): a resposta é a mesma, só as leituras são compartilhadas, e a
    natureza das categorias passa a ser a dele."""
    if regra is not None and regra.category_id:
        return Sugestao(regra.category, ORIGEM_REGRA)
    if contexto is not None:
        apenas_gerenciais = contexto.apenas_gerenciais
    intermediador = eh_intermediador(descricao)
    if contexto is not None:
        historico = contexto.historico.votacao(descricao, antes_de=antes_de)
    else:
        historico = _votacao_do_historico(descricao, apenas_gerenciais=apenas_gerenciais, antes_de=antes_de)
    if historico is not None:
        return Sugestao(historico.categoria, ORIGEM_HISTORICO, historico.votos, historico.iguais, intermediador)
    if conta is not None and tipo is not None and eh_generica(descricao):
        if contexto is not None:
            da_conta = contexto.da_conta(conta, tipo, antes_de)
        else:
            da_conta = _votacao_da_conta(conta, tipo, apenas_gerenciais=apenas_gerenciais, antes_de=antes_de)
        if da_conta is not None:
            return Sugestao(da_conta.categoria, ORIGEM_CONTA, da_conta.votos, da_conta.iguais)
    if contexto is not None:
        aprendida = contexto.do_banco(bank_category, antes_de)
    else:
        aprendida = _votacao_do_banco(bank_category, apenas_gerenciais=apenas_gerenciais, antes_de=antes_de)
    if aprendida is not None:
        return Sugestao(aprendida.categoria, ORIGEM_BANCO_APRENDIDA, aprendida.votos, aprendida.iguais, intermediador)

    def pelo_nome(nome: str | None) -> CashFlowCategory | None:
        if contexto is not None:
            return contexto.categoria_pelo_nome(nome)
        return _categoria_pelo_nome(nome, apenas_gerenciais)

    do_prefixo = pelo_nome(prefixo_de_categoria(descricao))
    if do_prefixo is not None:
        return Sugestao(do_prefixo, ORIGEM_PREFIXO)
    do_banco = pelo_nome(bank_category)
    if do_banco is not None:
        return Sugestao(do_banco, ORIGEM_BANCO)
    padrao = pelo_nome(CATEGORIA_PADRAO) if contexto is not None else _categoria_padrao(apenas_gerenciais)
    return Sugestao(padrao, ORIGEM_PADRAO)


def tipo_da_linha(linha: BankStatementLine) -> str:
    return ENTRY_TYPE_INCOME if linha.amount > 0 else ENTRY_TYPE_EXPENSE


def sugerir_para_linha(
    linha: BankStatementLine, *, regra=None, apenas_gerenciais: bool = False, antes_de: date | None = None,
    contexto: Contexto | None = None,
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
        contexto=contexto,
    )
