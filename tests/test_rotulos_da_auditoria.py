"""Trilha de auditoria: a tela mostra rótulo legível; o banco guarda o código.

Risco que protege: a tela voltar a exibir `auth_login`, `account_month_close` e
"Signed in." a quem lê em português; um código sem rótulo sumir da tela ou do
filtro em vez de aparecer como está; o `value` do filtro virar o rótulo (e o
filtro do servidor, que compara o código gravado, deixar de achar o registro);
o filtro de ID voltar a ser uma lista com todos os IDs já registrados.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.translation import override

from core import audit_labels
from core.models import AuditLog


@pytest.fixture
def logado(client):
    usuario = get_user_model().objects.create_user(
        username="auditor", password="senha-segura", user_type="administrator", language="pt-br",
    )
    client.force_login(usuario)
    return client


def _registro(entidade, entidade_id, acao, **extra):
    return AuditLog.objects.create(entity_name=entidade, entity_id=entidade_id, action=acao, **extra)


# --- Mapa de apresentação (sem banco) --------------------------------------------


def test_codigo_conhecido_vira_rotulo_e_o_desconhecido_sai_como_esta():
    with override("pt-br"):
        assert audit_labels.rotulo_entidade("account_month_close") != "account_month_close"
        assert audit_labels.rotulo_acao("auth_login") == "auth_login"  # não é ação: sem rótulo
        assert audit_labels.rotulo_acao("login") != "login"
        assert audit_labels.rotulo_resultado("success") != "success"
        for rotulo in (audit_labels.rotulo_entidade, audit_labels.rotulo_acao, audit_labels.rotulo_resultado):
            assert rotulo("codigo_que_ninguem_mapeou") == "codigo_que_ninguem_mapeou"
            assert rotulo(None) == ""


def test_opcoes_de_filtro_mantem_o_codigo_e_ordenam_pelo_rotulo_exibido():
    with override("pt-br"):
        opcoes = audit_labels.opcoes_de_filtro(
            ["statement_rule", "cash_flow_entry", "zz_novo", "account_owner"], audit_labels.rotulo_entidade,
        )
    assert {codigo for codigo, _ in opcoes} == {"statement_rule", "cash_flow_entry", "zz_novo", "account_owner"}
    rotulos = [rotulo for _, rotulo in opcoes]
    assert rotulos == sorted(rotulos, key=str.casefold)
    assert ("zz_novo", "zz_novo") in opcoes


def test_dois_codigos_nao_compartilham_rotulo_dentro_do_mesmo_filtro():
    # Duas opções iguais no <select> obrigariam a adivinhar qual filtra o quê.
    for mapa in (audit_labels.ENTIDADES, audit_labels.ACOES, audit_labels.RESULTADOS):
        assert len(set(mapa.values())) == len(mapa)


def test_resumo_gravado_em_portugues_ou_em_ingles_sai_no_idioma_de_quem_le():
    with override("en"):
        em_ingles = audit_labels.rotulo_resumo("Entrada no sistema.")
    assert em_ingles != "Entrada no sistema."
    with override("en"):
        assert audit_labels.rotulo_resumo(em_ingles) == em_ingles
    with override("pt-br"):
        assert audit_labels.rotulo_resumo(em_ingles) == "Entrada no sistema."
        assert audit_labels.rotulo_resumo("Entrada no sistema.") == "Entrada no sistema."


def test_resumo_com_valor_embutido_recompoe_a_frase_e_nao_confunde_fechar_com_reabrir():
    with override("pt-br"):
        assert audit_labels.rotulo_resumo("Fechamento mensal 03/2026 da conta #7.") == (
            "Fechamento mensal 03/2026 da conta #7."
        )
        assert audit_labels.rotulo_resumo("Fechamento mensal 03/2026 da conta #7 reaberto.") == (
            "Fechamento mensal 03/2026 da conta #7 reaberto."
        )
    with override("en"):
        fechado = audit_labels.rotulo_resumo("Fechamento mensal 03/2026 da conta #7.")
        reaberto = audit_labels.rotulo_resumo("Fechamento mensal 03/2026 da conta #7 reaberto.")
    assert fechado != reaberto
    assert "03/2026" in fechado and "#7" in fechado
    assert "03/2026" in reaberto and "#7" in reaberto


def test_resumo_sem_ponto_final_gravado_por_versao_antiga_e_reconhecido():
    with override("pt-br"):
        assert audit_labels.rotulo_resumo("Status da operação recalculado a partir das ocorrências") == (
            "Status da operação recalculado a partir das ocorrências."
        )


def test_resumo_livre_e_vazio_ficam_como_estao():
    assert audit_labels.rotulo_resumo("Categoria 'X' passa a ser gerencial (ajuste manual).") == (
        "Categoria 'X' passa a ser gerencial (ajuste manual)."
    )
    assert audit_labels.rotulo_resumo("") == ""
    assert audit_labels.rotulo_resumo(None) == ""


# --- A tela ----------------------------------------------------------------------


@pytest.mark.django_db
def test_tela_mostra_rotulo_e_mantem_o_codigo_no_title_e_no_value_do_filtro(logado):
    _registro("cash_flow_entry", "42", "create", summary="Lançamento criado.")
    _registro("zz_entidade_nova", "7", "zz_acao_nova", result="zz_novo")

    resposta = logado.get(reverse("core:settings_audit_log"))
    html = resposta.content.decode()

    entidades = dict(resposta.context["audit_filter_options"]["entity_name"])
    acoes = dict(resposta.context["audit_filter_options"]["action"])
    # O value do filtro é o código gravado; o texto da opção é o rótulo.
    assert entidades["cash_flow_entry"] != "cash_flow_entry"
    assert acoes["create"] != "create"
    assert 'value="cash_flow_entry"' in html and 'value="create"' in html
    # Código sem rótulo continua na tela e no filtro, como está.
    assert entidades["zz_entidade_nova"] == "zz_entidade_nova"
    assert acoes["zz_acao_nova"] == "zz_acao_nova"
    assert "zz_novo" in html
    # O código fica à mão para diagnóstico.
    assert 'title="cash_flow_entry"' in html


@pytest.mark.django_db
def test_opcoes_de_filtro_vem_ordenadas_pelo_rotulo(logado):
    for entidade in ("statement_rule", "cash_flow_entry", "account_owner", "financial_account"):
        _registro(entidade, "1", "create")

    resposta = logado.get(reverse("core:settings_audit_log"))

    rotulos = [rotulo for _, rotulo in resposta.context["audit_filter_options"]["entity_name"]]
    assert rotulos == sorted(rotulos, key=str.casefold)


@pytest.mark.django_db
def test_filtro_por_entidade_e_acao_continua_comparando_o_codigo_gravado(logado):
    alvo = _registro("account_month_close", "3", "close")
    _registro("account_month_close", "4", "reopen")
    _registro("cash_flow_entry", "5", "close")

    resposta = logado.get(reverse("core:settings_audit_log"), {"entity_name": "account_month_close", "action": "close"})

    assert [log.id for log in resposta.context["recent_audit_logs"]] == [alvo.id]


@pytest.mark.django_db
def test_id_e_campo_numerico_e_filtra_pelo_id_digitado(logado):
    alvo = _registro("cash_flow_entry", "1234", "update")
    _registro("cash_flow_entry", "12345", "update")
    _registro("cash_flow_entry", "99", "update")

    resposta = logado.get(reverse("core:settings_audit_log"), {"entity_id": "1234"})
    html = resposta.content.decode()

    assert [log.id for log in resposta.context["recent_audit_logs"]] == [alvo.id]
    # Não há mais lista com todos os IDs; o campo devolve o que foi digitado.
    assert "entity_id" not in resposta.context["audit_filter_options"]
    assert 'inputmode="numeric"' in html
    assert 'name="entity_id" value="1234"' in html
    assert '<select id="audit-filter-entity-id"' not in html


@pytest.mark.django_db
def test_id_que_nao_e_numero_nao_quebra_a_tela_e_nao_acha_nada(logado):
    _registro("cash_flow_entry", "1", "update")

    resposta = logado.get(reverse("core:settings_audit_log"), {"entity_id": "abc' OR '1'='1"})

    assert resposta.status_code == 200
    assert resposta.context["recent_audit_logs"] == []


@pytest.mark.django_db
def test_eventos_que_o_sistema_grava_tem_rotulo(client):
    """Login, falha de login e saída passam pela porta pública e deixam códigos mapeados."""
    get_user_model().objects.create_user(username="entrante", password="senha-segura", user_type="administrator")
    client.post(reverse("login"), {"username": "entrante", "password": "errada-errada"})
    client.post(reverse("login"), {"username": "entrante", "password": "senha-segura"})
    client.post(reverse("logout"))

    logs = list(AuditLog.objects.filter(entity_name="auth_login"))

    assert {log.action for log in logs} >= {"login", "failed", "logout"}
    for log in logs:
        assert log.entity_name in audit_labels.ENTIDADES
        assert log.action in audit_labels.ACOES
        assert log.result in audit_labels.RESULTADOS
