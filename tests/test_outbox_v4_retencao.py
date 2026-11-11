"""Retenção da outbox do v4: apaga o velho sem mudar o que o consumidor vê.

Em produção a `patrimonio_v4_outbox` tinha 4 mil linhas e nada a esvaziava. O
consumidor (Wealthfolio) pergunta `?after=<cursor>&limit=N` e, havendo item
depois do checkpoint, busca o snapshot inteiro. O expurgo só vale se essa
resposta não mudar (ver `core/outbox.py`).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from core import patrimonio
from core.models import PatrimonioV4Outbox
from transactions.models import CashFlowCategory

# A rota do feed abre `REPEATABLE READ`, que exige ser a primeira instrução da
# transação: por isso a camada sem transação de teste envolvente.
pytestmark = pytest.mark.django_db(transaction=True)

TOKEN_V4 = "token-de-integracao-v4-com-mais-de-trinta-e-dois-caracteres"


@pytest.fixture(autouse=True)
def token(monkeypatch, tmp_path):
    arquivo = tmp_path / "patrimonio_integration_token"
    arquivo.write_text(TOKEN_V4, encoding="utf-8")
    monkeypatch.delenv(patrimonio.NOME_DO_SEGREDO_V4, raising=False)
    monkeypatch.setenv(f"{patrimonio.NOME_DO_SEGREDO_V4}_FILE", str(arquivo))


def _changes(**parametros):
    resposta = Client().get(
        "/patrimonio/v4/changes", parametros, HTTP_AUTHORIZATION=f"Bearer {TOKEN_V4}",
    )
    assert resposta.status_code == 200
    return resposta.json()


def _gravar_mudancas(quantas: int) -> list[int]:
    """Cada categoria criada vira uma linha da outbox, por gatilho."""
    antes = set(PatrimonioV4Outbox.objects.values_list("cursor", flat=True))
    for numero in range(quantas):
        CashFlowCategory.objects.create(category_name=f"Categoria {numero}")
    return sorted(set(PatrimonioV4Outbox.objects.values_list("cursor", flat=True)) - antes)


def _envelhecer(cursores, dias: int) -> None:
    PatrimonioV4Outbox.objects.filter(cursor__in=cursores).update(
        changed_at=timezone.now() - timedelta(days=dias)
    )


def test_expurgo_apaga_o_velho_e_guarda_a_linha_mais_nova():
    _gravar_mudancas(4)
    mais_nova = PatrimonioV4Outbox.objects.order_by("-cursor").values_list("cursor", flat=True).first()
    _envelhecer(PatrimonioV4Outbox.objects.values_list("cursor", flat=True), 40)

    call_command("expurgar_outbox_v4")

    assert list(PatrimonioV4Outbox.objects.values_list("cursor", flat=True)) == [mais_nova]


def test_expurgo_nao_toca_linha_mais_nova_que_a_retencao():
    cursores = _gravar_mudancas(3)
    _envelhecer(cursores[:2], 40)
    _envelhecer(cursores[2:], 10)

    call_command("expurgar_outbox_v4")

    depois = set(PatrimonioV4Outbox.objects.values_list("cursor", flat=True))
    assert cursores[2] in depois
    assert not set(cursores[:2]) & depois


def test_depois_do_expurgo_um_checkpoint_antigo_ainda_ve_a_mudanca():
    """Quem parou antes do expurgo continua sendo avisado, e quem está em dia, não."""
    cursores = _gravar_mudancas(5)
    _envelhecer(PatrimonioV4Outbox.objects.values_list("cursor", flat=True), 40)
    antigo = patrimonio._cursor_v4(cursores[1])
    em_dia = _changes(limit=500)["high_watermark"]
    assert _changes(after=antigo, limit=500)["items"]
    assert _changes(after=em_dia, limit=500)["items"] == []

    call_command("expurgar_outbox_v4")

    depois_antigo = _changes(after=antigo, limit=500)
    assert depois_antigo["items"], "o checkpoint antigo precisa continuar vendo uma mudança"
    assert all(i["payload"] == {"mode": "snapshot_required"} for i in depois_antigo["items"])
    assert _changes(after=em_dia, limit=500)["items"] == []
    assert _changes(limit=500)["high_watermark"] == em_dia


def test_expurgo_com_a_outbox_vazia_nao_faz_nada():
    PatrimonioV4Outbox.objects.all().delete()

    call_command("expurgar_outbox_v4")

    assert PatrimonioV4Outbox.objects.count() == 0


def test_retencao_menor_que_um_dia_e_recusada():
    cursores = _gravar_mudancas(2)
    _envelhecer(cursores, 40)

    with pytest.raises(ValueError, match="pelo menos um dia"):
        call_command("expurgar_outbox_v4", dias=0)

    assert PatrimonioV4Outbox.objects.filter(cursor__in=cursores).count() == 2
