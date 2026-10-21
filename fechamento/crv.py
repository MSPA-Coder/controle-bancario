"""O que o Controle de Renda Variável diz do próprio fechamento.

O CRV publica `GET /fechamento/status?ate=AAAA-MM-DD` (contrato
`crv-fechamento/1`): itens já avaliados por ele -- negócios do myProfit
aplicados, Avenue, conferência por pregão, conciliação de papéis, proventos --,
cada um com etapa, estado e texto. O roteiro só os mostra junto dos do CB; quem
sabe se um negócio foi aplicado é o CRV.

A chamada vai pela rede interna do VPS (`CRV_FECHAMENTO_URL`), com o token do
vínculo CB <-> CRV: o `PATRIMONIO_INTEGRATION_TOKEN` daqui, que o CRV conhece
como `cb_patrimonio_token`. Falha ou ausência de configuração não derrubam a
tela: viram um item "CRV indisponível", com o motivo, e o resto do roteiro segue.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date

from django.utils.translation import gettext

from core.patrimonio import _token_configurado

CONTRATO = "crv-fechamento/1"
TIMEOUT_SEGUNDOS = 4
ESTADOS_ACEITOS = {"em_dia", "falta", "pendente", "espera", "fora", "depois", "sem_fonte"}
ETAPAS_ACEITAS = {"myprofit", "conferencias"}

logger = logging.getLogger(__name__)


@dataclass
class StatusDoCrv:
    itens: list[dict] = field(default_factory=list)
    erro: str = ""


def url_publica(caminho: str) -> str:
    """Link para a tela do CRV, quando o endereço público está configurado."""
    base = os.environ.get("CRV_PUBLIC_URL", "").rstrip("/")
    if not base or not caminho:
        return ""
    if caminho.startswith(("http://", "https://")):
        return caminho
    return f"{base}/{caminho.lstrip('/')}"


def _item_valido(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    if item.get("estado") not in ESTADOS_ACEITOS or item.get("etapa") not in ETAPAS_ACEITAS:
        return None
    if not isinstance(item.get("titulo"), str) or not isinstance(item.get("texto"), str):
        return None
    limpo = {chave: item.get(chave) for chave in ("chave", "etapa", "titulo", "subtitulo", "estado", "texto", "detalhe", "acao", "coberto_ate", "url")}
    limpo["url"] = url_publica(str(limpo.get("url") or ""))
    for chave in ("subtitulo", "detalhe", "acao", "coberto_ate", "chave"):
        limpo[chave] = str(limpo.get(chave) or "")
    passos = item.get("passos")
    limpo["passos"] = [str(passo) for passo in passos[:6]] if isinstance(passos, list) else []
    return limpo


def status(ate: date) -> StatusDoCrv:
    url = os.environ.get("CRV_FECHAMENTO_URL", "").strip()
    if not url:
        return StatusDoCrv(erro=gettext("CRV não configurado neste ambiente."))
    token = _token_configurado()
    if not token:
        return StatusDoCrv(erro=gettext("Falta o token do vínculo com o CRV."))
    pedido = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode({'ate': ate.isoformat()})}",
        # O CRV de produção força HTTPS atrás do Nginx; pela rede interna a
        # chamada é HTTP, então ela se declara como vinda do proxy TLS (o mesmo
        # recurso do healthcheck daqui).
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "X-Forwarded-Proto": "https"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEGUNDOS) as resposta:  # noqa: S310 - URL de configuração
            corpo = json.loads(resposta.read(512 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("CRV respondeu HTTP %s ao status de fechamento", exc.code)
        return StatusDoCrv(erro=gettext("O CRV recusou a consulta (HTTP %(codigo)s).") % {"codigo": exc.code})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("CRV indisponível para o status de fechamento: %s", type(exc).__name__)
        return StatusDoCrv(erro=gettext("O CRV não respondeu."))
    if not isinstance(corpo, dict) or corpo.get("contrato") != CONTRATO or not isinstance(corpo.get("itens"), list):
        return StatusDoCrv(erro=gettext("O CRV respondeu num formato que este CB não conhece."))
    return StatusDoCrv(itens=[item for item in map(_item_valido, corpo["itens"]) if item is not None])
