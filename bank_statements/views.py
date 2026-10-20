"""Views de importação, conciliação e anexos bancários (Bancos)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext, ngettext
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from accounts.services import has_function_permission
from banking.services import accessible_account_ids
from core.account_group_filter import account_group_q
from core.currency_filter import currency_q
from core.htmx import quer_fragmento
from core.permissions import permission_required
from core.services import audit_request_context
from core.templatetags.money_filters import balance_signed
from transactions.models import AccountMonthClose

from . import (
    extrato,
    fatura,
    fatura_projetada,
    painel_de_extratos,
    pending_imports,
    reclassificacao,
    reconciliation,
    saldo,
    situacao,
)
from .attachments import (
    attachment_download_path,
    attachment_for_download,
    delete_entry_attachment,
    recent_attachments_for_user,
    save_entry_attachment,
)
from .models import BankStatementLine
from .services import (
    accounts_for_import_form,
    statement_import_status,
    statement_imports_for_user,
)


def _import_table_context(request):
    return {
        "imports": statement_imports_for_user(request.user),
        "pode_desfazer_importacao": has_function_permission(request.user, 'banking.reconcile'),
    }


@login_required
@permission_required('banking.view')
@permission_required('banking.import', fallback='dashboard:dashboard')
def imports_view(request):
    """Lista de importações recentes e formulário de novo envio."""
    context = {
        **_import_table_context(request),
        "import_accounts": accounts_for_import_form(request.user),
    }
    return render(request, 'banking/imports.html', context)


@login_required
@permission_required('banking.import', fallback='bank_statements:imports_view')
@require_POST
def stage_imports_view(request):
    """Recebe um ou mais arquivos de extrato e tenta detectar a conta de cada um.

    Nada vira `BankStatementLine` aqui - só depois que o usuário confirmar (ou
    corrigir) a conta de cada arquivo em `confirm_imports_view`.
    """
    files = request.FILES.getlist('statement_files')
    if not files:
        messages.warning(request, gettext("Selecione ao menos um arquivo para importar."))
        if quer_fragmento(request):
            return render(request, 'banking/_import_table.html', _import_table_context(request))
        return redirect('bank_statements:imports_view')

    pending_imports.stage_uploaded_files(request.user, files)
    destino = reverse('bank_statements:confirm_imports')
    if quer_fragmento(request):
        resposta = HttpResponse(status=204)
        resposta['HX-Redirect'] = destino
        return resposta
    return redirect(destino)


@login_required
@permission_required('banking.view')
@permission_required('banking.import', fallback='bank_statements:imports_view')
def confirm_imports_view(request):
    """Prévia dos arquivos enviados: confirma ou corrige a conta de cada um antes de gravar."""
    uploads = list(pending_imports.pending_uploads_for_user(request.user))
    if not uploads:
        messages.info(request, gettext("Nenhuma importação pendente de confirmação."))
        return redirect('bank_statements:imports_view')
    context = {
        "uploads": uploads,
        "import_accounts": accounts_for_import_form(request.user),
    }
    return render(request, 'banking/pending_imports_confirm.html', context)


@sensitive_post_parameters('senha')
@login_required
@permission_required('banking.import', fallback='bank_statements:imports_view')
@require_POST
def unlock_pending_view(request, pending_id):
    """Abre com a senha o PDF protegido de uma importação pendente e detecta a conta.

    A senha vale só para esta requisição (ver `pdf_senha`) e fica fora dos
    relatórios de erro do Django."""
    try:
        upload = pending_imports.desbloquear(request.user, pending_id, request.POST.get('senha', ''))
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, gettext("%(nome)s: PDF aberto.") % {"nome": upload.original_filename})
    destino = reverse('bank_statements:confirm_imports')
    if quer_fragmento(request):
        resposta = HttpResponse(status=204)
        resposta['HX-Redirect'] = destino
        return resposta
    return redirect(destino)


@login_required
@permission_required('banking.import', fallback='bank_statements:imports_view')
@require_POST
def process_imports_view(request):
    """Importa, de uma vez, cada arquivo pendente com a conta que o usuário confirmou."""
    uploads = pending_imports.pending_uploads_for_user(request.user)
    choices = {upload.id: request.POST.get(f'account_{upload.id}', '') for upload in uploads}
    resultados, erros, lotes = pending_imports.resolve_pending_uploads(request.user, choices)

    for nome, inserted, skipped in resultados:
        messages.success(request, gettext(
            "%(nome)s: linhas novas %(novas)s, duplicadas ignoradas %(duplicadas)s."
        ) % {"nome": nome, "novas": inserted, "duplicadas": skipped})
    for nome, erro in erros:
        messages.error(request, gettext("%(nome)s: %(erro)s") % {"nome": nome, "erro": erro})
    if not resultados and not erros:
        messages.warning(request, gettext("Nenhum arquivo foi confirmado para importação."))

    # A fatura não para nas linhas: segue para a prévia do processamento. Mais
    # de um cartão no mesmo lote não tem como abrir duas prévias de uma vez -
    # vai para a primeira e nomeia as demais, em vez de escolher uma delas.
    faturas = [lote for lote in lotes if lote.account.is_credit_card]
    if faturas:
        if len(faturas) > 1:
            outras = ", ".join(lote.source_filename for lote in faturas[1:])
            messages.info(request, ngettext(
                "Outra fatura aguardando processamento: %(outras)s.",
                "Outras faturas aguardando processamento: %(outras)s.",
                len(faturas) - 1,
            ) % {"outras": outras})
        destino = reverse('bank_statements:fatura', args=[faturas[0].id])
        if quer_fragmento(request):
            resposta = HttpResponse(status=204)
            resposta['HX-Redirect'] = destino
            return resposta
        return redirect(destino)

    if quer_fragmento(request):
        return render(request, 'banking/_import_table.html', _import_table_context(request))
    return redirect('bank_statements:imports_view')


@login_required
@permission_required('banking.import', fallback='bank_statements:imports_view')
@permission_required('banking.reconcile', fallback='bank_statements:imports_view')
@require_POST
def undo_import_view(request, batch_id):
    """Desfaz um lote de importação inteiro (lançamento, não fatura de cartão)."""
    try:
        line_count, reconciled_count = reconciliation.undo_statement_import(request.user, batch_id=batch_id)
        linhas = ngettext(
            "Importação desfeita: %(n)s linha de extrato removida",
            "Importação desfeita: %(n)s linhas de extrato removidas",
            line_count,
        ) % {"n": line_count}
        if reconciled_count:
            conciliacoes = ngettext(
                "%(n)s conciliação revertida",
                "%(n)s conciliações revertidas",
                reconciled_count,
            ) % {"n": reconciled_count}
            texto = gettext(
                "%(linhas)s, %(conciliacoes)s — os lançamentos "
                "voltaram a ficar em aberto, conforme o vencimento, sem serem apagados."
            ) % {"linhas": linhas, "conciliacoes": conciliacoes}
        else:
            texto = gettext("%(linhas)s.") % {"linhas": linhas}
        messages.success(request, texto)
    except ValueError as exc:
        messages.error(request, str(exc))

    if quer_fragmento(request):
        return render(request, 'banking/_import_table.html', _import_table_context(request))
    return redirect('bank_statements:imports_view')


@login_required
@permission_required('banking.view')
def import_status_view(request, batch_id):
    """Status resumido de um lote de importação, em JSON."""
    status = statement_import_status(request.user, batch_id)
    if status is None:
        return JsonResponse({"error": gettext("Lote não encontrado.")}, status=404)
    return JsonResponse(status)


@login_required
@permission_required('banking.view')
@permission_required('banking.import', fallback='bank_statements:imports_view')
def fatura_view(request, batch_id):
    """Prévia da fatura importada: o que cada linha vai virar."""
    try:
        lote = fatura.lote_de_fatura(request.user, batch_id)
    except ValueError as exc:
        messages.warning(request, str(exc))
        return redirect('bank_statements:imports_view')
    novas = list(fatura.linhas_novas(lote))
    planos = fatura.planejar(lote.account, novas)
    context = {
        "lote": lote,
        "conta": lote.account,
        "planos": planos,
        "previa": fatura.organizar(planos),
        "tudo_no_saldo_inicial": bool(planos) and all(p.acao == fatura.SALDO_INICIAL for p in planos),
        "resumo": fatura.resumir(lote.lines.all()),
        "processadas": lote.lines.exclude(status="novo").count(),
        "categorias": list(fatura.categorias_gerenciais()),
        "projetadas": fatura_projetada.planejar(lote.account),
        "meses_fechados": fatura.meses_fechados(lote.account, planos),
    }
    return render(request, 'banking/fatura.html', context)


@login_required
@permission_required('banking.view')
def faturas_view(request):
    """Faturas e projeção: cada cartão com saldo, faturas importadas e projeção."""
    return render(request, 'banking/faturas.html', {"paineis": fatura_projetada.paineis(request.user)})


@login_required
@permission_required('banking.view')
def extratos_view(request):
    """Extratos importados: cada conta (fora cartão) com saldo e extratos importados."""
    return render(request, 'banking/extratos.html', {"paineis": painel_de_extratos.paineis(request.user)})


@login_required
@permission_required('banking.view')
def extrato_view(request, batch_id):
    """Um extrato importado: as linhas do lote e o status de cada uma."""
    try:
        importado = painel_de_extratos.extrato_do_lote(request.user, batch_id)
    except ValueError as exc:
        messages.warning(request, str(exc))
        return redirect('bank_statements:extratos')
    lote = importado.lote
    return render(request, 'banking/extrato.html', {
        "importado": importado,
        "lote": lote,
        "conta": lote.account,
        "linhas": painel_de_extratos.linhas_do_extrato(lote),
        "limite": painel_de_extratos.LIMITE_DE_LINHAS,
    })


def _mes_do_get(valor) -> date | None:
    try:
        ano, mes = str(valor).split('-')
        return date(int(ano), int(mes), 1)
    except ValueError:
        return None


def _destino_da_celula(conta, celula) -> str:
    """Onde resolver a célula: importar o que falta, conciliar o pendente, ver o que já está feito."""
    if conta.movement_account_id and celula.saldo_pendente:
        return reverse('bank_statements:atualizar_saldo')
    if celula.estado == situacao.SEM_IMPORTACAO:
        return reverse('bank_statements:imports_view')
    if celula.estado == situacao.SALDO_INFORMADO and not celula.lote_id:
        return reverse('bank_statements:atualizar_saldo')
    if celula.estado == situacao.COM_PENDENCIAS and not conta.is_credit_card:
        return reverse('bank_statements:reconciliation_view')  # linha de cartão só se resolve na fatura
    if celula.lote_id:
        return reverse('bank_statements:fatura' if conta.is_credit_card else 'bank_statements:extrato', args=[celula.lote_id])
    return ""


@login_required
@permission_required('banking.view')
def situacao_das_contas_view(request):
    """Situação das Contas: conta × mês, importado e conciliado."""
    try:
        quantos = int(request.GET.get('meses', situacao.MESES_PADRAO))
    except ValueError:
        quantos = situacao.MESES_PADRAO
    matriz = situacao.montar(request.user, quantos=quantos, referencia=_mes_do_get(request.GET.get('ref')))
    for linha in matriz.linhas:
        for celula in linha.celulas:
            celula.url = _destino_da_celula(linha.conta, celula)
    return render(request, 'banking/situacao_das_contas.html', {
        "matriz": matriz,
        "quantos": len(matriz.meses),
        "opcoes_de_meses": situacao.MESES_PERMITIDOS,
        "legenda": [(e, *situacao.ROTULOS[e]) for e in situacao.ESTADOS_EM_ORDEM],
    })


@login_required
@permission_required('banking.import', fallback='bank_statements:imports_view')
@permission_required('banking.reconcile', fallback='bank_statements:imports_view')
@require_POST
def processar_fatura_view(request, batch_id):
    """Grava a prévia: lança, concilia e ignora, tudo ou nada."""
    escolhas = fatura.escolhas_do_formulario(request.POST)
    try:
        conta = fatura.lote_de_fatura(request.user, batch_id).account
        antes = {(f.year, f.month): f.closing_balance for f in AccountMonthClose.objects.filter(account=conta, active=True)}
        contagem = fatura.processar(
            request.user, batch_id, escolhas, audit_context=audit_request_context(request),
            autorizar_meses=request.POST.get('autorizar_meses') == '1',
        )
        for f in AccountMonthClose.objects.filter(account=conta, active=True).order_by("year", "month"):
            anterior = antes.get((f.year, f.month))
            if anterior is not None and anterior != f.closing_balance:
                messages.info(request, gettext(
                    "%(mes)02d/%(ano)s reaberto e fechado de novo: saldo de %(antes)s para %(depois)s."
                ) % {"mes": f.month, "ano": f.year, "antes": balance_signed(anterior, conta.currency),
                     "depois": balance_signed(f.closing_balance, conta.currency)})
        pendentes = contagem.get(fatura.PAGAMENTO_SEM_PAR, 0)
        feitas = sum(contagem.values()) - pendentes
        texto = ngettext(
            "Fatura processada: %(n)s linha.",
            "Fatura processada: %(n)s linhas.",
            feitas,
        ) % {"n": feitas}
        if pendentes:
            texto += " " + ngettext(
                "%(n)s pagamento sem transferência ficou em Conciliação.",
                "%(n)s pagamentos sem transferência ficaram em Conciliação.",
                pendentes,
            ) % {"n": pendentes}
        messages.success(request, texto)
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('bank_statements:fatura', batch_id=batch_id)


def _escolhas_da_reclassificacao(post) -> dict:
    return {
        "entry_ids": post.getlist('entry_ids'),
        "categoria_id": post.get('categoria'),
        "incluir_iguais": post.get('iguais') == '1',
        "parecidas_ids": post.getlist('parecidas'),
        "bancos": post.getlist('bancos'),
    }


@login_required
@permission_required('banking.view')
@permission_required('banking.reclassify', fallback='dashboard:dashboard')
@require_http_methods(["GET", "POST"])
def reclassificacao_view(request):
    """Lista para reclassificar em lote; POST monta a prévia ou aplica."""
    voltar = request.POST.get('voltar', '') if request.method == 'POST' else request.GET.urlencode()
    plano = None
    escolhas = {}
    if request.method == 'POST':
        escolhas = _escolhas_da_reclassificacao(request.POST)
        try:
            if request.POST.get('acao') == 'aplicar':
                alterados = reclassificacao.aplicar(
                    request.user,
                    autorizar_meses=request.POST.get('autorizar_meses') == '1',
                    audit_context=audit_request_context(request),
                    **escolhas,
                )
                messages.success(request, ngettext(
                    "%(n)s lançamento reclassificado.",
                    "%(n)s lançamentos reclassificados.",
                    alterados,
                ) % {"n": alterados})
                destino = reverse('bank_statements:reclassificacao')
                return redirect(f"{destino}?{voltar}" if voltar else destino)
            plano = reclassificacao.planejar(request.user, **escolhas)
        except ValueError as exc:
            messages.error(request, str(exc))

    filtros = reclassificacao.Filtros.do_get(QueryDict(voltar))
    context = {
        "filtros": filtros,
        "voltar": voltar,
        "lancamentos": reclassificacao.lancamentos(request.user, filtros),
        "limite": reclassificacao.LIMITE_DA_LISTA,
        "categorias": list(fatura.categorias_gerenciais()),
        "categorias_do_banco": reclassificacao.categorias_do_banco(),
        "contas": accounts_for_import_form(request.user).filter(
            account_group_q(filtros.grupos) & currency_q(filtros.moeda)
        ),
        "plano": plano,
        "escolhas": escolhas,
        "pode_reabrir": has_function_permission(request.user, 'settings.monthly_close.manage'),
    }
    return render(request, 'banking/reclassificacao.html', context)


@login_required
@permission_required('banking.view')
@permission_required('banking.reconcile', fallback='dashboard:dashboard')
@require_http_methods(["GET", "POST"])
def atualizar_saldo_view(request):
    """Informa o saldo real de uma conta e lança a diferença com destino explícito."""
    previa = None
    dados = request.POST if request.method == 'POST' else request.GET
    data_informada = dados.get('data', '')
    try:
        data = date.fromisoformat(data_informada) if data_informada else date.today()
    except ValueError:
        data = date.today()
        messages.error(request, gettext("Data inválida."))
    if request.method == 'POST':
        try:
            if request.POST.get('acao') == 'aplicar':
                lancamento = saldo.aplicar(
                    request.user,
                    account_id=request.POST.get('conta'),
                    data=data,
                    saldo_informado=request.POST.get('saldo'),
                    diferenca_esperada=request.POST.get('diferenca'),
                    destino=request.POST.get('destino'),
                    motivo=request.POST.get('motivo', ''),
                    audit_context=audit_request_context(request),
                )
                messages.success(request, gettext("Diferença lançada: %(descricao)s (%(valor)s).") % {
                    "descricao": lancamento.description,
                    "valor": lancamento.entry_amount,
                })
                return redirect('bank_statements:atualizar_saldo')
            previa = saldo.previa(
                request.user, account_id=request.POST.get('conta'), data=data,
                saldo_informado=request.POST.get('saldo'),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
    contas = [
        conta for conta in accounts_for_import_form(request.user)
        if not conta.is_credit_card
    ]
    return render(request, 'banking/atualizar_saldo.html', {
        "contas": contas,
        "data": data,
        "previa": previa,
        "escolhas": request.POST if request.method == 'POST' else {},
        "assuncoes": saldo.assuncoes(request.user),
        "atualizacoes": saldo.atualizacoes(request.user),
        "categoria_de_ajuste": saldo.CATEGORIA_DE_AJUSTE,
        "destinos": saldo.DESTINOS,
    })


def _reconciliation_context(request, *, target_line_id=None):
    return reconciliation.reconciliation_view_data(request.user, target_line_id)


@login_required
@permission_required('banking.view')
@permission_required('banking.reconcile', fallback='dashboard:dashboard')
def reconciliation_view(request):
    """Linhas pendentes de conciliação e conciliações recentes."""
    target_line_id = request.GET.get('line_id')
    context = _reconciliation_context(request, target_line_id=target_line_id)
    return render(request, 'banking/reconciliation.html', context)


@login_required
@permission_required('banking.view')
def reconciliation_refresh_view(request):
    """Atualização HTMX das tabelas de conciliação.

    Exige apenas banking.view: é uma releitura, não uma conciliação. As ações
    que alteram estado continuam exigindo banking.reconcile."""
    target_line_id = request.GET.get('line_id')
    context = _reconciliation_context(request, target_line_id=target_line_id)
    return render(request, 'banking/_reconciliation_tables.html', context)


@login_required
@permission_required('banking.reconcile', fallback='bank_statements:reconciliation_view')
@require_POST
def reconcile_view(request):
    """Concilia uma linha de extrato com um lançamento."""
    line_id = request.POST.get('line_id')
    try:
        # Escolher o movimento e clicar em Conciliar é a autorização para corrigir
        # a realização pela linha do extrato, mesmo em mês fechado (com o saldo
        # de fechamento conferido; ver `_conciliar_corrigindo_realizacao`).
        linha = reconciliation.reconcile_line_with_entry(
            request.user,
            line_id=line_id,
            entry_id=request.POST.get('entry_id'),
            audit_context=audit_request_context(request),
            autorizar_meses=True,
        )
        correcao = getattr(linha, "correcao", "")
        if correcao:
            messages.success(request, gettext(
                "Linha conciliada; realização corrigida pelo extrato (%(correcao)s)."
            ) % {"correcao": correcao})
        else:
            messages.success(request, gettext("Linha conciliada e lançamento marcado como realizado."))
    except ValueError as exc:
        messages.error(request, str(exc))

    if quer_fragmento(request):
        return render(request, 'banking/_reconciliation_tables.html', _reconciliation_context(request))
    return redirect('bank_statements:reconciliation_view')


@login_required
@permission_required('banking.reconcile', fallback='bank_statements:reconciliation_view')
@require_POST
def create_entry_from_line_view(request):
    """Cria um lançamento novo a partir de uma linha de extrato sem candidato."""
    line_id = request.POST.get('line_id')
    try:
        reconciliation.create_entry_from_line(
            request.user,
            line_id=line_id,
            category_id=request.POST.get('category_id'),
            audit_context=audit_request_context(request),
        )
        messages.success(request, gettext("Lançamento criado e conciliado com a linha do extrato."))
    except ValueError as exc:
        messages.error(request, str(exc))

    if quer_fragmento(request):
        return render(request, 'banking/_reconciliation_tables.html', _reconciliation_context(request))
    return redirect('bank_statements:reconciliation_view')


@login_required
@permission_required('banking.reconcile', fallback='bank_statements:reconciliation_view')
@require_POST
def transfer_from_line_view(request):
    """Lança uma linha de extrato como transferência para (ou de) outra conta sua."""
    try:
        reconciliation.transfer_from_line(
            request.user,
            line_id=request.POST.get('line_id'),
            other_account_id=request.POST.get('other_account_id'),
            other_amount=_valor_opcional(request.POST.get('other_amount')),
            audit_context=audit_request_context(request),
        )
        messages.success(request, gettext("Transferência lançada e conciliada com a linha do extrato."))
    except ValueError as exc:
        messages.error(request, str(exc))

    if quer_fragmento(request):
        return render(request, 'banking/_reconciliation_tables.html', _reconciliation_context(request))
    return redirect('bank_statements:reconciliation_view')


def _valor_opcional(texto):
    """Valor digitado num campo opcional: vazio é `None`; o resto precisa ser número finito."""
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        valor = Decimal(texto.replace(",", "."))
    except InvalidOperation:
        valor = None
    if valor is None or not valor.is_finite():
        raise ValueError(gettext("Valor monetário inválido: %(valor)s.") % {"valor": texto})
    return valor


def _categorias_escolhidas(post) -> dict[int, int]:
    """O seletor de categoria de cada linha (`categoria_<id da linha>`), quando preenchido."""
    escolhidas = {}
    for chave, valor in post.items():
        if chave.startswith('categoria_') and chave[len('categoria_'):].isdigit() and valor.isdigit():
            escolhidas[int(chave[len('categoria_'):])] = int(valor)
    return escolhidas


@login_required
@permission_required('banking.reconcile', fallback='bank_statements:reconciliation_view')
@require_POST
def bulk_action_lines_view(request):
    """Concilia, cria lançamentos ou ignora várias linhas de extrato selecionadas de uma vez.

    O "Criar" de uma linha também chega aqui (`criar:<id da linha>`): o seletor
    de categoria de cada linha pertence a este formulário, para que o lote use o
    que foi escolhido nele."""
    action = request.POST.get('bulk_action') or ''
    line_ids = request.POST.getlist('line_ids')
    categorias = _categorias_escolhidas(request.POST)
    if action.startswith('criar:'):
        line_id = action[len('criar:'):]
        try:
            reconciliation.create_entry_from_line(
                request.user,
                line_id=line_id,
                category_id=categorias.get(int(line_id)) if line_id.isdigit() else None,
                audit_context=audit_request_context(request),
            )
            messages.success(request, gettext("Lançamento criado e conciliado com a linha do extrato."))
        except ValueError as exc:
            messages.error(request, str(exc))
    elif not line_ids:
        messages.warning(request, gettext("Selecione ao menos uma linha do extrato."))
    elif action == 'reconcile':
        reconciled, errors = reconciliation.bulk_reconcile_lines(
            request.user,
            line_ids=line_ids,
            audit_context=audit_request_context(request),
        )
        if reconciled:
            messages.success(request, ngettext(
                "%(n)s linha conciliada.",
                "%(n)s linhas conciliadas.",
                reconciled,
            ) % {"n": reconciled})
        if errors:
            messages.error(request, ngettext(
                "%(n)s linha não pôde ser conciliada: %(erro)s",
                "%(n)s linhas não puderam ser conciliadas: %(erro)s",
                len(errors),
            ) % {"n": len(errors), "erro": errors[0][1]})
    elif action == 'apply_plan':
        linhas = list(
            BankStatementLine.objects.filter(
                id__in=[valor for valor in line_ids if str(valor).isdigit()],
                account_id__in=accessible_account_ids(request.user, "update"),
            ).select_related("account__owner", "account__institution")
        )
        feitas, errors = extrato.aplicar(
            request.user, linhas, audit_context=audit_request_context(request), categorias=categorias
        )
        if feitas:
            detalhe = ", ".join(
                extrato.ROTULOS_CURTOS[acao](quantidade) for acao, quantidade in feitas.items()
            )
            messages.success(request, gettext("Sugestões aplicadas: %(detalhe)s.") % {"detalhe": detalhe})
        if errors:
            messages.warning(request, ngettext(
                "%(n)s linha espera decisão sua. Primeira: %(chave)s — %(erro)s",
                "%(n)s linhas esperam decisão sua. Primeira: %(chave)s — %(erro)s",
                len(errors),
            ) % {"n": len(errors), "chave": errors[0][0], "erro": errors[0][1]})
    elif action == 'create':
        created, errors = reconciliation.bulk_create_entries_from_lines(
            request.user,
            line_ids=line_ids,
            audit_context=audit_request_context(request),
            categorias=categorias,
        )
        if created:
            messages.success(request, ngettext(
                "%(n)s lançamento criado e conciliado.",
                "%(n)s lançamentos criados e conciliados.",
                created,
            ) % {"n": created})
        if errors:
            messages.error(request, ngettext(
                "%(n)s linha não pôde ser processada: %(erro)s",
                "%(n)s linhas não puderam ser processadas: %(erro)s",
                len(errors),
            ) % {"n": len(errors), "erro": errors[0][1]})
    elif action == 'ignore':
        ignored, errors = reconciliation.bulk_ignore_lines(request.user, line_ids=line_ids)
        if ignored:
            messages.success(request, ngettext(
                "%(n)s linha ignorada.",
                "%(n)s linhas ignoradas.",
                ignored,
            ) % {"n": ignored})
        if errors:
            messages.error(request, ngettext(
                "%(n)s linha não pôde ser ignorada: %(erro)s",
                "%(n)s linhas não puderam ser ignoradas: %(erro)s",
                len(errors),
            ) % {"n": len(errors), "erro": errors[0][1]})
    else:
        messages.warning(request, gettext("Ação em lote inválida."))

    if quer_fragmento(request):
        return render(request, 'banking/_reconciliation_tables.html', _reconciliation_context(request))
    return redirect('bank_statements:reconciliation_view')


@login_required
@permission_required('banking.reconcile', fallback='bank_statements:reconciliation_view')
@require_POST
def undo_reconciliation_view(request):
    """Desfaz a conciliação de uma linha."""
    line_id = request.POST.get('line_id')
    try:
        reconciliation.undo_reconciliation(request.user, line_id=line_id)
        messages.success(
            request,
            gettext(
                "Conciliação desfeita. A linha voltou a pendente e o lançamento "
                "voltou a ficar em aberto, conforme o vencimento."
            ),
        )
    except ValueError as exc:
        messages.error(request, str(exc))

    if quer_fragmento(request):
        return render(request, 'banking/_reconciliation_tables.html', _reconciliation_context(request))
    return redirect('bank_statements:reconciliation_view')


def _attachments_context(request, *, target_attachment_id=None):
    return {
        "recent_attachments": recent_attachments_for_user(request.user, target_attachment_id),
        "target_attachment_id": target_attachment_id,
    }


@login_required
@permission_required('banking.view')
@permission_required('banking.attachments.manage', fallback='dashboard:dashboard')
def attachments_view(request):
    """Lista de comprovantes recentes e formulário de anexação."""
    target_attachment_id = request.GET.get('attachment_id')
    target_attachment_id = int(target_attachment_id) if target_attachment_id and target_attachment_id.isdigit() else None
    context = _attachments_context(request, target_attachment_id=target_attachment_id)
    return render(request, 'banking/attachments.html', context)


@login_required
@permission_required('banking.attachments.manage', fallback='bank_statements:attachments_view')
@require_POST
def create_attachment_view(request):
    """Anexa um comprovante a um lançamento existente."""
    try:
        attachment = save_entry_attachment(
            request.user,
            request.POST.get('entry_id'),
            request.FILES.get('attachment_file'),
        )
        messages.success(request, gettext("Anexo salvo: %(nome)s.") % {"nome": attachment.original_filename})
    except ValueError as exc:
        messages.error(request, str(exc))

    if quer_fragmento(request):
        return render(request, 'banking/_attachments_table.html', _attachments_context(request))
    return redirect('bank_statements:attachments_view')


@login_required
@permission_required('banking.attachments.manage', fallback='bank_statements:attachments_view')
def attachment_download_view(request, attachment_id):
    """Baixa o arquivo de um comprovante."""
    attachment = attachment_for_download(request.user, attachment_id)
    if attachment is None:
        messages.warning(request, gettext("Anexo não encontrado."))
        return redirect('bank_statements:attachments_view')
    try:
        path = attachment_download_path(attachment)
    except ValueError as exc:
        messages.warning(request, str(exc))
        return redirect('bank_statements:attachments_view')
    return FileResponse(
        path.open('rb'),
        as_attachment=True,
        filename=attachment.original_filename,
        content_type=attachment.mime_type or 'application/octet-stream',
    )


@login_required
@permission_required('banking.attachments.manage', fallback='bank_statements:attachments_view')
@require_POST
def delete_attachment_view(request, attachment_id):
    """Exclui o metadado e o arquivo físico de um comprovante autorizado."""
    try:
        delete_entry_attachment(request.user, attachment_id=attachment_id)
        messages.success(request, gettext("Comprovante excluído."))
    except ValueError as exc:
        messages.error(request, str(exc))

    if quer_fragmento(request):
        return render(request, 'banking/_attachments_table.html', _attachments_context(request))
    return redirect('bank_statements:attachments_view')


@login_required
@permission_required('banking.reconcile', fallback='bank_statements:reconciliation_view')
@require_POST
def ignore_line_view(request):
    """Marca uma linha nova como ignorada."""
    line_id = request.POST.get('line_id')
    try:
        reconciliation.ignore_statement_line(request.user, line_id=line_id)
        messages.success(request, gettext("Linha do extrato marcada como ignorada."))
    except ValueError as exc:
        messages.error(request, str(exc))

    if quer_fragmento(request):
        return render(request, 'banking/_reconciliation_tables.html', _reconciliation_context(request))
    return redirect('bank_statements:reconciliation_view')
