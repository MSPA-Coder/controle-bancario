"""Aproxima o banco de produção do esquema que os modelos declaram.

O banco de produção foi criado antes da conversão para Django
(`docs/architecture.md`, "O esquema de produção veio de antes das migrações"). Esta
migração fecha duas das diferenças medidas em 10/11/2026 pelo
`manage.py conferir_esquema`:

- 52 colunas que os modelos exigem preenchidas e o banco deixava nulas;
- 25 chaves estrangeiras imediatas, que o Django cria adiáveis.

Num banco criado pelas migrações ela não muda nada: as colunas já são
`NOT NULL` e não há chave imediata. Não muda o estado dos modelos.

Dado: só `created_at` e `updated_at` tinham nulo (30 linhas em produção, de
cadastros anteriores à conversão). A data verdadeira não existe em lugar
nenhum; cada um recebe a do outro e, na falta dos dois, a mais antiga conhecida
da tabela. Nas outras colunas não havia nulo. Se houver, o `SET NOT NULL`
falha, a migração inteira é desfeita e o deploy volta: é o comportamento
desejado, porque inventar status ou tipo de lançamento seria pior.

Ficam de fora, por decisão ainda em aberto: chaves `integer` no lugar de
`bigint`, nomes de índice e de restrição, e as tabelas e colunas que sobraram.

Voltar atrás não exige nada: afrouxar de novo as colunas e as chaves não
devolve informação nenhuma, e o código não depende do estado antigo.
"""

from django.db import migrations

# Tabela -> colunas que os modelos exigem preenchidas (saída do `conferir_esquema`).
COLUNAS = {
    'account_month_close': ['created_at', 'reopen_reason', 'updated_at'],
    'account_owner': ['created_at', 'updated_at'],
    'app_permission': ['created_at'],
    'app_setting': ['created_at', 'updated_at'],
    'app_user': ['created_at', 'updated_at', 'username'],
    'bank_operation': ['created_at', 'description', 'updated_at'],
    'bank_statement_import': ['created_at', 'updated_at'],
    'bank_statement_line': ['created_at', 'updated_at'],
    'cash_flow_category': ['created_at', 'updated_at'],
    'cash_flow_entry': [
        'created_at', 'current_installment', 'description', 'installments',
        'is_recurring', 'operation_type', 'status', 'updated_at',
    ],
    'cash_flow_entry_project': ['created_at', 'updated_at'],
    'cash_flow_entry_tag': ['created_at', 'updated_at'],
    'entry_attachment': ['created_at', 'updated_at'],
    'financial_account': ['created_at', 'is_default', 'updated_at'],
    'financial_institution': ['created_at', 'institution_type', 'updated_at'],
    'login_lockout': ['created_at', 'updated_at'],
    'management_project': ['created_at', 'description', 'updated_at'],
    'management_tag': ['created_at', 'updated_at'],
    'monthly_budget': ['created_at', 'updated_at'],
    'user_owner_access': ['created_at'],
    'user_permission': ['created_at', 'updated_at'],
}


def _preencher(tabela: str, colunas: list[str]) -> list[str]:
    comandos = []
    if 'created_at' in colunas:
        outra = 'updated_at, ' if 'updated_at' in colunas else ''
        comandos.append(
            f'UPDATE {tabela} SET created_at = COALESCE({outra}'
            f'(SELECT min(created_at) FROM {tabela}), now()) WHERE created_at IS NULL;'
        )
    if 'updated_at' in colunas:
        comandos.append(
            f'UPDATE {tabela} SET updated_at = COALESCE(created_at, now()) WHERE updated_at IS NULL;'
        )
    return comandos


def _exigir(tabela: str, colunas: list[str]) -> str:
    alteracoes = ', '.join(f'ALTER COLUMN {coluna} SET NOT NULL' for coluna in colunas)
    return f'ALTER TABLE {tabela} {alteracoes};'


SQL = '\n'.join(
    [
        # Com a aplicação antiga ainda no ar, esperar um lock sem limite pararia o
        # deploy em silêncio; cinco segundos e a migração falha por inteiro.
        "SET LOCAL lock_timeout = '5s';",
        *[comando for tabela, colunas in COLUNAS.items() for comando in _preencher(tabela, colunas)],
        # O PostgreSQL recusa ALTER TABLE com evento de gatilho adiado pendente.
        'SET CONSTRAINTS ALL IMMEDIATE;',
        *[_exigir(tabela, colunas) for tabela, colunas in COLUNAS.items()],
        """
DO $$
DECLARE chave record;
BEGIN
    FOR chave IN
        SELECT conrelid::regclass AS tabela, conname
        FROM pg_constraint
        WHERE contype = 'f' AND connamespace = 'public'::regnamespace AND NOT condeferrable
    LOOP
        EXECUTE format(
            'ALTER TABLE %s ALTER CONSTRAINT %I DEFERRABLE INITIALLY DEFERRED',
            chave.tabela, chave.conname
        );
    END LOOP;
END $$;
""".strip(),
    ]
)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(SQL, migrations.RunSQL.noop),
    ]
