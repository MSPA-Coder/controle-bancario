"""O rótulo "Conta Origem: ..." / "Conta Destino: ..." das transferências.

Cada ponta de uma transferência guarda, na descrição, o nome da conta da outra
ponta ("Conta Destino: Mariano / C6 / Conta 02"). O texto é escrito uma vez, ao
criar a transferência; renomear o titular, a instituição ou a conta o deixava
com o nome antigo, e a mesma conta passava a aparecer com dois ou três nomes
nas listas. Em outubro de 2026 os titulares foram renomeados duas vezes e cem
transferências ficaram com nomes que não existiam mais.

Por isso o rótulo acompanha o cadastro: `atualizar_rotulos` é chamado por quem
renomeia e refaz o texto das pontas que apontam para as contas renomeadas.

- Só muda descrição que **o sistema escreveu** (começa por um dos dois
  prefixos). Texto que o usuário digitou numa transferência fica como está.
- Vale também em **mês fechado**. O fechamento protege valores, datas e
  conciliações; o rótulo é o nome atual de uma conta, não um fato do período,
  e trocá-lo não move saldo. A troca vai para a auditoria, num registro só.
- A outra ponta é a do vínculo `source_entry`, nos dois sentidos. Ponta sem par
  único fica como está, em vez de receber um nome adivinhado.
"""
from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from core.domain.finance import CATEGORY_KIND_TRANSFER, ENTRY_TYPE_EXPENSE
from transactions.models import CashFlowEntry

PREFIXO_DESTINO = "Conta Destino: "
PREFIXO_ORIGEM = "Conta Origem: "


def rotulo_da_conta(account) -> str:
    """ "Titular / Instituição / Conta", sem as partes que faltarem."""
    if not account:
        return ""
    titular = account.owner.name if account.owner_id else ""
    instituicao = account.institution.institution_name if account.institution_id else ""
    return " / ".join(p for p in (titular, instituicao, account.account_name) if p)


def rotulo_da_ponta(entrada, conta_da_outra_ponta) -> str:
    """A descrição que o sistema dá a uma ponta de transferência."""
    return rotulo_por_tipo(entrada.entry_type, conta_da_outra_ponta)


def rotulo_por_tipo(entry_type: str, conta_da_outra_ponta) -> str:
    """O mesmo rótulo, para a ponta que ainda não existe: a despesa diz para onde
    o dinheiro foi; a receita, de onde veio."""
    prefixo = PREFIXO_DESTINO if entry_type == ENTRY_TYPE_EXPENSE else PREFIXO_ORIGEM
    return f"{prefixo}{rotulo_da_conta(conta_da_outra_ponta)}"[:255]


def _escrita_pelo_sistema(descricao: str) -> bool:
    return descricao.startswith((PREFIXO_DESTINO, PREFIXO_ORIGEM))


def atualizar_rotulos(account_ids, *, user=None, motivo: str = "") -> int:
    """Refaz o rótulo das pontas cuja outra ponta está numa das `account_ids`.

    Devolve quantas descrições mudaram. `account_ids=None` revê todas as
    transferências (correção dos dados já existentes)."""
    from core.services import log_audit_event

    transferencias = CashFlowEntry.objects.filter(category__kind=CATEGORY_KIND_TRANSFER)
    filhas = transferencias.filter(source_entry__isnull=False, source_entry__category__kind=CATEGORY_KIND_TRANSFER)
    if account_ids is not None:
        ids = list(account_ids)
        filhas = filhas.filter(Q(account_id__in=ids) | Q(source_entry__account_id__in=ids))
    filhas = filhas.select_related(
        "account__owner", "account__institution",
        "source_entry__account__owner", "source_entry__account__institution",
    )

    pares: dict[int, list] = {}
    for filha in filhas:
        mae = filha.source_entry
        pares.setdefault(filha.id, []).append((filha, mae.account))
        pares.setdefault(mae.id, []).append((mae, filha.account))
    # A mãe pode ter outras filhas fora do recorte acima: conta todas antes de
    # decidir que o par é único.
    filhas_por_mae = dict(
        transferencias.filter(source_entry_id__in=list(pares))
        .values("source_entry_id")
        .annotate(n=Count("id"))
        .values_list("source_entry_id", "n")
    )

    trocas = []
    for entrada_id, candidatos in pares.items():
        entrada, outra_conta = candidatos[0]
        vinculos = filhas_por_mae.get(entrada_id, 0) + (entrada.source_entry_id is not None)
        if len(candidatos) != 1 or vinculos != 1:
            continue
        if not _escrita_pelo_sistema(entrada.description):
            continue
        novo = rotulo_da_ponta(entrada, outra_conta)
        if entrada.description != novo:
            trocas.append((entrada, entrada.description, novo))

    agora = timezone.now()
    for entrada, _, novo in trocas:
        entrada.description = novo
        entrada.updated_at = agora
    CashFlowEntry.objects.bulk_update([e for e, _, _ in trocas], ["description", "updated_at"])
    if trocas:
        log_audit_event(
            "cash_flow_entry", None, "update",
            old_values={str(e.id): antes for e, antes, _ in trocas},
            new_values={str(e.id): novo for e, _, novo in trocas},
            user=user,
            summary=motivo or "Rótulo de transferência refeito pelo nome atual da conta.",
        )
    return len(trocas)
