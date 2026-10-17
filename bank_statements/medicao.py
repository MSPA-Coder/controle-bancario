"""Medição da sugestão de categoria contra o que o usuário decidiu (`medir_sugestoes`).

É o teste retroativo que embasou os níveis de confiança (17/10/2026), mantido
no sistema para medir cada mudança com os mesmos números. Para cada linha de
extrato conciliada com um lançamento gerencial (ou movimentação, em conta), a
sugestão é refeita **só com o histórico de antes do mês da linha**
(`antes_de`) e comparada com a categoria que o lançamento tem hoje, depois de
todas as correções. "Outros" final fica de fora: o usuário ainda não decidiu.
Compra parcelada conta uma vez (a primeira linha).

Duas populações: todas as linhas avaliadas, e as que precisaram de lançamento
novo (o lançamento nasceu depois da linha). A segunda é onde a sugestão é usada
de verdade; na primeira, a linha casou com um lançamento que já existia.

Também lista os **suspeitos**: lançamentos cuja categoria contradiz a da mesma
loja ou a da categoria do banco. Eles ensinam errado as próximas sugestões e se
corrigem em Bancos > Reclassificação. Nada aqui grava.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from core.domain.finance import (
    CATEGORY_KIND_MANAGERIAL,
    CATEGORY_KIND_MOVEMENT,
    OPERATION_INSTALLMENT,
)
from transactions.models import CashFlowCategory, CashFlowEntry

from .classificacao import (
    CATEGORIA_PADRAO,
    Sugestao,
    chave_da_linha,
    eh_generica,
    eh_intermediador,
    sugerir_para_linha,
)
from .models import LINE_STATUS_RECONCILED, RULE_ACTION_CATEGORY, BankStatementLine
from .regras import Regras

# Mesma loja: a maioria precisa de base (3 compras) e de folga (70%) para a
# minoria parecer erro, e não uma loja que vende duas coisas.
_MINIMO_DA_LOJA = 3
_MAIORIA_DA_LOJA = (7, 10)
# Categoria do banco: mais base e mais folga, porque ela é mais grosseira.
_MINIMO_DO_BANCO = 10
_MAIORIA_DO_BANCO = (9, 10)


@dataclass(frozen=True)
class Caso:
    linha: BankStatementLine
    verdade: CashFlowCategory
    sugestao: Sugestao
    # O lançamento nasceu da linha: a sugestão foi usada para criá-lo.
    lancamento_novo: bool

    @property
    def acertou(self) -> bool:
        return self.sugestao.categoria is not None and self.sugestao.categoria.id == self.verdade.id

    @property
    def cartao(self) -> bool:
        return self.linha.account.is_credit_card


def _inicio_do_mes(dia: date) -> date:
    return dia.replace(day=1)


def _tipos(cartao: bool) -> tuple[str, ...]:
    return (CATEGORY_KIND_MANAGERIAL,) if cartao else (CATEGORY_KIND_MANAGERIAL, CATEGORY_KIND_MOVEMENT)


def casos(*, desde: date | None = None, ate: date | None = None) -> list[Caso]:
    """As linhas avaliáveis, cada uma com a sugestão que teria recebido."""
    linhas = (
        BankStatementLine.objects.filter(status=LINE_STATUS_RECONCILED, matched_entry__isnull=False)
        .exclude(matched_entry__category__category_name__iexact=CATEGORIA_PADRAO)
        .select_related("account__institution", "matched_entry__category")
        .order_by("statement_date", "id")
    )
    if desde is not None:
        linhas = linhas.filter(statement_date__gte=desde)
    if ate is not None:
        linhas = linhas.filter(statement_date__lte=ate)
    regras = Regras()
    vistas: set = set()
    resultado: list[Caso] = []
    for linha in linhas:
        entrada = linha.matched_entry
        cartao = linha.account.is_credit_card
        if entrada.category.kind not in _tipos(cartao):
            continue
        compra = (
            ("operacao", entrada.bank_operation_id)
            if entrada.operation_type == OPERATION_INSTALLMENT and entrada.bank_operation_id
            else ("lancamento", entrada.id)
        )
        if compra in vistas:
            continue
        vistas.add(compra)
        regra = None if cartao else regras.da_linha(linha)
        if regra is not None and regra.action != RULE_ACTION_CATEGORY:
            regra = None
        sugestao = sugerir_para_linha(
            linha, regra=regra, apenas_gerenciais=cartao, antes_de=_inicio_do_mes(linha.statement_date)
        )
        novo = entrada.created_at is not None and linha.created_at is not None and entrada.created_at >= linha.created_at
        resultado.append(Caso(linha, entrada.category, sugestao, novo))
    return resultado


@dataclass(frozen=True)
class Taxa:
    total: int
    certos: int

    @property
    def fracao(self) -> float | None:
        return self.certos / self.total if self.total else None


def taxa(selecionados) -> Taxa:
    selecionados = list(selecionados)
    return Taxa(len(selecionados), sum(1 for caso in selecionados if caso.acertou))


@dataclass(frozen=True)
class Esforco:
    pedem_categoria: int
    a_conferir: int
    decisoes: int


def esforco(selecionados) -> Esforco:
    """Quanto o usuário confere: as linhas sem confiança alta, e quantas decisões
    elas viram com a prévia da fatura agrupando a mesma loja do mesmo lote (a
    conciliação de conta não agrupa: cada linha é uma decisão)."""
    selecionados = list(selecionados)
    incertos = [caso for caso in selecionados if not caso.sugestao.confiavel]
    grupos = set()
    soltos = 0
    for caso in incertos:
        if caso.cartao:
            categoria = caso.sugestao.categoria.id if caso.sugestao.categoria else None
            grupos.add((caso.linha.import_batch_id, chave_da_linha(caso.linha.description), caso.linha.amount > 0, categoria))
        else:
            soltos += 1
    return Esforco(len(selecionados), len(incertos), len(grupos) + soltos)


@dataclass(frozen=True)
class Suspeito:
    lancamento: CashFlowEntry
    texto: str
    esperada: CashFlowCategory
    iguais: int
    total: int
    motivo: str  # "loja" ou "banco"
    bank_category: str = ""


def _maioria(contagem: Counter, total: int, numerador: int, denominador: int):
    if not contagem:
        return None, 0
    categoria_id, iguais = contagem.most_common(1)[0]
    if iguais * denominador < total * numerador:
        return None, 0
    return categoria_id, iguais


def suspeitos(*, limite: int = 30) -> list[Suspeito]:
    """Lançamentos que destoam da mesma loja ou da categoria do banco."""
    texto_do_banco = dict(
        BankStatementLine.objects.filter(status=LINE_STATUS_RECONCILED, matched_entry__isnull=False)
        .order_by("id")
        .values_list("matched_entry_id", "description")
    )
    lancamentos = (
        CashFlowEntry.objects.filter(category__kind=CATEGORY_KIND_MANAGERIAL)
        .exclude(category__category_name__iexact=CATEGORIA_PADRAO)
        .select_related("category", "account")
        .order_by("due_date", "id")
    )
    por_compra: dict = {}
    for entrada in lancamentos:
        compra = (
            ("operacao", entrada.bank_operation_id)
            if entrada.operation_type == OPERATION_INSTALLMENT and entrada.bank_operation_id
            else ("lancamento", entrada.id)
        )
        por_compra.setdefault(compra, entrada)
    categorias = {categoria.id: categoria for categoria in CashFlowCategory.objects.all()}
    achados: list[Suspeito] = []

    por_loja: dict = defaultdict(list)
    for entrada in por_compra.values():
        texto = texto_do_banco.get(entrada.id) or entrada.description or ""
        if eh_generica(texto) or eh_intermediador(texto):
            continue
        por_loja[(chave_da_linha(texto), entrada.entry_type)].append((entrada, texto))
    for membros in por_loja.values():
        if len(membros) < _MINIMO_DA_LOJA:
            continue
        contagem = Counter(entrada.category_id for entrada, _ in membros)
        esperada, iguais = _maioria(contagem, len(membros), *_MAIORIA_DA_LOJA)
        if esperada is None:
            continue
        for entrada, texto in membros:
            if entrada.category_id != esperada:
                achados.append(Suspeito(entrada, texto, categorias[esperada], iguais, len(membros), "loja"))

    por_banco: dict = defaultdict(list)
    linhas_do_cartao = (
        BankStatementLine.objects.filter(
            status=LINE_STATUS_RECONCILED,
            matched_entry__category__kind=CATEGORY_KIND_MANAGERIAL,
            account__account_kind="cartao_credito",
        )
        .exclude(bank_category="")
        .exclude(matched_entry__category__category_name__iexact=CATEGORIA_PADRAO)
        .select_related("matched_entry__category", "matched_entry__account")
    )
    ja = {suspeito.lancamento.id for suspeito in achados}
    for linha in linhas_do_cartao:
        por_banco[linha.bank_category].append(linha)
    for bank_category, membros in por_banco.items():
        if len(membros) < _MINIMO_DO_BANCO:
            continue
        contagem = Counter(linha.matched_entry.category_id for linha in membros)
        esperada, iguais = _maioria(contagem, len(membros), *_MAIORIA_DO_BANCO)
        if esperada is None:
            continue
        for linha in membros:
            entrada = linha.matched_entry
            if entrada.category_id != esperada and entrada.id not in ja:
                ja.add(entrada.id)
                achados.append(
                    Suspeito(entrada, linha.description, categorias[esperada], iguais, len(membros), "banco", bank_category)
                )
    achados.sort(key=lambda suspeito: (suspeito.lancamento.due_date, suspeito.lancamento.id), reverse=True)
    return achados[:limite]
