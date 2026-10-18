"""Grava o dado de investimento lido da descrição (`investimentos.interpretar`).

Dois caminhos, uma só regra de gravação (`gravar`):

* **lançamento novo**: o sinal `post_save` de `BankStatementLine` (ligado em
  `apps.py`) preenche o lançamento no instante em que uma linha de extrato de
  qualquer adaptador passa a conciliada com ele. Ficar no vínculo, e não em cada
  tela, cobre criar lançamento a partir da linha, conciliar com um existente, o
  motor do extrato e as transferências, sem ninguém precisar lembrar;
* **lançamento existente**: `preencher_existentes`, usado pelo comando
  `preencher_investimentos`, que lista (simulação) ou grava.

Idempotente: rodar de novo não muda nada, e só se grava o que a descrição diz.
Quem não casa com nenhuma regra não ganha linha. Uma linha já gravada nunca é
apagada por uma descrição que deixou de casar: o dado é só acréscimo.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from transactions.models import CashFlowEntry, EntryInvestmentDetail

from .investimentos import Detalhe, interpretar
from .models import LINE_STATUS_RECONCILED, BankStatementLine

_CAMPOS = ("instrument_code", "income_kind", "income_role", "settlement_pregao_date", "settlement_note")

CRIAR = "criar"
ATUALIZAR = "atualizar"


@dataclass(frozen=True)
class Mudanca:
    entry_id: int
    acao: str
    descricao: str
    antes: Detalhe | None
    depois: Detalhe


def _do_modelo(detalhe: EntryInvestmentDetail | None) -> Detalhe | None:
    if detalhe is None:
        return None
    return Detalhe(**{campo: getattr(detalhe, campo) for campo in _CAMPOS})


def acao_necessaria(atual: Detalhe | None, novo: Detalhe) -> str | None:
    """`criar`, `atualizar` ou `None` quando a linha já diz o mesmo."""
    if atual is None:
        return CRIAR
    return None if atual == novo else ATUALIZAR


def gravar(entry_id: int, detalhe: Detalhe) -> str | None:
    """Cria ou atualiza a linha do lançamento; devolve a ação feita (ou `None`)."""
    existente = EntryInvestmentDetail.objects.filter(entry_id=entry_id).first()
    acao = acao_necessaria(_do_modelo(existente), detalhe)
    if acao is None:
        return None
    valores = {campo: getattr(detalhe, campo) for campo in _CAMPOS}
    if existente is None:
        EntryInvestmentDetail.objects.create(entry_id=entry_id, **valores)
    else:
        for campo, valor in valores.items():
            setattr(existente, campo, valor)
        existente.save(update_fields=[*_CAMPOS, "updated_at"])
    return acao


def preencher_da_linha(sender, instance: BankStatementLine, **kwargs) -> None:
    """`post_save` da linha: lançamento recém-conciliado ganha o dado da descrição."""
    if instance.status != LINE_STATUS_RECONCILED or instance.matched_entry_id is None:
        return
    detalhe = interpretar(instance.description)
    if detalhe is not None and not detalhe.vazio:
        gravar(instance.matched_entry_id, detalhe)


def _interpretar_lancamento(entry: CashFlowEntry, descricoes_do_extrato: list[str]) -> Detalhe | None:
    """O que o lançamento diz; na falta, o que diz o extrato conciliado com ele."""
    for texto in (entry.description, *descricoes_do_extrato):
        detalhe = interpretar(texto)
        if detalhe is not None and not detalhe.vazio:
            return detalhe
    return None


def preencher_existentes(*, aplicar: bool, queryset=None) -> Iterator[Mudanca]:
    """Percorre os lançamentos e devolve (e, se `aplicar`, grava) o que mudaria.

    Qualquer conta entra; só os que casam com as regras recebem campos.
    """
    lancamentos = (queryset if queryset is not None else CashFlowEntry.objects.all()).select_related(
        "investment_detail"
    ).prefetch_related("statement_matches").order_by("id")
    for entry in lancamentos.iterator(chunk_size=500):
        descricoes = [
            linha.description for linha in entry.statement_matches.all()
            if linha.status == LINE_STATUS_RECONCILED
        ]
        novo = _interpretar_lancamento(entry, descricoes)
        if novo is None:
            continue
        atual = _do_modelo(getattr(entry, "investment_detail", None))
        acao = acao_necessaria(atual, novo)
        if acao is None:
            continue
        if aplicar:
            gravar(entry.id, novo)
        yield Mudanca(entry_id=entry.id, acao=acao, descricao=entry.description, antes=atual, depois=novo)
