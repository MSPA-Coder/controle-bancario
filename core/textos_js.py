"""Textos que o JavaScript mostra ao usuário, no idioma da requisição.

O JS não tem catálogo próprio: o servidor entrega estes textos prontos num JSON
(`#i18n-js` em `templates/base.html`) e `static/js/core/i18n.js` expõe `t()`.

Para mostrar um texto novo no JS:

1. escreva `t('Texto em português')` no `.js` (com `%(nome)s` para valores,
   `t('Faltam %(n)s', {n: 3})`);
2. acrescente o MESMO texto, idêntico, em `FONTES` abaixo, dentro de
   `gettext_noop(...)` -- é o que faz `makemessages` enxergá-lo.

`tests/test_textos_js.py` reprova um `t('...')` que não esteja em `FONTES`.
O texto em português é a chave: quem lê o `.js` vê a frase, não um identificador.
"""

from __future__ import annotations

from django.utils.translation import gettext, gettext_noop

FONTES: tuple[str, ...] = (
    # Diálogo de confirmação (rótulos padrão que o SharedAuth traria em português).
    gettext_noop("Confirmar"),
    gettext_noop("Cancelar"),
)


def textos_js() -> dict[str, str]:
    """`{texto em português: texto no idioma ativo}` para o JSON da página."""
    return {fonte: gettext(fonte) for fonte in FONTES}
