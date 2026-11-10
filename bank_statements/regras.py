"""Regras explícitas de linha de extrato (ver `models.StatementRule`).

A regra casa pelo texto da linha (sem acento nem caixa) e, opcionalmente, pela
instituição e pelo sinal. Quando mais de uma casa, vence a mais específica:
a que tem instituição, depois a de padrão mais longo.
"""
from __future__ import annotations

import unicodedata

from django.db import transaction as db_transaction
from django.utils.translation import gettext

from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import CATEGORY_KIND_TRANSFER

from .models import (
    RULE_ACTION_CATEGORY,
    RULE_ACTION_LINKED,
    RULE_ACTION_TRANSFER,
    RULE_SIGN_ANY,
    RULE_SIGN_CREDIT,
    VALID_RULE_ACTIONS,
    VALID_RULE_SIGNS,
    BankStatementLine,
    StatementRule,
)


def normalizar(texto: str) -> str:
    """Maiúsculas, sem acento e com espaços simples: a forma em que o padrão casa."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.upper().split())


class Regras:
    """As regras ativas, lidas uma vez: um plano consulta uma regra por linha."""

    def __init__(self, regras=None):
        if regras is None:
            regras = StatementRule.objects.filter(active=True).select_related("category", "institution")
        self._regras = sorted(
            ((normalizar(regra.pattern), regra) for regra in regras),
            key=lambda par: (par[1].institution_id is None, -len(par[0]), par[1].id),
        )

    def da_linha(self, linha: BankStatementLine) -> StatementRule | None:
        texto = normalizar(linha.description)
        instituicao_id = linha.account.institution_id
        for padrao, regra in self._regras:
            if regra.institution_id is not None and regra.institution_id != instituicao_id:
                continue
            if regra.sign != RULE_SIGN_ANY and (regra.sign == RULE_SIGN_CREDIT) != (linha.amount > 0):
                continue
            if padrao and padrao in texto:
                return regra
        return None


def _inteiro_ou_nada(valor) -> int | None:
    try:
        return int(valor) if str(valor or "").strip() else None
    except (TypeError, ValueError) as exc:
        raise ValueError(gettext("Escolha inválida no formulário da regra.")) from exc


@db_transaction.atomic
def salvar(regra_id, dados) -> StatementRule:
    """Cria ou altera uma regra a partir do formulário (Movimentação › Importação › Regras de extrato).

    Cada ação guarda só o que ela usa: a categoria some de uma regra que deixou
    de categorizar, e a conta de destino, de uma que deixou de transferir.
    `ValueError` com a mensagem para a tela."""
    from transactions.models import CashFlowCategory

    nome = " ".join((dados.get("name") or "").split())
    padrao = " ".join((dados.get("pattern") or "").split())
    acao = dados.get("action") or ""
    sinal = dados.get("sign") or RULE_SIGN_ANY
    if not nome:
        raise ValueError(gettext("Dê um nome à regra."))
    if len(nome) > 120 or len(padrao) > 120:
        raise ValueError(gettext("Nome e trecho do texto têm no máximo 120 caracteres."))
    if len(normalizar(padrao)) < 3:
        raise ValueError(gettext("O trecho do texto precisa de pelo menos 3 letras ou números."))
    if acao not in VALID_RULE_ACTIONS or sinal not in VALID_RULE_SIGNS:
        raise ValueError(gettext("Escolha inválida no formulário da regra."))

    instituicao_id = _inteiro_ou_nada(dados.get("institution"))
    if instituicao_id is not None and not FinancialInstitution.objects.filter(id=instituicao_id).exists():
        raise ValueError(gettext("Instituição não encontrada."))

    categoria = None
    conta_de_destino_nome = ""
    instituicao_de_destino_id = None
    if acao == RULE_ACTION_CATEGORY:
        categoria = CashFlowCategory.objects.filter(id=_inteiro_ou_nada(dados.get("category")) or 0).first()
        if categoria is None:
            raise ValueError(gettext("Escolha a categoria que a regra dá à linha."))
        if categoria.kind == CATEGORY_KIND_TRANSFER:
            raise ValueError(gettext(
                "Transferência tem outra ponta: use a ação de transferência e diga a conta de destino."
            ))
    elif acao in (RULE_ACTION_TRANSFER, RULE_ACTION_LINKED):
        conta_de_destino_nome = " ".join((dados.get("destination_account_name") or "").split())
        if acao == RULE_ACTION_TRANSFER:
            if not conta_de_destino_nome:
                raise ValueError(gettext("Diga o nome da conta de destino da transferência."))
            instituicao_de_destino_id = _inteiro_ou_nada(dados.get("destination_institution"))
        if conta_de_destino_nome and not FinancialAccount.objects.filter(
            account_name__iexact=conta_de_destino_nome
        ).exists():
            raise ValueError(
                gettext("Não há conta chamada “%(conta)s”: confira o nome em Cadastros › Contas.")
                % {"conta": conta_de_destino_nome}
            )
        if instituicao_de_destino_id is not None and not FinancialInstitution.objects.filter(
            id=instituicao_de_destino_id
        ).exists():
            raise ValueError(gettext("Instituição não encontrada."))

    if regra_id:
        try:
            regra = StatementRule.objects.select_for_update().get(id=regra_id)
        except (StatementRule.DoesNotExist, ValueError, TypeError) as exc:
            raise ValueError(gettext("Regra não encontrada.")) from exc
    else:
        regra = StatementRule()
    regra.name = nome
    regra.pattern = padrao
    regra.institution_id = instituicao_id
    regra.sign = sinal
    regra.action = acao
    regra.category = categoria
    regra.destination_account_name = conta_de_destino_nome
    regra.destination_institution_id = instituicao_de_destino_id
    regra.active = dados.get("active") == "1"
    regra.save()
    return regra


def linhas_pendentes_da_regra(user, regra: StatementRule) -> int:
    """Quantas linhas pendentes, ao alcance de `user`, a regra decide agora.

    Conta pelo mesmo caminho do plano (`Regras.da_linha`, com todas as regras
    ativas): uma regra mais específica que vença esta não entra na conta."""
    from banking.services import accessible_account_ids

    from .models import LINE_STATUS_NEW

    if not regra.active:
        return 0
    regras = Regras()
    pendentes = BankStatementLine.objects.filter(
        account_id__in=accessible_account_ids(user, "view"), status=LINE_STATUS_NEW
    ).exclude(account__account_kind="cartao_credito").select_related("account")
    return sum(1 for linha in pendentes if getattr(regras.da_linha(linha), "id", None) == regra.id)


def conta_de_destino(regra: StatementRule, conta: FinancialAccount) -> FinancialAccount | None:
    """A conta de destino da regra de transferência: mesmo titular, a instituição
    da regra (ou a da linha, se a regra não diz) e o nome informado. `None`
    quando a regra não é de transferência ou a conta ainda não existe.

    Na regra de aplicação vinculada, é a única aplicação cuja conta de movimento
    é a da linha (filtrada pelo nome, se a regra tiver um); nenhuma ou mais de
    uma também dá `None`, e a linha fica para decisão manual."""
    if regra.action == RULE_ACTION_LINKED:
        vinculadas = conta.linked_investments.all()
        if regra.destination_account_name.strip():
            vinculadas = vinculadas.filter(account_name__iexact=regra.destination_account_name.strip())
        vinculadas = list(vinculadas[:2])
        return vinculadas[0] if len(vinculadas) == 1 else None
    if regra.action != RULE_ACTION_TRANSFER:
        return None
    return (
        FinancialAccount.objects.filter(
            owner_id=conta.owner_id,
            institution_id=regra.destination_institution_id or conta.institution_id,
            account_name__iexact=regra.destination_account_name.strip(),
        )
        .exclude(id=conta.id)
        .first()
    )
