"""Linhas de extrato que podem ser a mesma transação importada duas vezes.

Reimportar um período já importado é seguro quando o banco repete a linha igual:
o hash a reconhece (`bank_statements.adapters.line_hash`). O que escapa é a mesma
transação com outra cara na segunda exportação -- "agendado" que virou
"efetivado", a data de lançamento no lugar da data da compra. Aí ela entra duas
vezes, e o saldo do arquivo é que acaba denunciando.

O sinal procurado aqui: mesma conta, mesmo valor, até `JANELA_DIAS` de distância,
descrições diferentes e lotes diferentes (no mesmo lote, duas linhas parecidas
são dois movimentos que o banco mesmo listou). Linha ignorada não conta. O par que
o usuário disse não ser duplicata fica em `DuplicataDescartada` e não volta.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction
from django.utils.translation import gettext

from bank_statements.models import LINE_STATUS_IGNORED, BankStatementLine
from banking.services import accessible_account_ids, can_access_account

from .models import DuplicataDescartada

JANELA_DIAS = 2
LIMITE = 20


@dataclass(frozen=True)
class Par:
    a: BankStatementLine
    b: BankStatementLine

    @property
    def chave(self) -> str:
        return f"{self.a.id}-{self.b.id}"


def _descricao(linha: BankStatementLine) -> str:
    return " ".join(linha.description.lower().split())


def possiveis(user, inicio: date, fim: date) -> list[Par]:
    ids = accessible_account_ids(user, "view")
    if not ids:
        return []
    linhas = list(
        BankStatementLine.objects.filter(account_id__in=ids, statement_date__gte=inicio, statement_date__lte=fim)
        .exclude(status=LINE_STATUS_IGNORED)
        .select_related("account__institution", "account__owner")
        .order_by("account_id", "amount", "statement_date", "id")
    )
    por_valor: dict[tuple, list[BankStatementLine]] = defaultdict(list)
    for linha in linhas:
        por_valor[(linha.account_id, linha.amount)].append(linha)
    descartados = set(
        DuplicataDescartada.objects.filter(linha_a__account_id__in=ids).values_list("linha_a_id", "linha_b_id")
    )
    pares: list[Par] = []
    for grupo in por_valor.values():
        for i, primeira in enumerate(grupo):
            for segunda in grupo[i + 1:]:
                if (segunda.statement_date - primeira.statement_date).days > JANELA_DIAS:
                    break
                if primeira.import_batch_id == segunda.import_batch_id:
                    continue
                if _descricao(primeira) == _descricao(segunda):
                    continue
                a, b = sorted((primeira, segunda), key=lambda linha: linha.id)
                if (a.id, b.id) in descartados:
                    continue
                pares.append(Par(a, b))
                if len(pares) >= LIMITE:
                    return pares
    return pares


def descartar(user, chave: str) -> None:
    """Registra que o par `"<id>-<id>"` não é duplicata."""
    try:
        ids = sorted(int(parte) for parte in str(chave).split("-"))
    except ValueError as exc:
        raise ValueError(gettext("Par de linhas inválido.")) from exc
    if len(ids) != 2 or ids[0] == ids[1]:
        raise ValueError(gettext("Par de linhas inválido."))
    linhas = {linha.id: linha for linha in BankStatementLine.objects.filter(id__in=ids)}
    if len(linhas) != 2 or not all(can_access_account(user, linha.account_id, "view") for linha in linhas.values()):
        raise ValueError(gettext("Par de linhas inválido."))
    try:
        with transaction.atomic():
            DuplicataDescartada.objects.create(linha_a_id=ids[0], linha_b_id=ids[1], descartada_por=user)
    except IntegrityError:
        pass  # já descartado: o pedido repetido não muda nada
