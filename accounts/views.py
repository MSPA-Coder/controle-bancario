"""Views de Cadastros: Titulares (AccountOwner) e sessão de conta."""
from dataclasses import replace

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext
from django.views.decorators.http import require_POST
from sharedauth.logs import sanitizar_log

from accounts.login_lockout import (
    LoginThrottledError,
    assert_login_not_throttled,
    clear_login_failures,
    failed_login_message,
    register_failed_login_attempt,
)
from accounts.models import AccountOwner
from accounts.services import (
    change_user_password,
    create_owner,
    delete_owner,
    list_owners,
    update_owner,
)
from core.htmx import quer_fragmento
from core.permissions import permission_required
from core.services import (
    audit_action,
    audit_request_context,
    audit_snapshot,
    log_audit_event,
    request_client_ip,
)
from core.volta import resposta_de_cadastro


def _owners_context(user):
    # A tela lista por nome, sem diferenciar maiúsculas (a ordem padrão do modelo é a do banco).
    return {"owners": list_owners(user).order_by(Lower('name'), 'id')}


@login_required
@permission_required('tables.view', fallback='accounts:owners_view')
@permission_required('tables.owners.manage', fallback='accounts:owners_view')
def owners_view(request):
    """Lista e cadastro de titulares, com suporte a HTMX."""
    context = _owners_context(request.user)
    if quer_fragmento(request):
        return render(request, 'tables/_owners_table.html', context)
    return render(request, 'tables/owners.html', context)


@login_required
@permission_required('tables.view', fallback='accounts:owners_view')
@permission_required('tables.owners.manage', fallback='accounts:owners_view')
@require_POST
def create_owner_view(request):
    try:
        owner = create_owner(request.POST.get('name', ''))
        audit_action(request, 'account_owner', owner.id, 'create', new_values=audit_snapshot(owner, 'name'))
        messages.success(request, gettext("Titular cadastrado."))
    except ValueError as exc:
        messages.error(request, str(exc))
        return _respond(request, sucesso=False)
    return _respond(request)


@login_required
@permission_required('tables.view', fallback='accounts:owners_view')
@permission_required('tables.owners.manage', fallback='accounts:owners_view')
@require_POST
def update_owner_view(request, owner_id):
    owner = get_object_or_404(AccountOwner, id=owner_id)
    antes = audit_snapshot(owner, 'name')
    try:
        update_owner(request.user, owner, request.POST.get('name', ''))
        audit_action(
            request, 'account_owner', owner.id, 'update',
            old_values=antes, new_values=audit_snapshot(owner, 'name'),
        )
        messages.success(request, gettext("Titular atualizado."))
    except ValueError as exc:
        messages.error(request, str(exc))
        return _respond(request, sucesso=False)
    return _respond(request)


@login_required
@permission_required('tables.view', fallback='accounts:owners_view')
@permission_required('tables.owners.manage', fallback='accounts:owners_view')
@require_POST
def delete_owner_view(request, owner_id):
    owner = get_object_or_404(AccountOwner, id=owner_id)
    antes = audit_snapshot(owner, 'name')
    try:
        delete_owner(request.user, owner)
        audit_action(request, 'account_owner', owner_id, 'delete', old_values=antes)
        messages.success(request, gettext("Titular excluído."))
    except ValueError as exc:
        messages.error(request, str(exc))
        return _respond(request, sucesso=False)
    return _respond(request)


def _respond(request, *, sucesso=True):
    return resposta_de_cadastro(request, 'accounts:owners_view', sucesso=sucesso)


def _safe_next_url(request, default_url: str) -> str:
    """Aceita apenas redirecionamentos internos para evitar open redirect."""
    candidate = request.POST.get('next') or request.GET.get('next')
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return candidate
    return default_url


def _auditar_login(request, action: str, result: str, username, *, user=None) -> None:
    """Registra tentativa, bloqueio e entrada na trilha de auditoria.

    O nome digitado entra no resumo (sem quebra de linha e truncado): numa
    falha não há usuário autenticado, e é ele que diz de quem foi a tentativa.
    A senha nunca entra.
    """
    nome = sanitizar_log((username or '').strip())[:80]
    resumos = {
        'login': gettext("Entrada no sistema."),
        'failed': gettext("Usuário ou senha inválidos. Usuário informado: %(nome)s.") % {'nome': nome or '-'},
        'throttled': gettext("Bloqueio de login acionado. Usuário informado: %(nome)s.") % {'nome': nome or '-'},
    }
    contexto = audit_request_context(request)
    if user is not None:
        contexto = replace(contexto, user=user)
    log_audit_event(
        'auth_login', user.id if user is not None else None, action,
        request_context=contexto, result=result, summary=resumos[action],
    )


class AppLoginView(LoginView):
    """LoginView padrao com bloqueio de tentativas e desvio para troca obrigatoria de senha."""

    def post(self, request, *args, **kwargs):
        # O IP vem da mesma regra da auditoria: atras do nginx, REMOTE_ADDR e
        # o gateway do Docker, e a trava viraria so por usuario.
        remote_addr = request_client_ip(request)
        try:
            assert_login_not_throttled(request.POST.get('username'), remote_addr)
        except LoginThrottledError as exc:
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data())
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        clear_login_failures(form.get_user().username, request_client_ip(self.request))
        response = super().form_valid(form)
        user = form.get_user()
        _auditar_login(self.request, 'login', 'success', user.get_username(), user=user)
        if getattr(user, 'must_change_password', False):
            next_url = self.get_success_url()
            change_url = reverse('accounts:change_password')
            return redirect(f"{change_url}?next={next_url}")
        return response

    def form_invalid(self, form):
        attempts_remaining, wait_seconds = register_failed_login_attempt(
            self.request.POST.get('username'), request_client_ip(self.request)
        )
        _auditar_login(self.request, 'failed', 'failure', self.request.POST.get('username'))
        if wait_seconds is not None:
            # Uma linha quando o bloqueio é acionado. As requisições recusadas
            # enquanto ele vale não gravam nada: senão quem insiste enche a trilha.
            _auditar_login(self.request, 'throttled', 'failure', self.request.POST.get('username'))
        messages.error(self.request, failed_login_message(attempts_remaining, wait_seconds))
        return super().form_invalid(form)


@login_required
def change_password_view(request):
    """Troca de senha autoatendida (equivalente a owner_session.change_password)."""
    next_url = _safe_next_url(request, settings.LOGIN_REDIRECT_URL)
    if request.method == 'POST':
        try:
            change_user_password(
                request.user,
                request.POST.get('current_password'),
                request.POST.get('new_password'),
                request.POST.get('password_confirm'),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            update_session_auth_hash(request, request.user)
            messages.success(request, gettext("Senha alterada."))
            return redirect(next_url)

    return render(request, 'accounts/change_password.html', {
        'next_url': next_url,
        'forced_change': bool(request.user.must_change_password),
    })
