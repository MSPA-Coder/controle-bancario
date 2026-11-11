"""Iguala o banco de produção ao esquema que as migrações montam.

O banco de produção foi criado antes da conversão para Django
(`docs/architecture.md`, "O esquema de produção veio de antes das migrações"). A
`core/0002` fechou nulos e chaves imediatas; esta fecha o resto, medido em
11/11/2026 comparando o catálogo de produção com o de um banco montado pelas
migrações:

- 47 colunas `integer` que os modelos declaram `bigint`, uma `varchar(255)`
  que é `text` e a senha, `varchar(255)` no lugar de `varchar(128)`;
- chaves `serial` no lugar de colunas de identidade, em 26 tabelas;
- nomes de 51 chaves estrangeiras e de dezenas de índices, índices que
  faltavam e índices repetidos;
- checks com outra redação e três unicidades que eram só índice;
- valores padrão em sete colunas de `app_user`;
- as tabelas `alembic_version` e `django_admin_log` e duas colunas
  `updated_at` que nenhum modelo usa.

O alvo é o esquema logo depois da `core/0003`, só nas tabelas do projeto (as
de `auth_*` e `django_*` já eram iguais). Num banco criado pelas migrações ela
não muda nada. Não muda o estado dos modelos. O último bloco do SQL confere o
resultado e, se sobrar diferença, falha e desfaz tudo.

Dado: nada é transformado. Sai a única linha da `alembic_version` (a revisão
do Alembic) e as duas colunas `updated_at`; a `django_admin_log` está vazia.

Toda migração do projeto posterior a esta tem de depender dela, direta ou
indiretamente: num banco novo, uma que rodasse antes deixaria o esquema fora
do alvo e esta falharia. `tests/test_nomes_de_migracao.py` cobra isso.

Voltar atrás não é possível nem necessário: o código funciona nos dois
esquemas, e o antigo não guarda informação que o novo perca.
"""

from pathlib import Path

from django.db import migrations

SQL = Path(__file__).with_suffix('.sql').read_text(encoding='utf-8')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_trilha_de_auditoria_so_de_insercao'),
    ]

    operations = [
        migrations.RunSQL(SQL, migrations.RunSQL.noop),
    ]
