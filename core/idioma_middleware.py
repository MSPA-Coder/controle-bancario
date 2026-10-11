"""Ativa o idioma da interface durante a requisição."""

from __future__ import annotations

from django.utils import translation
from django.utils.cache import patch_vary_headers

from core.domain.settings import normalize_language


class IdiomaMiddleware:
    """Idioma do usuário logado; para quem não está logado, o do navegador.

    Vem depois do `AuthenticationMiddleware` e antes do `FormatoRegionalMiddleware`,
    que resolve a região `auto` pelo idioma que este deixa ativo. O idioma volta ao
    que era quando a requisição termina (`override`), então nada vaza para a
    requisição seguinte da mesma thread.

    A tela de login não tem usuário: segue o `Accept-Language`, limitado aos
    idiomas de `settings.LANGUAGES`, e cai no padrão (`LANGUAGE_CODE`) se o
    navegador pedir outro.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        logado = user is not None and user.is_authenticated
        if logado:
            idioma = normalize_language(getattr(user, "language", None))
        else:
            idioma = translation.get_language_from_request(request, check_path=False)
        request.LANGUAGE_CODE = idioma
        with translation.override(idioma):
            resposta = self.get_response(request)
        if not logado:
            # A mesma URL responde em idiomas diferentes conforme o navegador.
            patch_vary_headers(resposta, ("Accept-Language",))
        resposta.headers.setdefault("Content-Language", idioma)
        return resposta
