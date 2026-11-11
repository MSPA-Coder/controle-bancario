"""Retenção da outbox de invalidação do contrato patrimônio v4.

A outbox (`patrimonio_v4_outbox`) recebe uma linha por mutação das tabelas
publicadas, gravada por gatilho na mesma transação. Sem expurgo, ela só cresce.

POR QUE APAGAR NÃO PERDE AVISO. O feed é de invalidação (`snapshot_required`),
não de conteúdo: o consumidor (o agendador do Wealthfolio) pergunta a
`/patrimonio/v4/changes?after=<cursor>&limit=N` se há item depois do seu
checkpoint e, havendo, busca o snapshot inteiro. Basta que essa resposta não
mude. Ela não muda se a linha mais nova continuar existindo: um checkpoint
anterior a ela continua vendo um item, e um posterior continua não vendo nada.
O cursor é a posição no contador, não a contagem de linhas, então buracos entre
os cursores são inofensivos. Por isso o expurgo nunca apaga a linha mais nova.
Aqui não há "dono" a separar (o CRV tem, e guarda a mais nova de cada um): o
feed do CB é um só.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Max

from core.models import PatrimonioV4Outbox

DIAS_DE_RETENCAO = 30


def expurgar_outbox_v4(agora: datetime, dias: int = DIAS_DE_RETENCAO) -> int:
    """Apaga as linhas com mais de `dias` dias, menos a mais nova de todas.

    Devolve quantas linhas saíram. Não abre transação: quem chama delimita.
    """
    if dias < 1:
        raise ValueError("A retenção da outbox precisa ser de pelo menos um dia.")
    mais_nova = PatrimonioV4Outbox.objects.aggregate(Max("cursor"))["cursor__max"]
    if mais_nova is None:
        return 0
    apagadas, _ = PatrimonioV4Outbox.objects.filter(
        changed_at__lt=agora - timedelta(days=dias),
        cursor__lt=mais_nova,
    ).delete()
    return apagadas
