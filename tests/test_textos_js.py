"""Todo texto que o JavaScript passa por `t('...')` tem de estar em `core.textos_js.FONTES`.

Risco que protege: um texto novo no `.js` que ninguém registrou em `FONTES` nunca
entra no catálogo de tradução e aparece em português para quem usa a interface em
inglês, sem erro nem aviso. Nenhum teste executa o navegador, então a varredura é a
única rede (docs/TESTES.md, T3 e T6).
"""

import re
from pathlib import Path

import pytest

from core import textos_js

RAIZ = Path(__file__).resolve().parent.parent
JS = RAIZ / "static" / "js"

# t('texto') ou t("texto"), com escape simples dentro. Não pega `.t(` (método) nem `at(`.
CHAMADA = re.compile(r"""(?<![\w.$])t\(\s*(?P<q>['"])(?P<texto>(?:\\.|(?!(?P=q)).)*)(?P=q)""")


def _sem_comentarios(fonte: str) -> str:
    """Tira comentário de bloco e de linha: exemplo em comentário não é uso.

    O `//` só conta se vier no começo da linha ou depois de espaço, para não cortar a
    URL `http://...` dentro de um texto.
    """
    fonte = re.sub(r"/\*.*?\*/", "", fonte, flags=re.DOTALL)
    return re.sub(r"(?:^|(?<=\s))//.*$", "", fonte, flags=re.MULTILINE)


def _desescapar(texto: str) -> str:
    return texto.replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


@pytest.mark.sentinela_front
def test_todo_texto_passado_a_t_esta_registrado_em_fontes():
    usados: dict[str, str] = {}
    for arquivo in sorted(JS.rglob("*.js")):
        if "vendor" in arquivo.parts:
            continue
        for achado in CHAMADA.finditer(_sem_comentarios(arquivo.read_text(encoding="utf-8"))):
            usados[_desescapar(achado.group("texto"))] = arquivo.relative_to(RAIZ).as_posix()

    faltando = {texto: onde for texto, onde in usados.items() if texto not in textos_js.FONTES}
    assert not faltando, (
        "Texto passado a t() no JavaScript e ausente de core/textos_js.py (FONTES); "
        f"sem isso ele não entra no catálogo de tradução: {faltando}"
    )


def test_o_json_da_pagina_tem_uma_entrada_por_fonte():
    assert set(textos_js.textos_js()) == set(textos_js.FONTES)


def test_o_varredor_acha_t_com_aspas_e_ignora_metodo_e_comentario():
    fonte = "a = t('Um'); b = t(\"Dois \\\"x\\\"\"); c = obj.t('Nao'); d = at('Nao'); // t('Comentario')"
    achados = [_desescapar(m.group("texto")) for m in CHAMADA.finditer(_sem_comentarios(fonte))]
    assert achados == ["Um", 'Dois "x"']
