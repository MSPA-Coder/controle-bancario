"""Processar a fatura de cartão importada (Bancos > Importações > fatura).

A importação só grava as linhas da fatura (`fatura_csv`); nenhum lançamento
nasce nela. Esta etapa decide o que cada linha vira e mostra a decisão numa
prévia antes de gravar. A mesma função (`planejar`) monta a prévia e o
processamento, então o que a tela mostra é o que acontece.

O que cada linha vira:

- **já no saldo inicial**: linha com data anterior à do saldo inicial do
  cartão. O saldo do CB soma todos os lançamentos, inclusive os anteriores a
  essa data; lançar a linha contaria a dívida duas vezes. Ela é ignorada. Se
  for uma parcela, as parcelas seguintes ainda não estão no saldo e são
  criadas como "a vencer";
- **pagamento**: crédito cuja descrição é de pagamento de fatura. Casa com a
  transferência que chega ao cartão (mesmo valor, até 10 dias de distância) e
  a realiza, com a ponta da conta que pagou. Sem transferência, a linha fica
  pendente em Bancos > Conciliação: o pagamento sai de uma conta que só você
  sabe qual é, e pode ter sido dividido;
- **parcela já lançada**: parcela de uma compra que já tem parcelado no
  cartão. Casa pela descrição e pela data (até 5 dias), não pelo número: o CB
  renumera as parcelas quando o grupo é editado ou tem uma parcela excluída;
- **compra parcelada nova**: cria as parcelas N a M e realiza a N;
- **compra já lançada**: lançamento avulso com o mesmo valor, descrição e até
  3 dias de distância. Se houver candidatos sem identificação inequívoca, a
  linha permanece pendente para conciliação manual;
- **compra** e **estorno**: criam a despesa ou a receita, já realizadas.

Mês fechado: a fatura de um mês traz compras do mês anterior, que pode já estar
fechado no cartão. A prévia mostra esses meses e o processamento, com a
autorização do usuário, os reabre e fecha de novo com o saldo que a fatura
deixou (ver `meses_fechados`).

A categoria sugerida vem, nesta ordem, da categoria mais frequente que o usuário
deu à mesma loja em qualquer conta, sem contar "Outros" (a descrição sem
portador, dólar e número de pedido; ver `reclassificacao.chave_da_descricao`),
da categoria escolhida antes para a mesma categoria do banco (a fatura aprende
com a prévia), da categoria do banco quando ela tem o nome de uma categoria
cadastrada, e de "Outros" (ver `classificacao`). A prévia deixa trocar cada uma.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils.translation import gettext

from accounts.services import has_function_permission
from banking.models import FinancialAccount
from banking.services import can_access_account
from core import regional
from core.domain.finance import (
    CALC_REPEAT,
    CATEGORY_KIND_MANAGERIAL,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    OPERATION_INSTALLMENT,
    OPERATION_INTERNAL_TRANSFER,
    OPERATION_SINGLE,
    STATUS_PROJECTED,
    STATUS_REALIZED,
)
from transactions.models import AccountMonthClose, CashFlowCategory, CashFlowEntry
from transactions.services import (
    TransactionRequest,
    assert_entry_period_open,
    assert_transfer_destination_authorized,
    close_month,
    create_transaction_batch,
    realize_transaction,
    reopen_month,
)

from .classificacao import (
    CONFIANCA_ALTA,
    CONFIANCA_BAIXA,
    CONFIANCA_MEDIA,
    CONFIANCA_NENHUMA,
    Sugestao,
    chave_da_linha,
    sugerir_para_linha,
)
from .models import (
    LINE_STATUS_IGNORED,
    LINE_STATUS_NEW,
    LINE_STATUS_RECONCILED,
    STATUS_PROCESSED,
    BankStatementImport,
    BankStatementLine,
)
from .reconciliation import _create_entry_from_locked_line

SALDO_INICIAL = "saldo_inicial"
PAGAMENTO = "pagamento"
PAGAMENTO_SEM_PAR = "pagamento_sem_par"
PARCELA_LANCADA = "parcela_lancada"
PARCELADO_NOVO = "parcelado_novo"
COMPRA_LANCADA = "compra_lancada"
COMPRA_PENDENTE = "compra_pendente"
REALIZACAO_PENDENTE = "realizacao_pendente"
COMPRA = "compra"
ESTORNO = "estorno"

_CRIAM_LANCAMENTO = (PARCELADO_NOVO, COMPRA, ESTORNO)

_JANELA_PAGAMENTO = timedelta(days=10)
_JANELA_PARCELA = timedelta(days=5)
_JANELA_COMPRA = timedelta(days=3)

# "Pag Fatura Boleto" (C6), "Pagamentos Validos Normais" (XP). A fronteira de
# palavra impede "Pague Menos" de virar pagamento.
_PAGAMENTO = re.compile(r"^pag(amentos?)?\b", re.IGNORECASE)
_CATEGORIA_PADRAO = "Outros"
# Chaves das operações que a fatura projetada cria (`fatura_projetada.py`).
PREFIXO_ESTIMATIVA = "cartao-estimativa"
PREFIXO_PAGAMENTO = "cartao-pagamento"


@dataclass
class Plano:
    """O que uma linha da fatura vira."""

    linha: BankStatementLine
    acao: str
    lancamento: CashFlowEntry | None = None
    categoria: CashFlowCategory | None = None
    # De onde veio a categoria sugerida e o quanto confiar nela (ver `classificacao`).
    sugestao: Sugestao | None = None
    # Linha já no saldo inicial que é parcela: a partir de qual parcela criar.
    futuras_a_partir_de: int | None = None
    futuras_vencimento: date | None = None

    @property
    def escolhe_categoria(self) -> bool:
        """Se a prévia pede a categoria desta linha: ela cria lançamento, ou cria as
        parcelas que faltam de uma compra que já está no saldo inicial."""
        return self.cria_lancamento or bool(self.futuras_a_partir_de)

    @property
    def confiavel(self) -> bool:
        return self.sugestao is not None and self.sugestao.confiavel

    @property
    def cria_lancamento(self) -> bool:
        return self.acao in _CRIAM_LANCAMENTO

    @property
    def rotulo(self) -> str:
        linha = self.linha
        if self.acao == SALDO_INICIAL:
            if self.futuras_a_partir_de:
                return gettext(
                    "Já está no saldo inicial; cria as parcelas %(primeira)s a %(total)s a vencer"
                ) % {"primeira": self.futuras_a_partir_de, "total": linha.installment_total}
            return gettext("Já está no saldo inicial")
        if self.acao == PAGAMENTO:
            return gettext("Pagamento: concilia com a transferência de %(data)s") % {
                "data": regional.formatar_data(self.lancamento.due_date),
            }
        if self.acao == PAGAMENTO_SEM_PAR:
            return gettext("Pagamento sem transferência correspondente: fica pendente em Conciliação")
        if self.acao == PARCELA_LANCADA:
            return gettext("Parcela já lançada (vencimento %(data)s)") % {
                "data": regional.formatar_data(self.lancamento.due_date),
            }
        if self.acao == PARCELADO_NOVO:
            return gettext("Compra parcelada nova: cria as parcelas %(atual)s a %(total)s") % {
                "atual": linha.installment_current, "total": linha.installment_total,
            }
        if self.acao == COMPRA_LANCADA:
            return gettext("Compra já lançada em %(data)s: concilia") % {
                "data": regional.formatar_data(self.lancamento.due_date),
            }
        if self.acao == COMPRA_PENDENTE:
            return gettext("Compra com lançamento semelhante: fica pendente em Conciliação para revisão")
        if self.acao == REALIZACAO_PENDENTE:
            return gettext("Lançamento realizado com data ou valor diferente: fica pendente em Conciliação para revisão")
        if self.acao == ESTORNO:
            return gettext("Estorno ou crédito")
        return gettext("Compra")


def eh_pagamento(linha: BankStatementLine) -> bool:
    return linha.amount > 0 and bool(_PAGAMENTO.match(linha.description.strip()))


def _descricoes(linha: BankStatementLine) -> list[str]:
    """A descrição com e sem o portador: a fatura de outro mês pode ter um só."""
    sufixo = f" · {linha.card_holder}" if linha.card_holder else ""
    base = linha.description.removesuffix(sufixo) if sufixo else linha.description
    return [base, f"{base}{sufixo}"] if sufixo else [base]


def _conciliados() -> Q:
    """Lançamentos que já têm linha de extrato conciliada."""
    return Q(statement_matches__status=LINE_STATUS_RECONCILED)


def _mais_perto(candidatos, data: date, usados: set[int], preferir=None) -> CashFlowEntry | None:
    livres = [c for c in candidatos if c.id not in usados]
    if not livres:
        return None
    return min(livres, key=lambda c: (0 if preferir and preferir(c) else 1, abs((c.due_date - data).days), c.id))


def _transferencia(conta, linha, usados) -> CashFlowEntry | None:
    # Lançamento realizado à mão também serve: a conciliação só o vincula.
    candidatos = CashFlowEntry.objects.filter(
        account=conta,
        entry_type=ENTRY_TYPE_INCOME,
        operation_type=OPERATION_INTERNAL_TRANSFER,
        entry_amount=abs(linha.amount),
        due_date__range=(linha.statement_date - _JANELA_PAGAMENTO, linha.statement_date + _JANELA_PAGAMENTO),
    ).exclude(_conciliados())
    return _mais_perto(candidatos, linha.statement_date, usados)


def _parcela(conta, linha, data, usados, *, livres=True) -> CashFlowEntry | None:
    candidatos = CashFlowEntry.objects.filter(
        account=conta,
        entry_type=ENTRY_TYPE_EXPENSE,
        operation_type=OPERATION_INSTALLMENT,
        description__in=_descricoes(linha),
        due_date__range=(data - _JANELA_PARCELA, data + _JANELA_PARCELA),
    )
    if livres:
        candidatos = candidatos.exclude(_conciliados())
    valor = abs(linha.amount)
    return _mais_perto(candidatos, data, usados, preferir=lambda c: c.entry_amount == valor)


def _compra_lancada(conta, linha, usados) -> tuple[CashFlowEntry | None, bool]:
    candidatos = CashFlowEntry.objects.filter(
        account=conta,
        entry_type=ENTRY_TYPE_EXPENSE if linha.amount < 0 else ENTRY_TYPE_INCOME,
        operation_type=OPERATION_SINGLE,
        is_recurring=False,
        entry_amount=abs(linha.amount),
        due_date__range=(linha.statement_date - _JANELA_COMPRA, linha.statement_date + _JANELA_COMPRA),
    ).exclude(_conciliados()).exclude(bank_operation__operation_key__startswith=f"{PREFIXO_ESTIMATIVA}:")
    candidatos = [c for c in candidatos if c.id not in usados]
    descricoes = {" ".join(d.split()).casefold() for d in _descricoes(linha)}
    iguais = [c for c in candidatos if " ".join(c.description.split()).casefold() in descricoes]
    if len(iguais) == 1 and (
        iguais[0].status != STATUS_REALIZED
        or (iguais[0].realized_date == linha.statement_date and iguais[0].realized_amount == abs(linha.amount))
    ):
        return iguais[0], False
    return None, bool(candidatos)


def _sugerir(plano: Plano) -> None:
    # A mesma loja em qualquer conta, a mais frequente entre as que o usuário
    # classificou (nunca "Outros"), e só depois a categoria do banco: ver
    # `classificacao`, que o extrato de conta também usa.
    plano.sugestao = sugerir_para_linha(plano.linha, apenas_gerenciais=True)
    plano.categoria = plano.sugestao.categoria


def planejar(conta: FinancialAccount, linhas) -> list[Plano]:
    """Decide o destino de cada linha nova, sem gravar nada."""
    from reports.services import add_months

    planos: list[Plano] = []
    usados: set[int] = set()
    for linha in sorted(linhas, key=lambda item: (item.statement_date, item.id)):
        plano = Plano(linha=linha, acao=COMPRA)
        antes_do_saldo = linha.statement_date < conta.initial_balance_date
        if antes_do_saldo:
            plano.acao = SALDO_INICIAL
            atual, total = linha.installment_current, linha.installment_total
            # Só as parcelas de depois do saldo inicial: as de antes estão em
            # faturas que ele já cobre.
            primeira = None
            if atual and atual < total:
                primeira = next(
                    (
                        k for k in range(atual + 1, total + 1)
                        if add_months(linha.statement_date, k - atual) >= conta.initial_balance_date
                    ),
                    None,
                )
            if primeira is not None:
                vencimento = add_months(linha.statement_date, primeira - atual)
                if _parcela(conta, linha, vencimento, usados, livres=False) is None:
                    plano.futuras_a_partir_de = primeira
                    plano.futuras_vencimento = vencimento
                    _sugerir(plano)
        elif eh_pagamento(linha):
            plano.lancamento = _transferencia(conta, linha, usados)
            plano.acao = PAGAMENTO if plano.lancamento else PAGAMENTO_SEM_PAR
        elif linha.installment_current and linha.amount < 0:
            plano.lancamento = _parcela(conta, linha, linha.statement_date, usados)
            plano.acao = PARCELA_LANCADA if plano.lancamento else PARCELADO_NOVO
        else:
            plano.lancamento, pendente = _compra_lancada(conta, linha, usados)
            if plano.lancamento:
                plano.acao = COMPRA_LANCADA
            elif pendente:
                plano.acao = COMPRA_PENDENTE
            else:
                plano.acao = ESTORNO if linha.amount > 0 else COMPRA
        if plano.lancamento is not None and plano.lancamento.status == STATUS_REALIZED and (
            plano.lancamento.realized_date != linha.statement_date
            or plano.lancamento.realized_amount != abs(linha.amount)
        ):
            plano.lancamento = None
            plano.acao = REALIZACAO_PENDENTE
        if plano.cria_lancamento:
            _sugerir(plano)
        if plano.lancamento is not None:
            usados.add(plano.lancamento.id)
        planos.append(plano)
    return planos


@dataclass
class Grupo:
    """Linhas a conferir da mesma loja, sinal e sugestão: uma escolha vale para todas.

    A viagem da United numa fatura só eram 25 linhas, uma por bilhete, com a
    mesma resposta. O formulário manda a escolha do grupo (`grupo_<numero>`) e a
    lista das linhas dele (`membros_<numero>`); a linha que tiver escolha
    própria (`categoria_<id>`) fica com a dela."""

    numero: int
    planos: list[Plano]

    @property
    def sugestao(self) -> Sugestao | None:
        return self.planos[0].sugestao

    @property
    def categoria(self) -> CashFlowCategory | None:
        return self.planos[0].categoria

    @property
    def linha(self) -> BankStatementLine:
        return self.planos[0].linha

    @property
    def total(self) -> Decimal:
        return sum((plano.linha.amount for plano in self.planos), Decimal("0.00"))

    @property
    def membros(self) -> str:
        return ",".join(str(plano.linha.id) for plano in self.planos)


@dataclass
class Previa:
    """A prévia na ordem de conferir: primeiro o incerto, agrupado por loja; no fim,
    recolhido, o que tem confiança alta e o que não pede categoria."""

    a_conferir: list[Grupo]
    confiaveis: list[Plano]
    sem_escolha: list[Plano]

    @property
    def linhas_a_conferir(self) -> int:
        return sum(len(grupo.planos) for grupo in self.a_conferir)


_ORDEM_DA_CONFIANCA = {CONFIANCA_NENHUMA: 0, CONFIANCA_BAIXA: 1, CONFIANCA_MEDIA: 2, CONFIANCA_ALTA: 3}


def organizar(planos: list[Plano]) -> Previa:
    """Separa e agrupa os planos para a prévia. Não muda nenhum plano."""
    sem_escolha = [plano for plano in planos if not plano.escolhe_categoria]
    confiaveis = [plano for plano in planos if plano.escolhe_categoria and plano.confiavel]
    grupos: dict[tuple, list[Plano]] = {}
    for plano in planos:
        if plano.escolhe_categoria and not plano.confiavel:
            chave = (
                chave_da_linha(plano.linha.description),
                plano.linha.amount > 0,
                plano.categoria.id if plano.categoria else None,
            )
            grupos.setdefault(chave, []).append(plano)
    ordenados = sorted(
        grupos.values(),
        key=lambda membros: (
            _ORDEM_DA_CONFIANCA[membros[0].sugestao.confianca if membros[0].sugestao else CONFIANCA_NENHUMA],
            membros[0].linha.statement_date,
            membros[0].linha.id,
        ),
    )
    return Previa(
        a_conferir=[Grupo(numero, membros) for numero, membros in enumerate(ordenados, start=1)],
        confiaveis=confiaveis,
        sem_escolha=sem_escolha,
    )


def escolhas_do_formulario(post) -> dict[str, str]:
    """As categorias escolhidas na prévia, por linha: a da própria linha, ou a do
    grupo dela quando a linha ficou em "igual ao grupo"."""
    escolhas = {
        chave.removeprefix("categoria_"): valor
        for chave, valor in post.items()
        if chave.startswith("categoria_") and valor
    }
    for chave, valor in post.items():
        if not chave.startswith("grupo_") or not valor:
            continue
        numero = chave.removeprefix("grupo_")
        for linha_id in post.get(f"membros_{numero}", "").split(","):
            if linha_id.strip():
                escolhas.setdefault(linha_id.strip(), valor)
    return escolhas


@dataclass
class Resumo:
    compras: Decimal
    creditos: Decimal
    pagamentos: Decimal

    @property
    def total_da_fatura(self) -> Decimal:
        """O que a fatura cobra: compras menos estornos, sem os pagamentos."""
        return -(self.compras + self.creditos)


def resumir(linhas) -> Resumo:
    compras = creditos = pagamentos = Decimal("0.00")
    for linha in linhas:
        if linha.amount < 0:
            compras += linha.amount
        elif eh_pagamento(linha):
            pagamentos += linha.amount
        else:
            creditos += linha.amount
    return Resumo(compras=compras, creditos=creditos, pagamentos=pagamentos)


def lote_de_fatura(user, batch_id, action: str = "view") -> BankStatementImport:
    """O lote, se for de cartão e estiver ao alcance de `user`."""
    try:
        lote = BankStatementImport.objects.select_related("account__owner", "account__institution").get(id=batch_id)
    except (BankStatementImport.DoesNotExist, ValueError, TypeError) as exc:
        raise ValueError(gettext("Importação não encontrada.")) from exc
    if not can_access_account(user, lote.account_id, action):
        raise ValueError(gettext("Importação não encontrada."))
    if not lote.account.is_credit_card:
        raise ValueError(gettext("Esta importação não é de um cartão de crédito."))
    return lote


def linhas_novas(lote: BankStatementImport):
    # A conta vem junto: a sugestão de cada linha a consulta (texto genérico).
    return lote.lines.filter(status=LINE_STATUS_NEW).select_related("account").order_by("statement_date", "id")


def categorias_gerenciais():
    return CashFlowCategory.objects.filter(kind=CATEGORY_KIND_MANAGERIAL).order_by("category_name")


def _categoria_escolhida(plano: Plano, escolhas: dict) -> CashFlowCategory:
    escolhida = escolhas.get(str(plano.linha.id)) or escolhas.get(plano.linha.id)
    if escolhida:
        try:
            return CashFlowCategory.objects.get(id=int(escolhida), kind=CATEGORY_KIND_MANAGERIAL)
        except (CashFlowCategory.DoesNotExist, ValueError, TypeError) as exc:
            raise ValueError(gettext("Categoria inválida para “%(descricao)s”.") % {
                "descricao": plano.linha.description,
            }) from exc
    if plano.categoria is None:
        raise ValueError(
            gettext("Sem categoria para “%(descricao)s”: escolha uma ou cadastre “Outros”.") % {
                "descricao": plano.linha.description,
            }
        )
    return plano.categoria


def _conciliar(user, linha: BankStatementLine, lancamento: CashFlowEntry, audit_context) -> None:
    if lancamento.operation_type == OPERATION_INTERNAL_TRANSFER:
        assert_transfer_destination_authorized(user, lancamento, "update")
    assert_entry_period_open(lancamento, action_label="conciliar")
    if lancamento.status != STATUS_REALIZED:
        realize_transaction(
            lancamento,
            realized_date=linha.statement_date,
            realized_amount=abs(linha.amount),
            audit_context=audit_context,
            user=user,
        )
    linha.matched_entry = lancamento
    linha.status = LINE_STATUS_RECONCILED
    linha.save(update_fields=["matched_entry", "status", "updated_at"])


def _criar_parcelas(user, conta, linha, categoria, *, primeira: int, vencimento: date,
                    realizar: bool, audit_context) -> list[CashFlowEntry]:
    valor = abs(linha.amount)
    return create_transaction_batch(
        TransactionRequest(
            account_id=conta.id,
            category_id=categoria.id,
            entry_type=ENTRY_TYPE_EXPENSE,
            description=linha.description,
            entry_amount=valor,
            installments=linha.installment_total,
            due_date=vencimento,
            calc_mode=CALC_REPEAT,
            status=STATUS_REALIZED if realizar else STATUS_PROJECTED,
            realized_date=linha.statement_date if realizar else None,
            realized_amount=valor if realizar else None,
            first_installment=primeira,
        ),
        audit_context=audit_context,
        user=user,
    )


def _meses_tocados(planos) -> set[tuple[int, int]]:
    """Os meses em que o processamento cria, realiza ou concilia lançamento."""
    from reports.services import add_months

    datas: list[date] = []
    for plano in planos:
        linha = plano.linha
        if plano.acao == SALDO_INICIAL:
            if plano.futuras_a_partir_de:
                restantes = linha.installment_total - plano.futuras_a_partir_de + 1
                datas += [add_months(plano.futuras_vencimento, k) for k in range(restantes)]
            continue
        if plano.acao in (PAGAMENTO_SEM_PAR, COMPRA_PENDENTE, REALIZACAO_PENDENTE):
            continue
        datas.append(linha.statement_date)
        if plano.lancamento is not None:
            datas += [d for d in (plano.lancamento.due_date, plano.lancamento.realized_date) if d]
        if plano.acao == PARCELADO_NOVO:
            restantes = linha.installment_total - linha.installment_current + 1
            datas += [add_months(linha.statement_date, k) for k in range(restantes)]
    return {(d.year, d.month) for d in datas}


def meses_fechados(conta: FinancialAccount, planos) -> list[AccountMonthClose]:
    """Os fechamentos do cartão que o processamento precisa reabrir.

    A fatura quase sempre atravessa dois meses: a de outubro traz as compras de
    meados de setembro em diante, e setembro pode já estar fechado. O mês só
    fica completo, no cartão, quando chega a fatura seguinte. Reabre-se o
    primeiro mês fechado que a fatura toca e todos os fechados depois dele,
    porque o saldo de fechamento é acumulado."""
    tocados = _meses_tocados(planos)
    fechados = list(AccountMonthClose.objects.filter(account=conta, active=True).order_by("year", "month"))
    atingidos = [(f.year, f.month) for f in fechados if (f.year, f.month) in tocados]
    if not atingidos:
        return []
    primeiro = min(atingidos)
    return [f for f in fechados if (f.year, f.month) >= primeiro]


MOTIVO_DA_REABERTURA = "Fatura do cartão com compras em mês fechado"


def processar(user, batch_id, escolhas: dict, audit_context=None, *, autorizar_meses: bool = False) -> dict[str, int]:
    """Aplica o plano às linhas novas do lote, tudo ou nada.

    `escolhas` mapeia o id da linha para o id da categoria escolhida na prévia;
    linha sem escolha usa a sugerida. Devolve a contagem por ação.

    Quando a fatura toca mês fechado do cartão (ver `meses_fechados`), só
    processa com `autorizar_meses`: reabre esses meses, grava e fecha de novo
    com o saldo que a fatura deixou. O saldo de fechamento muda, de propósito:
    a fatura é a verdade sobre o mês, e o fechamento anterior não tinha as
    compras que só ela trouxe.
    """
    lote = lote_de_fatura(user, batch_id, "update")
    conta = lote.account
    if not can_access_account(user, conta.id, "create"):
        raise ValueError(gettext("Acesso negado: você não tem permissão para lançar neste cartão."))

    contagem: dict[str, int] = {}
    with db_transaction.atomic():
        linhas = list(linhas_novas(lote).select_for_update())
        if not linhas:
            raise ValueError(gettext("Esta fatura não tem linhas pendentes."))
        planos = planejar(conta, linhas)
        fechamentos = meses_fechados(conta, planos)
        if fechamentos:
            if not autorizar_meses:
                raise ValueError(gettext(
                    "A fatura tem lançamentos em mês fechado do cartão (%(meses)s): autorize a reabertura "
                    "e o novo fechamento para processá-la."
                ) % {"meses": ", ".join(f"{f.month:02d}/{f.year}" for f in fechamentos)})
            if not has_function_permission(user, "settings.monthly_close.manage"):
                raise ValueError(gettext("Reabrir mês fechado exige a permissão de fechamento mensal."))
            for fechamento in fechamentos:
                reopen_month(conta, fechamento.year, fechamento.month, MOTIVO_DA_REABERTURA, user,
                             audit_context=audit_context)
        for plano in planos:
            linha = plano.linha
            if plano.acao == SALDO_INICIAL:
                if plano.futuras_a_partir_de:
                    _criar_parcelas(
                        user, conta, linha, _categoria_escolhida(plano, escolhas),
                        primeira=plano.futuras_a_partir_de,
                        vencimento=plano.futuras_vencimento,
                        realizar=False, audit_context=audit_context,
                    )
                linha.status = LINE_STATUS_IGNORED
                linha.save(update_fields=["status", "updated_at"])
            elif plano.acao in (PAGAMENTO, PARCELA_LANCADA, COMPRA_LANCADA):
                _conciliar(user, linha, plano.lancamento, audit_context)
            elif plano.acao == PARCELADO_NOVO:
                criadas = _criar_parcelas(
                    user, conta, linha, _categoria_escolhida(plano, escolhas),
                    primeira=linha.installment_current, vencimento=linha.statement_date,
                    realizar=True, audit_context=audit_context,
                )
                linha.matched_entry = criadas[0]
                linha.status = LINE_STATUS_RECONCILED
                linha.save(update_fields=["matched_entry", "status", "updated_at"])
            elif plano.acao in (COMPRA, ESTORNO):
                _create_entry_from_locked_line(
                    user, line=linha, category_id=_categoria_escolhida(plano, escolhas).id,
                    audit_context=audit_context,
                )
            contagem[plano.acao] = contagem.get(plano.acao, 0) + 1

        if not linhas_novas(lote).exists():
            lote.status = STATUS_PROCESSED
            lote.save(update_fields=["status", "updated_at"])

        # A fatura nova muda a base da estimativa e as parcelas do ciclo.
        from .fatura_projetada import atualizar

        atualizar(conta)
        for fechamento in fechamentos:
            # `None`: o saldo é calculado depois de trancar a conta, já com a fatura.
            close_month(conta, fechamento.year, fechamento.month, None, user, audit_context=audit_context)
    return contagem
