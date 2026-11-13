"""Filtros de apresentação da trilha de auditoria (código gravado -> rótulo).

O mapa e a regra de fallback moram em `core/audit_labels.py`; aqui só a ponte
para o template. Nenhum filtro altera o que está gravado.
"""

from __future__ import annotations

from django import template

from core import audit_labels

register = template.Library()


@register.filter
def rotulo_entidade(value) -> str:
    """Nome legível da entidade ou tabela; sem rótulo, o código como está."""
    return audit_labels.rotulo_entidade(value)


@register.filter
def rotulo_acao(value) -> str:
    """Nome legível da ação ou evento; sem rótulo, o código como está."""
    return audit_labels.rotulo_acao(value)


@register.filter
def rotulo_resultado(value) -> str:
    """Nome legível do resultado; sem rótulo, o código como está."""
    return audit_labels.rotulo_resultado(value)


@register.filter
def rotulo_resumo(value) -> str:
    """Resumo no idioma de quem lê, se for um texto fixo conhecido."""
    return audit_labels.rotulo_resumo(value)
