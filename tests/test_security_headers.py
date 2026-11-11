"""A Content-Security-Policy e os cabecalhos defensivos chegam ao cliente.

Este arquivo existe com o mesmo nome nos quatro projetos do mantenedor. Uma
politica que afrouxa nao quebra nada visivelmente -- a pagina continua
carregando --, entao so um teste percebe.
"""

from __future__ import annotations

import pytest
from django.conf import settings

from core.security import CONTENT_SECURITY_POLICY, SECURITY_HEADERS

# `/health/` responde sem sessao: e o alvo certo para medir cabecalho, que e
# aplicado por middleware em toda resposta. Como a rota consulta o banco, os
# testes daqui pedem `banco_sondavel` -- sem isso mediriam
# o cabecalho de um 503, que passaria igual e esconderia a intencao.
ROTA = "/health/"


def test_csp_fechada_na_propria_origem(client, banco_sondavel):
    csp = client.get(ROTA).headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_csp_nao_admite_inline_nem_origem_externa(client, banco_sondavel):
    csp = client.get(ROTA).headers.get("Content-Security-Policy", "")
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "http://" not in csp
    assert "https://" not in csp


@pytest.mark.parametrize(("cabecalho", "valor"), sorted(SECURITY_HEADERS.items()))
def test_cabecalho_do_middleware_presente(client, cabecalho, valor):
    assert client.get(ROTA).headers.get(cabecalho) == valor


def test_permissions_policy_restringe_dispositivos(client, banco_sondavel):
    # `browsing-topics` entrou no conjunto comum vindo do ControleRendaVariavel,
    # onde o Flask-Talisman o escrevia sozinho: recusar a Topics API e
    # estritamente mais restritivo que nao declarar nada.
    politica = client.get(ROTA).headers.get("Permissions-Policy", "")
    for recurso in (
        "camera=()",
        "microphone=()",
        "geolocation=()",
        "browsing-topics=()",
    ):
        assert recurso in politica


def test_csp_nao_libera_data_uri_para_nada(client, banco_sondavel):
    """A politica e a fechada da biblioteca, sem excecao nenhuma.

    A folga de `img-src ... data:` existia por um motivo unico -- o favicon
    era um SVG embutido no proprio `<link rel="icon">`. Ele virou
    `static/favicon.svg` e a folga saiu junto. Este teste passa a guardar a
    ausencia: se `data:` reaparecer na politica, alguem reabriu a excecao e
    precisa justificar por que.
    """
    csp = client.get(ROTA).headers.get("Content-Security-Policy", "")
    assert "img-src 'self';" in csp
    assert "font-src 'self';" in csp
    assert "data:" not in csp


@pytest.mark.parametrize(
    ("cabecalho", "valor"),
    [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "same-origin"),
    ],
)
def test_cabecalho_do_django_presente(client, cabecalho, valor):
    # Estes vem da configuracao do proprio Django, nao do middleware da
    # aplicacao; o conjunto entregue ao navegador precisa ser o mesmo dos
    # outros tres projetos, independentemente de quem escreve cada um.
    assert client.get(ROTA).headers.get(cabecalho) == valor


def test_configuracao_defensiva_do_django():
    assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert settings.X_FRAME_OPTIONS == "DENY"
    # `same-origin`, nao `no-referrer`: ver o comentario em settings.py. Sob
    # `no-referrer` o navegador manda `Origin: null` em POST de mesma origem e
    # o CSRF do Django recusa a requisicao com o token correto.
    assert settings.SECURE_REFERRER_POLICY == "same-origin"


def test_settings_do_django_nao_discordam_do_conjunto_comum():
    # Tres destes cabecalhos tem dois escritores: a configuracao do Django e o
    # middleware, que agora le os valores de `sharedauth.security`. Os dois
    # usam `setdefault`, entao uma divergencia nao quebraria nada visivelmente
    # -- o navegador receberia o valor de quem escrevesse primeiro. Este teste
    # e o que transforma "manter igual a mao" em algo verificado.
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert SECURITY_HEADERS["X-Frame-Options"] == settings.X_FRAME_OPTIONS
    assert SECURITY_HEADERS["Referrer-Policy"] == settings.SECURE_REFERRER_POLICY


def test_csp_do_middleware_e_a_declarada():
    assert CONTENT_SECURITY_POLICY.startswith("default-src 'self'")

# ---------------------------------------------------------------------------
# Nonce de estilo
# ---------------------------------------------------------------------------
#
# A CSP fecha `style-src` em 'self', o que bloqueia TAMBEM o estilo aplicado
# por CSSOM (`el.style.x = ...`) -- e o bloqueio e silencioso: violacao no
# console, nenhum erro de JavaScript, nenhum teste vermelho, e o estilo nao
# aparece. Foi assim que o teto de rolagem das tabelas nunca funcionou.


def test_style_src_continua_fechado_sem_excecao(client):
    """Nem `unsafe-inline`, nem nonce, nem hash."""
    politica = client.get(ROTA).headers["Content-Security-Policy"]

    assert "style-src 'self';" in politica
    assert "unsafe-inline" not in politica
    assert "nonce-" not in politica


def test_a_casca_nao_traz_estilo_embutido() -> None:
    """`<style>` sem nonce e o que a CSP realmente bloqueia (`style-src-elem`).

    Escrita por CSSOM (`el.style.x = ...`) NAO e bloqueada -- a politica governa
    o ATRIBUTO `style` do HTML e o elemento `<style>`, nao a propriedade `style`
    de um objeto. A distincao custou uma correcao errada; fica registrada aqui.
    """
    from django.template.loader import render_to_string

    rendered = render_to_string("base.html", {"app_menu_items": []})

    assert "<style" not in rendered


# ---------------------------------------------------------------------------
# Cache do navegador (SEG-L1)
# ---------------------------------------------------------------------------
#
# Sem `Cache-Control`, o navegador pode reabrir pelo botao Voltar, depois do
# logout, a tela com dado financeiro, e guardar a pagina que mostra a senha
# temporaria em claro.


@pytest.fixture
def administrador(client):
    from django.contrib.auth import get_user_model

    usuario = get_user_model().objects.create_user(
        username="adm-cache", password="senha-segura-123", user_type="administrator",
    )
    client.force_login(usuario)
    return usuario


@pytest.mark.django_db
def test_pagina_de_quem_entrou_nao_fica_no_cache_do_navegador(client, administrador):
    resposta = client.get("/dashboard/")

    assert resposta.status_code == 200
    diretivas = {d.strip() for d in resposta.headers["Cache-Control"].split(",")}
    assert {"no-store", "private"} <= diretivas


@pytest.mark.django_db
def test_a_resposta_com_a_senha_temporaria_nao_fica_no_cache(client, administrador):
    from django.contrib.auth import get_user_model

    alvo = get_user_model().objects.create_user(
        username="alvo-cache", password="senha-segura-456", user_type="user",
    )

    resposta = client.post(
        "/permissions/",
        {"table": "users", "action": "reset_password", "id": alvo.id, "user_id": alvo.id},
    )

    assert resposta.status_code == 200
    assert "no-store" in resposta.headers["Cache-Control"]
    alvo.refresh_from_db()
    assert alvo.must_change_password is True  # a redefinicao de fato ocorreu


@pytest.mark.django_db
def test_sonda_de_saude_nao_recebe_no_store_mesmo_com_sessao(client, administrador, banco_sondavel):
    assert "no-store" not in client.get("/health/").headers.get("Cache-Control", "")


@pytest.mark.django_db
def test_estatico_de_quem_entrou_segue_cacheavel(administrador):
    from django.http import HttpResponse
    from django.test import RequestFactory

    from core.security import ContentSecurityPolicyMiddleware

    requisicao = RequestFactory().get("/static/css/core/application.css")
    requisicao.user = administrador

    resposta = ContentSecurityPolicyMiddleware(lambda _r: HttpResponse("css"))(requisicao)

    assert "Cache-Control" not in resposta.headers


def test_quem_nao_entrou_nao_ganha_diretiva_nova(client, banco_sondavel):
    # A tela de login ja traz a dela (`LoginView`); o que nao tem sessao nao
    # muda por causa deste middleware.
    from django.http import HttpResponse
    from django.test import RequestFactory

    from core.security import ContentSecurityPolicyMiddleware

    class Anonimo:
        is_authenticated = False

    requisicao = RequestFactory().get("/qualquer/")
    requisicao.user = Anonimo()

    resposta = ContentSecurityPolicyMiddleware(lambda _r: HttpResponse("x"))(requisicao)

    assert "Cache-Control" not in resposta.headers
