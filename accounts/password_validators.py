"""Validador de senha com política configurável via AppSetting.

Tamanho mínimo configurável (com piso de 8 caracteres, que a configuração não
pode furar) mais requisitos opcionais de maiúsculas, números e especiais.

Ocupa o lugar de `MinimumLengthValidator` em AUTH_PASSWORD_VALIDATORS de
propósito: os dois juntos aplicariam mínimos diferentes, e a tela
Configurações > Parâmetros passaria a exibir um valor que não é o realmente
aplicado.
"""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext, ngettext

DEFAULT_MIN_LENGTH = 8
DEFAULT_MIN_UPPERCASE = 0
DEFAULT_MIN_NUMBERS = 0
DEFAULT_MIN_SPECIAL = 0
MIN_LENGTH_FLOOR = 8
MAX_LENGTH_CEILING = 256

_SPECIAL_CHARS_RE = re.compile(r"[^A-Za-z0-9]")
_UPPERCASE_RE = re.compile(r"[A-Z]")
_NUMBER_RE = re.compile(r"[0-9]")


def _current_settings():
    from core.domain.settings import (
        APP_SETTING_PASSWORD_MIN_LENGTH,
        APP_SETTING_PASSWORD_MIN_NUMBERS,
        APP_SETTING_PASSWORD_MIN_SPECIAL,
        APP_SETTING_PASSWORD_MIN_UPPERCASE,
    )
    from core.services import get_app_setting

    def _int_setting(key, default):
        try:
            return int(get_app_setting(key, str(default)))
        except (TypeError, ValueError):
            return default

    return {
        "min_length": max(_int_setting(APP_SETTING_PASSWORD_MIN_LENGTH, DEFAULT_MIN_LENGTH), MIN_LENGTH_FLOOR),
        "min_uppercase": max(_int_setting(APP_SETTING_PASSWORD_MIN_UPPERCASE, DEFAULT_MIN_UPPERCASE), 0),
        "min_numbers": max(_int_setting(APP_SETTING_PASSWORD_MIN_NUMBERS, DEFAULT_MIN_NUMBERS), 0),
        "min_special": max(_int_setting(APP_SETTING_PASSWORD_MIN_SPECIAL, DEFAULT_MIN_SPECIAL), 0),
    }


def current_min_length() -> int:
    """Tamanho mínimo de senha em vigor, já com o piso aplicado.

    Público porque a redefinição de senha precisa dele: o sorteio da senha
    temporária tem de produzir algo que esta mesma política aceite. Sem isso, a
    instalação que configurar 20 caracteres teria a redefinição recusando a
    própria senha que acabou de sortear -- foi o que aconteceu no banco local,
    configurado em 15 contra um sorteio de 12.
    """
    try:
        return int(_current_settings()["min_length"])
    except Exception:
        return DEFAULT_MIN_LENGTH


class ConfigurablePasswordPolicyValidator:
    """Substitui MinimumLengthValidator: lê a política de app_setting em tempo real."""

    def validate(self, password, user=None):
        try:
            policy = _current_settings()
        except Exception:
            policy = {
                "min_length": DEFAULT_MIN_LENGTH,
                "min_uppercase": DEFAULT_MIN_UPPERCASE,
                "min_numbers": DEFAULT_MIN_NUMBERS,
                "min_special": DEFAULT_MIN_SPECIAL,
            }

        if len(password) < policy["min_length"]:
            raise ValidationError(
                gettext("A senha deve ter pelo menos %(minimo)s caracteres.") % {"minimo": policy["min_length"]},
                code="password_too_short",
            )
        if len(password) > MAX_LENGTH_CEILING:
            raise ValidationError(
                gettext("A senha deve ter no máximo %(maximo)s caracteres.") % {"maximo": MAX_LENGTH_CEILING},
                code="password_too_long",
            )
        if policy["min_uppercase"] and len(_UPPERCASE_RE.findall(password)) < policy["min_uppercase"]:
            n = policy["min_uppercase"]
            raise ValidationError(
                ngettext(
                    "A senha deve conter pelo menos %(n)s letra maiúscula.",
                    "A senha deve conter pelo menos %(n)s letras maiúsculas.",
                    n,
                ) % {"n": n},
                code="password_missing_uppercase",
            )
        if policy["min_numbers"] and len(_NUMBER_RE.findall(password)) < policy["min_numbers"]:
            n = policy["min_numbers"]
            raise ValidationError(
                ngettext(
                    "A senha deve conter pelo menos %(n)s número.",
                    "A senha deve conter pelo menos %(n)s números.",
                    n,
                ) % {"n": n},
                code="password_missing_number",
            )
        if policy["min_special"] and len(_SPECIAL_CHARS_RE.findall(password)) < policy["min_special"]:
            n = policy["min_special"]
            raise ValidationError(
                ngettext(
                    "A senha deve conter pelo menos %(n)s caractere especial.",
                    "A senha deve conter pelo menos %(n)s caracteres especiais.",
                    n,
                ) % {"n": n},
                code="password_missing_special",
            )

    def get_help_text(self):
        try:
            policy = _current_settings()
        except Exception:
            return gettext("Sua senha deve ter pelo menos %(minimo)s caracteres.") % {"minimo": DEFAULT_MIN_LENGTH}
        parts = [gettext("pelo menos %(n)s caracteres") % {"n": policy["min_length"]}]
        if policy["min_uppercase"]:
            n = policy["min_uppercase"]
            parts.append(ngettext("%(n)s maiúscula", "%(n)s maiúsculas", n) % {"n": n})
        if policy["min_numbers"]:
            n = policy["min_numbers"]
            parts.append(ngettext("%(n)s número", "%(n)s números", n) % {"n": n})
        if policy["min_special"]:
            n = policy["min_special"]
            parts.append(ngettext("%(n)s caractere especial", "%(n)s caracteres especiais", n) % {"n": n})
        return gettext("Sua senha deve conter %(requisitos)s.") % {"requisitos": ", ".join(parts)}
