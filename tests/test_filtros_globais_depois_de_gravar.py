"""Gravar não devolve a tela à moeda e aos grupos padrão.

Em 20/10/2026, depois de lançar em Saldo aplicações, os filtros globais das
contas voltavam ao padrão: a view redirecionava para o endereço limpo. Não era
só ela -- Importações, Conciliação, Anexos, Faturas e Configurações faziam o
mesmo, porque só as views que usam `core.volta.url_de_volta` repunham os
globais. `FiltrosGlobaisNaVoltaMiddleware` cobre todas: o destino de qualquer
POST que redireciona ganha a moeda e os grupos da tela de origem.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory
from django.urls import reverse

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from core.volta import FiltrosGlobaisNaVoltaMiddleware


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}


def _resposta(request, destino, cabecalho="Location"):
    def view(_request):
        if cabecalho == "Location":
            return HttpResponseRedirect(destino)
        resposta = HttpResponse(status=200)
        resposta[cabecalho] = destino
        return resposta

    return FiltrosGlobaisNaVoltaMiddleware(view)(request)


def test_redirect_depois_de_gravar_leva_moeda_e_grupos_da_origem():
    request = RequestFactory().post("/banking/atualizar-saldo/", {"volta": "currency=USD&grupos=cartoes&conta=3"})

    resposta = _resposta(request, "/banking/atualizar-saldo/")

    # Só os globais: o resto da query é assunto de cada view.
    assert _query(resposta["Location"]) == {"currency": "USD", "grupos": "cartoes"}
    assert urlsplit(resposta["Location"]).path == "/banking/atualizar-saldo/"


def test_o_que_a_view_escreveu_no_destino_vence():
    request = RequestFactory().post("/x/", {"volta": "currency=USD&grupos=cartoes"})

    resposta = _resposta(request, "/y/?currency=BRL&line_id=7")

    assert _query(resposta["Location"]) == {"currency": "BRL", "line_id": "7", "grupos": "cartoes"}


def test_sem_campo_volta_vale_a_query_do_action():
    request = RequestFactory().post("/x/?currency=USD")

    assert _query(_resposta(request, "/y/")["Location"]) == {"currency": "USD"}


def test_hx_redirect_tambem_leva_os_globais():
    request = RequestFactory().post("/x/", {"volta": "grupos=bancos"})

    assert _query(_resposta(request, "/y/", cabecalho="HX-Redirect")["HX-Redirect"]) == {"grupos": "bancos"}


def test_destino_de_outro_host_e_get_ficam_como_estao():
    request = RequestFactory().post("/x/", {"volta": "currency=USD"})
    assert _resposta(request, "https://outro.exemplo/y/")["Location"] == "https://outro.exemplo/y/"

    request = RequestFactory().get("/x/?currency=USD")
    assert _resposta(request, "/y/")["Location"] == "/y/"


def test_origem_sem_globais_nao_suja_o_endereco():
    request = RequestFactory().post("/x/", {"volta": "conta=3"})

    assert _resposta(request, "/y/")["Location"] == "/y/"


@pytest.mark.django_db
def test_middleware_instalado_numa_tela_que_grava_e_redireciona(client):
    user = AppUser.objects.create_user(username="filtros-globais", password="senha-segura")
    titular = AccountOwner.objects.create(name="Titular")
    UserOwnerAccess.objects.create(
        user=user, owner=titular, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    client.force_login(user)

    # Ignorar uma linha volta para a Conciliação (aqui com erro, que também volta).
    resposta = client.post(
        reverse("bank_statements:ignore_line"), {"line_id": "999999", "volta": "currency=USD&grupos=cartoes"}
    )

    assert resposta.status_code == 302
    assert urlsplit(resposta["Location"]).path == reverse("bank_statements:reconciliation_view")
    assert _query(resposta["Location"]) == {"currency": "USD", "grupos": "cartoes"}


@pytest.mark.django_db
def test_saldo_aplicacoes_diz_que_o_saldo_e_o_liquido(client):
    user = AppUser.objects.create_user(username="saldo-liquido", password="senha-segura")
    client.force_login(user)

    html = client.get(reverse("bank_statements:atualizar_saldo")).content.decode()

    assert "líquido para resgate" in html
    assert "já sem IR e IOF" in html
