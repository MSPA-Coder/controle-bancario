"""Aplica a coleta do myProfit no CB: saldos de Tesouro, renda fixa EUA e caixa
em dólar, e a conferência das remessas de câmbio.

    python manage.py importar_coleta_myprofit /tmp/coleta.json --usuario NOME
    python manage.py importar_coleta_myprofit /tmp/coleta.json --usuario NOME --gravar

Sem `--gravar` é o ensaio: mostra o que cada conta recebe e não grava nada. É o
mesmo caminho da tela (Roteiro de fechamento > Coleta do myProfit); ver
`fechamento.myprofit`.
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import AppUser
from fechamento import myprofit


class Command(BaseCommand):
    help = "Aplica (ou ensaia) a coleta do myProfit: saldos e remessas."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--usuario", required=True)
        parser.add_argument("--gravar", action="store_true", help="Grava; sem isto só mostra o plano.")

    def handle(self, *args, arquivo, usuario, gravar, **options):
        try:
            user = AppUser.objects.get(username=usuario)
        except AppUser.DoesNotExist as exc:
            raise CommandError(f"Usuário \"{usuario}\" não existe.") from exc
        caminho = Path(arquivo)
        if not caminho.is_file():
            raise CommandError(f"Arquivo não encontrado: {arquivo}")
        try:
            plano = myprofit.planejar(user, myprofit.ler(caminho.read_bytes()[: myprofit.LIMITE_DE_BYTES + 1]))
        except myprofit.PacoteInvalidoError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Pacote de {plano.pacote.de:%d/%m/%Y} a {plano.pacote.ate:%d/%m/%Y}"
                          + (" (já aplicado)" if plano.ja_aplicada else ""))
        for linha in plano.linhas:
            if linha.acao == "lancar":
                o_que = f"lança {linha.diferenca} ({linha.destino})" + (f", {linha.rendimento} de proventos" if linha.rendimento else "")
            elif linha.acao == "conferir":
                o_que = "já bate"
            else:
                o_que = f"pula: {linha.motivo}"
            self.stdout.write(f"  {linha.titulo:40} {linha.data:%d/%m/%Y}  myProfit {linha.valor:>14}  CB {linha.saldo_no_cb:>14}  {o_que}")
        self.stdout.write(f"Remessas que conferem: {plano.remessas_conferidas}")
        for pendencia in plano.pendencias:
            self.stdout.write(f"  pendência: {pendencia}")
        if not gravar:
            self.stdout.write("Ensaio: nada foi gravado. Use --gravar para aplicar.")
            return
        coleta = myprofit.aplicar(user, plano)
        self.stdout.write(self.style.SUCCESS(f"Coleta até {coleta.ate:%d/%m/%Y} aplicada: {coleta.saldos} saldos."))
