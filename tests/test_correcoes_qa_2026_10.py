"""Correções da rodada de QA de outubro/2026.

Cada teste prende um defeito achado na varredura de ponta a ponta: o que a
pessoa fez, o que o sistema respondeu (500, silêncio, dado ruim) e o que ele
deve responder. A numeração do comentário é a do relatório da rodada.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.timezone import localdate

from accounts.models import AccountOwner
from banking.models import FinancialAccount, FinancialInstitution
from banking.services import create_account
from core.domain.finance import (
    ENTRY_TYPE_EXPENSE,
    MAX_MONEY_VALUE,
    OPERATION_SINGLE,
    STATUS_PROJECTED,
    assert_money_in_range,
)
from core.domain.identity import USER_TYPE_ADMINISTRATOR
from core.models import AuditLog
from transactions.models import CashFlowCategory, CashFlowEntry
from transactions.services import create_category, create_category_group, realize_transaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario():
    return get_user_model().objects.create_user(
        username="qa-admin",
        password="troca-esta-senha-no-primeiro-acesso",
        user_type=USER_TYPE_ADMINISTRATOR,
    )


@pytest.fixture
def titular():
    return AccountOwner.objects.create(name="Titular QA")


@pytest.fixture
def instituicao():
    return FinancialInstitution.objects.create(institution_name="Banco QA", institution_type="Banco")


def _campos(titular, instituicao, **extras):
    padrao = {
        "owner_id": str(titular.id),
        "institution_id": str(instituicao.id),
        "account_name": "Conta QA",
        "initial_balance": "100,00",
        "currency": "BRL",
    }
    padrao.update(extras)
    return padrao


@pytest.fixture
def conta(usuario, titular, instituicao):
    return create_account(usuario, **_campos(titular, instituicao))


def _lancamento(conta, **extras):
    categoria, _ = CashFlowCategory.objects.get_or_create(category_name="Categoria QA")
    campos = {
        "account": conta,
        "category": categoria,
        "entry_type": ENTRY_TYPE_EXPENSE,
        "description": "Lançamento QA",
        "entry_amount": Decimal("10.00"),
        "due_date": date(2026, 6, 10),
        "status": STATUS_PROJECTED,
        "operation_type": OPERATION_SINGLE,
    }
    campos.update(extras)
    return CashFlowEntry.objects.create(**campos)


# --- 5. Valor fora da coluna numeric(12,2) ---------------------------------


def test_limite_de_valor_aceita_o_maximo_e_recusa_o_que_passa():
    assert_money_in_range(MAX_MONEY_VALUE)
    assert_money_in_range(None)
    with pytest.raises(ValueError, match="acima do limite"):
        assert_money_in_range(MAX_MONEY_VALUE + Decimal("0.01"))


@pytest.mark.parametrize("texto", ["NaN", "Infinity", "-Infinity"])
def test_valor_nao_finito_e_recusado(texto):
    with pytest.raises(ValueError, match="inválido"):
        assert_money_in_range(Decimal(texto))


def test_saldo_inicial_acima_do_limite_nao_vira_erro_500(usuario, titular, instituicao):
    with pytest.raises(ValueError, match="limite"):
        create_account(usuario, **_campos(titular, instituicao, initial_balance="99999999999"))
    assert FinancialAccount.objects.count() == 0


def test_realizar_com_valor_gigante_e_recusado(conta):
    entrada = _lancamento(conta)
    with pytest.raises(ValueError, match="limite"):
        realize_transaction(entrada, localdate(), Decimal("99999999999"))
    entrada.refresh_from_db()
    assert entrada.status == STATUS_PROJECTED


# --- 8. Data de realização -------------------------------------------------


def test_realizar_no_futuro_e_recusado(conta):
    entrada = _lancamento(conta)
    with pytest.raises(ValueError, match="depois de hoje"):
        realize_transaction(entrada, localdate() + timedelta(days=30), None)


def test_data_de_realizacao_invalida_nao_vira_hoje(client, usuario, conta):
    entrada = _lancamento(conta)
    client.force_login(usuario)

    client.post(reverse("transactions:mark_realized", args=[entrada.id]), {"realized_date": "2026-13-45"})

    entrada.refresh_from_db()
    assert entrada.status == STATUS_PROJECTED
    assert entrada.realized_date is None


def test_valor_realizado_nan_via_formulario_e_recusado(client, usuario, conta):
    entrada = _lancamento(conta)
    client.force_login(usuario)

    client.post(reverse("transactions:mark_realized", args=[entrada.id]), {"realized_amount": "NaN"})

    entrada.refresh_from_db()
    assert entrada.status == STATUS_PROJECTED


# --- 9. Fechamento de mês --------------------------------------------------


def test_mes_corrente_nao_pode_ser_fechado(client, usuario, conta):
    client.force_login(usuario)
    hoje = localdate()

    client.post(
        reverse("core:settings_close_month"),
        {"account_id": conta.id, "year": hoje.year, "month": hoje.month},
    )

    from transactions.models import AccountMonthClose

    assert not AccountMonthClose.objects.filter(account=conta, year=hoje.year, month=hoje.month).exists()


# --- 10, 12. Cadastro de conta ---------------------------------------------


def test_data_do_saldo_inicial_no_futuro_e_recusada(usuario, titular, instituicao):
    futuro = (localdate() + timedelta(days=400)).isoformat()
    with pytest.raises(ValueError, match="depois de hoje"):
        create_account(usuario, **_campos(titular, instituicao, initial_balance_date=futuro))


def test_conta_com_mesmo_nome_no_mesmo_titular_e_recusada(usuario, titular, instituicao, conta):
    with pytest.raises(ValueError):
        create_account(usuario, **_campos(titular, instituicao))
    assert FinancialAccount.objects.count() == 1


def test_identificador_de_extrato_repetido_na_instituicao_e_recusado(usuario, titular, instituicao):
    create_account(usuario, **_campos(titular, instituicao, statement_identifier="12345-6"))
    with pytest.raises(ValueError, match="identificador"):
        create_account(
            usuario, **_campos(titular, instituicao, account_name="Outra conta", statement_identifier="12345-6")
        )


# --- 11. Nome de categoria e grupo -----------------------------------------


@pytest.mark.parametrize("repetido", ["qa-cat", "QA-CAT", " QA-Cat "])
def test_categoria_repetida_so_pela_caixa_e_recusada(repetido):
    create_category("QA-Cat", "gerencial")
    with pytest.raises(ValueError, match="Já existe"):
        create_category(repetido, "gerencial")


def test_categoria_repetida_so_pelo_acento_e_recusada():
    create_category("Saúde", "gerencial")
    with pytest.raises(ValueError, match="Já existe"):
        create_category("Saude", "gerencial")


def test_grupo_repetido_so_pela_caixa_e_recusado():
    create_category_group("Moradia")
    with pytest.raises(ValueError):
        create_category_group("MORADIA")


# --- 15. Nome do comprovante -----------------------------------------------


def test_nome_do_comprovante_perde_so_o_acento():
    from bank_statements.attachments import _sanitize_filename

    assert _sanitize_filename("comprovante ação.pdf") == "comprovante_acao.pdf"
    assert _sanitize_filename("../../etc/passwd") == "passwd"


# --- 4. Comprovante órfão --------------------------------------------------


def test_excluir_o_lancamento_remove_o_arquivo_do_comprovante(
    conta, settings, tmp_path, django_capture_on_commit_callbacks
):
    from bank_statements.attachments import attachment_storage_dir
    from bank_statements.models import EntryAttachment

    settings.MEDIA_ROOT = str(tmp_path)
    entrada = _lancamento(conta)
    arquivo = attachment_storage_dir() / "1_abc_recibo.txt"
    arquivo.write_text("recibo", encoding="utf-8")
    EntryAttachment.objects.create(
        entry=entrada,
        original_filename="recibo.txt",
        stored_filename=arquivo.name,
        stored_path=f"attachments/{arquivo.name}",
        mime_type="text/plain",
        file_size=6,
    )

    with django_capture_on_commit_callbacks(execute=True):
        entrada.delete()

    assert not arquivo.exists()
    assert EntryAttachment.objects.count() == 0


# --- 1, 2. Auditoria -------------------------------------------------------


def test_login_errado_e_certo_deixam_trilha(client, usuario):
    client.post(reverse("login"), {"username": "qa-admin", "password": "errada"})
    client.post(reverse("login"), {"username": "qa-admin", "password": "troca-esta-senha-no-primeiro-acesso"})

    eventos = list(AuditLog.objects.filter(entity_name="auth_login").order_by("id").values_list("action", "result"))
    assert ("failed", "failure") in eventos
    assert ("login", "success") in eventos


def test_logout_deixa_trilha(client, usuario):
    client.force_login(usuario)

    client.post(reverse("logout"))

    assert AuditLog.objects.filter(entity_name="auth_login", action="logout").exists()


def test_cadastro_de_categoria_deixa_trilha(client, usuario):
    client.force_login(usuario)

    client.post(reverse("transactions:create_category"), {"category_name": "Categoria auditada", "kind": "gerencial"})

    assert CashFlowCategory.objects.filter(category_name="Categoria auditada").exists()
    assert AuditLog.objects.filter(entity_name="cash_flow_category", action="create").exists()


# --- 6. Tempo de resposta do login -----------------------------------------


def test_usuario_inexistente_tambem_gasta_o_custo_do_hash(monkeypatch):
    from accounts import auth_backends

    chamadas = []
    monkeypatch.setattr(auth_backends, "check_password", lambda senha, hash_: chamadas.append(senha))

    auth_backends.CaseInsensitiveUsernameBackend().authenticate(None, username="ninguem", password="x")

    assert chamadas == ["x"]


# --- Revisão: ajustes depois do code review -------------------------------


def _requisicao(conta, categoria, **campos):
    from transactions.services import TransactionRequest

    padrao = {
        "account_id": conta.id,
        "category_id": categoria.id,
        "entry_type": ENTRY_TYPE_EXPENSE,
        "description": "Lançamento QA",
        "entry_amount": Decimal("10.00"),
        "installments": 1,
        "due_date": date(2026, 6, 10),
        "status": "realizado",
        "realized_date": date(2026, 6, 10),
    }
    padrao.update(campos)
    return TransactionRequest(**padrao)


def test_criar_realizado_no_futuro_e_recusado(conta, usuario):
    from transactions.services import create_transaction_batch

    categoria = CashFlowCategory.objects.create(category_name="Cat futura")
    futuro = localdate() + timedelta(days=10)

    with pytest.raises(ValueError, match="depois de hoje"):
        create_transaction_batch(_requisicao(conta, categoria, realized_date=futuro), user=usuario)


def test_editar_realizado_antigo_com_data_futura_so_recusa_data_nova(conta, usuario):
    from core.domain.finance import OPERATION_SCOPE_SINGLE
    from transactions.services import update_transaction_operation

    futuro = localdate() + timedelta(days=10)
    categoria = CashFlowCategory.objects.create(category_name="Cat antiga")
    entrada = _lancamento(
        conta, category=categoria, status="realizado", realized_date=futuro,
        realized_amount=Decimal("10.00"), due_date=futuro,
    )

    # Mexer só na descrição mantém a data de antes: segue editável.
    atualizadas = update_transaction_operation(
        entrada,
        _requisicao(conta, categoria, description="Nova descrição", due_date=futuro, realized_date=futuro),
        OPERATION_SCOPE_SINGLE, user=usuario,
    )
    assert atualizadas[0].description == "Nova descrição"

    outra = futuro + timedelta(days=1)
    with pytest.raises(ValueError, match="depois de hoje"):
        update_transaction_operation(
            entrada,
            _requisicao(conta, categoria, due_date=futuro, realized_date=outra),
            OPERATION_SCOPE_SINGLE, user=usuario,
        )


def test_editar_conta_que_ja_dividia_identificador_nao_e_recusado(usuario, titular, instituicao):
    from banking.services import update_account

    a = FinancialAccount.objects.create(
        owner=titular, institution=instituicao, account_name="Conta A", statement_identifier="999-9"
    )
    FinancialAccount.objects.create(
        owner=titular, institution=instituicao, account_name="Conta B", statement_identifier="999-9"
    )

    campos = _campos(titular, instituicao, account_name="Conta A", statement_identifier="999-9")
    update_account(usuario, a, **{**campos, "initial_balance": "250,00"})
    a.refresh_from_db()
    assert a.initial_balance == Decimal("250.00")

    with pytest.raises(ValueError, match="Este titular já tem uma conta"):
        update_account(usuario, a, **{**campos, "account_name": "conta b"})


def test_fechar_mes_com_ano_fora_do_intervalo_nao_vira_500(client, usuario, conta):
    client.force_login(usuario)

    resposta = client.post(reverse("core:settings_close_month"), {"account_id": conta.id, "year": 0, "month": 1})

    assert resposta.status_code == 302
    from transactions.models import AccountMonthClose

    assert not AccountMonthClose.objects.filter(account=conta).exists()


def test_excluir_lancamento_nao_falha_se_a_pasta_de_anexos_esta_inacessivel(
    conta, settings, tmp_path, monkeypatch
):
    from bank_statements import attachments
    from bank_statements.models import EntryAttachment

    settings.MEDIA_ROOT = str(tmp_path)
    entrada = _lancamento(conta)
    EntryAttachment.objects.create(
        entry=entrada, original_filename="r.txt", stored_filename="r.txt",
        stored_path="attachments/r.txt", mime_type="text/plain", file_size=1,
    )

    def sem_acesso():
        raise PermissionError("somente leitura")

    monkeypatch.setattr(attachments, "attachment_storage_dir", sem_acesso)

    entrada.delete()

    assert not CashFlowEntry.objects.filter(id=entrada.id).exists()
    assert EntryAttachment.objects.count() == 0


def test_bloqueio_de_login_grava_uma_linha_e_nao_uma_por_requisicao(client, usuario):
    from core.services import get_login_lockout_policy_settings

    limite = get_login_lockout_policy_settings().max_failures
    for _ in range(limite + 3):
        client.post(reverse("login"), {"username": "qa-admin", "password": "errada"})

    eventos = AuditLog.objects.filter(entity_name="auth_login")
    assert eventos.filter(action="failed").count() == limite
    assert eventos.filter(action="throttled").count() == 1


def test_sem_acentos_so_tira_o_acento():
    from core.texto import sem_acentos

    assert sem_acentos("Ação Saúde") == "Acao Saude"
    assert sem_acentos(None) == ""


def test_rotulo_conta_traz_titular_instituicao_e_conta(conta, titular, instituicao):
    from core.templatetags.contas import rotulo_conta

    assert rotulo_conta(conta) == "Titular QA / Banco QA / Conta QA"
