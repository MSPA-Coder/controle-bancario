"""Testes do leitor do extrato mensal em dólar da Avenue (PDF "Stmt").

Texto sintético no layout observado na extração real via pdfplumber (jan a set de
2026): resumo com o caixa de abertura e de fechamento, carteira e atividade da
conta, com o complemento de cada movimento na linha seguinte. Sem nome, endereço
nem número de conta reais.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from bank_statements.adapters import (
    AvenuePdfStatementAdapter,
    _parse_avenue_usd_lines,
    _saldo_do_pdf,
    avenue_us_carteira,
    conferir_moeda_do_extrato_avenue,
    sniff_pdf_format,
)
from bank_statements.investimentos import interpretar
from core.domain.finance import (
    INCOME_KIND_COUPON,
    INCOME_KIND_RENTAL,
    INCOME_ROLE_CREDIT,
    INCOME_ROLE_RENTAL_IRRF,
)

CABECALHO = """2601 Bayshore DR.
customer@avenue.us
PAGE 1 OF 6
April 01, 2026 - April 30, 2026
FULANO DE TAL
"""

RESUMO = """CASH & CASH EQUIVALENTS PORTFOLIO EQUITY ALLOCATION
OPENING BALANCE CLOSING BALANCE Fixed Income - 56.716%
Total Cash & Cash Equivalents $ 1,054.58 $ 1,069.89 Cash - 39.031%
Net Account Balance 1,054.58 1,069.89 Equities - 4.253%
"""

CARTEIRA = """SYMBOL/ ACCOUNT MARKET LAST PERIOD'S ANNUAL % OF TOTAL
EQUITIES / OPTIONS
Berkshire Hathaway Inc. - Class B BRK.B C 1.56365 475.38 $ 743.33 $ 784.63 -5.26% 4.253%
BRKB
Canopy Growth Corporation CGC O 1,200 1.30 1,560.00 1,080.00 44.44 8.92%
Total Equities $ 2,303.33 13.17%
FIXED INCOME
Oracle Corp 5CYRWW7 C 2 643.10 1,286.20 1,310.20 -1.83 7.358%
ORCL 3.95 25/03/51
Total Fixed Income $ 1,286.20 7.358%
"""

ATIVIDADE = """ACCOUNT ACTIVITY - AVENUE ACCOUNT NUMBER: 000000000
ACCOUNT
TRANSACTION DATE TYPE DESCRIPTION QUANTITY PRICE DEBIT CREDIT
BUY / SELL TRANSACTIONS
BOUGHT 13/04/2026 C Débito compra de ativo 1,200 1 $ 1,200.00
CGC
SOLD 23/04/2026 C Crédito venda de ativo 100 1.35 $ 135.00
CGC
Total Buy / Sell Transactions $ 1,200.00 $ 135.00
DIVIDENDS AND INTEREST
INTEREST 02/04/2026 C Crédito de Cupom $ 44.64
ORCL 3.95 25/03/51
INTEREST 14/04/2026 C Stock lending accrued interest $ 3.05
INTEREST 14/04/2026 C Retenção impostos sobre rendimentos do $ 0.92
aluguel de ações
Total Dividends And Interest $ 0.92 $ 47.69
FUNDS PAID AND RECEIVED
JOURNAL 13/04/2026 C BI Remessa de Câmbio Padrão Investimento $ 1,021.77
BR-EUA
Total Funds Paid And Received $ 1,021.77
MISCELLANEOUS TRANSACTIONS
MISC 22/04/2026 C Campanha de Marketing $ 11.77
Total Miscellaneous Transactions $ 11.77
All investment positions held in an Apex Clearing Corporation or Velocity Clearing LLC cash account unless indicated otherwise.
"""

SAMPLE_TEXT = CABECALHO + RESUMO + CARTEIRA + ATIVIDADE

# Venda de título no mês (outubro de 2026 foi o primeiro): o extrato separa o principal
# (BOUGHT/SOLD) dos juros corridos (INTEREST) e imprime a corretagem como FEE, sempre com o
# ativo na linha de baixo. O título vendido sai pelo código, não pelo nome.
RESUMO_COM_VENDA_DE_TITULO = """CASH & CASH EQUIVALENTS PORTFOLIO EQUITY ALLOCATION
OPENING BALANCE CLOSING BALANCE Fixed Income - 56.716%
Total Cash & Cash Equivalents $ 1,000.00 $ 1,684.11 Cash - 39.031%
Net Account Balance 1,000.00 1,684.11 Equities - 4.253%
"""

ATIVIDADE_COM_VENDA_DE_TITULO = """ACCOUNT ACTIVITY - AVENUE ACCOUNT NUMBER: 000000000
ACCOUNT
TRANSACTION DATE TYPE DESCRIPTION QUANTITY PRICE DEBIT CREDIT
BUY / SELL TRANSACTIONS
BOUGHT 13/04/2026 C Débito compra de ativo 498 0.83 $ 413.34
CGC
SOLD 16/04/2026 C Crédito venda de ativo 2 548.92 $ 1,097.84
5CYRWW7
Total Buy / Sell Transactions $ 413.34 $ 1,097.84
DIVIDENDS AND INTEREST
INTEREST 16/04/2026 C Crédito de Juros Acruados na Venda 2 548.92 $ 4.61
5CYRWW7
Total Dividends And Interest $ 0.00 $ 4.61
MISCELLANEOUS TRANSACTIONS
FEE 13/04/2026 C Corretagem 498 0.83 $ 5.00
CGC
Total Miscellaneous Transactions $ 5.00
All investment positions held in an Apex Clearing Corporation or Velocity Clearing LLC cash account unless indicated otherwise.
"""

TEXTO_COM_VENDA_DE_TITULO = CABECALHO + RESUMO_COM_VENDA_DE_TITULO + ATIVIDADE_COM_VENDA_DE_TITULO


def _linhas(texto=SAMPLE_TEXT):
    return _parse_avenue_usd_lines(texto, account_id=1)


def test_le_cada_movimento_com_sinal_descricao_e_categoria_do_banco():
    assert [(linha.statement_date, linha.amount, linha.description, linha.bank_category) for linha in _linhas()] == [
        (date(2026, 4, 13), Decimal("-1200.00"), "Compra de CGC na Avenue: 1200 a US$ 1, pregão 10/04/2026",
         "Operações em Bolsa"),
        (date(2026, 4, 23), Decimal("135.00"), "Venda de CGC na Avenue: 100 a US$ 1,35, pregão 22/04/2026",
         "Operações em Bolsa"),
        (date(2026, 4, 2), Decimal("44.64"), "Cupom de ORCL 3.95 25/03/51 na Avenue", "Cupom"),
        (date(2026, 4, 14), Decimal("3.05"), "Juros de aluguel de ações na Avenue (CGC)", "Aluguel de ações"),
        (date(2026, 4, 14), Decimal("-0.92"), "IR retido sobre aluguel de ações na Avenue (CGC)",
         "IR sobre aluguel de ações"),
        (date(2026, 4, 13), Decimal("1021.77"), "Remessa de câmbio BR-EUA", "Remessa de câmbio"),
        (date(2026, 4, 22), Decimal("11.77"), "Campanha de Marketing na Avenue", "Crédito diverso"),
    ]


def test_le_os_juros_corridos_da_venda_de_titulo_e_a_corretagem_e_a_conta_fecha():
    """O extrato não marca débito nem crédito: a corretagem sai negativa e os juros entram como cupom."""
    assert [
        (linha.statement_date, linha.amount, linha.description, linha.bank_category)
        for linha in _linhas(TEXTO_COM_VENDA_DE_TITULO)
    ] == [
        (date(2026, 4, 13), Decimal("-413.34"), "Compra de CGC na Avenue: 498 a US$ 0,83, pregão 10/04/2026",
         "Operações em Bolsa"),
        (date(2026, 4, 16), Decimal("1097.84"), "Venda de 5CYRWW7 na Avenue: 2 a US$ 548,92, pregão 15/04/2026",
         "Operações em Bolsa"),
        (date(2026, 4, 16), Decimal("4.61"), "Juros corridos na venda de 5CYRWW7 na Avenue", "Cupom"),
        (date(2026, 4, 13), Decimal("-5.00"), "Corretagem de CGC na Avenue: 498 a US$ 0,83", "Corretagem"),
    ]


def test_juros_corridos_com_outra_grafia_da_palavra_do_meio_tambem_sao_lidos():
    """O extrato imprime "Acruados"; se a Avenue corrigir a grafia, a importação não deve voltar a falhar."""
    corrigido = TEXTO_COM_VENDA_DE_TITULO.replace("Juros Acruados", "Juros Acumulados")
    juros = next(linha for linha in _linhas(corrigido) if linha.bank_category == "Cupom")
    assert (juros.amount, juros.description) == (Decimal("4.61"), "Juros corridos na venda de 5CYRWW7 na Avenue")


def test_juros_corridos_sem_o_titulo_na_linha_de_baixo_sao_recusados():
    sem_titulo = TEXTO_COM_VENDA_DE_TITULO.replace("548.92 $ 4.61\n5CYRWW7\n", "548.92 $ 4.61\n")
    with pytest.raises(ValueError, match="não conhece"):
        _linhas(sem_titulo)


def test_corretagem_sem_ativo_na_linha_de_baixo_e_recusada():
    sem_ativo = TEXTO_COM_VENDA_DE_TITULO.replace("$ 5.00\nCGC\n", "$ 5.00\n")
    with pytest.raises(ValueError, match="não conhece"):
        _linhas(sem_ativo)


def test_taxa_que_nao_e_corretagem_continua_recusada():
    """Só a corretagem tem formato conhecido: outra taxa pede um leitor novo, não um palpite."""
    outra_taxa = TEXTO_COM_VENDA_DE_TITULO.replace("Corretagem 498 0.83", "Taxa de custódia")
    with pytest.raises(ValueError, match="não conhece"):
        _linhas(outra_taxa)


def test_o_pregao_e_o_dia_util_anterior_a_liquidacao():
    """Liquidação numa segunda-feira: o pregão foi a sexta-feira (13/04/2026 é segunda)."""
    compra = _linhas()[0]
    assert interpretar(compra.description).settlement_pregao_date == date(2026, 4, 10)


def test_recusa_quando_os_movimentos_nao_fecham_com_o_caixa_do_extrato():
    with pytest.raises(ValueError, match="caixa de abertura"):
        _linhas(SAMPLE_TEXT.replace("$ 1,054.58 $ 1,069.89", "$ 1,054.58 $ 1,069.90"))


def test_recusa_movimento_que_o_leitor_nao_conhece():
    desconhecido = SAMPLE_TEXT.replace("Stock lending accrued interest", "Juros de outra coisa")
    with pytest.raises(ValueError, match="não conhece"):
        _linhas(desconhecido)


def test_aluguel_fica_sem_ativo_quando_nao_ha_uma_unica_acao_inteira():
    """O extrato não diz qual ação foi emprestada: com duas candidatas, o ativo fica em branco."""
    duas_acoes = SAMPLE_TEXT.replace("$ 135.00\nCGC\n", "$ 135.00\nSGOV\n")
    juros = next(linha for linha in _linhas(duas_acoes) if linha.bank_category == "Aluguel de ações")
    assert juros.description == "Juros de aluguel de ações na Avenue"


def test_mes_sem_movimento_importa_so_o_saldo():
    sem_atividade = CABECALHO + RESUMO.replace("$ 1,054.58 $ 1,069.89", "$ 1,264.26 $ 1,264.26") + CARTEIRA
    sem_atividade += "CASH & CASH EQUIVALENTS - AVENUE ACCOUNT NUMBER: 000000000\n"
    assert _linhas(sem_atividade) == []
    assert _saldo_do_pdf(sem_atividade) == (Decimal("1264.26"), date(2026, 4, 30))


def test_le_a_carteira_de_acoes_do_fim_do_mes_sem_os_titulos():
    assert avenue_us_carteira(SAMPLE_TEXT) == (("BRK.B", Decimal("1.56365")), ("CGC", Decimal("1200")))


def test_recusa_carteira_cujas_linhas_nao_somam_o_total_do_extrato():
    """Uma linha de ação que o leitor não reconhecesse sumiria da conferência de posição."""
    with pytest.raises(ValueError, match="carteira"):
        avenue_us_carteira(SAMPLE_TEXT.replace("Total Equities $ 2,303.33", "Total Equities $ 2,303.34"))


def test_extrato_sem_secao_de_acoes_tem_carteira_vazia():
    sem_acoes = SAMPLE_TEXT.replace(CARTEIRA, CARTEIRA.split("FIXED INCOME")[1])
    assert avenue_us_carteira(sem_acoes) == ()


def test_reconhece_o_formato_e_o_saldo_de_fechamento():
    assert sniff_pdf_format(SAMPLE_TEXT) == "avenue"
    assert _saldo_do_pdf(SAMPLE_TEXT) == (Decimal("1069.89"), date(2026, 4, 30))


@pytest.mark.parametrize(
    ("descricao", "ativo", "tipo", "papel"),
    [
        ("Cupom de ORCL 3.95 25/03/51 na Avenue", "ORCL 3.95 25/03/51", INCOME_KIND_COUPON, INCOME_ROLE_CREDIT),
        ("Juros corridos na venda de 5CYRWW7 na Avenue", "5CYRWW7", INCOME_KIND_COUPON, INCOME_ROLE_CREDIT),
        (
            "Juros corridos na venda de ORCL 3.95 25/03/51 na Avenue", "ORCL 3.95 25/03/51",
            INCOME_KIND_COUPON, INCOME_ROLE_CREDIT,
        ),
        ("Juros de aluguel de ações na Avenue (CGC)", "CGC", INCOME_KIND_RENTAL, INCOME_ROLE_CREDIT),
        ("Juros de aluguel de ações na Avenue", None, INCOME_KIND_RENTAL, INCOME_ROLE_CREDIT),
        ("IR retido sobre aluguel de ações na Avenue (CGC)", "CGC", INCOME_KIND_RENTAL, INCOME_ROLE_RENTAL_IRRF),
    ],
)
def test_a_descricao_escrita_pelo_leitor_vira_detalhe_de_investimento(descricao, ativo, tipo, papel):
    detalhe = interpretar(descricao)
    assert (detalhe.instrument_code, detalhe.income_kind, detalhe.income_role) == (ativo, tipo, papel)


def test_a_compra_no_exterior_vira_liquidacao_com_ativo_e_quantidade():
    detalhe = interpretar("Venda de BRK.B na Avenue: 1,56365 a US$ 499,13, pregão 01/10/2026")
    assert (detalhe.instrument_code, detalhe.settlement_pregao_date, detalhe.settlement_quantity) == (
        "BRK.B", date(2026, 10, 1), Decimal("1.56365"),
    )


def test_a_quantidade_escrita_pelo_leitor_volta_inteira():
    compra = _linhas()[0]
    assert interpretar(compra.description).settlement_quantity == Decimal("1200")


def test_liquidacao_editada_sem_quantidade_fica_so_com_ativo_e_pregao():
    detalhe = interpretar("Compra de CGC na Avenue: lote, pregão 10/04/2026")
    assert (detalhe.instrument_code, detalhe.settlement_quantity) == ("CGC", None)


def test_a_corretagem_do_exterior_nao_recebe_campos_de_investimento():
    """Custo da compra e da venda: fica no caixa e na categoria, sem virar renda nem liquidação de pregão."""
    assert interpretar("Corretagem de CGC na Avenue: 498 a US$ 0,83") is None


@pytest.mark.parametrize(
    "descricao",
    [
        "Cupom de desconto Loja X",
        "Cupom de ORCL 3.95 25/03/51",
        "Juros corridos na venda de 5CYRWW7",
        "Compra de CGC na Corretora: 1 a US$ 1, pregão 10/04/2026",
    ],
)
def test_texto_parecido_de_outro_lugar_nao_vira_detalhe(descricao):
    assert interpretar(descricao) is None


def test_titulo_maior_que_a_coluna_fica_sem_ativo():
    detalhe = interpretar("Cupom de TITULO COM NOME MUITO LONGO 1.0 01/01/50 na Avenue")
    assert detalhe.income_kind == INCOME_KIND_COUPON and detalhe.instrument_code is None


def test_o_adaptador_le_o_extrato_em_dolar_pelo_texto():
    lidas = AvenuePdfStatementAdapter().parse(None, 1, document=SimpleNamespace(raw=b"pdf", pdf_text=SAMPLE_TEXT))
    assert len(lidas) == 7


def test_extrato_em_dolar_so_entra_na_conta_em_dolar_e_o_em_reais_so_na_brasileira():
    em_reais = "www.avenue.us\nSaldo inicial R$ 0,00\n"
    conferir_moeda_do_extrato_avenue(SAMPLE_TEXT, "USD")
    conferir_moeda_do_extrato_avenue(em_reais, "BRL")
    with pytest.raises(ValueError, match="conta em dólar"):
        conferir_moeda_do_extrato_avenue(SAMPLE_TEXT, "BRL")
    with pytest.raises(ValueError, match="conta brasileira"):
        conferir_moeda_do_extrato_avenue(em_reais, "USD")


@pytest.mark.django_db
def test_a_importacao_confere_a_moeda_antes_de_gravar(monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from accounts.models import AccountOwner, AppUser, UserOwnerAccess
    from bank_statements.document import StatementDocument
    from bank_statements.models import BankStatementImport, BankStatementLine
    from bank_statements.services import import_statement_file
    from banking.models import FinancialAccount, FinancialInstitution

    user = AppUser.objects.create_user(username="operador-avenue", password="senha-segura")
    titular = AccountOwner.objects.create(name="Titular")
    UserOwnerAccess.objects.create(user=user, owner=titular, can_view=True, can_create=True, can_update=True)
    avenue = FinancialInstitution.objects.create(institution_name="Avenue", institution_type="Corretora", homologada=True)
    em_reais = FinancialAccount.objects.create(owner=titular, institution=avenue, account_name="Conta Brasileira",
                                               currency="BRL")
    em_dolar = FinancialAccount.objects.create(owner=titular, institution=avenue, account_name="Conta em dólar",
                                               currency="USD")
    monkeypatch.setattr(StatementDocument, "pdf_text", property(lambda self: SAMPLE_TEXT))

    def arquivo():
        return SimpleUploadedFile("Stmt.pdf", b"%PDF-falso", content_type="application/pdf")

    with pytest.raises(ValueError, match="conta em dólar"):
        import_statement_file(user, account_id=em_reais.id, uploaded_file=arquivo())
    assert not BankStatementImport.objects.filter(account=em_reais).exists()

    lote, inseridas, _ = import_statement_file(user, account_id=em_dolar.id, uploaded_file=arquivo())
    assert inseridas == 7
    assert (lote.statement_balance, lote.statement_balance_date) == (Decimal("1069.89"), date(2026, 4, 30))
    assert BankStatementLine.objects.get(import_batch=lote, amount=Decimal("44.64")).bank_category == "Cupom"
    assert lote.statement_holdings == [
        {"instrument": "BRK.B", "quantity": "1.56365"}, {"instrument": "CGC", "quantity": "1200"},
    ]


@pytest.mark.django_db
def test_o_detalhe_de_investimento_aceita_o_cupom():
    from accounts.models import AccountOwner
    from banking.models import FinancialAccount, FinancialInstitution
    from core.domain.finance import ENTRY_TYPE_INCOME, STATUS_REALIZED
    from transactions.models import CashFlowCategory, CashFlowEntry, EntryInvestmentDetail

    titular = AccountOwner.objects.create(name="Titular")
    avenue = FinancialInstitution.objects.create(institution_name="Avenue", institution_type="Corretora")
    conta = FinancialAccount.objects.create(owner=titular, institution=avenue, account_name="Conta em dólar",
                                            currency="USD", initial_balance=Decimal("0"),
                                            initial_balance_date=date(2025, 12, 31))
    categoria = CashFlowCategory.objects.create(category_name="Proventos")
    lancamento = CashFlowEntry.objects.create(
        account=conta, category=categoria, entry_type=ENTRY_TYPE_INCOME, description="Cupom de ORCL 3.95 25/03/51 na Avenue",
        entry_amount=Decimal("39.50"), due_date=date(2026, 9, 28), status=STATUS_REALIZED,
        realized_date=date(2026, 9, 28), realized_amount=Decimal("39.50"),
    )

    detalhe = EntryInvestmentDetail.objects.create(
        entry=lancamento, instrument_code="ORCL 3.95 25/03/51", income_kind=INCOME_KIND_COUPON, income_role=INCOME_ROLE_CREDIT,
    )

    assert EntryInvestmentDetail.objects.get(id=detalhe.id).income_kind == "cupom"
