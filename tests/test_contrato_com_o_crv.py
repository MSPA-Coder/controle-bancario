"""O que o CB e o Controle de Renda Variável (CRV) dizem um ao outro.

Cada lado testava o outro com dado sintético próprio: o CRV lia um snapshot
escrito à mão, e o CB lia um status de fechamento escrito à mão. Um campo
renomeado passava nas duas suítes e quebrava em produção, que era o único lugar
onde os dois sistemas se encontravam. Dois arquivos comuns fecham isso, ambos
cópias das canônicas em `manutencao/docs/contratos/` (`sincronizar.py`):

* `exemplo-cb-snapshot-vinculo.json`: o que **este** sistema responde ao CRV
  (snapshot v4 com o token do vínculo), gerado aqui pelo caminho real -- o parser
  do extrato grava o detalhe e a rota o publica. A suíte do CRV lê o mesmo
  arquivo com o cliente dele. Se o CB mudar o que publica, este teste reprova e
  mostra o arquivo novo; atualizar a canônica leva a mudança à suíte do CRV.
* `crv-fechamento-1.schema.json`: o que o CRV responde ao Roteiro de fechamento.
  O CRV valida a resposta real dele; aqui se confere que o leitor aceita
  exatamente os estados e as etapas do schema.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.test import Client
from jsonschema import Draft202012Validator

from accounts.models import AccountOwner
from bank_statements.investimentos import interpretar
from bank_statements.investimentos_preenchimento import gravar
from bank_statements.models import BankStatementImport
from banking.models import FinancialAccount, FinancialInstitution
from core import patrimonio
from core.domain.finance import (
    CATEGORY_KIND_MANAGERIAL,
    CATEGORY_KIND_MOVEMENT,
    ENTRY_TYPE_EXPENSE,
    ENTRY_TYPE_INCOME,
    STATUS_REALIZED,
)
from fechamento import crv
from transactions.models import CashFlowCategory, CashFlowEntry

CONTRATO = Path(__file__).parent / "contrato"
EXEMPLO = CONTRATO / "exemplo-cb-snapshot-vinculo.json"
SCHEMA_V4 = json.loads((CONTRATO / "patrimonio-v4.schema.json").read_text(encoding="utf-8"))
SCHEMA_DO_FECHAMENTO = json.loads((CONTRATO / "crv-fechamento-1.schema.json").read_text(encoding="utf-8"))
TOKEN_DE_INTEGRACAO = "token-de-integracao-v4-com-mais-de-trinta-e-dois-caracteres"
TOKEN_DO_VINCULO = "token-do-vinculo-cb-crv-com-mais-de-trinta-e-dois-caracteres"

# O que muda a cada execução sem que o contrato mude: chaves do banco de teste,
# instantes e a data de hoje. O resto do exemplo é o que a rota respondeu.
INSTANTE_FIXO = "2026-01-01T00:00:00+00:00"
DATA_FIXA = "2026-12-31"
_ID = re.compile(r"^controle-bancario:([a-z-]+):[0-9a-f]{24}$")


def _normalizar(snapshot: dict) -> dict:
    apelidos: dict[str, str] = {}

    def apelido(valor):
        achado = _ID.match(valor) if isinstance(valor, str) else None
        if achado is None:
            return valor
        if valor not in apelidos:
            apelidos[valor] = f"controle-bancario:{achado.group(1)}:exemplo-{len(apelidos) + 1}"
        return apelidos[valor]

    itens = []
    for item in snapshot["items"]:
        payload = {chave: apelido(valor) for chave, valor in item["payload"].items()}
        for chave in ("created_at", "updated_at"):
            if payload.get(chave):
                payload[chave] = INSTANTE_FIXO
        if "deep_link" in payload:
            payload["deep_link"] = "/exemplo"
        if payload.get("balance_as_of"):
            payload["balance_as_of"] = DATA_FIXA
        itens.append({"resource": item["resource"], "source_id": apelido(item["source_id"]), "payload": payload})
    return {
        "_origem": (
            "Gerado por tests/test_contrato_com_o_crv.py do ControleBancario: o snapshot v4 que o CB responde "
            "ao CRV com o token do vinculo. Ids, instantes e data do saldo sao fixos; o resto e a resposta real."
        ),
        "contrato": snapshot["contrato"],
        "sistema": snapshot["sistema"],
        "scope": snapshot["scope"],
        "items": itens,
    }


@pytest.fixture
def tokens(monkeypatch, tmp_path):
    for nome, valor in (
        (patrimonio.NOME_DO_SEGREDO_V4, TOKEN_DE_INTEGRACAO),
        (patrimonio.NOME_DO_SEGREDO_DO_VINCULO, TOKEN_DO_VINCULO),
    ):
        arquivo = tmp_path / nome.lower()
        arquivo.write_text(valor, encoding="utf-8")
        monkeypatch.delenv(nome, raising=False)
        monkeypatch.setenv(f"{nome}_FILE", str(arquivo))


@pytest.fixture
def cenario(tokens):
    """Um de cada coisa que o CRV lê, com as descrições que as corretoras imprimem."""
    # A categoria que uma migração semeia existe ou não conforme os testes que
    # rodaram antes no mesmo banco; o exemplo não pode depender disso.
    CashFlowCategory.objects.all().delete()
    titular = AccountOwner.objects.create(name="Titular")
    genial = FinancialInstitution.objects.create(institution_name="Genial", institution_type="Corretora")
    avenue = FinancialInstitution.objects.create(institution_name="Avenue", institution_type="Corretora")
    banco = FinancialInstitution.objects.create(institution_name="Banco da Casa", institution_type="Banco")

    def conta(instituicao, nome, moeda):
        return FinancialAccount.objects.create(
            owner=titular, institution=instituicao, account_name=nome, currency=moeda,
            initial_balance=Decimal("0.00"), initial_balance_date=date(2025, 12, 31),
        )

    conta_genial = conta(genial, "Conta 03", "BRL")
    conta_avenue = conta(avenue, "Conta em dólar", "USD")
    conta_da_casa = conta(banco, "Conta corrente", "BRL")
    bolsa = CashFlowCategory.objects.create(category_name="Operações em Bolsa", kind=CATEGORY_KIND_MOVEMENT)
    renda = CashFlowCategory.objects.create(category_name="Aluguel de Açoes / Dividendos / JCP", kind=CATEGORY_KIND_MANAGERIAL)
    irrf = CashFlowCategory.objects.create(category_name="IRRF sobre investimentos", kind=CATEGORY_KIND_MANAGERIAL)
    mercado = CashFlowCategory.objects.create(category_name="Mercado", kind=CATEGORY_KIND_MANAGERIAL)

    def lancar(conta_, categoria, tipo, descricao, valor, dia, *, do_extrato=True):
        entry = CashFlowEntry.objects.create(
            account=conta_, category=categoria, entry_type=tipo, description=descricao,
            entry_amount=Decimal(valor), due_date=dia, realized_date=dia, realized_amount=Decimal(valor),
            status=STATUS_REALIZED,
        )
        detalhe = interpretar(descricao) if do_extrato else None
        if detalhe is not None and not detalhe.vazio:
            gravar(entry.id, detalhe)

    # B3: liquidação com nota, com nota mascarada, futuro e uma digitada à mão.
    lancar(conta_genial, bolsa, ENTRY_TYPE_INCOME, "Operações Bolsa D+2 Pr 27/01/2026 Nc. 543216", "1252.10", date(2026, 1, 29))
    lancar(conta_genial, bolsa, ENTRY_TYPE_EXPENSE, "Operações Bolsa D+2 Pr 20/03/2026 Nc. *", "300.00", date(2026, 3, 24))
    lancar(conta_genial, bolsa, ENTRY_TYPE_EXPENSE, "Operações Bm&F Pr 06/01/2026 Nc. 126168", "0.50", date(2026, 1, 7))
    lancar(conta_genial, bolsa, ENTRY_TYPE_INCOME, "Operações Bolsa D+2 Pr 01/04/2026", "40.00", date(2026, 4, 6), do_extrato=False)
    # Renda: dividendo, JCP e o aluguel com a retenção dele.
    lancar(conta_genial, renda, ENTRY_TYPE_INCOME, "Dividendos Brwegeacnor0", "8.00", date(2026, 6, 2))
    lancar(conta_genial, renda, ENTRY_TYPE_INCOME, "Juros S/ Capital EALT4", "15.00", date(2026, 6, 11))
    lancar(conta_genial, renda, ENTRY_TYPE_INCOME, "Taxa de Remuneração Emprestimo Ações Brraizacnpr6", "10.00", date(2026, 7, 1))
    lancar(conta_genial, irrf, ENTRY_TYPE_EXPENSE, "Irrf S/Rendimentos Empréstimos de Ações Brraizacnpr6", "1.50", date(2026, 7, 1))
    # Exterior: negócio com ativo e quantidade, e o cupom de um título.
    lancar(conta_avenue, bolsa, ENTRY_TYPE_EXPENSE, "Compra de CGC na Avenue: 5000 a US$ 0,95, pregão 16/06/2026", "4750.00", date(2026, 6, 17))
    lancar(conta_avenue, renda, ENTRY_TYPE_INCOME, "Cupom de ORCL 3.95 25/03/51 na Avenue", "39.50", date(2026, 9, 25))
    # O gasto da casa, que o CRV não pode receber.
    lancar(conta_da_casa, mercado, ENTRY_TYPE_EXPENSE, "Supermercado", "99.90", date(2026, 2, 3))

    BankStatementImport.objects.create(
        account=conta_genial, source_filename="extrato.pdf", statement_period_end=date(2026, 9, 30)
    )
    BankStatementImport.objects.create(
        account=conta_avenue, source_filename="Stmt_20260930.pdf", statement_balance=Decimal("0.00"),
        statement_balance_date=date(2026, 9, 30),
        statement_holdings=[{"instrument": "BRK.B", "quantity": "1.56365"}, {"instrument": "CGC", "quantity": "5000"}],
    )


@pytest.mark.django_db(transaction=True)
def test_o_exemplo_que_o_crv_le_e_o_que_o_cb_responde_hoje(cenario):
    resposta = Client().get("/patrimonio/v4/snapshot", HTTP_AUTHORIZATION=f"Bearer {TOKEN_DO_VINCULO}")
    assert resposta.status_code == 200
    snapshot = resposta.json()
    erros = list(Draft202012Validator({"$ref": "#/$defs/cb_snapshot", "$defs": SCHEMA_V4["$defs"]}).iter_errors(snapshot))
    assert not erros, [erro.message for erro in erros[:5]]
    assert "Supermercado" not in resposta.content.decode(), "o gasto da casa vazou para o CRV"

    atual = _normalizar(snapshot)
    guardado = json.loads(EXEMPLO.read_text(encoding="utf-8")) if EXEMPLO.exists() else None

    assert atual == guardado, (
        "O CB passou a responder outra coisa ao CRV. Se a mudança é intencional, grave o texto abaixo em "
        "_manutencao/docs/contratos/exemplos/cb-snapshot-vinculo.json, rode sincronizar.py --aplicar e "
        "rode a suíte do CRV, que lê o mesmo arquivo.\n<<<EXEMPLO\n"
        + json.dumps(atual, ensure_ascii=False, indent=2)
        + "\nEXEMPLO>>>"
    )


def test_o_roteiro_aceita_exatamente_os_estados_e_as_etapas_do_contrato():
    """Um estado que o CRV passe a emitir e o CB não conheça some do roteiro, calado."""
    Draft202012Validator.check_schema(SCHEMA_DO_FECHAMENTO)
    definicoes = SCHEMA_DO_FECHAMENTO["$defs"]

    assert set(definicoes["estado"]["enum"]) == crv.ESTADOS_ACEITOS
    assert set(definicoes["etapa"]["enum"]) == crv.ETAPAS_ACEITAS
    assert definicoes["resposta"]["properties"]["contrato"]["const"] == crv.CONTRATO


def test_item_que_cumpre_o_contrato_nao_e_descartado_pelo_roteiro(monkeypatch):
    monkeypatch.setenv("CRV_PUBLIC_URL", "https://renda.exemplo")
    validador = Draft202012Validator({"$ref": "#/$defs/item", "$defs": SCHEMA_DO_FECHAMENTO["$defs"]})
    for estado in sorted(crv.ESTADOS_ACEITOS):
        for etapa in sorted(crv.ETAPAS_ACEITAS):
            # Só os campos obrigatórios: o que o schema não exige o roteiro não pode exigir.
            item = {"chave": "pregoes", "etapa": etapa, "titulo": "Pregões", "estado": estado, "texto": "12 conferem"}
            assert not list(validador.iter_errors(item))
            assert crv._item_valido(item) is not None, (estado, etapa)
    completo = {
        "chave": "pregoes", "etapa": "conferencias", "titulo": "Pregões", "subtitulo": "CRV", "estado": "pendente",
        "texto": "1 pregão não confere", "detalhe": "Diferença 1.", "acao": "Abrir a conferência",
        "url": "/executions/reconciliation", "passos": ["Abra a conferência."],
    }
    assert not list(validador.iter_errors(completo))
    assert crv._item_valido(completo)["url"] == "https://renda.exemplo/executions/reconciliation"
