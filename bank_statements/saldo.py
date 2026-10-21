"""Atualizar saldo: o usuário informa o saldo real de uma conta numa data e o
sistema lança a diferença com um destino explícito.

Serve ao que o extrato não mostra linha a linha: o rendimento de um CDB, do
cofrinho ou de uma conta remunerada, o IR e o IOF retidos, uma perda. Em vez de
mexer no saldo inicial, a diferença vira um lançamento realizado, com data,
categoria e motivo, que entra nos relatórios e na auditoria.

Destinos da diferença:

- **entrada** (o saldo real é maior que o do CB): *Rendimentos* ou *Ajuste
  assumido*;
- **saída** (o saldo real é menor): *IR/IOF*, *Perda* ou *Ajuste assumido*;
- **nos dois sentidos**: *Marcação a mercado* (Tesouro e renda fixa, cujo valor
  sobe e desce com o preço; categoria "Rendimentos") e *Investimentos* (o caixa
  de uma corretora que foi para ativos ou voltou deles; categoria de
  movimentação "Operações em Bolsa", que não é gasto nem renda).

Cada saldo informado fica registrado por conta e data (`fechamento.SaldoConferido`),
com ou sem diferença. Informar de novo o mesmo dia não duplica nada: o saldo do CB
já inclui a diferença lançada da primeira vez, e o registro só passa a guardar o
valor mais recente.

*Ajuste assumido* é o "assumo isto para a movimentação bater": exige motivo, usa
a categoria "Ajustes de Saldo" e aparece na lista de assunções, para nada ficar
escondido e dar para revisar depois.

O saldo comparado é o realizado até a data, inclusive. Mês fechado recusa o
lançamento, como qualquer outro.

Aplicação com conta de movimento (`FinancialAccount.movement_account`) só aceita
o saldo depois que o extrato dessa conta foi importado no mês e conciliado até a
data: a diferença é tudo o que as transferências não explicam, e uma
transferência que ainda não entrou viraria rendimento.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Q
from django.utils.translation import gettext, gettext_lazy, ngettext

from banking.models import FinancialAccount
from banking.services import accessible_account_ids, can_access_account
from core import regional
from core.domain.finance import (
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_REALIZED,
    VIEW_REALIZED,
)
from fechamento.models import ORIGEM_MANUAL, ORIGENS_DO_SALDO, SaldoConferido
from reports.services import decimal_balances_before_by_account
from transactions.models import CashFlowCategory, CashFlowEntry
from transactions.services import TransactionRequest, create_transaction_batch

from .models import LINE_STATUS_NEW, BankStatementImport, BankStatementLine

CATEGORIA_DE_AJUSTE = "Ajustes de Saldo"
#: Início da descrição de todo lançamento daqui (a Situação das Contas também o reconhece por ele).
PREFIXO_DA_DESCRICAO = "Atualização de saldo"

DESTINO_RENDIMENTOS = "rendimentos"
DESTINO_IR_IOF = "ir_iof"
DESTINO_PERDA = "perda"
DESTINO_AJUSTE = "ajuste"
DESTINO_MARCACAO = "marcacao"
DESTINO_INVESTIMENTOS = "investimentos"

# destino -> (rótulo, nome da categoria, tipo do lançamento, exige motivo)
# O nome da categoria é chave de busca no banco: não se traduz.
DESTINOS = {
    DESTINO_RENDIMENTOS: (gettext_lazy("Rendimentos"), "Rendimentos", ENTRY_TYPE_INCOME, False),
    DESTINO_IR_IOF: (gettext_lazy("IR / IOF"), "Impostos e Tributos", ENTRY_TYPE_EXPENSE, False),
    DESTINO_PERDA: (gettext_lazy("Perda"), CATEGORIA_DE_AJUSTE, ENTRY_TYPE_EXPENSE, True),
    DESTINO_AJUSTE: (gettext_lazy("Ajuste assumido"), CATEGORIA_DE_AJUSTE, None, True),
    DESTINO_MARCACAO: (gettext_lazy("Marcação a mercado"), "Rendimentos", None, False),
    DESTINO_INVESTIMENTOS: (gettext_lazy("Investimentos (compra ou venda de ativos)"), "Operações em Bolsa", None, False),
}
# O que vai para a descrição gravada do lançamento (e que a Situação reconhece):
# fica em português, como o resto do que é gravado, qualquer que seja o idioma da tela.
_ROTULO_NA_DESCRICAO = {
    DESTINO_RENDIMENTOS: "rendimentos",
    DESTINO_IR_IOF: "ir / iof",
    DESTINO_PERDA: "perda",
    DESTINO_AJUSTE: "ajuste assumido",
    DESTINO_MARCACAO: "marcação a mercado",
    DESTINO_INVESTIMENTOS: "investimentos",
}
_QUANTO = Decimal("0.01")


@dataclass(frozen=True)
class Previa:
    conta: FinancialAccount
    data: date
    saldo_informado: Decimal
    saldo_no_cb: Decimal
    pendencia: str = ""
    ja_conferido: SaldoConferido | None = None

    @property
    def diferenca(self) -> Decimal:
        return (self.saldo_informado - self.saldo_no_cb).quantize(_QUANTO)

    @property
    def tipo(self) -> str | None:
        if self.diferenca > 0:
            return ENTRY_TYPE_INCOME
        if self.diferenca < 0:
            return ENTRY_TYPE_EXPENSE
        return None

    @property
    def destinos(self) -> list[tuple[str, str]]:
        """Os destinos que servem ao sentido da diferença, como `(chave, rótulo)`."""
        return [
            (chave, str(rotulo))
            for chave, (rotulo, _, tipo, _) in DESTINOS.items()
            if tipo is None or tipo == self.tipo
        ]


def _conta(user, account_id, acao: str) -> FinancialAccount:
    try:
        conta = FinancialAccount.objects.select_related("owner", "institution", "movement_account__institution").get(id=int(account_id))
    except (FinancialAccount.DoesNotExist, ValueError, TypeError) as exc:
        raise ValueError(gettext("Conta não encontrada.")) from exc
    if not can_access_account(user, conta.id, acao):
        raise ValueError(gettext("Acesso negado: você não tem permissão para acessar esta conta."))
    if conta.is_credit_card:
        raise ValueError(gettext("Cartão de crédito não tem saldo para atualizar: use a fatura."))
    return conta


def _decimal(valor, rotulo: str) -> Decimal:
    texto = str(valor).strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation as exc:
        raise ValueError(gettext("%(rotulo)s inválido.") % {"rotulo": rotulo}) from exc


def pendencia_da_movimentacao(conta: FinancialAccount, data: date) -> str:
    """O que falta na conta de movimento para o saldo da aplicação valer, ou "".

    Falta o extrato do mês (nenhuma linha, saldo de extrato ou fim de período
    do arquivo desde o dia 1º) ou falta conciliar alguma linha até a data."""
    movimento = conta.movement_account
    if movimento is None:
        return ""
    rotulo = f"{movimento.institution.institution_name} / {movimento.account_name}"
    pendentes = BankStatementLine.objects.filter(
        account=movimento, status=LINE_STATUS_NEW, statement_date__lte=data
    ).count()
    if pendentes:
        return ngettext(
            "A conta de movimento %(conta)s tem %(n)s linha de extrato pendente até %(data)s: "
            "concilie antes, ou uma transferência que falta vira rendimento.",
            "A conta de movimento %(conta)s tem %(n)s linhas de extrato pendentes até %(data)s: "
            "concilie antes, ou uma transferência que falta vira rendimento.",
            pendentes,
        ) % {"conta": rotulo, "n": pendentes, "data": regional.formatar_data(data)}
    ultima_linha = BankStatementLine.objects.filter(account=movimento).aggregate(d=Max("statement_date"))["d"]
    lotes = BankStatementImport.objects.filter(account=movimento).aggregate(
        saldo=Max("statement_balance_date"), periodo=Max("statement_period_end")
    )
    coberto = max((d for d in (ultima_linha, lotes["saldo"], lotes["periodo"]) if d is not None), default=None)
    if coberto is None or coberto < data.replace(day=1):
        return gettext(
            "O extrato de %(mes)s da conta de movimento %(conta)s ainda não foi importado: "
            "importe e concilie antes de informar o saldo."
        ) % {"mes": regional.formatar_mes(data), "conta": rotulo}
    return ""


def previa(user, *, account_id, data: date, saldo_informado) -> Previa:
    conta = _conta(user, account_id, "view")
    informado = _decimal(saldo_informado, gettext("Saldo")).quantize(_QUANTO)
    saldos = decimal_balances_before_by_account([conta.id], data + timedelta(days=1), VIEW_REALIZED)
    return Previa(
        conta=conta, data=data, saldo_informado=informado, saldo_no_cb=saldos.get(conta.id, Decimal("0.00")),
        pendencia=pendencia_da_movimentacao(conta, data),
        ja_conferido=SaldoConferido.objects.filter(account=conta, data=data).first(),
    )


def _registrar(user, conta: FinancialAccount, data: date, valor: Decimal, origem: str, lancamento=None) -> SaldoConferido:
    """Um registro por conta e data: o saldo mais recente informado para aquele dia."""
    if origem not in dict(ORIGENS_DO_SALDO):
        origem = ORIGEM_MANUAL
    defaults = {"valor": valor, "origem": origem, "created_by": user}
    if lancamento is not None:
        defaults["lancamento"] = lancamento
    registro, _ = SaldoConferido.objects.update_or_create(account=conta, data=data, defaults=defaults)
    return registro


def confirmar(user, *, account_id, data: date, saldo_informado, origem: str = ORIGEM_MANUAL) -> SaldoConferido:
    """Registra um saldo que já bate com o do CB: a conferência fica, sem lançamento."""
    atual = previa(user, account_id=account_id, data=data, saldo_informado=saldo_informado)
    conta = _conta(user, account_id, "create")
    if atual.pendencia:
        raise ValueError(atual.pendencia)
    if atual.tipo is not None:
        raise ValueError(gettext("O saldo informado não bate com o do CB: lance a diferença com um destino."))
    return _registrar(user, conta, data, atual.saldo_informado, origem)


def _categoria(nome: str) -> CashFlowCategory:
    categoria = CashFlowCategory.objects.filter(category_name__iexact=nome).first()
    if categoria is None:
        raise ValueError(gettext("Cadastre a categoria “%(nome)s” antes de lançar esta diferença.") % {"nome": nome})
    return categoria


def aplicar(
    user, *, account_id, data: date, saldo_informado, diferenca_esperada, destino: str, motivo: str = "",
    audit_context=None, origem: str = ORIGEM_MANUAL,
) -> CashFlowEntry:
    """Lança a diferença como um lançamento realizado na data do saldo.

    `diferenca_esperada` é a que a prévia mostrou: se o saldo do CB mudou desde
    então (outra importação, outro usuário), nada é gravado e a prévia é refeita."""
    if destino not in DESTINOS:
        raise ValueError(gettext("Escolha o destino da diferença."))
    rotulo, nome_da_categoria, tipo_fixo, exige_motivo = DESTINOS[destino]
    motivo = (motivo or "").strip()
    if exige_motivo and not motivo:
        raise ValueError(gettext("“%(rotulo)s” exige um motivo.") % {"rotulo": rotulo})

    atual = previa(user, account_id=account_id, data=data, saldo_informado=saldo_informado)
    conta = _conta(user, account_id, "create")
    if atual.pendencia:
        raise ValueError(atual.pendencia)
    if atual.diferenca != _decimal(diferenca_esperada, gettext("Diferença")).quantize(_QUANTO):
        raise ValueError(gettext("O saldo do CB mudou desde a prévia. Confira a nova diferença."))
    if atual.tipo is None:
        raise ValueError(gettext("O saldo informado já bate com o do CB: não há o que lançar."))
    if tipo_fixo is not None and tipo_fixo != atual.tipo:
        raise ValueError(gettext("“%(rotulo)s” não serve ao sentido desta diferença.") % {"rotulo": rotulo})

    descricao = f"{PREFIXO_DA_DESCRICAO}: {_ROTULO_NA_DESCRICAO[destino]}"
    if motivo:
        descricao = f"{descricao} ({motivo})"
    valor = abs(atual.diferenca)
    with transaction.atomic():
        lancamento = create_transaction_batch(
            TransactionRequest(
                account_id=conta.id,
                category_id=_categoria(nome_da_categoria).id,
                entry_type=atual.tipo,
                description=descricao,
                entry_amount=valor,
                installments=1,
                due_date=data,
                status=STATUS_REALIZED,
                realized_date=data,
                realized_amount=valor,
            ),
            audit_context=audit_context,
            user=user,
        )[0]
        _registrar(user, conta, data, atual.saldo_informado, origem, lancamento)
    return lancamento


def atualizacoes(user, limit: int = 200) -> list[CashFlowEntry]:
    """Tudo o que entrou por "Atualizar saldo" (rendimento, IR/IOF, perda,
    ajuste assumido) e qualquer outro lançamento de "Ajustes de Saldo" das
    contas do usuário, do mais recente ao mais antigo."""
    contas = accessible_account_ids(user, "view")
    if not contas:
        return []
    return list(
        CashFlowEntry.objects.filter(account_id__in=contas)
        .filter(Q(description__startswith=PREFIXO_DA_DESCRICAO) | Q(category__category_name__iexact=CATEGORIA_DE_AJUSTE))
        .select_related("account__owner", "account__institution", "category")
        .order_by("-due_date", "-id")[:limit]
    )


def assuncoes(user, limit: int = 200) -> list[CashFlowEntry]:
    """Todos os lançamentos de "Ajustes de Saldo" das contas do usuário."""
    contas = accessible_account_ids(user, "view")
    if not contas:
        return []
    return list(
        CashFlowEntry.objects.filter(
            account_id__in=contas, category__category_name__iexact=CATEGORIA_DE_AJUSTE
        )
        .select_related("account__owner", "account__institution")
        .order_by("-due_date", "-id")[:limit]
    )
