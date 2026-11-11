"""Confere se o banco conectado tem o esquema que os modelos declaram.

Num banco criado pelas migrações a resposta é "nenhuma diferença", e
`tests/test_conferir_esquema.py` prova isso. O banco de produção não nasceu das
migrações: foi criado antes da conversão para Django e adotado depois, com
colunas anuláveis, chaves `integer`, chaves estrangeiras imediatas e nomes de
índice que as migrações não produzem. Essas diferenças foram fechadas pelas
`core/0002` e `core/0004` (`docs/architecture.md`, "O esquema de produção veio
de antes das migrações"). A suíte roda sobre o banco das migrações; este módulo
serve de alarme: em produção deve responder zero diferença, e qualquer uma que
apareça é desvio novo.

O que é conferido: tabelas, colunas (tipo e nulidade), chaves estrangeiras
(existência e se são adiáveis, como o Django as cria), unicidade de campo e os
nomes de `constraints` e `indexes` do `Meta`. O que não é: índices a mais no
banco, valores padrão e o esquema `leitura`, que tem teste próprio.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.db import connection, models

# Tabelas do `public` que não são de modelo nenhum, de propósito.
TABELAS_SEM_MODELO = frozenset({"django_migrations"})


@dataclass(frozen=True, order=True)
class Diferenca:
    tipo: str
    onde: str
    detalhe: str

    def __str__(self) -> str:
        return f"{self.tipo}: {self.onde}: {self.detalhe}"


def _tipo(texto: str) -> str:
    """`varchar(20)` e `character varying(20)` são o mesmo tipo escrito de dois jeitos."""
    return texto.lower().replace("varchar", "character varying").replace(" ", "")


def _catalogo(cursor) -> dict:
    cursor.execute(
        """
        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
          AND a.attnum > 0 AND NOT a.attisdropped
        """
    )
    colunas: dict[str, dict[str, tuple[str, bool]]] = {}
    for tabela, coluna, tipo, nao_nulo in cursor.fetchall():
        colunas.setdefault(tabela, {})[coluna] = (_tipo(tipo), nao_nulo)

    cursor.execute(
        """
        SELECT c.relname, a.attname, alvo.relname, k.condeferrable
        FROM pg_constraint k
        JOIN pg_class c ON c.oid = k.conrelid
        JOIN pg_class alvo ON alvo.oid = k.confrelid
        JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
        WHERE k.contype = 'f' AND k.connamespace = 'public'::regnamespace
          AND cardinality(k.conkey) = 1
        """
    )
    chaves = {(tabela, coluna): (alvo, adiavel) for tabela, coluna, alvo, adiavel in cursor.fetchall()}

    cursor.execute(
        """
        SELECT c.relname, k.conname
        FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
        WHERE k.connamespace = 'public'::regnamespace
        UNION
        SELECT t.relname, i.relname
        FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_class t ON t.oid = x.indrelid
        WHERE t.relnamespace = 'public'::regnamespace
        """
    )
    nomes: dict[str, set[str]] = {}
    for tabela, nome in cursor.fetchall():
        nomes.setdefault(tabela, set()).add(nome)

    cursor.execute(
        """
        SELECT t.relname, array_agg(a.attname ORDER BY a.attname)
        FROM pg_index x
        JOIN pg_class t ON t.oid = x.indrelid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY (x.indkey)
        WHERE t.relnamespace = 'public'::regnamespace
          AND x.indisunique AND x.indpred IS NULL AND x.indexprs IS NULL
        GROUP BY x.indexrelid, t.relname
        """
    )
    unicos: dict[str, set[tuple[str, ...]]] = {}
    for tabela, colunas_do_indice in cursor.fetchall():
        unicos.setdefault(tabela, set()).add(tuple(colunas_do_indice))

    return {"colunas": colunas, "chaves": chaves, "nomes": nomes, "unicos": unicos}


def _modelos() -> list[type[models.Model]]:
    return [
        modelo
        for modelo in apps.get_models(include_auto_created=True)
        if modelo._meta.managed and not modelo._meta.proxy
    ]


def diferencas() -> list[Diferenca]:
    """Lista, em ordem estável, onde o banco conectado se afasta dos modelos."""
    with connection.cursor() as cursor:
        banco = _catalogo(cursor)

    achadas: list[Diferenca] = []
    tabelas_de_modelo: set[str] = set()

    for modelo in _modelos():
        meta = modelo._meta
        tabela = meta.db_table
        tabelas_de_modelo.add(tabela)
        colunas = banco["colunas"].get(tabela)
        if colunas is None:
            achadas.append(Diferenca("tabela ausente", tabela, "o modelo existe, a tabela não"))
            continue

        esperadas: set[str] = set()
        for campo in meta.local_concrete_fields:
            coluna = campo.column
            esperadas.add(coluna)
            onde = f"{tabela}.{coluna}"
            if coluna not in colunas:
                achadas.append(Diferenca("coluna ausente", onde, "o modelo tem, o banco não"))
                continue

            tipo_no_banco, nao_nulo = colunas[coluna]
            tipo_esperado = _tipo(campo.db_type(connection))
            # A chave de tabela de ligação automática (M2M sem `through`) fica de fora:
            # em execução ela segue o `default_auto_field` do app dono, e nas migrações
            # o `DEFAULT_AUTO_FIELD` do projeto. Em `auth_group_permissions` os dois
            # diferem até num banco recém-criado, e nenhum código lê essa coluna.
            chave_automatica = bool(meta.auto_created) and campo.primary_key
            if tipo_no_banco != tipo_esperado and not chave_automatica:
                achadas.append(
                    Diferenca("tipo", onde, f"modelo {tipo_esperado}, banco {tipo_no_banco}")
                )
            if not campo.null and not nao_nulo:
                achadas.append(Diferenca("aceita nulo", onde, "o modelo exige valor, o banco não"))
            if campo.null and nao_nulo:
                achadas.append(Diferenca("recusa nulo", onde, "o modelo aceita nulo, o banco não"))

            if isinstance(campo, models.ForeignKey) and campo.db_constraint:
                chave = banco["chaves"].get((tabela, coluna))
                alvo = campo.remote_field.model._meta.db_table
                if chave is None:
                    achadas.append(Diferenca("chave estrangeira ausente", onde, f"deveria apontar para {alvo}"))
                elif chave[0] != alvo:
                    achadas.append(Diferenca("chave estrangeira", onde, f"modelo {alvo}, banco {chave[0]}"))
                elif not chave[1]:
                    achadas.append(
                        Diferenca("chave estrangeira imediata", onde, "o Django a cria adiável; a do banco não é")
                    )

            if campo.unique and not campo.primary_key and (coluna,) not in banco["unicos"].get(tabela, set()):
                achadas.append(Diferenca("unicidade ausente", onde, "o modelo declara único"))

        for coluna in sorted(set(colunas) - esperadas):
            achadas.append(Diferenca("coluna a mais", f"{tabela}.{coluna}", "o banco tem, o modelo não"))

        nomes = banco["nomes"].get(tabela, set())
        for restricao in meta.constraints:
            if restricao.name not in nomes:
                achadas.append(Diferenca("restrição ausente", f"{tabela}.{restricao.name}", "declarada no Meta"))
        for indice in meta.indexes:
            if indice.name not in nomes:
                achadas.append(Diferenca("índice ausente", f"{tabela}.{indice.name}", "declarado no Meta"))

    for tabela in sorted(set(banco["colunas"]) - tabelas_de_modelo - TABELAS_SEM_MODELO):
        achadas.append(Diferenca("tabela a mais", tabela, "o banco tem, nenhum modelo usa"))

    return sorted(achadas)
