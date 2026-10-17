"""Nível de confiança da sugestão, aprendizado pelo texto do banco e medição.

Fixa as regras medidas em 17/10/2026 (ver `classificacao`): regra, ou histórico
com dois ou mais casos unânimes, é confiança alta, e intermediador nunca é; o
histórico aprende também do texto da linha conciliada, um voto por lançamento;
texto genérico cai na categoria dominante da conta; a prévia da fatura agrupa o
incerto da mesma loja; a conciliação põe o incerto primeiro; e a medição refaz o
passado sem olhar o futuro, sem gravar nada.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.http import QueryDict

from accounts.models import AccountOwner, AppUser, UserOwnerAccess
from bank_statements import fatura, medicao
from bank_statements.classificacao import (
    CONFIANCA_ALTA,
    CONFIANCA_BAIXA,
    CONFIANCA_MEDIA,
    CONFIANCA_NENHUMA,
    ORIGEM_BANCO_APRENDIDA,
    ORIGEM_CONTA,
    ORIGEM_HISTORICO,
    ORIGEM_PADRAO,
    ORIGEM_PREFIXO,
    ORIGEM_REGRA,
    Sugestao,
    eh_intermediador,
    sugerir_categoria,
)
from bank_statements.models import LINE_STATUS_RECONCILED, BankStatementImport, BankStatementLine
from bank_statements.reconciliation import reconciliation_view_data
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import (
    ACCOUNT_KIND_CREDIT_CARD,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_PROJECTED,
    STATUS_REALIZED,
)
from core.models import AuditLog
from transactions import services
from transactions.models import CashFlowCategory, CashFlowEntry


def _categoria(nome: str, pk: int) -> CashFlowCategory:
    categoria = CashFlowCategory(category_name=nome)
    categoria.id = pk
    return categoria


# --- O nível de confiança (sem banco) -----------------------------------------------


@pytest.mark.parametrize(
    ("origem", "votos", "iguais", "intermediador", "esperada"),
    [
        (ORIGEM_REGRA, 0, 0, False, CONFIANCA_ALTA),
        (ORIGEM_HISTORICO, 2, 2, False, CONFIANCA_ALTA),
        (ORIGEM_HISTORICO, 1, 1, False, CONFIANCA_MEDIA),
        (ORIGEM_HISTORICO, 10, 9, False, CONFIANCA_MEDIA),
        (ORIGEM_HISTORICO, 3, 2, False, CONFIANCA_BAIXA),
        (ORIGEM_HISTORICO, 5, 5, True, CONFIANCA_MEDIA),
        (ORIGEM_CONTA, 6, 6, False, CONFIANCA_ALTA),
        (ORIGEM_BANCO_APRENDIDA, 20, 20, False, CONFIANCA_MEDIA),
        (ORIGEM_BANCO_APRENDIDA, 9, 5, False, CONFIANCA_BAIXA),
        (ORIGEM_PREFIXO, 0, 0, False, CONFIANCA_BAIXA),
        (ORIGEM_PADRAO, 0, 0, False, CONFIANCA_NENHUMA),
    ],
)
def test_nivel_de_confianca(origem, votos, iguais, intermediador, esperada):
    sugestao = Sugestao(_categoria("Casa", 1), origem, votos, iguais, intermediador)
    assert sugestao.confianca == esperada
    assert sugestao.confiavel is (esperada == CONFIANCA_ALTA)


def test_sem_categoria_nao_ha_confianca():
    assert Sugestao(None, ORIGEM_HISTORICO, 3, 3).confianca == CONFIANCA_NENHUMA


@pytest.mark.parametrize(
    ("descricao", "esperado"),
    [
        ("MERCADOLIVRE*2PRODUTOS · Mariano", True),
        ("MERCADO*MERCADOLIVRE · Mariano", True),
        ("MP *JOANA · Claudia", True),
        ("SHOPEE *TOPCASA", True),
        ("AMAZON BR   *AMAZON BR", True),
        ("MERCADO DO JOAO", False),
        ("PATRICIA HARU", False),
        ("PAG TIT INT", False),
    ],
)
def test_intermediador(descricao, esperado):
    assert eh_intermediador(descricao) is esperado


# --- Prévia da fatura organizada (sem banco) ------------------------------------------


def _plano(pk, descricao, sugestao=None, *, acao=fatura.COMPRA, dia=date(2026, 9, 10), valor="-10.00"):
    linha = BankStatementLine(id=pk, description=descricao, amount=Decimal(valor), statement_date=dia)
    return fatura.Plano(
        linha=linha, acao=acao, categoria=sugestao.categoria if sugestao else None, sugestao=sugestao
    )


def test_previa_agrupa_o_incerto_da_mesma_loja_e_separa_o_resto():
    viagem, casa, outros = _categoria("Viagem", 1), _categoria("Casa", 2), _categoria("Outros", 3)
    banco = Sugestao(viagem, ORIGEM_BANCO_APRENDIDA, 9, 5)
    planos = [
        _plano(1, "UNITED01647204721164", banco, dia=date(2026, 9, 1)),
        _plano(2, "UNITED01647204721175 (US$ 24.00)", banco, dia=date(2026, 9, 2)),
        _plano(3, "UNITED01647204721186", banco, dia=date(2026, 9, 3)),
        _plano(4, "LOJA NUNCA VISTA", Sugestao(outros, ORIGEM_PADRAO), dia=date(2026, 9, 20)),
        _plano(5, "COMGAS", Sugestao(casa, ORIGEM_HISTORICO, 4, 4)),
        _plano(6, "TV NOVA", acao=fatura.PARCELA_LANCADA),
    ]
    previa = fatura.organizar(planos)

    # O que não tem sugestão vem antes do que tem sugestão fraca, mesmo sendo depois.
    assert [[p.linha.id for p in grupo.planos] for grupo in previa.a_conferir] == [[4], [1, 2, 3]]
    united = previa.a_conferir[1]
    assert (united.numero, united.membros, united.total) == (2, "1,2,3", Decimal("-30.00"))
    assert previa.linhas_a_conferir == 4
    assert [p.linha.id for p in previa.confiaveis] == [5]
    assert [p.linha.id for p in previa.sem_escolha] == [6]


def test_mesma_loja_com_sinal_ou_sugestao_diferente_nao_se_mistura():
    viagem, lazer = _categoria("Viagem", 1), _categoria("Lazer", 2)
    previa = fatura.organizar([
        _plano(1, "LOJA X", Sugestao(viagem, ORIGEM_BANCO_APRENDIDA, 2, 1)),
        _plano(2, "LOJA X", Sugestao(viagem, ORIGEM_BANCO_APRENDIDA, 2, 1), acao=fatura.ESTORNO, valor="10.00"),
        _plano(3, "LOJA X", Sugestao(lazer, ORIGEM_BANCO_APRENDIDA, 2, 1)),
    ])
    assert len(previa.a_conferir) == 3


def test_escolha_do_grupo_vale_para_quem_ficou_igual_ao_grupo():
    post = QueryDict("grupo_1=7&membros_1=11,12,13&categoria_12=9&categoria_14=&categoria_15=5&grupo_2=&membros_2=16")
    assert fatura.escolhas_do_formulario(post) == {"11": "7", "12": "9", "13": "7", "15": "5"}


# --- Com banco ----------------------------------------------------------------------


@pytest.fixture
def mundo(db):
    user = AppUser.objects.create_user(username="operador-confianca", password="senha-segura")
    titular = AccountOwner.objects.create(name="Titular")
    UserOwnerAccess.objects.create(
        user=user, owner=titular, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    banco = FinancialInstitution.objects.create(institution_name="C6", institution_type="Banco")
    contas = {
        nome: FinancialAccount.objects.create(owner=titular, institution=banco, account_name=nome)
        for nome in ("corrente", "administrada", "poucos", "dividida")
    }
    cat = {
        nome: CashFlowCategory.objects.create(category_name=nome)
        for nome in ("Outros", "Salário", "Jardim Iva", "Lazer", "Alimentação", "Supermercado")
    }
    return user, contas, cat


def _lancar(user, conta, categoria, descricao, dia, *, valor="10.00", tipo=ENTRY_TYPE_EXPENSE):
    return services.create_transaction_batch(
        services.TransactionRequest(
            account_id=conta.id, category_id=categoria.id, entry_type=tipo, description=descricao,
            entry_amount=Decimal(valor), installments=1, due_date=dia, status=STATUS_REALIZED,
            realized_date=dia, realized_amount=Decimal(valor),
        ),
        user=user,
    )[0]


def _linha(conta, texto, dia, valor, *, lancamento=None):
    lote, _ = BankStatementImport.objects.get_or_create(
        account=conta, source_filename="extrato.ofx", defaults={"row_count": 0}
    )
    return BankStatementLine.objects.create(
        import_batch=lote, account=conta, statement_date=dia, description=texto, amount=Decimal(valor),
        line_hash=f"h{BankStatementLine.objects.count()}-{conta.id}",
        status=LINE_STATUS_RECONCILED if lancamento else "novo", matched_entry=lancamento,
    )


def test_historico_aprende_do_texto_do_banco_quando_a_descricao_foi_reescrita(mundo):
    user, contas, cat = mundo
    for dia in (date(2026, 7, 25), date(2026, 8, 25)):
        salario = _lancar(user, contas["corrente"], cat["Salário"], "Salário", dia, valor="9000.00", tipo=ENTRY_TYPE_INCOME)
        _linha(contas["corrente"], "PAGTO SALARIO", dia, "9000.00", lancamento=salario)

    sugestao = sugerir_categoria("PAGTO SALARIO")
    assert (sugestao.categoria, sugestao.origem) == (cat["Salário"], ORIGEM_HISTORICO)
    assert (sugestao.votos, sugestao.iguais, sugestao.confianca) == (2, 2, CONFIANCA_ALTA)


def test_lancamento_vota_uma_vez_mesmo_casando_pelos_dois_textos(mundo):
    user, contas, cat = mundo
    padaria = _lancar(user, contas["corrente"], cat["Alimentação"], "Padaria Central", date(2026, 8, 3))
    _linha(contas["corrente"], "Padaria Central", date(2026, 8, 3), "-10.00", lancamento=padaria)

    sugestao = sugerir_categoria("Padaria Central")
    assert (sugestao.votos, sugestao.confianca) == (1, CONFIANCA_MEDIA)


def test_antes_de_ignora_o_historico_posterior(mundo):
    user, contas, cat = mundo
    _lancar(user, contas["corrente"], cat["Lazer"], "Cinema Bom", date(2026, 9, 5))
    assert sugerir_categoria("Cinema Bom", antes_de=date(2026, 9, 1)).origem == ORIGEM_PADRAO
    assert sugerir_categoria("Cinema Bom", antes_de=date(2026, 10, 1)).categoria == cat["Lazer"]


def test_texto_generico_usa_a_categoria_dominante_da_conta(mundo):
    user, contas, cat = mundo
    for dia in range(1, 6):
        _lancar(user, contas["administrada"], cat["Jardim Iva"], f"Repasse {dia}", date(2026, 8, dia))
        _lancar(user, contas["corrente"], cat["Lazer"], f"Passeio {dia}", date(2026, 8, dia))
    for dia in range(1, 5):
        _lancar(user, contas["poucos"], cat["Jardim Iva"], f"Repasse {dia}", date(2026, 8, dia))
    for dia, categoria in enumerate(("Jardim Iva", "Jardim Iva", "Jardim Iva", "Lazer", "Lazer"), start=1):
        _lancar(user, contas["dividida"], cat[categoria], f"Repasse {dia}", date(2026, 8, dia))

    sugestao = sugerir_categoria("Boleto", conta=contas["administrada"], tipo=ENTRY_TYPE_EXPENSE)
    assert (sugestao.categoria, sugestao.origem, sugestao.confianca) == (cat["Jardim Iva"], ORIGEM_CONTA, CONFIANCA_ALTA)
    assert sugerir_categoria("Boleto", conta=contas["corrente"], tipo=ENTRY_TYPE_EXPENSE).categoria == cat["Lazer"]
    # Outro tipo, base pequena, maioria fraca, sem conta, ou descrição que não é genérica: não vale.
    assert sugerir_categoria("Boleto", conta=contas["administrada"], tipo=ENTRY_TYPE_INCOME).origem == ORIGEM_PADRAO
    assert sugerir_categoria("Boleto", conta=contas["poucos"], tipo=ENTRY_TYPE_EXPENSE).origem == ORIGEM_PADRAO
    assert sugerir_categoria("Boleto", conta=contas["dividida"], tipo=ENTRY_TYPE_EXPENSE).origem == ORIGEM_PADRAO
    assert sugerir_categoria("Boleto").origem == ORIGEM_PADRAO
    assert sugerir_categoria("Loja nova", conta=contas["administrada"], tipo=ENTRY_TYPE_EXPENSE).origem == ORIGEM_PADRAO


def test_conciliacao_poe_o_incerto_primeiro(mundo):
    user, contas, cat = mundo
    conta = contas["corrente"]
    previsto = services.create_transaction_batch(
        services.TransactionRequest(
            account_id=conta.id, category_id=cat["Lazer"].id, entry_type=ENTRY_TYPE_EXPENSE, description="Academia",
            entry_amount=Decimal("120.00"), installments=1, due_date=date(2026, 9, 20), status=STATUS_PROJECTED,
        ),
        user=user,
    )[0]
    nova = _linha(conta, "LOJA NUNCA VISTA", date(2026, 9, 5), "-33.00")
    com_candidato = _linha(conta, "ACADEMIA", date(2026, 9, 20), "-120.00")

    linhas = reconciliation_view_data(user)["lines"]
    assert [linha.id for linha in linhas] == [nova.id, com_candidato.id]
    assert [linha.confiavel for linha in linhas] == [False, True]
    assert linhas[1].plano.lancamento == previsto


def test_medicao_refaz_o_passado_sem_olhar_o_futuro(mundo):
    user, contas, cat = mundo
    conta = contas["corrente"]
    # Julho: o lançamento já existia quando a linha chegou. Agosto: nasceu da linha.
    julho = _lancar(user, conta, cat["Alimentação"], "Padaria Central", date(2026, 7, 3))
    _linha(conta, "Padaria Central", date(2026, 7, 3), "-10.00", lancamento=julho)
    linha_agosto = _linha(conta, "Padaria Central", date(2026, 8, 3), "-12.00")
    agosto = _lancar(user, conta, cat["Alimentação"], "Padaria Central", date(2026, 8, 3), valor="12.00")
    BankStatementLine.objects.filter(id=linha_agosto.id).update(status=LINE_STATUS_RECONCILED, matched_entry=agosto)

    casos = {caso.linha.statement_date.month: caso for caso in medicao.casos()}
    # Julho não tem histórico anterior: a compra de agosto não pode ensinar julho.
    assert (casos[7].sugestao.origem, casos[7].acertou, casos[7].lancamento_novo) == (ORIGEM_PADRAO, False, False)
    assert (casos[8].sugestao.origem, casos[8].acertou, casos[8].lancamento_novo) == (ORIGEM_HISTORICO, True, True)
    assert medicao.taxa(casos.values()) == medicao.Taxa(2, 1)


def _nascido_da_linha(user, conta, categoria, texto, dia, *, bank_category=""):
    """Lançamento criado a partir da linha (a linha existia antes dele)."""
    linha = _linha(conta, texto, dia, "-10.00")
    if bank_category:
        BankStatementLine.objects.filter(id=linha.id).update(bank_category=bank_category)
    entrada = _lancar(user, conta, categoria, texto, dia)
    BankStatementLine.objects.filter(id=linha.id).update(status=LINE_STATUS_RECONCILED, matched_entry=entrada)
    return entrada


def test_suspeito_e_o_lancamento_do_extrato_que_destoa_da_mesma_loja(mundo):
    user, contas, cat = mundo
    conta = contas["corrente"]
    for dia in range(1, 8):  # digitados à mão: contam para a maioria da loja
        _lancar(user, conta, cat["Lazer"], "ARMARINHO ARTE", date(2026, 8, dia))
    destoa = _nascido_da_linha(user, conta, cat["Supermercado"], "ARMARINHO ARTE", date(2026, 8, 10))
    # Digitado à mão, com ou sem linha conciliada depois: a categoria foi escolhida
    # junto com o texto, não é suspeito.
    _lancar(user, conta, cat["Supermercado"], "ARMARINHO ARTE", date(2026, 8, 11))
    ja_existia = _lancar(user, conta, cat["Supermercado"], "ARMARINHO ARTE", date(2026, 8, 12))
    _linha(conta, "ARMARINHO ARTE", date(2026, 8, 12), "-10.00", lancamento=ja_existia)
    for dia in (1, 2, 3):  # intermediador: vender de tudo não é destoar
        _nascido_da_linha(user, conta, cat["Lazer"], "MERCADOLIVRE*LOJA", date(2026, 8, dia))
    _nascido_da_linha(user, conta, cat["Alimentação"], "MERCADOLIVRE*LOJA", date(2026, 8, 4))

    achados = medicao.suspeitos()
    assert [(s.lancamento.id, s.esperada, s.iguais, s.total) for s in achados] == [(destoa.id, cat["Lazer"], 7, 10)]


def test_destoar_so_da_categoria_do_banco_nao_e_suspeito(mundo):
    user, _, cat = mundo
    banco = FinancialInstitution.objects.create(institution_name="C6 cartão", institution_type="Banco")
    titular = AccountOwner.objects.get(name="Titular")
    cartao = FinancialAccount.objects.create(
        owner=titular, institution=banco, account_name="Carbon", account_kind=ACCOUNT_KIND_CREDIT_CARD,
        card_closing_day=19, card_due_day=25,
    )
    for dia in range(1, 11):
        _nascido_da_linha(user, cartao, cat["Lazer"], f"CINEMA {chr(64 + dia)}", date(2026, 8, dia),
                          bank_category="Entretenimento")
    # Uma escolha mais específica que a do banco, numa loja sem outras compras.
    _nascido_da_linha(user, cartao, cat["Alimentação"], "LASTPASS", date(2026, 8, 20), bank_category="Entretenimento")
    assert medicao.suspeitos() == []


def test_comando_mede_e_desfaz_o_que_a_medicao_gravar(mundo, monkeypatch):
    user, contas, cat = mundo
    conta = contas["corrente"]
    entrada = _lancar(user, conta, cat["Lazer"], "Cinema Bom", date(2026, 8, 5))
    _linha(conta, "Cinema Bom", date(2026, 8, 5), "-10.00", lancamento=entrada)
    antes = (CashFlowEntry.objects.count(), BankStatementLine.objects.count(), AuditLog.objects.count())
    original = medicao.casos

    def casos_que_gravam(**filtros):
        # A medição só lê; se um dia algo nela gravar, o comando desfaz.
        CashFlowCategory.objects.create(category_name="Criada durante a medição")
        return original(**filtros)

    monkeypatch.setattr(medicao, "casos", casos_que_gravam)
    saida = StringIO()
    call_command("medir_sugestoes", stdout=saida)
    texto = saida.getvalue()
    assert "Linhas avaliadas: 1" in texto and "Acerto" in texto and "Suspeitos" in texto
    assert not CashFlowCategory.objects.filter(category_name="Criada durante a medição").exists()
    assert (CashFlowEntry.objects.count(), BankStatementLine.objects.count(), AuditLog.objects.count()) == antes
