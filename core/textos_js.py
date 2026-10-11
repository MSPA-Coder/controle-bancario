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
    # static/js/core/application.js: validação nativa, modo discreto e menu lateral.
    gettext_noop("Selecione uma opção."),
    gettext_noop("Selecione um arquivo."),
    gettext_noop("Informe uma data."),
    gettext_noop("Preencha este campo."),
    gettext_noop("Informe um valor válido."),
    gettext_noop("Informe um valor igual ou maior que o mínimo permitido."),
    gettext_noop("Informe um valor igual ou menor que o máximo permitido."),
    gettext_noop("Informe um valor válido para este campo."),
    gettext_noop("Informe um valor no formato solicitado."),
    gettext_noop("Corrija este campo antes de continuar."),
    gettext_noop("Ativar modo discreto"),
    gettext_noop("Desativar modo discreto"),
    gettext_noop("Valor oculto"),
    gettext_noop("Expandir menu"),
    gettext_noop("Recolher menu"),
    # static/js/core/regional.js: campos de data, mês e valor (os de validação
    # acima já são usados aqui e não se repetem).
    gettext_noop("Informe uma data válida (%(formato)s)."),
    gettext_noop("Informe um mês válido (%(formato)s)."),
    gettext_noop("Informe um valor numérico válido."),
    gettext_noop("Informe uma data a partir de %(data)s."),
    gettext_noop("Informe um mês a partir de %(data)s."),
    gettext_noop("Informe uma data até %(data)s."),
    gettext_noop("Informe um mês até %(data)s."),
    gettext_noop("dd"),
    gettext_noop("mm"),
    gettext_noop("aaaa"),
    gettext_noop("Abrir calendário"),
    gettext_noop("Escolher mês"),
    # static/js/dashboard.js: rótulos e tooltips dos gráficos do Painel.
    gettext_noop("Cobertura"),
    gettext_noop("Cobertura: %(valor)sx"),
    gettext_noop("Geração mensal"),
    gettext_noop("Média 3m"),
    gettext_noop("Saldo diário"),
    gettext_noop("Receitas"),
    gettext_noop("Despesas"),
    gettext_noop("Geração"),
    gettext_noop("Saldo"),
    gettext_noop("Valores"),
    # Mesmo texto que o servidor usa para a fatia sem grupo; o JS compara com ele.
    gettext_noop("Sem grupo"),
    # static/js/transactions.js: diálogo ao editar com escopo "este e os próximos".
    gettext_noop("Este registro e os próximos serão recriados. Deseja continuar?"),
    gettext_noop("Confirmar alteração"),
    # static/js/profile.js: diálogo ao trocar o tema.
    gettext_noop("Salvar este tema como sua preferência?"),
    gettext_noop("Confirmar tema"),
)


def textos_js() -> dict[str, str]:
    """`{texto em português: texto no idioma ativo}` para o JSON da página."""
    return {fonte: gettext(fonte) for fonte in FONTES}
