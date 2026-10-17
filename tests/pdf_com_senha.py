"""Gera um PDF de uma página protegido por senha, para os testes.

Nenhuma biblioteca instalada no projeto escreve PDF criptografado (o pdfplumber
e o pypdfium2 só leem e regravam), e um arquivo de banco de verdade não entra no
repositório. Por isso o PDF é montado aqui, à mão: o "Standard security handler"
revisão 2 (RC4 de 40 bits), o mais simples que todo leitor de PDF aceita.
"""
from __future__ import annotations

import hashlib

_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")
_ID = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
_PERMISSOES = -4  # tudo permitido


def _rc4(chave: bytes, dados: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + chave[i % len(chave)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    saida = bytearray()
    for byte in dados:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        saida.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(saida)


def _completar(senha: str) -> bytes:
    return (senha.encode("latin-1") + _PAD)[:32]


def _texto_pdf(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_com_senha(linhas: list[str], senha: str) -> bytes:
    """O PDF com `linhas` de texto, que só abre com `senha`."""
    dono = _rc4(hashlib.md5(_completar(senha)).digest()[:5], _completar(senha))
    chave = hashlib.md5(
        _completar(senha) + dono + _PERMISSOES.to_bytes(4, "little", signed=True) + _ID
    ).digest()[:5]
    usuario = _rc4(chave, _PAD)

    def cifrar(numero: int, dados: bytes) -> bytes:
        chave_do_objeto = hashlib.md5(chave + numero.to_bytes(3, "little") + b"\x00\x00").digest()[:10]
        return _rc4(chave_do_objeto, dados)

    comandos = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td"]
    comandos += [f"({_texto_pdf(linha)}) Tj T*" for linha in linhas]
    comandos.append("ET")
    conteudo = cifrar(4, "\n".join(comandos).encode("latin-1"))

    objetos = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
           b" /Resources << /Font << /F1 5 0 R >> >> >>",
        4: b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"\nendstream",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        6: b"<< /Filter /Standard /V 1 /R 2 /O <" + dono.hex().encode() + b"> /U <"
           + usuario.hex().encode() + b"> /P %d >>" % _PERMISSOES,
    }
    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posicoes = {}
    for numero, corpo in objetos.items():
        posicoes[numero] = len(saida)
        saida += b"%d 0 obj\n" % numero + corpo + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for numero in sorted(objetos):
        saida += b"%010d 00000 n \n" % posicoes[numero]
    saida += (
        b"trailer\n<< /Size %d /Root 1 0 R /Encrypt 6 0 R /ID [<%s> <%s>] >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objetos) + 1, _ID.hex().encode(), _ID.hex().encode(), inicio_xref)
    )
    return bytes(saida)
