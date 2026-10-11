"""Catálogo de tradução para o inglês: o que garante que a interface em inglês sai inteira.

Risco que protege: texto novo em português que ninguém traduziu aparece em português para quem
usa a interface em inglês, sem erro nem aviso; um marcador `%(n)s` alterado na tradução quebra a
tela em tempo de execução (`KeyError`/`TypeError`), e só no idioma em que ninguém testou.

Os testes leem o `.po` (versionado), não o `.mo` compilado, e por isso rodam no host sem
GNU gettext. A conferência de que o catálogo está em dia com o código precisa do `xgettext`,
que só existe no contêiner `quality`; fora dele o teste se explica e é pulado.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys

import pytest

from core import textos_js
from tests import po_catalogo as po

CABECALHO, ENTRADAS = po.ler()

# Letras que só existem em português: sobra delas numa tradução = texto que ficou sem traduzir.
ACENTOS = re.compile("[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]")


def _palavras(texto: str) -> set[str]:
    return set(re.findall(r"\w+", texto))


def test_o_catalogo_tem_entradas():
    # Se o leitor deixasse de achar as entradas, todos os testes abaixo passariam sem olhar nada.
    assert len(ENTRADAS) > 1000


def test_cabecalho_declara_o_plural_do_ingles():
    assert "Language: en" in CABECALHO
    assert "nplurals=2; plural=(n != 1);" in CABECALHO


def test_toda_entrada_esta_traduzida():
    faltando = [
        pt[:70]
        for entrada in ENTRADAS
        for pt, en in entrada.origens
        if not en.strip()
    ]
    assert not faltando, f"{len(faltando)} texto(s) sem tradução, por exemplo: {faltando[:5]}"


def test_nenhuma_entrada_esta_marcada_fuzzy():
    # `fuzzy` é tradução adivinhada pelo gettext: o Django a ignora e o texto volta ao português.
    assert [e.msgid[:70] for e in ENTRADAS if "fuzzy" in e.flags] == []


def test_marcadores_de_formatacao_iguais_ao_original():
    divergentes = [
        f"{pt[:60]!r}: {po.marcadores(pt)} x {po.marcadores(en)}"
        for entrada in ENTRADAS
        for pt, en in entrada.origens
        if po.marcadores(pt) != po.marcadores(en)
    ]
    assert not divergentes, "\n".join(divergentes[:10])


def test_plurais_tem_duas_formas():
    errados = [e.msgid[:70] for e in ENTRADAS if e.plural is not None and len(e.msgstr) != 2]
    assert errados == []


def test_traducao_nao_traz_portugues():
    # Aceita palavra acentuada que também existe no texto-fonte: é nome próprio ("Itaú"), não vazamento.
    vazando = []
    for entrada in ENTRADAS:
        for pt, en in entrada.origens:
            sobra = [p for p in _palavras(en) if ACENTOS.search(p) and p not in _palavras(pt)]
            if sobra:
                vazando.append(f"{pt[:50]!r}: {sobra}")
    assert not vazando, "\n".join(vazando[:10])


def test_pontuacao_final_acompanha_o_original():
    # Mensagem completa termina em ponto; rótulo e botão não. A tradução segue o original.
    destoantes = []
    for entrada in ENTRADAS:
        for pt, en in entrada.origens:
            if pt.rstrip().endswith(".") != en.rstrip().endswith("."):
                destoantes.append(f"{pt[:50]!r} -> {en[:50]!r}")
    assert not destoantes, f"{len(destoantes)} divergência(s): {destoantes[:8]}"


def test_titulos_de_permissao_mantem_o_separador():
    # `permission_catalog_sections` separa seção e subgrupo pelo " · " do título já traduzido.
    sem_separador = [
        pt
        for entrada in ENTRADAS
        for pt, en in entrada.origens
        if " · " in pt and pt.count(" · ") != en.count(" · ")
    ]
    assert sem_separador == []


def test_textos_do_javascript_estao_no_catalogo():
    ids = {pt for entrada in ENTRADAS for pt, _ in entrada.origens}
    faltando = [texto for texto in textos_js.FONTES if texto not in ids]
    assert not faltando, f"texto(s) de JS fora do catálogo (rode scripts/mensagens.ps1): {faltando}"


@pytest.mark.skipif(shutil.which("xgettext") is None, reason="precisa do GNU gettext (contêiner quality)")
def test_catalogo_esta_em_dia_com_o_codigo(tmp_path):
    """Rodar o `makemessages` não pode produzir diferença: texto marcado e não extraído é buraco."""
    copia = tmp_path / "w"
    ignorar = shutil.ignore_patterns(".git", ".venv", "__pycache__", "staticfiles", ".claude", ".pytest_cache")
    shutil.copytree(po.RAIZ, copia, ignore=ignorar)
    comando = [
        sys.executable,
        "manage.py",
        "makemessages",
        "-l",
        "en",
        "--no-obsolete",
        "--no-wrap",
        "--add-location=file",
    ]
    for padrao in ("tests/*", "static/*", "staticfiles/*", "docs/*", "scripts/*", ".venv/*", "*/migrations/*", "*/management/commands/*"):
        comando += ["-i", padrao]
    resultado = subprocess.run(comando, cwd=copia, capture_output=True, text=True, timeout=240, check=False)
    assert resultado.returncode == 0, resultado.stderr[-800:]

    def _sem_data(texto: str) -> list[str]:
        return [linha for linha in texto.splitlines() if not linha.startswith('"POT-Creation-Date')]

    gerado = (copia / "locale/en/LC_MESSAGES/django.po").read_text(encoding="utf-8")
    atual = po.CATALOGO_EN.read_text(encoding="utf-8")
    assert _sem_data(gerado) == _sem_data(atual), "catálogo desatualizado: rode scripts/mensagens.ps1 e traduza o que entrou"
