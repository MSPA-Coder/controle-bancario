"""Chaves e valores permitidos para configurações da aplicação."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Tema e densidade de tabela sao preferencias por usuario e ficam em
# `AppUser.ui_theme` / `AppUser.table_scroll_rows`, nao em app_setting.
APP_SETTING_LAST_OPTIMIZE_INFO: Final = "last_optimize_info"
APP_SETTING_PROJECTION_HORIZON_MONTHS: Final = "projection_horizon_months"
APP_SETTING_PROJECTION_RUN_DAY: Final = "projection_run_day"
APP_SETTING_LAST_PROJECTION_RUN: Final = "last_projection_run"
APP_SETTING_SYSTEM_START_DATE: Final = "system_start_date"
APP_SETTING_PASSWORD_MIN_LENGTH: Final = "password_min_length"
APP_SETTING_PASSWORD_MIN_UPPERCASE: Final = "password_min_uppercase"
APP_SETTING_PASSWORD_MIN_NUMBERS: Final = "password_min_numbers"
APP_SETTING_PASSWORD_MIN_SPECIAL: Final = "password_min_special"
APP_SETTING_LOGIN_LOCK_MAX_FAILURES: Final = "login_lock_max_failures"
APP_SETTING_LOGIN_LOCK_MINUTES: Final = "login_lock_minutes"

UI_THEME_LIGHT: Final = "light"
UI_THEME_DARK: Final = "dark"
UI_THEME_SOLARIZED_LIGHT: Final = "solarized_light"
UI_THEME_SOLARIZED_DARK: Final = "solarized_dark"
UI_THEME_DRACULA: Final = "dracula"
UI_THEME_NORD: Final = "nord"
UI_THEME_MONOKAI: Final = "monokai"
UI_THEME_GRAY: Final = "gray"
UI_THEME_SOFT_LIGHT: Final = "soft_light"
UI_THEME_SOFT_DARK: Final = "soft_dark"
UI_THEME_CORPORATE_BLUE: Final = "corporate_blue"
UI_THEME_EMERALD: Final = "emerald"
VALID_UI_THEMES: Final = (
    UI_THEME_LIGHT,
    UI_THEME_DARK,
    UI_THEME_SOLARIZED_LIGHT,
    UI_THEME_SOLARIZED_DARK,
    UI_THEME_DRACULA,
    UI_THEME_NORD,
    UI_THEME_MONOKAI,
    UI_THEME_GRAY,
    UI_THEME_SOFT_LIGHT,
    UI_THEME_SOFT_DARK,
    UI_THEME_CORPORATE_BLUE,
    UI_THEME_EMERALD,
)
UI_THEME_LABELS: Final = {
    UI_THEME_LIGHT: "Light",
    UI_THEME_DARK: "Dark",
    UI_THEME_SOLARIZED_LIGHT: "Solarized Light",
    UI_THEME_SOLARIZED_DARK: "Solarized Dark",
    UI_THEME_DRACULA: "Dracula",
    UI_THEME_NORD: "Nord",
    UI_THEME_MONOKAI: "Monokai",
    UI_THEME_GRAY: "Gray Scale",
    UI_THEME_SOFT_LIGHT: "Soft Light",
    UI_THEME_SOFT_DARK: "Soft Dark",
    UI_THEME_CORPORATE_BLUE: "Corporate Blue",
    UI_THEME_EMERALD: "Emerald",
}
UI_THEME_DESCRIPTIONS: Final = {
    UI_THEME_LIGHT: "Claro e neutro",
    UI_THEME_DARK: "Escuro e focado",
    UI_THEME_SOLARIZED_LIGHT: "Claro suave",
    UI_THEME_SOLARIZED_DARK: "Escuro suave",
    UI_THEME_DRACULA: "Alto contraste",
    UI_THEME_NORD: "Azul frio",
    UI_THEME_MONOKAI: "Técnico vibrante",
    UI_THEME_GRAY: "Neutro analítico",
    UI_THEME_SOFT_LIGHT: "Claro confortável",
    UI_THEME_SOFT_DARK: "Escuro confortável",
    UI_THEME_CORPORATE_BLUE: "Azul corporativo",
    UI_THEME_EMERALD: "Verde financeiro",
}


def normalize_ui_theme(value: str | None) -> str:
    return value if value in VALID_UI_THEMES else UI_THEME_LIGHT


# Idioma da interface (`AppUser.language`). Só os textos que o usuário lê: dados
# gravados, logs, importação e exportação não mudam com ele. O português é a
# língua-fonte dos textos; o inglês vem do catálogo em `locale/` (que só passa a
# existir na etapa de tradução: até lá o `en` cai no português).
LANGUAGE_PT_BR: Final = "pt-br"
LANGUAGE_EN: Final = "en"
VALID_LANGUAGES: Final = (LANGUAGE_PT_BR, LANGUAGE_EN)
DEFAULT_LANGUAGE: Final = LANGUAGE_PT_BR
# Cada idioma aparece no próprio idioma: quem não lê o atual ainda acha o seu.
LANGUAGE_LABELS: Final = {
    LANGUAGE_PT_BR: "Português (Brasil)",
    LANGUAGE_EN: "English (US)",
}
LANGUAGE_LOCALES: Final = {LANGUAGE_PT_BR: "pt-BR", LANGUAGE_EN: "en-US"}


def normalize_language(value: str | None) -> str:
    return value if value in VALID_LANGUAGES else DEFAULT_LANGUAGE


# Formato regional de datas e números na tela (`AppUser.regional_format`).
# Só apresentação e digitação: o que é gravado, exportado ou importado não muda.
# `auto` acompanha o idioma; `br` e `us` fixam a região. As chaves `br` e `us`
# já estavam gravadas, por isso não foram trocadas por tags de locale.
REGIONAL_FORMAT_AUTO: Final = "auto"
REGIONAL_FORMAT_BR: Final = "br"
REGIONAL_FORMAT_US: Final = "us"
VALID_REGIONAL_FORMATS: Final = (REGIONAL_FORMAT_AUTO, REGIONAL_FORMAT_BR, REGIONAL_FORMAT_US)
DEFAULT_REGIONAL_FORMAT: Final = REGIONAL_FORMAT_AUTO

# Região que `auto` escolhe para cada idioma.
REGIONAL_FORMAT_FOR_LANGUAGE: Final = {
    LANGUAGE_PT_BR: REGIONAL_FORMAT_BR,
    LANGUAGE_EN: REGIONAL_FORMAT_US,
}


@dataclass(frozen=True)
class RegionalSpec:
    """Como uma região escreve datas e números. Incluir região = uma linha na tabela."""

    code: str
    locale: str  # tag BCP 47, para `Intl`/`toLocaleString` no navegador
    date_order: str  # "dmy", "mdy" ou "ymd"
    date_sep: str
    decimal_sep: str
    thousands_sep: str

    @property
    def date_pattern(self) -> str:
        """Padrão `strftime` da data completa."""
        partes = {"d": "%d", "m": "%m", "y": "%Y"}
        return self.date_sep.join(partes[letra] for letra in self.date_order)

    @property
    def month_pattern(self) -> str:
        """Padrão `strftime` de mês e ano."""
        return self.date_sep.join(("%Y", "%m") if self.date_order == "ymd" else ("%m", "%Y"))

    @property
    def day_month_pattern(self) -> str:
        """Padrão `strftime` de dia e mês, sem o ano."""
        return self.date_sep.join(("%m", "%d") if self.date_order in ("mdy", "ymd") else ("%d", "%m"))

    def as_dict(self) -> dict[str, str]:
        """O que o navegador precisa para ler e escrever datas e números."""
        return {
            "code": self.code,
            "locale": self.locale,
            "dateOrder": self.date_order,
            "dateSep": self.date_sep,
            "decimal": self.decimal_sep,
            "thousands": self.thousands_sep,
        }


REGIONAL_SPECS: Final = {
    REGIONAL_FORMAT_BR: RegionalSpec(REGIONAL_FORMAT_BR, "pt-BR", "dmy", "/", ",", "."),
    REGIONAL_FORMAT_US: RegionalSpec(REGIONAL_FORMAT_US, "en-US", "mdy", "/", ".", ","),
}


def normalize_regional_format(value: str | None) -> str:
    return value if value in VALID_REGIONAL_FORMATS else DEFAULT_REGIONAL_FORMAT


def resolve_regional_format(value: str | None, language: str | None) -> str:
    """Região efetiva (`br` ou `us`): `auto` segue o idioma."""
    normalizado = normalize_regional_format(value)
    if normalizado != REGIONAL_FORMAT_AUTO:
        return normalizado
    return REGIONAL_FORMAT_FOR_LANGUAGE.get(normalize_language(language), REGIONAL_FORMAT_BR)


TABLE_SCROLL_ROWS_MIN: Final = 5
TABLE_SCROLL_ROWS_MAX: Final = 200


def normalize_table_scroll_rows(value: object, default: int = 15) -> int:
    if not isinstance(value, (int, float, str)):
        return default
    try:
        rows = int(value)
    except (TypeError, ValueError):
        return default
    return max(TABLE_SCROLL_ROWS_MIN, min(rows, TABLE_SCROLL_ROWS_MAX))
