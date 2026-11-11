# Controle Bancário — guia de trabalho

<!-- comum: início. Cópia de _manutencao/compartilhados/AGENTS-comum.md; mude lá e rode sincronizar.py --aplicar. -->
## Regras comuns aos repositórios

**O que espera o "sim" do mantenedor:** deploy ou publicação, qualquer ação no
VPS, e apagar dados, volumes ou backups (`docker compose down -v` inclusive).
Commit e push não esperam. Na dúvida sobre algo irreversível, pergunte; no
resto, decida e diga o que decidiu.

**Ciclo.** Altere, rode a verificação completa deste repositório (seção
"Validação"), commite direto no `main` quando o bloco de trabalho estiver
pronto e dê `git push`: sem PR, sem push forçado, sem rebase do `main`
publicado. A CI roda depois, só como aviso, mas vermelho no `main` se
investiga. O Dependabot chega por PR, com merge manual. Ao terminar, diga o que
rodou, o resultado e o que deixou de validar.

**Dados e segredos.** Os bancos desta máquina são de teste: não provam nada
sobre valores reais e não pedem backup. Segredos ficam fora do Git (`.secrets/`
ou configuração do usuário) e não aparecem em código, imagem, log, diff,
documento nem relatório.

**Dependências.** Alargue o teto e preserve o piso já verificado: elevar o piso
afirma uma incompatibilidade, e isso exige prova. Vulnerabilidade se corrige
atualizando; exceção só explícita, com motivo e data. O Dependabot propõe
atualização do `uv.lock` por PR (PRs de 08 e 09/11/2026), mas não se confirmou
que o grafo de dependências do GitHub acompanha o lock (última conferência:
parado no lock de 13/10/2026): não conte só com o alerta do GitHub, confira
pela versão travada no repositório e atualize à mão
(`uv lock --upgrade-package <pacote>`, onde há `uv.lock`) quando o `pip-audit`
ou o Trivy apontarem.

**Testes.** `docs/TESTES.md`, onde existe, diz o que testar e como. Diante de
vermelho, decida de quem é o defeito; nunca escreva código para um teste
passar. Não rode duas verificações do mesmo repositório ao mesmo tempo: a
segunda recria o ambiente de teste e derruba a primeira.

**Cópias.** Este bloco, `docs/TESTES.md` e os arquivos listados em
`_manutencao/compartilhados/sincronizar.py` são cópias: mude a canônica lá e
rode `python compartilhados/sincronizar.py --aplicar` no `_manutencao`.

**Este arquivo.** Guarde aqui só o que o código não diz: limites, decisões com
o motivo, armadilhas e comandos. Cada regra mora num lugar só: o que este bloco
ou `docs/` já dizem não se repete. História fica no `git log`; decisão com
alternativas vira ADR, que abre com a linha `Estado:` (vigente, ou substituído
por qual); detalhe de implementação fica no código. Para acrescentar uma
regra, retire ou funda
outra: `sincronizar.py` reprova este arquivo acima de 900 palavras fora deste
bloco.

**Deploy (o que roda no VPS).** Só com o "sim", a cada vez. `~/deploy.sh <app>`
no VPS1 leva o checkout ao `main`, monta a imagem no servidor, confere
`/health` e volta sozinho se falhar; a volta não desfaz migração nem dado. O
VPS só espelha o `main`: nada se edita lá. Imagem-base nova (correção do Debian
ou do Python) só quando ele pedir: testa na máquina e depois
`~/deploy.sh <app> --refresh`.

**Dados de produção.** Mudança destrutiva, migração que transforma dado ou
conversão começa por um dump novo, feito com `~/backup-db.sh --forcar` no VPS e
conferido no catálogo do BackupRestore. Dump feito à mão não tem `.sha256` e
reprova a sincronização.
<!-- comum: fim -->

## O sistema

Controle bancário em Django 6.1, HTMX e PostgreSQL 17, no ar em
`https://bancario-mspa.duckdns.org` (deploy `~/deploy.sh bancario`). Docker
Compose é a interface: não instale ferramentas no host para contornar uma
falha; o `.venv` local é só de runtime.

Faz parte da frota com o MegaSena e o ControleRendaVariavel, que são Flask: a
semelhança buscada é de operação e contrato, não de framework. Divergir é
permitido quando for escolha consciente. O ConfortoTermico segue trilha
própria, e diferença em relação a ele não é débito.

Leia só o documento do assunto da mudança:

- `docs/domain.md`: invariantes financeiras; leia antes de mexer em saldo,
  recorrência, transferência, fechamento, importação ou conciliação;
- `docs/architecture.md`: componentes, esquema `leitura`, idioma e formato;
- `docs/development.md`: comandos e imagens-base;
- `docs/operations.md`: configuração, volumes, backup e VPS;
- `docs/CONCEITOS_FINANCEIROS.md`: vocabulário comum com o CRV e o Wealthfolio;
- `docs/travas.md`: locks de banco e o que cada um protege;
- `docs/decisoes-evolucao.md`: por que a projeção mensal roda no middleware, com
  as medidas e a condição de revisão; leia antes de mexer nesse gatilho;
- `docs/annual-planning-report.md`: contrato de contexto do relatório anual.

O projeto subiu para o Django 6.1 em 08/09/2026: ao depender de comportamento
do framework, confira as notas da série 6 em vez de assumir a 5.2.

## Validação

```powershell
.\scripts\quality.ps1
```

Ruff e pytest, em paralelo, contra o `postgres-teste` efêmero, que recebe a
cadeia inteira de migrações num banco vazio. Use sempre o script, também para
rodar parte da suíte (passe os argumentos a ele): ele serializa por mutex
antes de o Compose recriar o banco. Com outro comando, a suíte roda em série,
salvo se incluir `-n`. Durante o trabalho, teste focado à vontade; antes de
todo commit de código, o script completo.

- Mudança visível (template, HTMX, JS): suba a pilha e percorra a tela.
- Texto de interface: nasce marcado, com o português como `msgid` (como marcar
  está em `docs/architecture.md`, "Idioma e formato regional"; termos e tom em
  `docs/GLOSSARIO_I18N.md`). Rode `.\scripts\mensagens.ps1`, traduza e confira
  com `-Conferir`. Mudar a redação em português muda o `msgid`. Dado gravado,
  nome digitado e texto de máquina não se traduzem.
- Só documentação: `git diff --check` e
  `python ../_manutencao/compartilhados/sincronizar.py`.
- Docker ou dependência: `docker compose config --quiet`, suba a pilha e
  confira `/health`.
- Schema ou transformação de dados: revise a migration à mão; em produção, o
  dump do bloco comum vem antes.
- A camada `django_db` não se desmarca: foi ela que mostrou que
  `@transaction.atomic` nunca tinha sido exercitado.

## Invariantes do domínio

- Valores financeiros em `Decimal`. Lançamento guarda valor positivo e o tipo
  define o efeito no saldo. Status: `a_vencer`, `vencidos` e `realizado`.
- A moeda pertence à conta, e conta com lançamento não muda de moeda; o que não
  tem conta está em `BRL`. Converter moeda não é assunto deste sistema: somar
  moedas diferentes levanta `MixedCurrencyError`, e as telas mostram um bloco
  de totais por moeda (`banking.services.currency_blocks`).
- Transferência interna mantém as duas pontas consistentes e não é receita nem
  despesa gerencial. Só se espelha na mesma moeda; entre moedas, cada ponta
  guarda o seu valor, sem parcelamento nem recorrência, e a taxa efetiva é
  derivada, nunca gravada.
- Fechamento mensal bloqueia mutações e conciliações do período; reabrir é
  explícito e auditável.
- Operação composta é atômica, com a transação delimitada no service; data e
  hora persistidas têm fuso.
- A projeção recorrente roda pelo middleware, em requisição autenticada, uma
  vez por mês a partir do dia configurado, e é idempotente. Worker ou fila pode
  substituir esse gatilho se preservar idempotência, auditoria, retry seguro e
  coordenação entre processos.
- Fluxo `urls -> views -> services -> models`; consulta vive no service (ou na
  view, se trivial). Repository ou query object só quando simplificar de
  verdade (consulta reutilizada, cache, fronteira de teste), com o motivo em
  `docs/architecture.md`.
- Colunas lidas pelo esquema `leitura` (FinancasMCP, Wealthfolio) não são
  removidas nem mudam de tipo sem recriar a view na mesma migração: o
  PostgreSQL recusa, de propósito.

## Segurança

- Autorização é de servidor, por titular e permissão; escrita usa CSRF; CSP
  sem código inline.
- O piso de senha é o do SharedAuth (`sharedauth.passwords.MIN_PASSWORD_LENGTH`,
  10), lido por `accounts/password_validators.py` e `core/services.py`. Vale só
  para senha nova ou trocada; o login não revalida o tamanho, e o valor gravado
  em `app_setting` abaixo do piso vale o piso.
- Senha criada ou redefinida pelo administrador liga `must_change_password`, e
  o middleware de `accounts/middleware.py` desvia toda requisição para
  `/change-password/` até a troca. O tamanho da senha sorteada vem de
  Configurações > Parâmetros.
- O SharedAuth entra sem o extra `[flask]`, de propósito: só o núcleo
  (`secrets`, `security`, `formatting`, `passwords`, `logs`, `ui`), sem
  middleware nem autenticação; `secrets` e `ui` quebram o boot, então subir a
  tag se valida abrindo uma tela. Vem do GitHub, na tag do `pyproject.toml` e
  no commit do `uv.lock`.

## Armadilhas

- O dump de produção do bloco comum não cobre `media_volume` (comprovantes):
  se a operação puder afetá-los, preserve a mídia à parte
  (`docs/operations.md`). Restauração é administrativa, com a aplicação parada
  e o destino conferido.
- `web` é o único serviço de aplicação (não há `app`); `migrate` aplica as
  migrações e o `collectstatic` antes dele.
- O PostgreSQL fica na série 17 para preservar o formato dos volumes.
- A varredura da imagem roda como contêiner, com `docker save` e `--input`:
  não monte o socket Docker nem troque por action de terceiro, que a política
  do repositório barra.
