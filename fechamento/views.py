"""Roteiro de fechamento: o painel, as fontes, os cortes e a coleta do myProfit."""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext, ngettext
from django.views.decorators.http import require_POST

from banking.models import FinancialAccount
from banking.services import accessible_account_ids, can_access_account
from core.permissions import permission_required
from core.services import audit_request_context

from . import duplicatas, fontes, myprofit, roteiro
from .models import CLASSES_MYPROFIT, FONTES, FREQUENCIAS, CorteDeFechamento

#: A coleta enviada fica na sessão entre a prévia e a gravação, como texto.
CHAVE_DA_COLETA = "fechamento_coleta_myprofit"


def _corte_do_get(valor, hoje: date) -> date:
    try:
        corte = date.fromisoformat(str(valor))
    except ValueError:
        return hoje
    return corte if date(2000, 1, 1) <= corte <= date(2100, 12, 31) else hoje


def _url_do_painel(corte: date, filtro: str = "", ancora: str = "") -> str:
    url = f"{reverse('fechamento:painel')}?corte={corte.isoformat()}"
    if filtro == "tudo":
        url += "&ver=tudo"
    return url + (f"#{ancora}" if ancora else "")


def _plano_da_sessao(request):
    texto = request.session.get(CHAVE_DA_COLETA)
    if not texto:
        return None
    try:
        return myprofit.planejar(request.user, myprofit.ler(texto.encode("utf-8")))
    except ValueError:
        request.session.pop(CHAVE_DA_COLETA, None)
        return None


@login_required
@permission_required('banking.view')
def painel_view(request):
    hoje = date.today()
    corte = _corte_do_get(request.GET.get('corte', ''), hoje)
    filtro = "tudo" if request.GET.get('ver') == "tudo" else "falta"
    dados = roteiro.montar(request.user, corte, hoje)
    return render(request, 'fechamento/painel.html', {
        "roteiro": dados,
        "filtro": filtro,
        "aba": "roteiro",
        "legenda": [(estado, rotulo) for estado, rotulo in roteiro.ROTULOS.items() if estado != roteiro.DEPOIS],
        "plano": _plano_da_sessao(request),
        "pode_conciliar": request.user.has_perm('banking.reconcile'),
    })


@login_required
@permission_required('banking.view')
def fontes_view(request):
    contas = list(
        FinancialAccount.objects.filter(id__in=accessible_account_ids(request.user, "view"))
        .select_related("owner", "institution")
        .order_by("owner__name", "institution__institution_name", "account_name")
    )
    efetivas = fontes.fontes_das_contas(contas)
    return render(request, 'fechamento/fontes.html', {
        "linhas": [(conta, efetivas[conta.id]) for conta in contas],
        "opcoes_de_fonte": FONTES,
        "opcoes_de_frequencia": FREQUENCIAS,
        "opcoes_de_classe": CLASSES_MYPROFIT,
        "aba": "fontes",
        "pode_editar": request.user.has_perm('banking.import'),
    })


@login_required
@permission_required('banking.import', fallback='fechamento:fontes')
@require_POST
def salvar_fonte_view(request, account_id: int):
    if not can_access_account(request.user, account_id, "update"):
        messages.error(request, gettext("Acesso negado: você não tem permissão para acessar esta conta."))
        return redirect('fechamento:fontes')
    conta = FinancialAccount.objects.select_related("institution").get(id=account_id)
    try:
        fontes.salvar(request.user, conta, request.POST, audit_context=audit_request_context(request))
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, gettext("Fonte de %(conta)s gravada. O roteiro já usa o novo cadastro.") % {
            "conta": f"{conta.institution.institution_name} / {conta.account_name}",
        })
    return redirect(f"{reverse('fechamento:fontes')}#conta-{account_id}")


@login_required
@permission_required('banking.view')
def cortes_view(request):
    return render(request, 'fechamento/cortes.html', {
        "cortes": CorteDeFechamento.objects.filter(user=request.user)[:36],
        "aba": "cortes",
    })


@login_required
@permission_required('banking.reconcile', fallback='fechamento:painel')
@require_POST
def concluir_corte_view(request):
    hoje = date.today()
    corte = _corte_do_get(request.POST.get('corte', ''), hoje)
    try:
        registro = roteiro.concluir(request.user, roteiro.montar(request.user, corte, hoje))
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, gettext("Corte de %(dia)s concluído: %(em_dia)s de %(total)s em dia.") % {
            "dia": corte.strftime("%d/%m"), "em_dia": registro.em_dia, "total": registro.total,
        })
    return redirect(_url_do_painel(corte))


@login_required
@permission_required('banking.reconcile', fallback='fechamento:painel')
@require_POST
def coleta_view(request):
    corte = _corte_do_get(request.POST.get('corte', ''), date.today())
    acao = request.POST.get('acao', 'previa')
    if acao == 'descartar':
        request.session.pop(CHAVE_DA_COLETA, None)
        return redirect(_url_do_painel(corte, ancora="coleta"))
    if acao == 'gravar':
        plano = _plano_da_sessao(request)
        if plano is None:
            messages.error(request, gettext("Envie o pacote de novo: a prévia expirou."))
            return redirect(_url_do_painel(corte, ancora="coleta"))
        try:
            coleta = myprofit.aplicar(request.user, plano, audit_context=audit_request_context(request))
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(_url_do_painel(corte, ancora="coleta"))
        request.session.pop(CHAVE_DA_COLETA, None)
        messages.success(request, ngettext(
            "Coleta até %(dia)s aplicada: %(n)s saldo lançado ou conferido.",
            "Coleta até %(dia)s aplicada: %(n)s saldos lançados ou conferidos.",
            coleta.saldos,
        ) % {"dia": coleta.ate.strftime("%d/%m/%Y"), "n": coleta.saldos})
        return redirect(_url_do_painel(corte, ancora="coleta"))
    arquivo = request.FILES.get('pacote')
    conteudo = arquivo.read(myprofit.LIMITE_DE_BYTES + 1) if arquivo else b""
    try:
        myprofit.ler(conteudo)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(_url_do_painel(corte, ancora="coleta"))
    request.session[CHAVE_DA_COLETA] = conteudo.decode("utf-8-sig")
    return redirect(_url_do_painel(corte, ancora="coleta"))


@login_required
@permission_required('banking.reconcile', fallback='fechamento:painel')
@require_POST
def descartar_duplicata_view(request):
    corte = _corte_do_get(request.POST.get('corte', ''), date.today())
    try:
        duplicatas.descartar(request.user, request.POST.get('par', ''))
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, gettext("Anotado: o par não é duplicata e não volta a aparecer."))
    return redirect(_url_do_painel(corte, "tudo", "conferencias"))
