"""Reclassifica a marcação a mercado antiga de "Rendimentos" para "Variação de mercado".

Até 21/10/2026 a atualização de saldo de Tesouro, renda fixa e caixa em dólar
entrava como "Rendimentos" (gerencial): um papel que caiu 5% aparecia como
despesa do mês. Agora é variação de mercado (`valorizacao`), que muda o saldo e
não é receita nem despesa. Esta rotina move para a categoria nova o que já foi
lançado, e **só** a categoria muda: valor, data, conta e status ficam como
estão, então o saldo de cada conta e de cada mês é idêntico antes e depois.

Duas travas: só toca lançamento que está em "Rendimentos" **e** cuja descrição
diz "marcação a mercado" (o texto que a Atualização de saldo grava). Mês-conta
fechado só é reaberto com autorização, e fecha de novo com o saldo conferido.
Tudo ou nada, com auditoria de cada troca.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils.translation import gettext

from accounts.services import has_function_permission
from banking.services import accessible_account_ids
from core.domain.finance import CATEGORY_KIND_MANAGERIAL, CATEGORY_KIND_VALUATION, ENTRY_TYPE_INCOME
from reports.services import VIEW_REALIZED, decimal_balance_before
from transactions.models import (
    AccountMonthClose,
    CashFlowCategory,
    CashFlowCategoryGroup,
    CashFlowEntry,
)
from transactions.services import close_month, reopen_month

from .saldo import CATEGORIA_DE_VARIACAO

CATEGORIA_DE_ORIGEM = "Rendimentos"
TRECHO_DA_DESCRICAO = "marcação a mercado"
GRUPO = "Investimentos"
MOTIVO_DA_REABERTURA = "Reclassificação da marcação a mercado para variação de mercado"


@dataclass
class Efeito:
    entradas: list[CashFlowEntry] = field(default_factory=list)
    categoria_nova: bool = False
    meses_fechados: list[tuple] = field(default_factory=list)

    @property
    def total_assinado(self) -> Decimal:
        """Quanto as entradas somam no saldo (receita +, despesa −), por conta e moeda misturadas: só indicativo."""
        return sum(
            ((e.realized_amount or e.entry_amount) * (1 if e.entry_type == ENTRY_TYPE_INCOME else -1)
             for e in self.entradas),
            Decimal("0.00"),
        )


def _candidatos(user):
    return (
        CashFlowEntry.objects.filter(
            account_id__in=accessible_account_ids(user, "update"),
            category__category_name=CATEGORIA_DE_ORIGEM,
            category__kind=CATEGORY_KIND_MANAGERIAL,
            description__icontains=TRECHO_DA_DESCRICAO,
        )
        .select_related("account", "category")
        .order_by("account_id", "due_date", "id")
    )


def _meses_fechados(entradas) -> list[tuple]:
    meses = sorted({
        (e.account_id, d.year, d.month) for e in entradas for d in (e.due_date, e.realized_date) if d
    })
    if not meses:
        return []
    fechados = {
        (f.account_id, f.year, f.month): f.account
        for f in AccountMonthClose.objects.filter(
            active=True, account_id__in={m[0] for m in meses}
        ).select_related("account")
    }
    return [(fechados[m], m[1], m[2]) for m in meses if m in fechados]


def simular(user) -> Efeito:
    """O que a reclassificação tocaria, sem gravar nada."""
    entradas = list(_candidatos(user))
    existente = CashFlowCategory.objects.filter(
        category_name=CATEGORIA_DE_VARIACAO, kind=CATEGORY_KIND_VALUATION
    ).exists()
    return Efeito(entradas=entradas, categoria_nova=not existente, meses_fechados=_meses_fechados(entradas))


def _categoria_de_destino() -> CashFlowCategory:
    categoria = CashFlowCategory.objects.filter(category_name__iexact=CATEGORIA_DE_VARIACAO).first()
    if categoria is None:
        grupo = CashFlowCategoryGroup.objects.filter(group_name=GRUPO).first()
        return CashFlowCategory.objects.create(
            category_name=CATEGORIA_DE_VARIACAO, kind=CATEGORY_KIND_VALUATION, group=grupo
        )
    if categoria.kind != CATEGORY_KIND_VALUATION:
        raise ValueError(gettext(
            "A categoria \"%(nome)s\" existe e não é do tipo variação de mercado; corrija-a antes."
        ) % {"nome": categoria.category_name})
    return categoria


def aplicar(user, *, autorizar_meses: bool = False, audit_context=None) -> int:
    """Grava a reclassificação, tudo ou nada. Devolve quantos lançamentos mudaram."""
    from core.services import log_audit_event

    with db_transaction.atomic():
        entradas = list(_candidatos(user))
        if not entradas:
            return 0
        fechados = _meses_fechados(entradas)
        if fechados:
            if not autorizar_meses:
                raise ValueError(
                    gettext("Há meses fechados entre os lançamentos: autorize a reabertura e o novo fechamento.")
                )
            if not has_function_permission(user, "settings.monthly_close.manage"):
                raise ValueError(gettext("Reabrir mês fechado exige a permissão de fechamento mensal."))
        destino = _categoria_de_destino()

        saldos = {}
        for conta, ano, mes in fechados:
            fechamento = AccountMonthClose.objects.get(account=conta, year=ano, month=mes, active=True)
            saldos[(conta.id, ano, mes)] = (conta, fechamento.closing_balance)
            reopen_month(conta, ano, mes, MOTIVO_DA_REABERTURA, user, audit_context=audit_context)

        for entrada in entradas:
            anterior = entrada.category
            entrada.category = destino
            entrada.save(update_fields=["category", "updated_at"])
            log_audit_event(
                "cash_flow_entry", entrada.id, "update",
                old_values={"category": anterior.category_name},
                new_values={"category": destino.category_name},
                user=user, request_context=audit_context,
                summary="Marcação a mercado reclassificada como variação de mercado.",
            )

        for (conta_id, ano, mes), (conta, anterior) in saldos.items():
            fim = date(ano + (mes == 12), mes % 12 + 1, 1)
            novo = decimal_balance_before([conta_id], fim, VIEW_REALIZED)
            if novo != anterior:
                raise ValueError(gettext(
                    "O saldo de fechamento de %(mes)02d/%(ano)s (%(conta)s) mudaria de %(anterior)s para %(novo)s; "
                    "nada foi gravado."
                ) % {"mes": mes, "ano": ano, "conta": conta, "anterior": anterior, "novo": novo})
            close_month(conta, ano, mes, novo, user, audit_context=audit_context)
    return len(entradas)
