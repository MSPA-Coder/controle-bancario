"""Seletor de lançamento em Controle gerencial e Comprovantes.

Antes o usuário digitava à mão o número interno do lançamento. Agora escolhe
numa lista, e o servidor decide o que a lista contém: só lançamentos de contas
que o usuário pode alterar (o mesmo teste do POST), do mês pedido, mais
recentes primeiro. O rótulo segue o formato regional de quem lê.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import AccountOwner, AppPermission, UserOwnerAccess, UserPermission
from banking.models import FinancialAccount, FinancialInstitution
from core.domain.finance import ENTRY_TYPE_EXPENSE, STATUS_PROJECTED
from core.domain.identity import USER_TYPE_USER
from transactions.models import CashFlowCategory, CashFlowEntry

pytestmark = pytest.mark.django_db

MES = date(2026, 11, 1)


def _conta(titular: str):
    dono = AccountOwner.objects.create(name=titular)
    banco, _ = FinancialInstitution.objects.get_or_create(
        institution_name="Banco dos testes", defaults={"institution_type": "Banco"}
    )
    conta = FinancialAccount.objects.create(
        owner=dono, institution=banco, account_name=f"Corrente {titular}",
        initial_balance=Decimal("0"), initial_balance_date=date(2026, 1, 1),
    )
    return dono, conta


def _lancamento(conta, descricao: str, dia: date, valor: str = "150.00") -> CashFlowEntry:
    categoria, _ = CashFlowCategory.objects.get_or_create(category_name="Mercado")
    return CashFlowEntry.objects.create(
        account=conta, category=categoria, entry_type=ENTRY_TYPE_EXPENSE, description=descricao,
        entry_amount=Decimal(valor), due_date=dia, status=STATUS_PROJECTED,
    )


@pytest.fixture
def cenario():
    """Dois titulares; o usuário comum só altera o primeiro e apenas VÊ o segundo."""
    meu_dono, minha_conta = _conta("Meu")
    outro_dono, outra_conta = _conta("Alheio")
    visto_dono, vista_conta = _conta("Somente leitura")
    # O tipo padrão do modelo é administrador, que alcança todos os titulares.
    usuario = get_user_model().objects.create_user(
        username="comum", password="senha-segura", user_type=USER_TYPE_USER
    )
    UserOwnerAccess.objects.create(
        user=usuario, owner=meu_dono, can_view=True, can_create=True, can_update=True, can_delete=True
    )
    # As quatro colunas nascem True no modelo: "só leitura" tem de negar as outras três.
    UserOwnerAccess.objects.create(
        user=usuario, owner=visto_dono, can_view=True, can_create=False, can_update=False, can_delete=False
    )
    for nome in ("management.view", "management.manage", "banking.view", "banking.attachments.manage"):
        UserPermission.objects.create(user=usuario, permission=AppPermission.objects.get(name=nome))
    return usuario, minha_conta, outra_conta, vista_conta


def _ids(resposta) -> list[int]:
    return [e.id for e in resposta.context["entry_choices"]]


def test_gerencial_lista_so_o_que_o_usuario_pode_alterar_do_mes_mais_recentes_primeiro(client, cenario):
    usuario, minha, outra, vista = cenario
    antigo = _lancamento(minha, "Dia 3", date(2026, 11, 3))
    recente = _lancamento(minha, "Dia 20", date(2026, 11, 20))
    _lancamento(minha, "Mês anterior", date(2026, 10, 30))
    _lancamento(outra, "De outro titular", date(2026, 11, 10))
    _lancamento(vista, "Só leitura", date(2026, 11, 11))
    client.force_login(usuario)

    resposta = client.get(reverse("management:management_view"), {"month": "2026-11"})

    assert _ids(resposta) == [recente.id, antigo.id]


def test_gerencial_respeita_o_filtro_de_conta_da_tela(client, cenario):
    usuario, minha, _outra, _vista = cenario
    outra_minha = FinancialAccount.objects.create(
        owner=minha.owner, institution=minha.institution, account_name="Poupança",
        initial_balance=Decimal("0"), initial_balance_date=date(2026, 1, 1),
    )
    _lancamento(minha, "Na corrente", date(2026, 11, 5))
    na_poupanca = _lancamento(outra_minha, "Na poupança", date(2026, 11, 6))
    client.force_login(usuario)

    resposta = client.get(
        reverse("management:management_view"), {"month": "2026-11", "account_id": outra_minha.id}
    )

    assert _ids(resposta) == [na_poupanca.id]


def test_entry_id_na_url_pre_seleciona_mesmo_fora_do_mes_mas_nunca_o_de_outro_titular(client, cenario):
    usuario, minha, outra, _vista = cenario
    fora_do_mes = _lancamento(minha, "Mês anterior", date(2026, 10, 30))
    alheio = _lancamento(outra, "De outro titular", date(2026, 11, 10))
    client.force_login(usuario)
    url = reverse("management:management_view")

    com_proprio = client.get(url, {"month": "2026-11", "entry_id": fora_do_mes.id})
    com_alheio = client.get(url, {"month": "2026-11", "entry_id": alheio.id})
    com_lixo = client.get(url, {"month": "2026-11", "entry_id": "abc"})

    assert com_proprio.context["selected_entry_id"] == fora_do_mes.id
    assert _ids(com_proprio)[0] == fora_do_mes.id
    assert alheio.id not in _ids(com_alheio)
    assert com_lixo.status_code == 200 and com_lixo.context["selected_entry_id"] is None


def test_rotulo_sai_no_formato_regional_de_quem_le(client, cenario):
    usuario, minha, _outra, _vista = cenario
    _lancamento(minha, "Feira", date(2026, 11, 25), valor="1234.50")
    client.force_login(usuario)
    url = reverse("management:management_view")

    usuario.regional_format = "br"
    usuario.save()
    em_br = client.get(url, {"month": "2026-11"}).content.decode()
    usuario.regional_format = "us"
    usuario.save()
    em_us = client.get(url, {"month": "2026-11"}).content.decode()

    assert "25/11/2026 · Feira" in em_br and "1.234,50" in em_br
    assert "11/25/2026 · Feira" in em_us and "1,234.50" in em_us


def test_sem_lancamento_no_recorte_o_seletor_vem_desabilitado_com_a_explicacao(client, cenario):
    usuario, minha, _outra, _vista = cenario
    _lancamento(minha, "Outro mês", date(2026, 9, 5))
    client.force_login(usuario)

    resposta = client.get(reverse("management:management_view"), {"month": "2026-11"})
    html = resposta.content.decode()

    assert _ids(resposta) == []
    assert 'name="entry_id" id="mgc-tag-entry" required disabled' in html
    assert "Nenhum lançamento neste recorte" in html


def test_comprovantes_usa_o_mes_atual_por_padrao_e_aceita_outro_mes(client, cenario):
    usuario, minha, outra, vista = cenario
    hoje = date.today()
    deste_mes = _lancamento(minha, "Deste mês", date(hoje.year, hoje.month, 1))
    de_setembro = _lancamento(minha, "Setembro", date(2026, 9, 5))
    _lancamento(outra, "De outro titular", date(2026, 9, 6))
    _lancamento(vista, "Só leitura", date(2026, 9, 7))
    client.force_login(usuario)
    url = reverse("bank_statements:attachments_view")

    padrao = client.get(url)
    setembro = client.get(url, {"month": "2026-09"})

    assert _ids(padrao) == [deste_mes.id]
    assert _ids(setembro) == [de_setembro.id]


def test_comprovantes_sem_lancamento_no_mes_mostra_seletor_desabilitado(client, cenario):
    usuario, *_ = cenario
    client.force_login(usuario)

    html = client.get(reverse("bank_statements:attachments_view"), {"month": "2026-11"}).content.decode()

    assert 'name="entry_id" id="att-entry" required disabled' in html
    assert "Nenhum lançamento neste recorte" in html


def test_post_continua_recusando_lancamento_de_titular_sem_acesso_mesmo_com_o_id_forjado(client, cenario):
    """A lista é conforto; quem protege é o servidor, que revalida o entry_id recebido."""
    from management.models import ManagementTag

    usuario, _minha, outra, vista = cenario
    alheio = _lancamento(outra, "De outro titular", date(2026, 11, 10))
    so_leitura = _lancamento(vista, "Só leitura", date(2026, 11, 11))
    tag = ManagementTag.objects.create(tag_name="reembolsável")
    client.force_login(usuario)

    for lancamento in (alheio, so_leitura):
        client.post(
            reverse("management:assign_tag"), {"entry_id": lancamento.id, "tag_id": tag.id}
        )

    assert not tag.entry_links.exists()
