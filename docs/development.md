# Desenvolvimento e validação

## Ambiente local

Use Docker Compose como interface do projeto. No host, o único Python do
projeto é o venv opcional do laço rápido (ver `AGENTS.md`); nada vai para o
Python global, e PostgreSQL roda só em contêiner.

Prepare `.env.docker` e provisione os secrets de Django e PostgreSQL conforme o
[README](../README.md). O script preserva os secrets de runtime existentes e cria
arquivos separados para o perfil `quality`, evitando que testes reutilizem
credenciais operacionais. Para iniciar o modo de desenvolvimento:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.dev.yaml up --build -d
```

O override monta o código do host em `/workspace` e executa `runserver`. Para
validar exatamente a imagem operacional, use apenas `compose.yaml`.

## Comandos reproduzíveis

Verificação da configuração Django:

```powershell
docker compose --env-file .env.docker -f compose.yaml run --rm web python manage.py check
```

Ruff e suíte automatizada:

```powershell
docker compose --env-file .env.docker -f compose.yaml --profile quality run --build --rm quality
```

**`--build` não é opcional.** O serviço `quality` não monta o código do
host: o que ele executa é o que foi copiado para a imagem. `docker compose
run` reconstrói sem cache a partir das tags base atuais antes de executar os
testes. A CI semanal repete build, testes e auditorias para conferir as
atualizações automáticas do sistema e das dependências.

O mesmo vale para os comandos de diagnóstico que usam `run --rm web` sem o
override de desenvolvimento — `manage.py check` e `showmigrations`: eles
inspecionam a imagem, não a árvore de trabalho. `makemigrations` é a
exceção, porque passa `compose.dev.yaml` e portanto enxerga o código do
host.

Inspeção e geração de migrations:

```powershell
docker compose --env-file .env.docker -f compose.yaml run --rm web python manage.py showmigrations
docker compose --env-file .env.docker -f compose.yaml -f compose.dev.yaml run --rm web python manage.py makemigrations
```

Revise toda migration gerada. Uma mudança de schema só está pronta depois de
validar `manage.py migrate` em PostgreSQL vazio e no caminho de atualização
aplicável.

## Textos da interface (idioma)

O português é a língua-fonte: o texto em português é o `msgid`, e o inglês fica em
`locale/en/LC_MESSAGES/django.po`. O `.mo` compilado **não é versionado**: o
`Dockerfile` o gera no build (`msgfmt --check-format`, que reprova o build se um
marcador estiver quebrado).

Depois de marcar um texto novo, extraia e traduza:

```powershell
.\scripts\mensagens.ps1            # atualiza o .po; o texto novo entra com msgstr vazio
.\scripts\mensagens.ps1 -Conferir  # só confere se o .po está em dia (sai com 1 se não estiver)
```

O script roda no contêiner `quality` (que tem o GNU gettext) e só devolve o `.po`.
No Windows PowerShell 5.1 o `docker` escreve progresso em stderr e o PowerShell o
mostra como erro: o que vale é o código de saída. Entrada nova vem vazia, ou
`fuzzy` quando o gettext a achou parecida com outra; **`fuzzy` é chute, nunca fica**
(o Django o ignora): traduza e tire a marca. `tests/test_catalogo_en.py` reprova
texto sem tradução, `fuzzy`, marcador de formatação diferente do original, português
vazando na tradução e catálogo fora de dia com o código.

`tests/test_varredura_de_idioma.py` renderiza as telas principais com usuário em inglês
e dados em ASCII e reprova se sobrar letra acentuada ou palavra de interface em
português. Tela nova entra na lista `TELAS` dele.

## Validação proporcional

- documentação: `git diff --check`, links/caminhos e comandos documentados;
- template, HTMX ou JavaScript: fluxo afetado no navegador;
- regra, view ou service: testes focados e fluxo completo com dados
  representativos;
- autenticação, autorização, sessão ou CSRF: serviço `quality` completo;
- schema ou transformação de dados: backup validado e revisão da migration.
  O bootstrap em PostgreSQL vazio não é mais passo manual: o serviço
  `quality` sobe o `postgres-teste` e o pytest-django aplica a cadeia
  inteira de migrações a um banco vazio para construir o banco de teste;
- dependências, Dockerfile ou Compose: build sem cache quando pertinente,
  `docker compose config`, serviço `quality` e smoke test da pilha.

A CI valida o Compose, executa Ruff e pytest, audita as dependências Python,
varre a imagem operacional e confere a fronteira de escrita do runtime. Isso
não substitui a validação manual do fluxo alterado nem um ensaio de restauração.

## Antes de alterar dados reais

Leia [Operação, dados e backup](operations.md), faça o backup correspondente e
confirme que ele é restaurável. Não use `down -v`, não remova volumes e não
substitua arquivos de mídia sem autorização explícita.

## Reclassificar lançamentos em lote

`reclassificar_lancamentos` move lançamentos que foram registrados na categoria
errada -- aplicação contada como despesa, liquidação de bolsa contada como
gasto, rendimento misturado com aporte. Ele **simula por padrão**:

```bash
docker compose --env-file .env.docker -f compose.yaml run --rm web \
  python manage.py reclassificar_lancamentos --usuario SEU_USUARIO
```

O relatório sai inteiro, lançamento a lançamento, e nada é gravado. Confira o
relatório; só então repita com `--aplicar`.

Três coisas que valem saber antes de rodar com `--aplicar`:

- **ele reabre meses fechados** e os fecha de novo com o mesmo saldo. Nenhum
  valor muda -- o que muda é em que coluna cada lançamento entra;
- **ele não adivinha.** Descrição que nenhuma família de `REGRAS` descreve fica
  onde está e sai listada como pendente. Acrescentar uma família é acrescentar
  uma linha em `REGRAS`, e rodar de novo é seguro: o comando é idempotente;
- **transferência entre moedas precisa do extrato.** Quanto entrou na conta em
  moeda estrangeira não é dedutível do valor em reais, e o sistema não converte
  moeda de propósito. Passe `--valores-em-moeda arquivo.csv`, com uma linha
  `data;valor_origem;valor_destino` por operação.

Faça o backup antes, como em qualquer alteração de dados reais.
