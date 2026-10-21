"""Roteiro de fechamento: o que falta, conta a conta, para conferir tudo até uma data.

O corte é uma data qualquer (10, 25, o último dia do mês, hoje): cada fonte é
avaliada contra ela, sem travar nada. A trava continua sendo o fechamento mensal,
que o roteiro só sugere no corte do último dia.

Etapas, na ordem em que se faz:

1. **Extratos e faturas** -- conta com arquivo do banco: o extrato cobre até o
   corte e nada ficou por conciliar; cartão: a fatura que fechou até o corte foi
   importada;
2. **Saldos sem extrato** -- aplicação e conta de print: o saldo do corte foi
   informado (ou o do fim do mês, se a conta só é conferida no fim do mês). A
   aplicação com conta de movimento espera o extrato dela, como em Saldo aplicações;
3. **myProfit** -- a coleta do período chegou, e as contas que dependem dela
   (Tesouro, renda fixa EUA, caixa em dólar) têm o saldo lançado; mais o que o CRV
   diz dos negócios e da posição;
4. **Conferências** -- possíveis duplicatas, fontes do saldo que não concordam, saldo do arquivo contra o do CB, o que
   a coleta não resolveu e as conferências do CRV;
5. **Fechar o mês** -- no corte do último dia, quando o resto está em dia.

Datas: o extrato de hoje quase nunca existe ainda, então a cobertura exigida vai
até a véspera (`alvo`). Um saldo de print é o de agora, e vale até hoje
(`alvo_do_saldo`). Corte no futuro cobra só até hoje e mostra o resto como
"depois".
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Max
from django.urls import reverse
from django.utils.translation import gettext, gettext_lazy, ngettext

from bank_statements.fatura_projetada import _no_dia, faturas_importadas
from bank_statements.models import LINE_STATUS_NEW, BankStatementImport, BankStatementLine
from bank_statements.saldo import pendencia_da_movimentacao
from banking.models import FinancialAccount
from banking.services import accessible_account_ids
from core import regional
from core.domain.finance import ACCOUNT_KIND_INVESTMENT, STATUS_REALIZED, VIEW_REALIZED
from core.patrimonio import coberturas_de_extrato
from core.templatetags.money_filters import money_signed
from reports.services import decimal_balances_before_by_account
from transactions.models import AccountMonthClose, CashFlowEntry

from . import crv, duplicatas, fontes_divergentes
from .fontes import (
    FONTE_ARQUIVO,
    FONTE_FATURA,
    FONTE_MYPROFIT,
    FONTE_NENHUMA,
    FONTE_PRINT,
    Fonte,
    fontes_das_contas,
)
from .models import (
    FREQUENCIA_MENSAL,
    ORIGENS_DO_SALDO,
    ColetaMyProfit,
    CorteDeFechamento,
    SaldoConferido,
)

EM_DIA = "em_dia"
FALTA = "falta"
PENDENTE = "pendente"
ESPERA = "espera"
FORA = "fora"
DEPOIS = "depois"
SEM_FONTE = "sem_fonte"

#: estado -> rótulo da legenda. A cor acompanha o estado, mas o texto do item
#: sempre diz o que é: a tela não depende da cor.
ROTULOS = {
    EM_DIA: gettext_lazy("Em dia"),
    FALTA: gettext_lazy("Falta fazer"),
    PENDENTE: gettext_lazy("Pede decisão"),
    ESPERA: gettext_lazy("Espera outro passo"),
    SEM_FONTE: gettext_lazy("Sem fonte ou conta"),
    FORA: gettext_lazy("Não se aplica neste corte"),
    DEPOIS: gettext_lazy("Em dia até hoje"),
}
A_FAZER = (FALTA, PENDENTE)
PROBLEMAS = (FALTA, PENDENTE, ESPERA, SEM_FONTE)

ETAPA_EXTRATOS = "extratos"
ETAPA_SALDOS = "saldos"
ETAPA_MYPROFIT = "myprofit"
ETAPA_CONFERENCIAS = "conferencias"
ETAPA_FECHAR = "fechar"
ETAPAS = (
    (ETAPA_EXTRATOS, gettext_lazy("Extratos e faturas"),
     gettext_lazy("Contas com movimento linha a linha. Pode exportar um período maior: o que já foi importado é reconhecido e ignorado.")),
    (ETAPA_SALDOS, gettext_lazy("Saldos sem extrato"),
     gettext_lazy("Aplicações e contas em que só o saldo entra. O rendimento sai da diferença; a conta de movimento precisa estar em dia antes.")),
    (ETAPA_MYPROFIT, gettext_lazy("myProfit"),
     gettext_lazy("Uma coleta alimenta o CB (Tesouro, renda fixa EUA, caixa em dólar, câmbio) e o CRV (negócios e posição).")),
    (ETAPA_CONFERENCIAS, gettext_lazy("Conferências"),
     gettext_lazy("Rodam sozinhas com o que já foi importado. Aqui aparece o resultado e o que pede decisão sua.")),
    (ETAPA_FECHAR, gettext_lazy("Fechar o mês"),
     gettext_lazy("Trava o mês nas contas conferidas. Só no corte do último dia; os cortes do meio do mês não travam nada.")),
)


def ultimo_dia(dia: date) -> date:
    return dia.replace(day=calendar.monthrange(dia.year, dia.month)[1])


def _dia(d: date) -> str:
    return regional.formatar_dia_mes(d)


def _periodo(de: date, ate: date) -> str:
    return _dia(ate) if de >= ate else f"{_dia(de)} a {_dia(ate)}"


@dataclass
class Item:
    chave: str
    etapa: str
    titulo: str
    subtitulo: str
    estado: str
    texto: str
    detalhe: str = ""
    fonte: Fonte | None = None
    acao: str = ""
    url: str = ""
    passos: list[str] = field(default_factory=list)
    barra: list[str] = field(default_factory=list)
    automatico: bool = False
    externo: bool = False
    pares: list = field(default_factory=list)

    @property
    def a_fazer(self) -> bool:
        return self.estado in A_FAZER

    @property
    def problema(self) -> bool:
        return self.estado in PROBLEMAS

    @property
    def rotulo_do_estado(self) -> str:
        return str(ROTULOS[self.estado])


@dataclass
class Etapa:
    chave: str
    numero: int
    titulo: str
    explicacao: str
    itens: list[Item]

    @property
    def em_dia(self) -> int:
        return sum(1 for item in self.itens if not item.problema)

    @property
    def completa(self) -> bool:
        return all(not item.problema for item in self.itens)


@dataclass
class Corte:
    data: date
    rotulo: str
    concluido: CorteDeFechamento | None = None


@dataclass(frozen=True)
class DiaDaRegua:
    dia: int
    classe: str  # "feito" (até o último corte concluído), "periodo" (até o corte), ""
    marca: str = ""  # "concluido", "corte", "hoje"
    rotulo: str = ""


@dataclass
class Roteiro:
    corte: date
    hoje: date
    alvo: date
    etapas: list[Etapa]
    cortes: list[Corte]
    regua: list[DiaDaRegua]

    @property
    def itens(self) -> list[Item]:
        return [item for etapa in self.etapas for item in etapa.itens]

    @property
    def proximo(self) -> Item | None:
        return next((item for item in self.itens if item.a_fazer), None)

    def _conta(self, *estados) -> int:
        return sum(1 for item in self.itens if item.estado in estados)

    @property
    def em_dia(self) -> int:
        return self._conta(EM_DIA, FORA, DEPOIS)

    @property
    def a_fazer(self) -> int:
        return self._conta(FALTA, PENDENTE)

    @property
    def esperando(self) -> int:
        return self._conta(ESPERA)

    @property
    def sem_fonte(self) -> int:
        return self._conta(SEM_FONTE)

    @property
    def total(self) -> int:
        return len(self.itens)

    @property
    def percentual(self) -> int:
        return round(100 * self.em_dia / self.total) if self.total else 0

    @property
    def anel(self) -> str:
        """`stroke-dasharray` do anel de progresso (círculo de raio 36)."""
        circunferencia = 226.19
        return f"{circunferencia * self.percentual / 100:.2f} {circunferencia:.2f}"

    @property
    def dias_no_mes(self) -> int:
        return len(self.regua)

    @property
    def concluivel(self) -> bool:
        return self.total > 0 and self.em_dia == self.total and self.corte <= self.hoje


# --- barras ------------------------------------------------------------------

def _barra_de_cobertura(corte: date, coberto: date | None, alvo: date) -> list[str]:
    inicio = corte.replace(day=1)
    marcas = []
    for dia in range(1, ultimo_dia(corte).day + 1):
        d = inicio.replace(day=dia)
        if coberto is not None and d <= coberto:
            marcas.append("c")
        elif d <= alvo:
            marcas.append("g")
        else:
            marcas.append("")
    return marcas


def _barra_de_saldos(corte: date, dias_com_saldo: set[date], alvo: date | None) -> list[str]:
    inicio = corte.replace(day=1)
    marcas = []
    for dia in range(1, ultimo_dia(corte).day + 1):
        d = inicio.replace(day=dia)
        if d in dias_com_saldo:
            marcas.append("b")
        elif alvo is not None and d == alvo:
            marcas.append("g")
        else:
            marcas.append("")
    return marcas


# --- consultas ---------------------------------------------------------------

def _pendentes(ids: list[int], ate: date) -> dict[int, int]:
    return dict(
        BankStatementLine.objects.filter(account_id__in=ids, status=LINE_STATUS_NEW, statement_date__lte=ate)
        .values("account_id").annotate(n=Count("id")).values_list("account_id", "n")
    )


def _datas_de_saldo(ids: list[int]) -> dict[int, set[date]]:
    """Todos os dias em que cada conta teve saldo informado (conferido ou lançado)."""
    datas: dict[int, set[date]] = {conta_id: set() for conta_id in ids}
    for conta_id, dia in SaldoConferido.objects.filter(account_id__in=ids).values_list("account_id", "data"):
        datas[conta_id].add(dia)
    for conta_id, dia in CashFlowEntry.objects.filter(
        account_id__in=ids, status=STATUS_REALIZED, description__startswith="Atualização de saldo"
    ).values_list("account_id", "due_date"):
        datas[conta_id].add(dia)
    return datas


def _movimentadas(ids: list[int], inicio: date, fim: date) -> set[int]:
    return set(
        CashFlowEntry.objects.filter(account_id__in=ids, status=STATUS_REALIZED, realized_date__gte=inicio, realized_date__lte=fim)
        .values_list("account_id", flat=True).distinct()
    )


def _titulo(conta: FinancialAccount) -> str:
    return f"{conta.institution.institution_name} / {conta.account_name}"


def _url_do_saldo(conta: FinancialAccount, dia: date, origem: str) -> str:
    return f"{reverse('bank_statements:atualizar_saldo')}?conta={conta.id}&data={dia.isoformat()}&origem={origem}"


# --- etapas ------------------------------------------------------------------

def _item_de_extrato(conta, fonte: Fonte, corte, alvo, hoje, coberto, pendentes) -> Item:
    titulo, titular = _titulo(conta), conta.owner.name
    so_fim_do_mes = fonte.frequencia == FREQUENCIA_MENSAL and corte < ultimo_dia(corte)
    if so_fim_do_mes:
        # Conta conferida só no fim do mês: no meio dele, basta o mês anterior completo.
        alvo = min(alvo, corte.replace(day=1) - timedelta(days=1))
    barra = _barra_de_cobertura(corte, coberto, alvo)
    formato = fonte.formato or gettext("extrato do banco")
    base = {"chave": f"conta-{conta.id}", "etapa": ETAPA_EXTRATOS, "titulo": titulo, "subtitulo": titular, "fonte": fonte, "barra": barra}
    if so_fim_do_mes and coberto is not None and coberto >= alvo and not pendentes:
        return Item(estado=FORA, texto=gettext("Só no fim do mês"), detalhe=_coberto(coberto), **base)
    if coberto is None or coberto < alvo:
        de = (coberto + timedelta(days=1)) if coberto else max(conta.initial_balance_date + timedelta(days=1), corte.replace(day=1))
        return Item(
            estado=FALTA,
            texto=gettext("Falta %(periodo)s") % {"periodo": _periodo(de, alvo)},
            detalhe=_coberto(coberto),
            acao=gettext("Importar %(formato)s") % {"formato": formato},
            url=reverse("bank_statements:imports_view"),
            passos=[
                (gettext("Onde: %(onde)s.") % {"onde": fonte.onde}) if fonte.onde else gettext("Exporte o extrato no app ou no site do banco."),
                gettext("Período: %(de)s a %(ate)s. Começar uns dias antes é seguro: o que já foi importado é ignorado.") % {
                    "de": _dia(max(de - timedelta(days=3), conta.initial_balance_date)), "ate": _dia(alvo),
                },
                gettext("Envie o arquivo em Importar extratos e faturas e concilie as linhas novas."),
            ],
            **base,
        )
    if pendentes:
        return Item(
            estado=PENDENTE,
            texto=ngettext("%(n)s linha para conciliar", "%(n)s linhas para conciliar", pendentes) % {"n": pendentes},
            detalhe=_coberto(coberto),
            acao=gettext("Abrir a conciliação"),
            url=reverse("bank_statements:reconciliation_view"),
            **base,
        )
    if corte > hoje:
        return Item(estado=DEPOIS, texto=gettext("Em dia até %(dia)s") % {"dia": _dia(coberto)}, detalhe=gettext("O corte é %(dia)s; o restante entra depois.") % {"dia": _dia(corte)}, **base)
    return Item(estado=EM_DIA, texto=gettext("Em dia até %(dia)s") % {"dia": _dia(coberto)}, **base)


def _coberto(coberto: date | None) -> str:
    if coberto is None:
        return gettext("Nenhum extrato importado.")
    return gettext("Extrato até %(dia)s.") % {"dia": regional.formatar_data(coberto)}


def _item_de_fatura(conta, fonte: Fonte, corte, alvo, pendentes) -> Item:
    base = {"chave": f"conta-{conta.id}", "etapa": ETAPA_EXTRATOS, "titulo": _titulo(conta), "subtitulo": conta.owner.name, "fonte": fonte}
    fechamento = _no_dia(alvo.year, alvo.month, conta.card_closing_day)
    if fechamento > alvo:
        anterior = alvo.replace(day=1) - timedelta(days=1)
        fechamento = _no_dia(anterior.year, anterior.month, conta.card_closing_day)
    if fechamento < conta.initial_balance_date:
        return Item(estado=FORA, texto=gettext("Nenhuma fatura até o corte"), **base)
    faturas = faturas_importadas(conta)
    ultima = faturas[0].fechamento if faturas else None
    if ultima is None or ultima < fechamento:
        detalhe = gettext("Última fatura importada: fechamento em %(dia)s.") % {"dia": regional.formatar_data(ultima)} if ultima else gettext("Nenhuma fatura importada.")
        return Item(
            estado=FALTA,
            texto=gettext("Falta a fatura que fechou em %(dia)s") % {"dia": _dia(fechamento)},
            detalhe=detalhe,
            acao=gettext("Importar %(formato)s") % {"formato": fonte.formato or gettext("fatura")},
            url=reverse("bank_statements:imports_view"),
            passos=[
                (gettext("Onde: %(onde)s.") % {"onde": fonte.onde}) if fonte.onde else gettext("Baixe a fatura fechada no app do cartão."),
                gettext("Só fatura fechada: a fatura aberta ainda muda até o fechamento."),
                gettext("Envie o arquivo em Importar extratos e faturas e processe a prévia."),
            ],
            **base,
        )
    if pendentes:
        return Item(
            estado=PENDENTE,
            texto=ngettext("%(n)s linha da fatura para processar", "%(n)s linhas da fatura para processar", pendentes) % {"n": pendentes},
            acao=gettext("Abrir as faturas"), url=reverse("bank_statements:faturas"), **base,
        )
    return Item(estado=EM_DIA, texto=gettext("Fatura de %(dia)s importada") % {"dia": _dia(ultima)}, **base)


def _alvo_do_saldo(fonte: Fonte, corte: date, hoje: date) -> tuple[date, bool]:
    """A data do saldo que o corte pede e se ela é só a do fim do mês anterior."""
    if fonte.frequencia == FREQUENCIA_MENSAL and corte < ultimo_dia(corte):
        return corte.replace(day=1) - timedelta(days=1), True
    return min(corte, hoje), False


def _item_de_saldo(conta, fonte: Fonte, etapa, corte, hoje, datas: set[date], saldo_atual: Decimal, movimentada: bool, coleta: ColetaMyProfit | None) -> Item:
    titulo, titular = _titulo(conta), conta.owner.name
    alvo, so_fim_do_mes = _alvo_do_saldo(fonte, corte, hoje)
    ultima = max(datas) if datas else None
    barra = _barra_de_saldos(corte, datas, None if so_fim_do_mes else alvo)
    base = {"chave": f"conta-{conta.id}", "etapa": etapa, "titulo": titulo, "subtitulo": titular, "fonte": fonte, "barra": barra}
    detalhe = gettext("Último saldo em %(dia)s.") % {"dia": regional.formatar_data(ultima)} if ultima else gettext("Nenhum saldo informado ainda.")
    if alvo < conta.initial_balance_date:
        return Item(estado=FORA, texto=gettext("A conta começa depois do corte"), **base)
    if fonte.fonte == FONTE_NENHUMA:
        if not saldo_atual and not movimentada:
            return Item(estado=FORA, texto=gettext("Sem saldo nem movimento"), detalhe=gettext("Sem fonte definida, mas também sem nada a conferir."), **base)
        return Item(
            estado=SEM_FONTE, texto=gettext("Ainda sem fonte"), detalhe=gettext("Diga em Fontes de onde vem o saldo desta conta."),
            acao=gettext("Definir a fonte"), url=reverse("fechamento:fontes"), **base,
        )
    if ultima is not None and ultima >= alvo:
        if so_fim_do_mes:
            return Item(estado=FORA, texto=gettext("Só no fim do mês"), detalhe=detalhe, **base)
        estado = DEPOIS if corte > hoje else EM_DIA
        return Item(estado=estado, texto=gettext("Saldo de %(dia)s informado") % {"dia": _dia(ultima)}, detalhe=detalhe, **base)
    if not saldo_atual and not movimentada and conta.account_kind == ACCOUNT_KIND_INVESTMENT:
        return Item(estado=EM_DIA, texto=gettext("Zerada e sem movimento"), **base)
    if fonte.fonte == FONTE_MYPROFIT and (coleta is None or coleta.ate < alvo):
        return Item(
            estado=ESPERA, texto=gettext("Depende da coleta do myProfit até %(dia)s") % {"dia": _dia(alvo)},
            detalhe=detalhe, **base,
        )
    pendencia = pendencia_da_movimentacao(conta, alvo) if conta.movement_account_id else ""
    if pendencia:
        return Item(estado=ESPERA, texto=gettext("Espera o extrato da conta de movimento"), detalhe=pendencia, **base)
    if fonte.fonte == FONTE_MYPROFIT:
        return Item(
            estado=FALTA, texto=gettext("Saldo de %(dia)s ainda não lançado") % {"dia": _dia(alvo)}, detalhe=detalhe,
            acao=gettext("Aplicar a coleta do myProfit"), url="#coleta",
            passos=[gettext("Reenvie o pacote da coleta: o que já foi lançado é reconhecido e só o que falta entra.")],
            **base,
        )
    return Item(
        estado=FALTA,
        texto=gettext("Informar o saldo de %(dia)s") % {"dia": _dia(alvo)},
        detalhe=detalhe,
        acao=gettext("Informar o saldo"),
        url=_url_do_saldo(conta, alvo, "print"),
        passos=[
            (gettext("Onde: %(onde)s.") % {"onde": fonte.onde}) if fonte.onde else gettext("Abra o app e anote o saldo da conta (ou tire um print com a data visível)."),
            gettext("Aplicação: valor líquido para resgate, já sem IR e IOF."),
            gettext("Informar o mesmo dia de novo não duplica: só uma diferença nova vira lançamento."),
        ],
        **base,
    )


def _item_da_coleta(coleta: ColetaMyProfit | None, corte: date, alvo: date, hoje: date) -> Item:
    base = {"chave": "coleta-myprofit", "etapa": ETAPA_MYPROFIT, "titulo": gettext("Coleta do myProfit"), "subtitulo": gettext("B3 e Avenue")}
    passos = [
        gettext("No navegador interno do Claude, com o myProfit logado, o Claude roda a coleta do período (scripts/myprofit/coletar.js)."),
        gettext("Sai um pacote .json só com posições, negócios, proventos e remessas: sem nome, CPF ou e-mail."),
        gettext("Envie o pacote aqui embaixo. A prévia mostra o que entra; o que já entrou é reconhecido e não se repete."),
        gettext("A parte do CRV (negócios e posição) é importada no CRV, com o mesmo pacote."),
    ]
    if coleta is None or coleta.ate < alvo:
        de = coleta.ate + timedelta(days=1) if coleta else corte.replace(day=1)
        return Item(
            estado=FALTA, texto=gettext("Coletar %(periodo)s") % {"periodo": _periodo(de, alvo)},
            detalhe=gettext("Última coleta até %(dia)s.") % {"dia": regional.formatar_data(coleta.ate)} if coleta else gettext("Nenhuma coleta aplicada ainda."),
            acao=gettext("Coletar no myProfit"), url="#coleta", passos=passos,
            barra=_barra_de_cobertura(corte, coleta.ate if coleta else None, alvo), **base,
        )
    return Item(
        estado=DEPOIS if corte > hoje else EM_DIA, texto=gettext("Coletado até %(dia)s") % {"dia": _dia(coleta.ate)},
        detalhe=gettext("Aplicada em %(quando)s.") % {"quando": regional.formatar_data(coleta.importada_em.date())},
        barra=_barra_de_cobertura(corte, coleta.ate, alvo), **base,
    )


def _itens_do_crv(status: crv.StatusDoCrv) -> list[Item]:
    if status.erro:
        return [Item(
            chave="crv", etapa=ETAPA_MYPROFIT, titulo=gettext("Renda variável (CRV)"), subtitulo="CRV",
            estado=ESPERA, texto=status.erro, detalhe=gettext("Negócios, posição e conferências do CRV ficam de fora até ele responder."),
            automatico=True,
        )]
    return [
        Item(
            chave=f"crv-{dado['chave']}", etapa=dado["etapa"], titulo=dado["titulo"], subtitulo=dado["subtitulo"] or "CRV",
            estado=dado["estado"], texto=dado["texto"], detalhe=dado["detalhe"], acao=dado["acao"], url=dado["url"],
            passos=dado["passos"], automatico=dado["etapa"] == ETAPA_CONFERENCIAS, externo=bool(dado["url"]),
        )
        for dado in status.itens
    ]


def _conferencias_do_cb(user, contas, corte, alvo, coleta) -> list[Item]:
    itens = []
    pares = duplicatas.possiveis(user, corte.replace(day=1) - timedelta(days=duplicatas.JANELA_DIAS), alvo)
    base = {"etapa": ETAPA_CONFERENCIAS, "subtitulo": "CB", "automatico": True}
    if pares:
        itens.append(Item(
            chave="duplicatas", titulo=gettext("Possíveis duplicatas"), estado=PENDENTE,
            texto=ngettext("%(n)s par de linhas parecidas", "%(n)s pares de linhas parecidas", len(pares)) % {"n": len(pares)},
            detalhe=gettext("Mesmo valor e conta, até dois dias de distância, descrições e arquivos diferentes."),
            acao=gettext("Revisar"), pares=pares, **base,
        ))
    else:
        itens.append(Item(chave="duplicatas", titulo=gettext("Possíveis duplicatas"), estado=EM_DIA, texto=gettext("Nenhuma no período"), **base))

    divergentes = _saldos_de_arquivo_divergentes(contas)
    if divergentes:
        itens.append(Item(
            chave="saldo-arquivo", titulo=gettext("Saldo do arquivo × saldo do CB"), estado=PENDENTE,
            texto=ngettext("%(n)s conta não bate", "%(n)s contas não batem", len(divergentes)) % {"n": len(divergentes)},
            detalhe="; ".join(divergentes), acao=gettext("Abrir os extratos"), url=reverse("bank_statements:extratos"), **base,
        ))
    else:
        itens.append(Item(chave="saldo-arquivo", titulo=gettext("Saldo do arquivo × saldo do CB"), estado=EM_DIA, texto=gettext("Todos os últimos arquivos conferem"), **base))

    discordam = fontes_divergentes.divergentes(user, corte.replace(day=1) - timedelta(days=31), alvo)
    if discordam:
        origens = dict(ORIGENS_DO_SALDO)
        itens.append(Item(
            chave="fontes-divergentes", titulo=gettext("Fontes do saldo que não concordam"), estado=PENDENTE,
            texto=ngettext("%(n)s dia com saldos diferentes", "%(n)s dias com saldos diferentes", len(discordam)) % {"n": len(discordam)},
            detalhe="; ".join(
                gettext("%(conta)s em %(dia)s: %(valores)s") % {
                    "conta": _titulo(d.conta), "dia": _dia(d.data),
                    "valores": " × ".join(f"{origens.get(o, o)} {money_signed(v, d.conta.currency)}" for o, v in d.valores.items()),
                }
                for d in discordam[:6]
            ),
            acao=gettext("Decidir qual vale"), url=_url_do_saldo(discordam[0].conta, discordam[0].data, ""), **base,
        ))
    else:
        itens.append(Item(
            chave="fontes-divergentes", titulo=gettext("Fontes do saldo que não concordam"), estado=EM_DIA,
            texto=gettext("Nenhuma no período"), **base,
        ))

    if coleta is not None and coleta.pendencias:
        itens.append(Item(
            chave="coleta-pendencias", titulo=gettext("O que a coleta do myProfit não resolveu"), estado=PENDENTE,
            texto=ngettext("%(n)s ponto para decidir", "%(n)s pontos para decidir", len(coleta.pendencias)) % {"n": len(coleta.pendencias)},
            detalhe="; ".join(str(p) for p in coleta.pendencias[:6]), **base,
        ))
    return itens


def _saldos_de_arquivo_divergentes(contas) -> list[str]:
    """O último lote de cada conta que informa saldo, contra o saldo do CB naquela data."""
    from bank_statements.painel_de_extratos import _conferencias

    ids = [conta.id for conta in contas if not conta.is_credit_card]
    ultimos = (
        BankStatementImport.objects.filter(account_id__in=ids, statement_balance__isnull=False, statement_balance_date__isnull=False)
        .values("account_id").annotate(ultimo=Max("id")).values_list("ultimo", flat=True)
    )
    lotes = list(BankStatementImport.objects.filter(id__in=list(ultimos)).select_related("account__institution"))
    conferencias = _conferencias(lotes)
    textos = []
    for lote in lotes:
        conferencia = conferencias.get(lote.id)
        if conferencia is not None and not conferencia.bate:
            textos.append(gettext("%(conta)s em %(dia)s: diferença de %(valor)s") % {
                "conta": _titulo(lote.account), "dia": _dia(conferencia.data),
                "valor": money_signed(conferencia.diferenca, lote.account.currency),
            })
    return textos


def _item_de_fechar(etapas_anteriores: list[Etapa], corte: date) -> Item:
    base = {"chave": "fechar-mes", "etapa": ETAPA_FECHAR, "titulo": gettext("Fechar o mês"), "subtitulo": "CB", "automatico": False}
    mes = regional.formatar_mes(corte)
    if corte < ultimo_dia(corte):
        return Item(estado=FORA, texto=gettext("Disponível no corte de %(dia)s") % {"dia": _dia(ultimo_dia(corte))}, detalhe=gettext("Cortes parciais não travam nada."), **base)
    # Fecha-se o que o roteiro conferiu: conta fora do corte (sem fonte e sem
    # nada a conferir, conta que começa depois) não precisa de trava.
    ids = [
        int(item.chave.removeprefix("conta-"))
        for etapa in etapas_anteriores for item in etapa.itens
        if item.chave.startswith("conta-") and item.estado != FORA
    ]
    fechadas = AccountMonthClose.objects.filter(account_id__in=ids, active=True, year=corte.year, month=corte.month).count()
    if ids and fechadas >= len(ids):
        return Item(estado=EM_DIA, texto=gettext("%(mes)s fechado") % {"mes": mes}, **base)
    faltam = sum(1 for etapa in etapas_anteriores for item in etapa.itens if item.problema)
    if faltam:
        return Item(
            estado=ESPERA, texto=ngettext("Falta %(n)s item antes de fechar", "Faltam %(n)s itens antes de fechar", faltam) % {"n": faltam},
            detalhe=gettext("Contas já conferidas podem ser fechadas uma a uma em Fechamento mensal."), **base,
        )
    return Item(
        estado=FALTA, texto=gettext("Tudo conferido: pode fechar %(mes)s") % {"mes": mes}, acao=gettext("Fechar o mês"),
        url="/settings/monthly-close/",
        passos=[gettext("Trava o mês nas contas conferidas. Reabrir exige motivo e fica na auditoria.")], **base,
    )


# --- montagem ----------------------------------------------------------------

def sugestoes_de_corte(corte: date, hoje: date) -> list[date]:
    mes = corte.replace(day=1)
    datas = {mes.replace(day=10), mes.replace(day=25), ultimo_dia(mes)}
    if hoje.replace(day=1) == mes:
        datas.add(hoje)
    return sorted(datas)


def montar(user, corte: date, hoje: date | None = None) -> Roteiro:
    hoje = hoje or date.today()
    alvo = min(corte, hoje - timedelta(days=1))
    contas = list(
        FinancialAccount.objects.filter(id__in=accessible_account_ids(user, "view"))
        .select_related("owner", "institution", "movement_account__institution")
        .order_by("owner__name", "institution__institution_name", "account_name")
    )
    contas = [conta for conta in contas if conta.initial_balance_date <= corte]
    fontes = fontes_das_contas(contas)
    ids = [conta.id for conta in contas]
    coberturas = coberturas_de_extrato(ids)
    pendentes = _pendentes(ids, max(alvo, corte))
    datas = _datas_de_saldo(ids)
    saldos = decimal_balances_before_by_account(ids, min(corte, hoje) + timedelta(days=1), VIEW_REALIZED)
    movimentadas = _movimentadas(ids, corte.replace(day=1), min(corte, hoje))
    coleta = ColetaMyProfit.objects.order_by("-ate", "-id").first()

    por_etapa: dict[str, list[Item]] = {chave: [] for chave, *_ in ETAPAS}
    for conta in contas:
        fonte = fontes[conta.id]
        if conta.is_credit_card:
            por_etapa[ETAPA_EXTRATOS].append(_item_de_fatura(conta, fonte, corte, alvo, pendentes.get(conta.id, 0)))
        elif fonte.fonte == FONTE_ARQUIVO:
            por_etapa[ETAPA_EXTRATOS].append(_item_de_extrato(conta, fonte, corte, alvo, hoje, coberturas.get(conta.id), pendentes.get(conta.id, 0)))
        elif fonte.fonte in (FONTE_PRINT, FONTE_NENHUMA, FONTE_FATURA):
            por_etapa[ETAPA_SALDOS].append(_item_de_saldo(
                conta, fonte, ETAPA_SALDOS, corte, hoje, datas.get(conta.id, set()),
                saldos.get(conta.id, Decimal("0")), conta.id in movimentadas, coleta,
            ))
        elif fonte.fonte == FONTE_MYPROFIT:
            por_etapa[ETAPA_MYPROFIT].append(_item_de_saldo(
                conta, fonte, ETAPA_MYPROFIT, corte, hoje, datas.get(conta.id, set()),
                saldos.get(conta.id, Decimal("0")), conta.id in movimentadas, coleta,
            ))
    por_etapa[ETAPA_MYPROFIT].insert(0, _item_da_coleta(coleta, corte, alvo, hoje))
    for item in _itens_do_crv(crv.status(alvo)):
        por_etapa[item.etapa].append(item)
    por_etapa[ETAPA_CONFERENCIAS][:0] = _conferencias_do_cb(user, contas, corte, alvo, coleta)

    etapas = [
        Etapa(chave, numero, str(titulo), str(explicacao), por_etapa[chave])
        for numero, (chave, titulo, explicacao) in enumerate(ETAPAS, start=1)
        if chave != ETAPA_FECHAR
    ]
    chave, titulo, explicacao = ETAPAS[-1]
    etapas.append(Etapa(chave, len(ETAPAS), str(titulo), str(explicacao), [_item_de_fechar(etapas, corte)]))

    concluidos = {c.data: c for c in CorteDeFechamento.objects.filter(user=user, data__year=corte.year, data__month=corte.month)}
    cortes = []
    for dia in sorted(set(sugestoes_de_corte(corte, hoje)) | set(concluidos) | {corte}):
        rotulo = gettext("hoje") if dia == hoje else ""
        cortes.append(Corte(dia, rotulo, concluidos.get(dia)))
    return Roteiro(
        corte=corte, hoje=hoje, alvo=alvo, etapas=etapas, cortes=cortes,
        regua=_regua(corte, hoje, set(concluidos)),
    )


def _regua(corte: date, hoje: date, concluidos: set[date]) -> list[DiaDaRegua]:
    feito_ate = max((d for d in concluidos if d <= corte), default=None)
    regua = []
    for numero in range(1, ultimo_dia(corte).day + 1):
        dia = corte.replace(day=numero)
        if feito_ate is not None and dia <= feito_ate:
            classe = "feito"
        elif dia <= min(corte, hoje):
            classe = "periodo"
        else:
            classe = ""
        if dia in concluidos:
            marca, rotulo = "concluido", _dia(dia)
        elif dia == corte:
            marca, rotulo = "corte", _dia(dia)
        elif dia == hoje:
            marca, rotulo = "hoje", gettext("hoje")
        else:
            marca, rotulo = "", ""
        regua.append(DiaDaRegua(numero, classe, marca, rotulo))
    return regua


def concluir(user, roteiro: Roteiro) -> CorteDeFechamento:
    if not roteiro.concluivel:
        raise ValueError(gettext("O corte só pode ser concluído com tudo em dia e com a data já passada."))
    registro, _ = CorteDeFechamento.objects.update_or_create(
        user=user, data=roteiro.corte, defaults={"em_dia": roteiro.em_dia, "total": roteiro.total},
    )
    return registro
