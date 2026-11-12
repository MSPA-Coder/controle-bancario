"""Teto de páginas do PDF de extrato (`MAX_PDF_PAGES`).

O limite de 5 MiB em bytes não impede um PDF pequeno com milhares de páginas de
prender um worker. O PDF é real (páginas em branco montadas com o `pypdfium2`),
e o teto vale para os dois leitores: `extract_pdf_text` e o da XP.
"""
from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from bank_statements.adapters import (
    MAX_PDF_PAGES,
    PdfGrandeDemaisError,
    XpPdfStatementAdapter,
    extract_pdf_text,
)


def _pdf_em_branco(paginas: int) -> bytes:
    import pypdfium2

    documento = pypdfium2.PdfDocument.new()
    for _ in range(paginas):
        documento.new_page(200, 200)
    saida = io.BytesIO()
    documento.save(saida)
    return saida.getvalue()


def test_pdf_no_teto_e_lido():
    assert extract_pdf_text(_pdf_em_branco(MAX_PDF_PAGES)) == "\n" * (MAX_PDF_PAGES - 1)


def test_pdf_acima_do_teto_e_recusado_com_a_causa():
    with pytest.raises(PdfGrandeDemaisError, match="páginas demais"):
        extract_pdf_text(_pdf_em_branco(MAX_PDF_PAGES + 1))


def test_leitor_da_xp_tambem_respeita_o_teto():
    arquivo = SimpleUploadedFile(
        "extrato.pdf", _pdf_em_branco(MAX_PDF_PAGES + 1), content_type="application/pdf"
    )
    with pytest.raises(PdfGrandeDemaisError):
        XpPdfStatementAdapter().parse(arquivo, account_id=7)
