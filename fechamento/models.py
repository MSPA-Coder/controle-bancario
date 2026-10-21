"""Roteiro de fechamento: de onde vem o dado de cada conta e o que já foi conferido.

O roteiro (`fechamento.roteiro`) lê o resto do sistema -- extratos, faturas,
saldos informados -- e só guarda aqui o que não existe em outro lugar:

- **a fonte de cada conta** (`FonteDaConta`): arquivo do banco, fatura, print de
  saldo, myProfit ou "ainda não tenho", com o formato e a frequência esperados.
  Conta sem registro tem a fonte deduzida (`fechamento.fontes.deduzir`);
- **o saldo conferido** (`SaldoConferido`): um por conta e data. Informar de novo o
  mesmo dia não lança outra diferença, porque o CB já inclui a primeira; o registro
  só passa a guardar o valor mais recente;
- **o corte** (`CorteDeFechamento`): uma conferência até uma data, sem trava. A
  trava continua sendo o fechamento mensal (`transactions.AccountMonthClose`);
- **a coleta do myProfit** (`ColetaMyProfit`): o pacote que já foi aplicado,
  reconhecido pelo sha256, para reimportar sem lançar de novo;
- **o par de linhas que não é duplicata** (`DuplicataDescartada`).
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

FONTE_ARQUIVO = 'arquivo'
FONTE_FATURA = 'fatura'
FONTE_PRINT = 'print'
FONTE_MYPROFIT = 'myprofit'
FONTE_NENHUMA = 'nenhuma'
FONTES = [
    (FONTE_ARQUIVO, gettext_lazy('Extrato em arquivo')),
    (FONTE_FATURA, gettext_lazy('Fatura do cartão')),
    (FONTE_PRINT, gettext_lazy('Print de saldo')),
    (FONTE_MYPROFIT, gettext_lazy('myProfit')),
    (FONTE_NENHUMA, gettext_lazy('Ainda não tenho')),
]

FREQUENCIA_CORTE = 'corte'
FREQUENCIA_MENSAL = 'mensal'
FREQUENCIAS = [
    (FREQUENCIA_CORTE, gettext_lazy('A cada corte')),
    (FREQUENCIA_MENSAL, gettext_lazy('Só no fim do mês')),
]

# O que a conta representa no myProfit. O nome da corretora no myProfit
# (`corretora_myprofit`) separa a mesma classe em duas contas: o Tesouro da XP e
# o da Genial.
CLASSE_TESOURO = 'tesouro'
CLASSE_RENDA_FIXA_EUA = 'renda_fixa_eua'
CLASSE_CAIXA_USD = 'caixa_usd'
CLASSES_MYPROFIT = [
    (CLASSE_TESOURO, gettext_lazy('Tesouro Direto')),
    (CLASSE_RENDA_FIXA_EUA, gettext_lazy('Renda fixa EUA')),
    (CLASSE_CAIXA_USD, gettext_lazy('Caixa em dólar')),
]

ORIGEM_PRINT = 'print'
ORIGEM_MYPROFIT = 'myprofit'
ORIGEM_MANUAL = 'manual'
ORIGENS_DO_SALDO = [
    (ORIGEM_PRINT, gettext_lazy('Print')),
    (ORIGEM_MYPROFIT, gettext_lazy('myProfit')),
    (ORIGEM_MANUAL, gettext_lazy('Digitado')),
]


class FonteDaConta(models.Model):
    account = models.OneToOneField('banking.FinancialAccount', on_delete=models.CASCADE, related_name='fonte')
    fonte = models.CharField(max_length=20, choices=FONTES)
    formato = models.CharField(max_length=40, blank=True, default='')
    frequencia = models.CharField(max_length=10, choices=FREQUENCIAS, default=FREQUENCIA_CORTE)
    classe_myprofit = models.CharField(max_length=20, choices=CLASSES_MYPROFIT, blank=True, default='')
    corretora_myprofit = models.CharField(max_length=40, blank=True, default='')
    onde = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Onde o arquivo ou o saldo é obtido, para o roteiro mostrar.',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'fechamento_fonte'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fonte__in=[valor for valor, _ in FONTES]),
                name='ck_fechamento_fonte_valida',
            ),
            models.CheckConstraint(
                condition=models.Q(frequencia__in=[valor for valor, _ in FREQUENCIAS]),
                name='ck_fechamento_frequencia_valida',
            ),
            models.CheckConstraint(
                condition=models.Q(classe_myprofit='') | models.Q(fonte=FONTE_MYPROFIT),
                name='ck_fechamento_classe_so_no_myprofit',
            ),
        ]

    def __str__(self):
        return f'{self.account_id}: {self.fonte}'


class SaldoConferido(models.Model):
    account = models.ForeignKey('banking.FinancialAccount', on_delete=models.CASCADE, related_name='saldos_conferidos')
    data = models.DateField()
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    origem = models.CharField(max_length=10, choices=ORIGENS_DO_SALDO)
    lancamento = models.ForeignKey(
        'transactions.CashFlowEntry', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text='O lançamento da diferença, quando houve diferença.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'fechamento_saldo_conferido'
        ordering = ['-data', '-id']
        constraints = [
            models.UniqueConstraint(fields=['account', 'data'], name='uq_fechamento_saldo_conta_data'),
            models.CheckConstraint(
                condition=models.Q(origem__in=[valor for valor, _ in ORIGENS_DO_SALDO]),
                name='ck_fechamento_saldo_origem_valida',
            ),
        ]


class CorteDeFechamento(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cortes_de_fechamento')
    data = models.DateField()
    concluido_em = models.DateTimeField(auto_now_add=True)
    em_dia = models.PositiveIntegerField()
    total = models.PositiveIntegerField()

    class Meta:
        db_table = 'fechamento_corte'
        ordering = ['-data']
        constraints = [
            models.UniqueConstraint(fields=['user', 'data'], name='uq_fechamento_corte_usuario_data'),
        ]


class ColetaMyProfit(models.Model):
    sha256 = models.CharField(max_length=64, unique=True)
    ate = models.DateField()
    importada_em = models.DateTimeField(auto_now_add=True)
    importada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    saldos = models.PositiveIntegerField(default=0)
    remessas = models.PositiveIntegerField(default=0)
    # O que a coleta encontrou e o CB não resolve sozinho: posição sem conta no CB,
    # remessa de câmbio que não bate. Lista de textos já prontos para a tela.
    pendencias = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'fechamento_coleta_myprofit'
        ordering = ['-ate', '-id']


class DuplicataDescartada(models.Model):
    """Duas linhas que pareciam a mesma transação e não são. O par é guardado na
    ordem dos ids, para valer nos dois sentidos."""

    linha_a = models.ForeignKey('bank_statements.BankStatementLine', on_delete=models.CASCADE, related_name='+')
    linha_b = models.ForeignKey('bank_statements.BankStatementLine', on_delete=models.CASCADE, related_name='+')
    descartada_em = models.DateTimeField(auto_now_add=True)
    descartada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'fechamento_duplicata_descartada'
        constraints = [
            models.UniqueConstraint(fields=['linha_a', 'linha_b'], name='uq_fechamento_duplicata_par'),
            models.CheckConstraint(condition=models.Q(linha_a__lt=models.F('linha_b')), name='ck_fechamento_duplicata_ordem'),
        ]
