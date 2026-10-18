"""Uma leitura produz linhas e metadados sem repetir extração externa.

Preserva o contrato dos adaptadores legados: hashes, sinais, parcelas e
metadados opcionais não mudam ao juntar o resultado em um objeto imutável.
"""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from bank_statements import adapters
from bank_statements.document import parse_statement
from tests.test_bank_statements_avenue_pdf_adapter import SAMPLE_TEXT as AVENUE
from tests.test_bank_statements_genial_pdf_adapter import SAMPLE_TEXT as GENIAL
from tests.test_bank_statements_itau_pdf_adapter import SAMPLE_TEXT as ITAU
from tests.test_bank_statements_mercadopago_pdf_adapter import SAMPLE_TEXT as MERCADO_PAGO
from tests.test_bank_statements_xp_pdf_adapter import LINHAS, TEXTO_XP, _pagina, _PdfFalso
from tests.test_saldo_do_extrato import (
    OFX_SGML,
    OFX_SO_COM_SALDO,
    OFX_XML_NEGATIVO,
    _conta_para_importar,
)


class CountingUpload(SimpleUploadedFile):
    reads = 0

    def read(self, *args, **kwargs):
        self.reads += 1
        return super().read(*args, **kwargs)


@pytest.mark.parametrize("adapter,text", [
    (adapters.GenialPdfStatementAdapter(), GENIAL),
    (adapters.MercadoPagoPdfStatementAdapter(), MERCADO_PAGO),
    (adapters.ItauPdfStatementAdapter(), ITAU),
    (adapters.AvenuePdfStatementAdapter(), AVENUE),
])
def test_pdf_complete_result_preserves_lines_and_extracts_text_once(monkeypatch, adapter, text):
    calls = []

    def extract(raw):
        calls.append(raw)
        return text

    monkeypatch.setattr(adapters, "extract_pdf_text", extract)
    upload = CountingUpload("synthetic.pdf", b"%PDF-synthetic", content_type="application/pdf")
    expected = adapter.parse(upload, 17)
    upload.reads = 0
    calls.clear()
    result = parse_statement(upload, 17, adapter=adapter)
    assert result.lines == tuple(expected)
    assert result.balance == adapters._saldo_do_pdf(text)
    assert result.account_hint == adapters.extract_conta_label(text)
    assert (upload.reads, len(calls)) == (1, 1)
    with pytest.raises(FrozenInstanceError):
        result.lines = ()


def test_xp_geometry_is_read_once_for_lines_and_balance(monkeypatch):
    openings = []

    def open_pdf(raw):
        openings.append(raw)
        return _PdfFalso([_pagina(LINHAS)])

    monkeypatch.setattr(adapters, "_xp_abrir", open_pdf)
    monkeypatch.setattr(adapters, "extract_pdf_text", lambda raw: TEXTO_XP)
    upload = CountingUpload("synthetic.pdf", b"%PDF-synthetic", content_type="application/pdf")
    result = parse_statement(upload, 17, adapter=adapters.XpPdfStatementAdapter())
    assert len(result.lines) == 3
    assert sorted(line.amount for line in result.lines) == [Decimal("-100"), Decimal("-5"), Decimal("150")]
    assert result.balance == (Decimal("50"), date(2026, 6, 30))
    assert result.account_hint == "323220"
    assert (len(openings), upload.reads) == (1, 1)


@pytest.mark.parametrize("text", [OFX_SGML, OFX_SO_COM_SALDO, OFX_XML_NEGATIVO])
def test_ofx_full_result_preserves_zero_negative_and_movement_free_balance(text):
    upload = CountingUpload("synthetic.ofx", text.encode(), content_type="application/x-ofx")
    adapter = adapters.OfxStatementAdapter()
    expected = adapter.parse(upload, 17)
    upload.reads = 0
    result = parse_statement(upload, 17, adapter=adapter)
    assert result.lines == tuple(expected)
    assert result.balance == adapters._saldo_do_ofx(text)
    assert result.period_end == adapters.extract_statement_period_end(upload)
    # A chamada de compatibilidade acima lê mais uma vez, mas o parse leu só uma.
    assert upload.reads == 2


def test_optional_invalid_balance_does_not_discard_valid_ofx_lines():
    text = OFX_SGML.replace("<DTASOF>20260930", "<DTASOF>20269999")
    upload = CountingUpload("synthetic.ofx", text.encode(), content_type="application/x-ofx")
    result = parse_statement(upload, 17, adapter=adapters.OfxStatementAdapter())
    assert len(result.lines) == 1
    assert result.balance is None
    assert upload.reads == 1


@pytest.mark.django_db
def test_detection_and_import_each_extract_pdf_once_without_cross_request_cache(monkeypatch):
    from bank_statements.pending_imports import detect_account
    from bank_statements.services import import_statement_file

    user, account = _conta_para_importar("synthetic-document")
    account.statement_identifier = "1234567-8"
    account.save()
    institution = account.institution
    institution.institution_name = "Genial"
    institution.homologada = True
    institution.save()
    calls = []

    def extract(raw):
        calls.append(raw)
        return GENIAL

    monkeypatch.setattr(adapters, "extract_pdf_text", extract)
    found, _, error = detect_account(user, filename="synthetic.pdf", content_type="application/pdf", raw=b"%PDF-synthetic")
    assert error == ""
    assert found == account
    assert len(calls) == 1
    upload = CountingUpload("synthetic.pdf", b"%PDF-synthetic", content_type="application/pdf")
    batch, inserted, _ = import_statement_file(user, account_id=account.id, uploaded_file=upload)
    assert inserted == 4
    assert batch.statement_balance == Decimal("1087.68")
    assert (len(calls), upload.reads) == (2, 1)
    # A confirmação/reimportação é outra operação: não reutiliza cache de outro request.
    _, inserted, skipped = import_statement_file(user, account_id=account.id, uploaded_file=upload)
    assert (inserted, skipped, len(calls), upload.reads) == (0, 4, 3, 2)
