"""Ativa o formato regional do usuário durante a requisição."""

from __future__ import annotations

from core import regional


class FormatoRegionalMiddleware:
    """Lê `request.user.regional_format` e o deixa disponível a filtros e helpers.

    Vem depois do `AuthenticationMiddleware`. Quem não está logado (tela de
    login) segue o idioma do navegador, que o `IdiomaMiddleware` deixa ativo. O token é devolvido no `finally` para o valor
    não vazar para a requisição seguinte da mesma thread. Resposta em streaming
    seria gerada depois disso, já no padrão: se algum export passar a usar
    `StreamingHttpResponse` com data ou número, formate antes de devolver.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        formato = getattr(user, "regional_format", None) if user is not None and user.is_authenticated else None
        token = regional.ativar(formato)
        try:
            return self.get_response(request)
        finally:
            regional.desativar(token)
