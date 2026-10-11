"""Filtros de data e número no formato regional do usuário (Brasil ou EUA).

Substituem os `|date:"d/m/Y"` espalhados pelos templates. Só os textos que o
usuário LÊ passam por aqui; valores de `<input>` e atributos de máquina seguem
em ISO (`|date:'Y-m-d'`), porque é o que o servidor espera receber.
"""

from __future__ import annotations

from datetime import date

from django import template
from django.utils.translation import gettext

from core import regional

register = template.Library()


@register.filter
def udate(value) -> str:
    """31/12/2026 no Brasil, 12/31/2026 nos EUA. Vazio se não há data."""
    return regional.formatar_data(value)


@register.filter
def udatetime(value) -> str:
    """Data e hora até o minuto no formato do usuário."""
    return regional.formatar_data_hora(value)


@register.filter
def udatetime_s(value) -> str:
    """Data e hora até o segundo no formato do usuário."""
    return regional.formatar_data_hora(value, segundos=True)


@register.filter
def traduzido(value) -> str:
    """Mostra no idioma de quem lê um texto que foi gravado em português.

    Serve a registros de vida curta (o erro de leitura de um arquivo na fila de
    importação), gravados com o texto de uma mensagem já marcada: se o texto
    existir no catálogo, sai na língua ativa; se não existir (mensagem com valor
    embutido, por exemplo), sai como foi gravado. Vazio continua vazio: o
    `gettext("")` devolveria o cabeçalho do catálogo.
    """
    return gettext(value) if value else ""


@register.filter
def udaymonth(value) -> str:
    """Dia e mês sem o ano (11/10 no Brasil, 10/11 nos EUA). Aceita data ou texto ISO (2026-10-11)."""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            return value
    return regional.formatar_dia_mes(value)


@register.filter
def umonth(value) -> str:
    """12/2026 nos dois formatos (mês antes do ano em ambos)."""
    return regional.formatar_mes(value)
