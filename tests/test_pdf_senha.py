"""`bank_statements/pdf_senha.py`: reconhecer o PDF trancado e abri-lo com a senha.

O PDF é real (montado por `tests/pdf_com_senha.py`): o que importa aqui é o
comportamento do leitor de PDF, que um dublê esconderia.
"""
from __future__ import annotations

import pytest

from bank_statements.adapters import extract_pdf_text
from bank_statements.pdf_senha import pede_senha, sem_senha
from tests.pdf_com_senha import pdf_com_senha

LINHAS = ["Fatura de teste", "10/09/2026 PADARIA CENTRAL 12,50"]


def test_pdf_trancado_pede_senha_e_o_leitor_comum_nao_le():
    trancado = pdf_com_senha(LINHAS, "12345")
    assert pede_senha(trancado)
    with pytest.raises(ValueError):
        extract_pdf_text(trancado)


def test_com_a_senha_o_pdf_volta_sem_protecao_e_com_o_mesmo_texto():
    aberto = sem_senha(pdf_com_senha(LINHAS, "12345"), "12345")
    assert not pede_senha(aberto)
    assert extract_pdf_text(aberto).splitlines() == LINHAS


@pytest.mark.parametrize("senha", ["", "54321"])
def test_senha_vazia_ou_errada_e_recusada(senha):
    with pytest.raises(ValueError):
        sem_senha(pdf_com_senha(LINHAS, "12345"), senha)


def test_arquivo_corrompido_nao_e_tratado_como_trancado():
    assert not pede_senha(b"%PDF-1.4 nao e um pdf de verdade")
