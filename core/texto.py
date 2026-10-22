"""Utilitários de texto compartilhados."""

from __future__ import annotations

import unicodedata


def sem_acentos(texto: str | None) -> str:
    """O texto sem os acentos: "ação" vira "acao". Não altera caixa nem espaços."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c))
