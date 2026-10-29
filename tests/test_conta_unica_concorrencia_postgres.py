"""Duas criações simultâneas da mesma conta: só uma vale.

Nome e identificador de extrato não têm constraint única (contas antigas podem repeti-los), então a
unicidade depende da trava tomada em `_assert_account_unique` até o fim da transação de criação.
"""

import pytest
from test_concorrencia_financeira_postgres import disputar
from test_gestao_persistida import cenario as cenario  # noqa: F401

from banking import services
from banking.models import FinancialAccount, FinancialInstitution

pytestmark = pytest.mark.django_db(transaction=True)

TENTATIVAS = 3


def _criar(cenario, instituicao, nome, identificador=""):
    return lambda: services.create_account(
        cenario.admin, owner_id=str(cenario.dono.pk), institution_id=str(instituicao.pk),
        account_name=nome, initial_balance="0", currency="BRL", statement_identifier=identificador,
    )


def test_mesmo_nome_ao_mesmo_tempo_cria_uma_conta_so(cenario):
    for i in range(TENTATIVAS):
        banco = FinancialInstitution.objects.create(institution_name=f"Banco do nome {i}")
        erro = disputar(_criar(cenario, banco, "Conta da disputa"), _criar(cenario, banco, "conta da disputa"))
        assert "já tem uma conta com esse nome" in erro
        assert FinancialAccount.objects.filter(institution=banco).count() == 1


def test_mesmo_identificador_ao_mesmo_tempo_cria_uma_conta_so(cenario):
    for i in range(TENTATIVAS):
        banco = FinancialInstitution.objects.create(institution_name=f"Banco do identificador {i}")
        erro = disputar(
            _criar(cenario, banco, "Conta A", "ID-1234"), _criar(cenario, banco, "Conta B", "ID-1234"),
        )
        assert "identificador de extrato" in erro
        assert FinancialAccount.objects.filter(institution=banco, statement_identifier="ID-1234").count() == 1
