"""Formato regional (Brasil/EUA) por usuário: só apresentação.

Risco que protege: o usuário escolher EUA e ver número ou data em formato
trocado pela metade (a mistura que motivou a mudança), ou a escolha de um
usuário vazar para a requisição seguinte. O que é gravado, importado e
exportado não passa por esta camada e não deve mudar.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.urls import reverse
from django.utils import translation

from core import regional
from core.domain.settings import (
    REGIONAL_FORMAT_AUTO,
    REGIONAL_FORMAT_BR,
    REGIONAL_FORMAT_US,
    normalize_regional_format,
    resolve_regional_format,
)

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def eua():
    token = regional.ativar(REGIONAL_FORMAT_US)
    yield
    regional.desativar(token)


def _renderizar(texto: str, **contexto) -> str:
    return Template("{% load money_filters regional_filters %}" + texto).render(Context(contexto))


def test_sem_requisicao_vale_o_formato_do_brasil():
    assert regional.formatar_data(date(2026, 12, 31)) == "31/12/2026"
    assert regional.formatar_data_hora(datetime(2026, 12, 31, 8, 5, 9)) == "31/12/2026 08:05"


def test_formato_desconhecido_cai_no_padrao_do_idioma():
    assert normalize_regional_format("xx") == REGIONAL_FORMAT_AUTO
    assert normalize_regional_format(None) == REGIONAL_FORMAT_AUTO


def test_datas_no_formato_dos_eua(eua):
    assert regional.formatar_data(date(2026, 12, 31)) == "12/31/2026"
    assert regional.formatar_data(date(2026, 3, 4)) == "03/04/2026"
    assert regional.formatar_data_hora(datetime(2026, 12, 31, 8, 5, 9), segundos=True) == "12/31/2026 08:05:09"
    assert regional.formatar_dia_mes(date(2026, 12, 31)) == "12/31"
    assert regional.formatar_mes(date(2026, 12, 31)) == "12/2026"


def test_hora_gravada_em_utc_aparece_no_fuso_do_sistema():
    # O banco devolve UTC. 02:30 UTC de 11/10 ainda é 23:30 de 10/10 em Brasília:
    # a hora e o DIA têm de sair no fuso do sistema, não em UTC.
    utc = datetime(2026, 10, 11, 2, 30, tzinfo=UTC)
    assert regional.formatar_data_hora(utc) == "10/10/2026 23:30"
    assert regional.formatar_data(utc) == "10/10/2026"
    assert _renderizar("{{ t|udatetime }}", t=utc) == "10/10/2026 23:30"


def test_data_ausente_nao_vira_texto():
    assert regional.formatar_data(None) == ""
    assert regional.formatar_data_hora(None) == ""


def test_dinheiro_troca_so_os_separadores_e_mantem_o_simbolo(eua):
    saida = _renderizar("{{ v|money }}|{{ v|money:'USD' }}|{{ v|money_signed }}", v=Decimal("-1234567.89"))
    assert saida == "R$ -1,234,567.89|US$ -1,234,567.89|- R$ 1,234,567.89"


def test_dinheiro_no_brasil_continua_igual():
    assert _renderizar("{{ v|money }}", v=Decimal("1234.56")) == "R$ 1.234,56"


def test_filtros_de_data_seguem_o_formato_ativo(eua):
    saida = _renderizar("{{ d|udate }}|{{ t|udatetime }}|{{ t|udatetime_s }}|{{ d|umonth }}",
                        d=date(2026, 12, 31), t=datetime(2026, 12, 31, 23, 59, 58))
    assert saida == "12/31/2026|12/31/2026 23:59|12/31/2026 23:59:58|12/2026"


def test_filtro_de_data_aceita_vazio():
    assert _renderizar("[{{ d|udate }}]", d=None) == "[]"


def test_regiao_auto_acompanha_o_idioma():
    assert resolve_regional_format("auto", "pt-br") == REGIONAL_FORMAT_BR
    assert resolve_regional_format("auto", "en") == REGIONAL_FORMAT_US
    # Escolha explícita ganha do idioma; valor desconhecido cai em `auto`.
    assert resolve_regional_format("br", "en") == REGIONAL_FORMAT_BR
    assert resolve_regional_format("us", "pt-br") == REGIONAL_FORMAT_US
    assert resolve_regional_format("../x", "en") == REGIONAL_FORMAT_US
    assert resolve_regional_format(None, None) == REGIONAL_FORMAT_BR


def test_ativar_resolve_o_auto_pelo_idioma_dado():
    token = regional.ativar("auto", "en")
    try:
        assert regional.formatar_data(date(2026, 12, 31)) == "12/31/2026"
    finally:
        regional.desativar(token)
    assert regional.formatar_data(date(2026, 12, 31)) == "31/12/2026"


def test_previa_mostra_data_numero_valor_e_hora():
    assert regional.exemplo("br") == "10/07/2026 · 1.234,56 · R$ 1.234,56 · 14:30"
    assert regional.exemplo("us") == "07/10/2026 · 1,234.56 · R$ 1,234.56 · 14:30"


def test_opcoes_de_regiao_sao_auto_br_us_e_o_auto_tem_previa_por_idioma():
    opcoes = regional.opcoes_de_regiao("en")
    assert [o["value"] for o in opcoes] == ["auto", "br", "us"]
    auto = opcoes[0]
    assert auto["preview"] == regional.exemplo("us")
    assert dict(auto["by_language"]) == {"pt-br": regional.exemplo("br"), "en": regional.exemplo("us")}


@pytest.mark.django_db
class TestPreferenciaDoUsuario:
    @pytest.fixture
    def usuario(self, client):
        user = get_user_model().objects.create_user(
            username="formato-regional", password="senha-segura", user_type="administrator",
        )
        client.force_login(user)
        return user

    def _salvar(self, client, **dados):
        return client.post(reverse("core:settings_update_locale"), dados)

    def test_quem_nasce_agora_comeca_em_portugues_e_no_padrao_do_idioma(self, usuario):
        assert usuario.language == "pt-br"
        assert usuario.regional_format == REGIONAL_FORMAT_AUTO

    def test_perfil_grava_a_escolha_e_recusa_valor_estranho(self, client, usuario):
        resposta = self._salvar(client, language="en", regional_format="us")
        assert resposta.status_code == 302
        usuario.refresh_from_db()
        assert (usuario.language, usuario.regional_format) == ("en", REGIONAL_FORMAT_US)

        self._salvar(client, language="../x", regional_format="../x")
        usuario.refresh_from_db()
        assert (usuario.language, usuario.regional_format) == ("pt-br", REGIONAL_FORMAT_AUTO)

    def test_perfil_oferece_idiomas_e_regioes_e_marca_a_escolhida(self, client, usuario):
        usuario.language = "en"
        usuario.regional_format = REGIONAL_FORMAT_BR
        usuario.save()
        resposta = client.get(reverse("core:settings_profile"))
        contexto = resposta.context
        assert [v for v, *_ in contexto["language_options"]] == ["pt-br", "en"]
        assert [o["value"] for o in contexto["regional_options"]] == ["auto", "br", "us"]
        assert contexto["current_language"] == "en"
        assert contexto["current_regional_format"] == REGIONAL_FORMAT_BR

    def test_cada_requisicao_usa_o_idioma_e_o_formato_do_seu_usuario(self, client, usuario):
        from django.test import Client

        usuario.regional_format = REGIONAL_FORMAT_US
        usuario.save()
        pagina = client.get(reverse("core:settings_profile")).content.decode()
        assert 'data-regional="us"' in pagina and 'lang="pt-br"' in pagina

        em_ingles = get_user_model().objects.create_user(
            username="formato-en", password="senha-segura", user_type="administrator", language="en",
        )
        cliente_en = Client()
        cliente_en.force_login(em_ingles)
        pagina_en = cliente_en.get(reverse("core:settings_profile")).content.decode()
        # `auto` + inglês = formato dos EUA, sem ninguém ter escolhido a região.
        assert 'data-regional="us"' in pagina_en and 'lang="en"' in pagina_en

        outro = get_user_model().objects.create_user(
            username="formato-br", password="senha-segura", user_type="administrator",
        )
        cliente_br = Client()
        cliente_br.force_login(outro)
        pagina_br = cliente_br.get(reverse("core:settings_profile")).content.decode()
        assert 'data-regional="br"' in pagina_br and 'lang="pt-br"' in pagina_br
        # E nada ficou ativo depois das requisições: fora delas vale o Brasil em português.
        assert regional.formatar_data(date(2026, 12, 31)) == "31/12/2026"
        assert translation.get_language() == "pt-br"

    def test_tela_de_login_segue_o_idioma_do_navegador_e_cai_no_portugues(self, client):
        em_ingles = client.get(reverse("login"), headers={"Accept-Language": "en-US,en;q=0.9"})
        assert 'lang="en"' in em_ingles.content.decode()
        assert "Accept-Language" in em_ingles.headers["Vary"]
        em_alemao = client.get(reverse("login"), headers={"Accept-Language": "de-DE"})
        assert 'lang="pt-br"' in em_alemao.content.decode()
