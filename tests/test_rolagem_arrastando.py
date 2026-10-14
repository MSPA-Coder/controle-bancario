"""Rolagem horizontal arrastando com o botão esquerdo (`static/js/core/drag-scroll.js`).

O comportamento é de navegador e foi conferido nele; aqui fica o que o servidor
garante: o script é carregado em toda página com o menu (`base.html`), existe no
disco, e o CSS do cursor/arrasto está no estilo compartilhado.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

RAIZ = Path(__file__).resolve().parent.parent


@pytest.mark.django_db
def test_pagina_com_menu_carrega_o_script_de_arrasto(client):
    user = get_user_model().objects.create_user(
        username="arrasto", password="senha-segura", user_type="administrator",
    )
    client.force_login(user)

    html = client.get("/dashboard/").content.decode()

    assert "js/core/drag-scroll" in html


def test_script_e_estilo_existem():
    script = (RAIZ / "static" / "js" / "core" / "drag-scroll.js").read_text(encoding="utf-8")
    css = (RAIZ / "static" / "css" / "core" / "application.css").read_text(encoding="utf-8")

    assert "evento.button !== 0" in script  # só o botão esquerdo
    assert "html.drag-scrolling" in css and ".is-drag-scrolling" in css and ".drag-scroll-ready" in css
