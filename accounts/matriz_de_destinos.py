"""Matriz Usuário × conta destino de transferência, derivada do histórico.

A concessão `UserTransferDestinationAccess` é explícita, e o rollout dela não
distribuiu nada (docs/operations.md): o que existe veio de ajustes manuais, e o
histórico de transferências é maior do que a matriz. Esta regra reconstrói o que
cada pessoa precisa a partir das transferências que já existem:

    quem tem acesso de criação (por titular) à conta de ORIGEM de uma
    transferência existente pode usar como destino a conta que a recebeu.

Só acrescenta. Concessão que já existe nunca é retirada (retirar é decisão do
administrador, na tela de Permissões), e conta que nunca recebeu transferência
de uma origem do usuário não é concedida: "poder criar na origem" não vira
"poder enviar para qualquer lugar".
"""
from __future__ import annotations

from collections import defaultdict

from django.db import transaction

from accounts.models import AppUser, UserOwnerAccess, UserTransferDestinationAccess
from accounts.services import transfer_destination_access_ids
from banking.models import FinancialAccount
from core.domain.finance import OPERATION_INTERNAL_TRANSFER
from transactions.models import CashFlowEntry


def pares_existentes() -> set[tuple[int, int]]:
    """Pares (conta de origem, conta de destino) das transferências já lançadas."""
    pontas = (
        CashFlowEntry.objects.filter(operation_type=OPERATION_INTERNAL_TRANSFER)
        .exclude(source_entry__isnull=True)
        .values_list("source_entry__account_id", "account_id")
    )
    return {(origem, destino) for origem, destino in pontas if origem != destino}


def propor() -> dict[AppUser, set[int]]:
    """Para cada usuário ativo, os destinos que a matriz deveria ter e ainda não tem."""
    pares = pares_existentes()
    dono_da_conta = dict(FinancialAccount.objects.values_list("id", "owner_id"))
    destinos_por_dono: dict[int, set[int]] = defaultdict(set)
    for origem, destino in pares:
        destinos_por_dono[dono_da_conta[origem]].add(destino)

    faltando: dict[AppUser, set[int]] = {}
    for usuario in AppUser.objects.filter(is_active=True).order_by("id"):
        # Só o acesso registrado por titular: o acesso amplo do administrador
        # não vira concessão (conta de teste sem titular não ganha destino).
        necessarios: set[int] = set()
        donos = UserOwnerAccess.objects.filter(user=usuario, can_create=True).values_list("owner_id", flat=True)
        for dono_id in donos:
            necessarios |= destinos_por_dono.get(dono_id, set())
        novos = necessarios - transfer_destination_access_ids(usuario)
        if novos:
            faltando[usuario] = novos
    return faltando


def aplicar(proposta: dict[AppUser, set[int]]) -> int:
    """Grava a proposta (tudo ou nada) e audita cada usuário; devolve quantas concessões criou."""
    from core.services import log_audit_event

    total = 0
    with transaction.atomic():
        for usuario, novos in proposta.items():
            antes = sorted(transfer_destination_access_ids(usuario))
            UserTransferDestinationAccess.objects.bulk_create(
                [UserTransferDestinationAccess(user=usuario, destination_account_id=i) for i in sorted(novos)],
                ignore_conflicts=True,
            )
            log_audit_event(
                "app_user_transfer_destination_access", usuario.id, "update",
                old_values={"account_ids": antes},
                new_values={"account_ids": sorted(transfer_destination_access_ids(usuario))},
                summary="Matriz de destinos completada a partir do histórico de transferências.",
            )
            total += len(novos)
    return total
