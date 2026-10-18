"""Leitura de um upload por operação e resultado normalizado imutável.

O contexto só vive durante detecção/importação. Não é cache de processo nem
persiste conteúdo financeiro extra; confirmar um upload relê o arquivo salvo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from typing import TYPE_CHECKING

from django.core.files.uploadedfile import UploadedFile

from .contracts import ParsedStatement as ParsedStatement

if TYPE_CHECKING:
    from .adapters import ParsedStatementLine, StatementAdapter, _LinhaXp


def _optional[T](read: Callable[[], T]) -> T | None:
    # Metadado ilegível não pode inviabilizar linhas válidas (contrato legado).
    try:
        return read()
    except (ValueError, ArithmeticError):
        return None




@dataclass(frozen=True)
class StatementDocument:
    raw: bytes
    filename: str
    content_type: str = ""

    @classmethod
    def from_upload(cls, file: UploadedFile) -> StatementDocument:
        from .adapters import read_statement_upload

        return cls(read_statement_upload(file, label="de extrato"), file.name or "", file.content_type or "")

    @property
    def is_pdf(self) -> bool:
        return self.filename.lower().endswith(".pdf") or "pdf" in self.content_type.lower()

    @property
    def is_ofx(self) -> bool:
        from .adapters import _OFX_EXTENSIONS, _OFX_MIMETYPES

        return self.filename.lower().endswith(_OFX_EXTENSIONS) or any(
            marker in self.content_type.lower() for marker in _OFX_MIMETYPES
        )

    @cached_property
    def text(self) -> str:
        try:
            return self.raw.decode("utf-8")
        except UnicodeDecodeError:
            return self.raw.decode("latin-1")

    @cached_property
    def pdf_text(self) -> str:
        from .adapters import extract_pdf_text

        return extract_pdf_text(self.raw)

    @cached_property
    def xp_lines(self) -> tuple[_LinhaXp, ...]:
        from .adapters import _xp_abrir, _xp_ler

        with _xp_abrir(self.raw) as pdf:
            return tuple(_xp_ler(pdf.pages))

    def complete(self, lines: Iterable[ParsedStatementLine]) -> ParsedStatement:
        from . import adapters

        balance = period_end = hint = None
        format_key = "csv"
        if self.is_pdf:
            format_key = "pdf"
            text = _optional(lambda: self.pdf_text)
            if text is not None:
                format_key = adapters.sniff_pdf_format(text) or "pdf"
                hint = adapters.extract_conta_label(text)
                if format_key == "xp investimentos":
                    def xp_balance():
                        period = adapters._RE_XP_PERIODO_FIM.search(text)
                        if period is None or not self.xp_lines:
                            return None
                        end = date(int(period.group(3)), int(period.group(2)), int(period.group(1)))
                        return self.xp_lines[0].saldo, end
                    balance = _optional(xp_balance)
                else:
                    balance = _optional(lambda: adapters._saldo_do_pdf(text))
        elif self.is_ofx:
            format_key = "ofx"
            balance = _optional(lambda: adapters._saldo_do_ofx(self.text))
            hint = adapters.extract_ofx_account_hint(self.text)
            end = adapters._RE_OFX_DTEND.search(self.text)
            period_end = _optional(lambda: adapters._parse_ofx_date(end.group(1))) if end else None
        return ParsedStatement(tuple(lines), balance, period_end, hint, format_key)


def parse_statement(
    file: UploadedFile, account_id: int, *, adapter: StatementAdapter,
    document: StatementDocument | None = None,
) -> ParsedStatement:
    document = document or StatementDocument.from_upload(file)
    lines = adapter.parse(file, account_id, document=document)
    return document.complete(lines)
