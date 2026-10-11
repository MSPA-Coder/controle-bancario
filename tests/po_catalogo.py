"""Leitor mínimo do catálogo `.po` para os testes de paridade (sem dependência externa).

Entende o formato que o `makemessages --no-wrap` gera: entradas separadas por linha em
branco, `msgid`/`msgid_plural`/`msgstr[n]` e continuação em linhas `"..."`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CATALOGO_EN = RAIZ / "locale" / "en" / "LC_MESSAGES" / "django.po"

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}
_MARCADOR = re.compile(r"%(?:\([A-Za-z_]\w*\))?[#0\- +]*\d*(?:\.\d+)?[sdifr%]")
_LINHA = re.compile(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+"(.*)"$')


def _desescapar(texto: str) -> str:
    saida, i = [], 0
    while i < len(texto):
        if texto[i] == "\\" and i + 1 < len(texto):
            saida.append(_ESCAPES.get(texto[i + 1], texto[i + 1]))
            i += 2
        else:
            saida.append(texto[i])
            i += 1
    return "".join(saida)


@dataclass
class Entrada:
    comentarios: list[str] = field(default_factory=list)
    msgid: str = ""
    plural: str | None = None
    msgstr: list[str] = field(default_factory=lambda: [""])

    @property
    def flags(self) -> set[str]:
        achados: set[str] = set()
        for linha in self.comentarios:
            if linha.startswith("#, "):
                achados.update(parte.strip() for parte in linha[3:].split(","))
        return achados

    @property
    def origens(self) -> list[tuple[str, str]]:
        """Pares (texto-fonte, tradução) de cada forma: singular e, se houver, plural."""
        pares = [(self.msgid, self.msgstr[0])]
        if self.plural is not None:
            pares.append((self.plural, self.msgstr[1] if len(self.msgstr) > 1 else ""))
        return pares


def marcadores(texto: str) -> list[str]:
    """Marcadores de formatação (`%(n)s`, `%(n)02d`, `%%`), ordenados, para comparar fonte e tradução."""
    return sorted(_MARCADOR.findall(texto))


def ler(caminho: Path = CATALOGO_EN) -> tuple[str, list[Entrada]]:
    """Devolve (texto do cabeçalho, entradas de tradução)."""
    texto = caminho.read_text(encoding="utf-8").replace("\r\n", "\n")
    entradas: list[Entrada] = []
    for bloco in (b for b in texto.split("\n\n") if b.strip()):
        entrada, campo, indice = Entrada(), None, 0
        for linha in bloco.strip("\n").split("\n"):
            if linha.startswith("#"):
                entrada.comentarios.append(linha)
                continue
            achado = _LINHA.match(linha)
            if achado:
                nome, valor = achado.group(1), _desescapar(achado.group(3))
                if nome == "msgid":
                    entrada.msgid, campo = valor, "id"
                elif nome == "msgid_plural":
                    entrada.plural, campo = valor, "plural"
                elif nome == "msgctxt":
                    campo = "ctxt"
                else:
                    indice = int(achado.group(2)) if achado.group(2) is not None else 0
                    while len(entrada.msgstr) <= indice:
                        entrada.msgstr.append("")
                    entrada.msgstr[indice], campo = valor, "str"
                continue
            continuacao = re.match(r'^"(.*)"$', linha)
            if not (continuacao and campo):
                raise ValueError(f"linha de .po não reconhecida: {linha!r}")
            valor = _desescapar(continuacao.group(1))
            if campo == "id":
                entrada.msgid += valor
            elif campo == "plural":
                entrada.plural = (entrada.plural or "") + valor
            elif campo == "str":
                entrada.msgstr[indice] += valor
        entradas.append(entrada)
    cabecalho, *traducoes = entradas
    return cabecalho.msgstr[0], traducoes
