"""Idioma e formato regional de apresentação, por usuário.

Só UX: decide como datas e números aparecem e são digitados na tela. O que o
servidor recebe, grava, exporta ou importa não passa por aqui -- continua ISO
(`AAAA-MM-DD`) e decimal com ponto (`1234.56`), como sempre foi.

A região efetiva (`br` ou `us`) do usuário da requisição fica numa `ContextVar`
preenchida pelo `FormatoRegionalMiddleware`; `auto` já chega resolvida pelo
idioma. Fora de uma requisição (comando de manutenção, teste de serviço) vale o
Brasil, que é o que o sistema sempre mostrou.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from core.domain.settings import (
    REGIONAL_FORMAT_AUTO,
    REGIONAL_FORMAT_BR,
    REGIONAL_FORMAT_US,
    REGIONAL_SPECS,
    VALID_LANGUAGES,
    RegionalSpec,
    resolve_regional_format,
)

_formato: ContextVar[str] = ContextVar("formato_regional", default=REGIONAL_FORMAT_BR)

# Exemplo mostrado na prévia: o mesmo valor em todas as regiões, para a diferença
# saltar aos olhos.
_EXEMPLO_DATA = datetime(2026, 7, 10, 14, 30)
_EXEMPLO_NUMERO = Decimal("1234.56")


def ativar(formato: str | None, idioma: str | None = None):
    """Ativa a região do usuário e devolve o token para `desativar`.

    `auto` (e qualquer valor desconhecido) acompanha o idioma; sem `idioma`, vale o
    idioma ativo na requisição.
    """
    return _formato.set(resolve_regional_format(formato, idioma or get_language()))


def desativar(token) -> None:
    _formato.reset(token)


def especificacao(codigo: str | None = None) -> RegionalSpec:
    """Especificação da região `codigo`, ou da região ativa."""
    return REGIONAL_SPECS[codigo or _formato.get()]


def _local(valor: date | datetime) -> date | datetime:
    """Leva um `datetime` com fuso para o fuso do sistema antes de formatar.

    O banco devolve `DateTimeField` em UTC; formatar direto mostraria a hora (e,
    perto da meia-noite, o dia) três horas à frente de Brasília. `date` e
    `datetime` sem fuso passam como vieram.
    """
    if isinstance(valor, datetime) and timezone.is_aware(valor):
        return timezone.localtime(valor)
    return valor


def formatar_data(valor: date | datetime | None, *, ausente: str = "") -> str:
    if not valor:
        return ausente
    return _local(valor).strftime(especificacao().date_pattern)


def formatar_data_hora(valor: datetime | None, *, segundos: bool = False, ausente: str = "") -> str:
    if not valor:
        return ausente
    hora = "%H:%M:%S" if segundos else "%H:%M"
    return _local(valor).strftime(f"{especificacao().date_pattern} {hora}")


def formatar_mes(valor: date | datetime | None, *, ausente: str = "") -> str:
    if not valor:
        return ausente
    return _local(valor).strftime(especificacao().month_pattern)


def formatar_dia_mes(valor: date | datetime | None, *, ausente: str = "") -> str:
    if not valor:
        return ausente
    return _local(valor).strftime(especificacao().day_month_pattern)


def adaptar_numero(texto: str, codigo: str | None = None) -> str:
    """Troca os separadores de um número já formatado no padrão brasileiro.

    `1.234,56` vira `1,234.56` no formato EUA. O marcador `\\x00` evita passar
    duas vezes pelo mesmo caractere (o mesmo cuidado de `sharedauth.formatting`).
    """
    spec = especificacao(codigo)
    if spec.code == REGIONAL_FORMAT_BR:
        return texto
    return (
        texto.replace(".", "\x00").replace(",", spec.decimal_sep).replace("\x00", spec.thousands_sep)
    )


def exemplo(codigo: str, simbolo: str = "R$") -> str:
    """Prévia de uma região: data, número, valor e hora, separados por ponto médio."""
    spec = especificacao(codigo)
    brasileiro = f"{_EXEMPLO_NUMERO:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    numero = adaptar_numero(brasileiro, codigo)
    return " · ".join((
        _EXEMPLO_DATA.strftime(spec.date_pattern),
        numero,
        f"{simbolo} {numero}",
        _EXEMPLO_DATA.strftime("%H:%M"),
    ))


def opcoes_de_regiao(idioma: str | None) -> list[dict[str, str]]:
    """Opções do seletor de região: `auto`, `br` e `us`, cada uma com a sua prévia."""
    efetiva_do_idioma = resolve_regional_format(REGIONAL_FORMAT_AUTO, idioma)
    return [
        {
            "value": REGIONAL_FORMAT_AUTO,
            "label": _("Padrão do idioma"),
            "preview": exemplo(efetiva_do_idioma),
            # A prévia do `auto` depende do idioma escolhido na mesma tela.
            "by_language": [
                (idioma_, exemplo(resolve_regional_format(REGIONAL_FORMAT_AUTO, idioma_)))
                for idioma_ in VALID_LANGUAGES
            ],
        },
        {"value": REGIONAL_FORMAT_BR, "label": _("Brasil (pt-BR)"), "preview": exemplo(REGIONAL_FORMAT_BR)},
        {"value": REGIONAL_FORMAT_US, "label": _("Estados Unidos (en-US)"), "preview": exemplo(REGIONAL_FORMAT_US)},
    ]
