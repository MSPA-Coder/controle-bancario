"""PDF protegido por senha: reconhecer e tirar a proteção com a senha do usuário.

Faturas e extratos chegam do banco trancados (a senha costuma ser parte do
CPF). Os leitores do sistema (`adapters`) recebem os bytes do arquivo e não
sabem de senha; em vez de levar a senha por todos eles, o arquivo é aberto uma
vez com a senha e regravado sem a proteção, e daí em diante segue o caminho de
qualquer PDF.

A senha só passa por aqui, em memória, durante a requisição em que o usuário a
digita: não é gravada, não vai para log nem para auditoria.

Quem lê é o PDFium (`pypdfium2`, o mesmo que o `pdfplumber` já usa para
desenhar páginas): ele distingue "precisa de senha" de "arquivo corrompido" pelo
código de erro, sem adivinhar pela mensagem.
"""
from __future__ import annotations

import io

from django.utils.translation import gettext


def _pdfium():
    try:
        import pypdfium2
        import pypdfium2.raw as pdfium_c
    except ImportError as exc:
        raise ValueError(
            gettext("Suporte a extrato em PDF indisponível no momento (dependência não instalada).")
        ) from exc
    return pypdfium2, pdfium_c


def pede_senha(raw: bytes) -> bool:
    """Se o PDF só abre com senha. Arquivo ilegível por outro motivo dá `False`:
    o erro de leitura de sempre aparece adiante, na leitura do texto."""
    pdfium, pdfium_c = _pdfium()
    try:
        documento = pdfium.PdfDocument(raw)
    except pdfium.PdfiumError as exc:
        return exc.err_code == pdfium_c.FPDF_ERR_PASSWORD
    documento.close()
    return False


def sem_senha(raw: bytes, senha: str) -> bytes:
    """O mesmo PDF, sem a proteção. `ValueError` se a senha não abre o arquivo."""
    pdfium, pdfium_c = _pdfium()
    if not senha:
        raise ValueError(gettext("Informe a senha do PDF."))
    try:
        documento = pdfium.PdfDocument(raw, password=senha)
    except pdfium.PdfiumError as exc:
        if exc.err_code == pdfium_c.FPDF_ERR_PASSWORD:
            raise ValueError(gettext("Senha do PDF incorreta.")) from None
        raise ValueError(gettext("Não foi possível ler o PDF do extrato.")) from None
    try:
        saida = io.BytesIO()
        documento.save(saida, flags=pdfium_c.FPDF_REMOVE_SECURITY)
    finally:
        documento.close()
    return saida.getvalue()
