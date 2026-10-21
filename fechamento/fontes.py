"""De onde vem o dado de cada conta.

O cadastro (`FonteDaConta`) é opcional: a conta sem registro tem a fonte deduzida
do que o CB já sabe dela, e é essa dedução que preenche a aba Fontes na primeira
vez. Gravar a aba só fixa o que o usuário confirmou ou mudou.

Dedução, na ordem:

- cartão de crédito: fatura, no formato do último arquivo importado;
- aplicação cujo nome fala de Tesouro: myProfit, classe Tesouro, corretora da
  instituição, saldo do fim do mês (é o preço oficial do último dia);
- outra aplicação: print do saldo, no fim do mês;
- conta com extrato importado: arquivo, no formato do último;
- conta em dólar da Avenue: myProfit, caixa em dólar (o myProfit lê a Avenue);
- conta sem extrato mas com saldo informado alguma vez: print;
- o resto: "ainda não tenho".
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from django.db.models import Max
from django.utils.translation import gettext

from bank_statements.models import BankStatementImport
from banking.models import FinancialAccount
from core.domain.finance import ACCOUNT_KIND_INVESTMENT, CURRENCY_USD
from transactions.models import CashFlowEntry

from .models import (
    CLASSE_CAIXA_USD,
    CLASSE_TESOURO,
    CLASSES_MYPROFIT,
    FONTE_ARQUIVO,
    FONTE_FATURA,
    FONTE_MYPROFIT,
    FONTE_NENHUMA,
    FONTE_PRINT,
    FONTES,
    FREQUENCIA_CORTE,
    FREQUENCIA_MENSAL,
    FREQUENCIAS,
    FonteDaConta,
)

PREFIXO_DO_SALDO_INFORMADO = "Atualização de saldo"  # o mesmo de `bank_statements.saldo`

_EXTENSOES = {".ofx": "OFX", ".ofc": "OFX", ".qfx": "OFX", ".pdf": "PDF", ".csv": "CSV"}


@dataclass(frozen=True)
class Fonte:
    fonte: str
    formato: str = ""
    frequencia: str = FREQUENCIA_CORTE
    classe_myprofit: str = ""
    corretora_myprofit: str = ""
    onde: str = ""
    cadastrada: bool = False

    @property
    def rotulo(self) -> str:
        return str(dict(FONTES)[self.fonte])

    @property
    def rotulo_da_frequencia(self) -> str:
        return str(dict(FREQUENCIAS)[self.frequencia])

    @property
    def rotulo_da_classe(self) -> str:
        return str(dict(CLASSES_MYPROFIT).get(self.classe_myprofit, ""))


def formato_do_arquivo(nome: str, instituicao: str, *, fatura: bool = False) -> str:
    """"OFX C6", "PDF Genial", "CSV fatura XP": o tipo do arquivo e de quem é."""
    tipo = _EXTENSOES.get(os.path.splitext(nome or "")[1].lower(), "")
    if not tipo:
        return ""
    if fatura:
        return f"{tipo} {gettext('fatura')} {instituicao}"
    return f"{tipo} {instituicao}"


def _ultimos_arquivos(ids: list[int]) -> dict[int, str]:
    ultimos = dict(
        BankStatementImport.objects.filter(account_id__in=ids).values("account_id").annotate(u=Max("id")).values_list("account_id", "u")
    )
    nomes = dict(BankStatementImport.objects.filter(id__in=ultimos.values()).values_list("id", "source_filename"))
    return {conta_id: nomes.get(lote_id, "") for conta_id, lote_id in ultimos.items()}


def _com_saldo_informado(ids: list[int]) -> set[int]:
    return set(
        CashFlowEntry.objects.filter(account_id__in=ids, description__startswith=PREFIXO_DO_SALDO_INFORMADO)
        .values_list("account_id", flat=True).distinct()
    )


def deduzir(conta: FinancialAccount, *, ultimo_arquivo: str | None, teve_saldo_informado: bool) -> Fonte:
    instituicao = conta.institution.institution_name
    if conta.is_credit_card:
        return Fonte(FONTE_FATURA, formato_do_arquivo(ultimo_arquivo or ".csv", instituicao, fatura=True))
    if conta.account_kind == ACCOUNT_KIND_INVESTMENT:
        if "tesouro" in conta.account_name.lower():
            return Fonte(
                FONTE_MYPROFIT, gettext("Posição do myProfit"), FREQUENCIA_MENSAL,
                classe_myprofit=CLASSE_TESOURO, corretora_myprofit=instituicao,
            )
        return Fonte(FONTE_PRINT, gettext("Print do app"), FREQUENCIA_MENSAL)
    if ultimo_arquivo:
        return Fonte(FONTE_ARQUIVO, formato_do_arquivo(ultimo_arquivo, instituicao))
    if conta.currency == CURRENCY_USD and instituicao.lower() == "avenue":
        return Fonte(
            FONTE_MYPROFIT, gettext("Posição do myProfit"), FREQUENCIA_CORTE,
            classe_myprofit=CLASSE_CAIXA_USD, corretora_myprofit=instituicao,
        )
    if teve_saldo_informado:
        return Fonte(FONTE_PRINT, gettext("Print do app"))
    return Fonte(FONTE_NENHUMA)


def _da_cadastrada(registro: FonteDaConta) -> Fonte:
    return Fonte(
        registro.fonte, registro.formato, registro.frequencia,
        classe_myprofit=registro.classe_myprofit, corretora_myprofit=registro.corretora_myprofit,
        onde=registro.onde, cadastrada=True,
    )


def fontes_das_contas(contas: list[FinancialAccount]) -> dict[int, Fonte]:
    """A fonte efetiva de cada conta: a cadastrada ou, sem cadastro, a deduzida."""
    ids = [conta.id for conta in contas]
    cadastradas = {registro.account_id: registro for registro in FonteDaConta.objects.filter(account_id__in=ids)}
    faltam = [conta for conta in contas if conta.id not in cadastradas]
    arquivos = _ultimos_arquivos([conta.id for conta in faltam]) if faltam else {}
    com_saldo = _com_saldo_informado([conta.id for conta in faltam]) if faltam else set()
    resultado = {}
    for conta in contas:
        if conta.id in cadastradas:
            resultado[conta.id] = _da_cadastrada(cadastradas[conta.id])
        else:
            resultado[conta.id] = deduzir(conta, ultimo_arquivo=arquivos.get(conta.id), teve_saldo_informado=conta.id in com_saldo)
    return resultado


def salvar(user, conta: FinancialAccount, dados, audit_context=None) -> FonteDaConta:
    """Grava a fonte de uma conta. `dados` é um mapeamento com os campos do formulário.

    Trocar a fonte (ou o que ela mede no myProfit) é um fato: fica na auditoria,
    com o valor de antes, porque a partir dali o saldo da conta passa a valer por
    outra origem."""
    fonte = (dados.get("fonte") or "").strip()
    if fonte not in dict(FONTES):
        raise ValueError(gettext("Escolha a fonte."))
    frequencia = (dados.get("frequencia") or FREQUENCIA_CORTE).strip()
    if frequencia not in dict(FREQUENCIAS):
        raise ValueError(gettext("Escolha a frequência."))
    classe = (dados.get("classe_myprofit") or "").strip()
    if fonte != FONTE_MYPROFIT:
        classe = ""
    elif classe not in dict(CLASSES_MYPROFIT):
        raise ValueError(gettext("Conta que vem do myProfit precisa dizer o que ela é lá: Tesouro, renda fixa EUA ou caixa em dólar."))
    if conta.is_credit_card and fonte not in (FONTE_FATURA, FONTE_NENHUMA):
        raise ValueError(gettext("Cartão de crédito só entra por fatura."))
    antes = fontes_das_contas([conta])[conta.id]
    registro, _ = FonteDaConta.objects.update_or_create(
        account=conta,
        defaults={
            "fonte": fonte,
            "formato": (dados.get("formato") or "").strip()[:40],
            "frequencia": frequencia,
            "classe_myprofit": classe,
            "corretora_myprofit": (dados.get("corretora_myprofit") or "").strip()[:40] if fonte == FONTE_MYPROFIT else "",
            "onde": (dados.get("onde") or "").strip()[:200],
            "updated_by": user,
        },
    )
    mudou = (antes.fonte, antes.classe_myprofit, antes.corretora_myprofit, antes.frequencia) != (
        registro.fonte, registro.classe_myprofit, registro.corretora_myprofit, registro.frequencia,
    )
    if audit_context is not None and mudou:
        from core.services import log_audit_event

        log_audit_event(
            "account_source", conta.id, "update", request_context=audit_context,
            old_values={"fonte": antes.fonte, "classe_myprofit": antes.classe_myprofit,
                        "corretora_myprofit": antes.corretora_myprofit, "frequencia": antes.frequencia,
                        "cadastrada": antes.cadastrada},
            new_values={"fonte": registro.fonte, "classe_myprofit": registro.classe_myprofit,
                        "corretora_myprofit": registro.corretora_myprofit, "frequencia": registro.frequencia},
            summary="Fonte do saldo da conta alterada.",
        )
    return registro


__all__ = [
    "FONTE_ARQUIVO", "FONTE_FATURA", "FONTE_MYPROFIT", "FONTE_NENHUMA", "FONTE_PRINT",
    "Fonte", "deduzir", "fontes_das_contas", "formato_do_arquivo", "salvar",
]
