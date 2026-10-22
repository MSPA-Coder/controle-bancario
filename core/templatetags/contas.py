"""Seletores de conta agrupados por titular.

Dois titulares podem ter contas de mesmo nome na mesma instituição ("C6 /
Conta 02"), e uma lista plana deixa as duas lado a lado, difíceis de
distinguir -- foi assim que um extrato caiu na conta errada. Agrupar por
titular (`<optgroup>`) deixa o titular no cabeçalho da lista aberta, e o
rótulo da opção (`rotulo_conta`) repete o titular para que o seletor fechado
também diga de qual conta se trata ("Titular / Instituição / Conta").

O filtro ordena aqui, e não nas views, porque cada tela monta a sua lista de
contas de um jeito e `{% regroup %}` exige a sequência já ordenada pela chave.
"""

from __future__ import annotations

from django.template import Library

register = Library()


@register.filter
def rotulo_conta(conta):
    """"Titular / Instituição / Conta": o texto da opção de um seletor de conta."""
    return f"{conta.owner.name} / {conta.institution.institution_name} / {conta.account_name}"


@register.filter
def por_titular(contas):
    """[(nome do titular, [contas]), ...], titulares em ordem alfabética.

    Dentro de cada titular a ordem original da lista é mantida.
    """
    grupos: dict[str, list] = {}
    for conta in contas or []:
        grupos.setdefault(conta.owner.name, []).append(conta)
    return sorted(grupos.items(), key=lambda item: item[0].casefold())
