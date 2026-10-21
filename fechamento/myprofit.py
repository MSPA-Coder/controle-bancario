"""A coleta do myProfit, do lado do CB: saldos de Tesouro, renda fixa EUA e caixa
em dólar, e a conferência das remessas de câmbio.

O pacote (`myprofit-coleta/1`) sai de `scripts/myprofit/coletar.js`, no
repositório do CRV, rodado na aba do myProfit já logada. Ele traz só campos de
uma lista fixa -- nada de nome, CPF, e-mail ou telefone, que as APIs do myProfit
também devolvem. O CB usa:

- `posicoes`: a posição por corretora em uma ou mais datas (fins de mês e a data
  da coleta). Cada conta com fonte myProfit diz o que é lá (`classe_myprofit`) e
  em que corretora (`corretora_myprofit`): o Tesouro da XP e o da Genial são duas
  contas;
- `cambio`: as notas de câmbio (remessas de R$ para US$).

Para cada conta e data, o saldo do myProfit é comparado com o do CB e a diferença
segue o caminho de Saldo aplicações (`bank_statements.saldo`), com o destino da
classe: Tesouro e renda fixa EUA são **marcação a mercado**; no caixa em dólar, o
que veio de proventos no período é **rendimento** e o resto foi para ativos ou
voltou deles (**investimentos**, uma movimentação). Saldo que já bate só fica
registrado como conferido.

Reenviar o mesmo pacote, ou um que cobre datas já aplicadas, é seguro: o saldo do
CB já inclui o que foi lançado, então a diferença dá zero. O que o pacote não
resolve vira pendência no roteiro: posição sem conta no CB, remessa que não está
no CB, conta cujo mês está fechado ou cuja conta de movimento ainda não tem
extrato. No caixa em dólar, uma remessa do período que ainda não está no CB faz a
data ser pulada: sem ela, a remessa viraria "investimentos".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.translation import gettext

from bank_statements import saldo
from banking.models import FinancialAccount
from banking.services import accessible_account_ids
from core import regional
from core.domain.finance import CURRENCY_BRL, CURRENCY_USD, ENTRY_TYPE_INCOME, STATUS_REALIZED
from core.templatetags.money_filters import money
from transactions.models import CashFlowEntry
from transactions.services import is_month_closed

from .fontes import FONTE_MYPROFIT, fontes_das_contas
from .models import (
    CLASSE_CAIXA_USD,
    CLASSE_RENDA_FIXA_EUA,
    CLASSE_TESOURO,
    FREQUENCIA_MENSAL,
    ORIGEM_MYPROFIT,
    ColetaMyProfit,
    SaldoConferido,
)
from .roteiro import ultimo_dia

FORMATO = "myprofit-coleta/1"
LIMITE_DE_BYTES = 2 * 1024 * 1024
_CENTAVO = Decimal("0.01")
#: Uma remessa confere com a entrada na conta em dólar até esta distância e diferença.
JANELA_DA_REMESSA = timedelta(days=4)
TOLERANCIA_DA_REMESSA = Decimal("1.00")

#: Classe da conta -> (grupo do ativo no myProfit, moeda da conta, campo do valor).
CLASSES = {
    CLASSE_TESOURO: ("TREASURY", CURRENCY_BRL, "valor_brl"),
    CLASSE_RENDA_FIXA_EUA: ("FIXED_INCOME_USA", CURRENCY_USD, "valor_usd"),
    CLASSE_CAIXA_USD: ("CASH_USD", CURRENCY_USD, "quantidade"),
}
NOMES_DAS_CLASSES = {
    "TREASURY": "Tesouro Direto",
    "FIXED_INCOME_USA": "Renda fixa EUA",
    "CASH_USD": "Conta corrente em dólar",
}


class PacoteInvalidoError(ValueError):
    pass


@dataclass(frozen=True)
class Posicao:
    data: date
    corretora: str
    classe: str
    ticker: str
    quantidade: Decimal
    valor_brl: Decimal
    valor_usd: Decimal


@dataclass(frozen=True)
class Remessa:
    data: date
    numero: str
    corretora: str
    valor_brl: Decimal
    valor_usd: Decimal


@dataclass(frozen=True)
class Provento:
    data: date
    corretora: str
    ticker: str
    tipo: str
    valor_usd: Decimal


@dataclass
class Pacote:
    sha256: str
    de: date
    ate: date
    posicoes: list[Posicao]
    remessas: list[Remessa]
    proventos: list[Provento]

    @property
    def datas(self) -> list[date]:
        return sorted({p.data for p in self.posicoes})


@dataclass
class Linha:
    conta: FinancialAccount
    data: date
    valor: Decimal
    saldo_no_cb: Decimal
    acao: str  # "lancar", "conferir", "pular"
    destino: str = ""
    motivo: str = ""
    rendimento: Decimal = Decimal("0")

    @property
    def diferenca(self) -> Decimal:
        return (self.valor - self.saldo_no_cb).quantize(_CENTAVO)

    @property
    def titulo(self) -> str:
        return f"{self.conta.institution.institution_name} / {self.conta.account_name}"


@dataclass
class Plano:
    pacote: Pacote
    linhas: list[Linha] = field(default_factory=list)
    pendencias: list[str] = field(default_factory=list)
    remessas_conferidas: int = 0
    ja_aplicada: ColetaMyProfit | None = None

    @property
    def a_lancar(self) -> list[Linha]:
        return [linha for linha in self.linhas if linha.acao == "lancar"]

    @property
    def a_conferir(self) -> list[Linha]:
        return [linha for linha in self.linhas if linha.acao == "conferir"]

    @property
    def puladas(self) -> list[Linha]:
        return [linha for linha in self.linhas if linha.acao == "pular"]


# --- leitura ---------------------------------------------------------------------

def _data(valor, campo: str) -> date:
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError) as exc:
        raise PacoteInvalidoError(gettext("Data inválida em %(campo)s.") % {"campo": campo}) from exc


def _decimal(valor, campo: str) -> Decimal:
    if valor is None or valor == "":
        return Decimal("0")
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as exc:
        raise PacoteInvalidoError(gettext("Número inválido em %(campo)s.") % {"campo": campo}) from exc
    if not numero.is_finite():
        raise PacoteInvalidoError(gettext("Número inválido em %(campo)s.") % {"campo": campo})
    return numero


def _texto(valor, limite: int = 80) -> str:
    return " ".join(str(valor or "").split())[:limite]


def _linhas_da_tabela(posicoes) -> list[dict]:
    """As posições de uma data como dicionários: o pacote as manda como tabela
    (`{"colunas": [...], "linhas": [[...], ...]}`) ou como lista de objetos."""
    if isinstance(posicoes, dict):
        colunas = posicoes.get("colunas")
        linhas = posicoes.get("linhas")
        if not isinstance(colunas, list) or not isinstance(linhas, list):
            raise PacoteInvalidoError(gettext("As posições do pacote estão num formato inválido."))
        return [dict(zip(colunas, linha, strict=False)) for linha in linhas if isinstance(linha, list)]
    if isinstance(posicoes, list):
        return [linha for linha in posicoes if isinstance(linha, dict)]
    raise PacoteInvalidoError(gettext("As posições do pacote estão num formato inválido."))


def ler(conteudo: bytes) -> Pacote:
    if not conteudo:
        raise PacoteInvalidoError(gettext("Envie o pacote .json da coleta."))
    if len(conteudo) > LIMITE_DE_BYTES:
        raise PacoteInvalidoError(gettext("O pacote passa de 2 MB."))
    try:
        dados = json.loads(conteudo.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PacoteInvalidoError(gettext("O arquivo não é um pacote JSON da coleta do myProfit.")) from exc
    if not isinstance(dados, dict) or dados.get("formato") != FORMATO:
        raise PacoteInvalidoError(gettext("O arquivo não é um pacote %(formato)s.") % {"formato": FORMATO})
    de, ate = _data(dados.get("de"), "de"), _data(dados.get("ate"), "ate")
    if ate < de:
        raise PacoteInvalidoError(gettext("O período do pacote é inválido."))
    posicoes = []
    por_data = dados.get("posicoes") or {}
    if not isinstance(por_data, dict):
        raise PacoteInvalidoError(gettext("As posições do pacote estão num formato inválido."))
    for chave, linhas in por_data.items():
        dia = _data(chave, "posicoes")
        if dia > ate:
            raise PacoteInvalidoError(gettext("O pacote traz posição depois da data da coleta."))
        for linha in _linhas_da_tabela(linhas):
            if not isinstance(linha, dict):
                continue
            posicoes.append(Posicao(
                data=dia,
                corretora=_texto(linha.get("corretora"), 40),
                classe=_texto(linha.get("classe"), 40).upper(),
                ticker=_texto(linha.get("ticker")),
                quantidade=_decimal(linha.get("quantidade"), "quantidade"),
                valor_brl=_decimal(linha.get("valor_brl"), "valor_brl"),
                valor_usd=_decimal(linha.get("valor_usd"), "valor_usd"),
            ))
    remessas = [
        Remessa(
            data=_data(r.get("data"), "cambio"), numero=_texto(r.get("numero")), corretora=_texto(r.get("corretora"), 40),
            valor_brl=_decimal(r.get("valor_de"), "cambio"), valor_usd=_decimal(r.get("valor_para"), "cambio"),
        )
        for r in dados.get("cambio") or [] if isinstance(r, dict) and str(r.get("para", "USD")).upper() == "USD"
    ]
    proventos = [
        Provento(
            data=_data(p.get("data_pagamento"), "proventos"), corretora=_texto(p.get("corretora"), 40),
            ticker=_texto(p.get("ticker")), tipo=_texto(p.get("tipo"), 30), valor_usd=_decimal(p.get("valor_usd"), "proventos"),
        )
        for p in dados.get("proventos") or [] if isinstance(p, dict)
    ]
    return Pacote(hashlib.sha256(conteudo).hexdigest(), de, ate, posicoes, remessas, proventos)


# --- plano -------------------------------------------------------------------------

def _mesma(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _valor(pacote: Pacote, dia: date, classe_conta: str, corretora: str) -> Decimal | None:
    """O saldo da conta no myProfit naquele dia, ou `None` quando o pacote não o diz.

    Posição de ativo ausente numa data que veio no pacote é zero (o papel não
    existia). Já o caixa em dólar só é publicado pelo myProfit na data de hoje:
    nas datas passadas a linha não vem, e ausência ali é "não sei", não zero."""
    grupo, _, campo = CLASSES[classe_conta]
    linhas = [p for p in pacote.posicoes if p.data == dia and p.classe == grupo and _mesma(p.corretora, corretora)]
    if not linhas and (classe_conta == CLASSE_CAIXA_USD or not any(p.data == dia for p in pacote.posicoes)):
        return None
    return sum((getattr(p, campo) for p in linhas), Decimal("0")).quantize(_CENTAVO)


def _entradas_em_dolar(conta: FinancialAccount) -> list[CashFlowEntry]:
    return list(
        CashFlowEntry.objects.filter(account=conta, entry_type=ENTRY_TYPE_INCOME, status=STATUS_REALIZED)
        .exclude(description__startswith=saldo.PREFIXO_DA_DESCRICAO)
    )


def _remessa_no_cb(remessa: Remessa, entradas: list[CashFlowEntry], usadas: set[int]) -> CashFlowEntry | None:
    for entrada in entradas:
        if entrada.id in usadas or entrada.realized_date is None:
            continue
        valor = entrada.realized_amount or entrada.entry_amount
        if abs(entrada.realized_date - remessa.data) <= JANELA_DA_REMESSA and abs(valor - remessa.valor_usd) <= TOLERANCIA_DA_REMESSA:
            return entrada
    return None


def planejar(user, pacote: Pacote) -> Plano:
    plano = Plano(pacote=pacote, ja_aplicada=ColetaMyProfit.objects.filter(sha256=pacote.sha256).first())
    contas = list(
        FinancialAccount.objects.filter(id__in=accessible_account_ids(user, "view"))
        .select_related("owner", "institution", "movement_account__institution")
        .order_by("owner__name", "institution__institution_name", "account_name")
    )
    fontes = fontes_das_contas(contas)
    do_myprofit = [(conta, fontes[conta.id]) for conta in contas if fontes[conta.id].fonte == FONTE_MYPROFIT and fontes[conta.id].classe_myprofit in CLASSES]

    # Remessas: cada uma precisa ter entrado na conta em dólar da corretora.
    remessas_faltando: list[Remessa] = []
    for conta, fonte in do_myprofit:
        if fonte.classe_myprofit != CLASSE_CAIXA_USD:
            continue
        entradas, usadas = _entradas_em_dolar(conta), set()
        for remessa in sorted(pacote.remessas, key=lambda r: r.data):
            if not _mesma(remessa.corretora, fonte.corretora_myprofit) or remessa.data < conta.initial_balance_date:
                continue
            achada = _remessa_no_cb(remessa, entradas, usadas)
            if achada is None:
                remessas_faltando.append(remessa)
                plano.pendencias.append(gettext("Remessa de %(dia)s (%(usd)s) não está em %(conta)s") % {
                    "dia": regional.formatar_data(remessa.data), "usd": money(remessa.valor_usd, CURRENCY_USD),
                    "conta": f"{conta.institution.institution_name} / {conta.account_name}",
                })
            else:
                usadas.add(achada.id)
                plano.remessas_conferidas += 1

    # Posição que o myProfit tem e nenhuma conta do CB representa.
    if pacote.datas:
        ultima = pacote.datas[-1]
        cobertas = {(CLASSES[f.classe_myprofit][0], f.corretora_myprofit.casefold()) for _, f in do_myprofit}
        sem_conta: dict[tuple[str, str], Decimal] = {}
        for p in pacote.posicoes:
            if p.data == ultima and p.classe in NOMES_DAS_CLASSES and (p.classe, p.corretora.casefold()) not in cobertas:
                chave = (p.classe, p.corretora)
                sem_conta[chave] = sem_conta.get(chave, Decimal("0")) + (p.valor_brl if p.classe == "TREASURY" else p.valor_usd)
        for (classe, corretora), total in sorted(sem_conta.items()):
            if total:
                moeda = CURRENCY_BRL if classe == "TREASURY" else CURRENCY_USD
                plano.pendencias.append(gettext("%(classe)s na %(corretora)s (%(valor)s) sem conta no CB") % {
                    "classe": NOMES_DAS_CLASSES[classe], "corretora": corretora, "valor": money(total, moeda),
                })

    for conta, fonte in do_myprofit:
        _, moeda, _ = CLASSES[fonte.classe_myprofit]
        if conta.currency != moeda:
            plano.pendencias.append(gettext("%(conta)s está em %(moeda)s, mas o myProfit a mede em %(esperada)s") % {
                "conta": f"{conta.institution.institution_name} / {conta.account_name}", "moeda": conta.currency, "esperada": moeda,
            })
            continue
        conferidos = sorted(SaldoConferido.objects.filter(account=conta).values_list("data", flat=True))
        anterior = conta.initial_balance_date
        for dia in pacote.datas:
            if dia <= conta.initial_balance_date:
                continue
            if fonte.frequencia == FREQUENCIA_MENSAL and dia != ultimo_dia(dia):
                continue
            valor = _valor(pacote, dia, fonte.classe_myprofit, fonte.corretora_myprofit)
            if valor is None:
                continue
            # Os proventos que entram como rendimento são os pagos depois do
            # último saldo já conferido: os de antes já estão no saldo do CB.
            anterior = max([anterior, *(d for d in conferidos if d < dia)])
            plano.linhas.append(_linha(user, conta, fonte.classe_myprofit, dia, valor, anterior, pacote, remessas_faltando))
            anterior = dia
    return plano


def _linha(user, conta, classe, dia, valor, anterior, pacote: Pacote, remessas_faltando: list[Remessa]) -> Linha:
    previa = saldo.previa(user, account_id=conta.id, data=dia, saldo_informado=str(valor))
    linha = Linha(conta=conta, data=dia, valor=valor, saldo_no_cb=previa.saldo_no_cb, acao="lancar")
    if is_month_closed(conta, dia.year, dia.month):
        linha.acao, linha.motivo = "pular", gettext("mês fechado")
        return linha
    if previa.pendencia:
        linha.acao, linha.motivo = "pular", previa.pendencia
        return linha
    if classe == CLASSE_CAIXA_USD:
        faltando = [r for r in remessas_faltando if r.data <= dia and _mesma(r.corretora, conta.institution.institution_name)]
        if faltando:
            linha.acao = "pular"
            linha.motivo = gettext("remessa de %(dia)s ainda não está no CB") % {"dia": regional.formatar_data(faltando[0].data)}
            return linha
    if linha.diferenca == 0:
        linha.acao = "conferir"
        return linha
    if classe == CLASSE_CAIXA_USD:
        linha.destino = saldo.DESTINO_INVESTIMENTOS
        linha.rendimento = sum(
            (p.valor_usd for p in pacote.proventos if anterior < p.data <= dia and _mesma(p.corretora, conta.institution.institution_name)),
            Decimal("0"),
        ).quantize(_CENTAVO)
    else:
        linha.destino = saldo.DESTINO_MARCACAO
    return linha


# --- gravação ----------------------------------------------------------------------

@transaction.atomic
def aplicar(user, plano: Plano, *, audit_context=None) -> ColetaMyProfit:
    """Grava o plano: lançamentos e conferências, tudo ou nada.

    O plano é refeito antes de gravar, para que a gravação use o saldo do CB de
    agora e não o da prévia."""
    plano = planejar(user, plano.pacote)
    for linha in plano.linhas:
        if linha.acao == "conferir":
            saldo.confirmar(user, account_id=linha.conta.id, data=linha.data, saldo_informado=str(linha.valor), origem=ORIGEM_MYPROFIT)
        elif linha.acao == "lancar":
            _lancar(user, linha, audit_context)
    coleta, _ = ColetaMyProfit.objects.update_or_create(
        sha256=plano.pacote.sha256,
        defaults={
            "ate": plano.pacote.ate, "importada_por": user,
            "saldos": len(plano.a_lancar) + len(plano.a_conferir), "remessas": plano.remessas_conferidas,
            "pendencias": plano.pendencias + [
                gettext("%(conta)s em %(dia)s: %(motivo)s") % {"conta": linha.titulo, "dia": regional.formatar_data(linha.data), "motivo": linha.motivo}
                for linha in plano.puladas if linha.motivo != gettext("mês fechado")
            ],
        },
    )
    return coleta


def _lancar(user, linha: Linha, audit_context) -> None:
    comum = {"account_id": linha.conta.id, "data": linha.data, "audit_context": audit_context, "origem": ORIGEM_MYPROFIT}
    if linha.rendimento > 0:
        # Primeiro os proventos do período, como rendimento; o resto da diferença
        # foi para ativos ou voltou deles.
        parcial = linha.saldo_no_cb + linha.rendimento
        saldo.aplicar(
            user, saldo_informado=str(parcial), diferenca_esperada=str(linha.rendimento),
            destino=saldo.DESTINO_RENDIMENTOS, motivo="proventos do myProfit", **comum,
        )
        restante = (linha.valor - parcial).quantize(_CENTAVO)
        if restante == 0:
            saldo.confirmar(user, account_id=linha.conta.id, data=linha.data, saldo_informado=str(linha.valor), origem=ORIGEM_MYPROFIT)
            return
        saldo.aplicar(
            user, saldo_informado=str(linha.valor), diferenca_esperada=str(restante),
            destino=saldo.DESTINO_INVESTIMENTOS, motivo="caixa do myProfit", **comum,
        )
        return
    motivo = "posição do myProfit" if linha.destino == saldo.DESTINO_MARCACAO else "caixa do myProfit"
    saldo.aplicar(
        user, saldo_informado=str(linha.valor), diferenca_esperada=str(linha.diferenca),
        destino=linha.destino, motivo=motivo, **comum,
    )


def ultima_coleta() -> ColetaMyProfit | None:
    return ColetaMyProfit.objects.order_by("-ate", "-id").first()


__all__ = ["FORMATO", "PacoteInvalidoError", "Plano", "aplicar", "ler", "planejar", "ultima_coleta", "SaldoConferido"]
