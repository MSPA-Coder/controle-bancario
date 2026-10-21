# Regras de domínio

## Moeda

A moeda pertence à **conta** (`financial_account.currency`), nunca ao
lançamento: todo lançamento é de uma conta e herda a moeda dela. Repetir a
moeda no lançamento criaria duas verdades para o mesmo valor, e um dia elas
divergiriam sem que nenhum relatório soubesse qual vale. Uma instituição que
guarde duas moedas vira duas contas, como o extrato dela mesma apresenta.

- as siglas válidas são `BRL` e `USD`, garantidas pela `CheckConstraint`
  `ck_financial_account_currency_valid`;
- **conta com lançamento não muda de moeda**: a troca não converteria nada, só
  faria os valores já gravados passarem a valer outra coisa. `update_account`
  recusa, e a tela de Contas trava o seletor nesse caso;
- `initial_balance` vem acompanhado de `initial_balance_date`, a data a que ele
  se refere. Sem data, saldo inicial em moeda estrangeira não teria como ser
  convertido nem posicionado numa série histórica. As contas existentes foram
  datadas em 31/12/2025, o corte a partir do qual há lançamentos;
- o que não tem conta está na **moeda base** (`BRL`): é o caso do orçamento
  mensal, que é por categoria e mês;
- **converter moeda não acontece aqui.** Este sistema registra o fato: a compra
  de moeda estrangeira é uma transferência entre duas contas suas, e a taxa
  efetiva é a divisão de uma ponta pela outra. Cotação e conversão para uma
  moeda de exibição pertencem a quem consolida.

## Agregação por moeda

Somar valores de contas de moedas diferentes é erro, não arredondamento — um
total que mistura real com dólar sai formatado e alinhado, e ninguém desconfia
dele até conferir à mão.

A resposta certa não é recusar a seleção: é **um bloco de totais por moeda**.
Sem conversão, "quanto eu tenho" tem uma resposta por moeda, e é isso que as
telas mostram. O número único convertido pertence a quem consolida.

- `banking.services.account_ids_by_currency` reparte a seleção por moeda
  (moeda base primeiro), e `currency_blocks` garante pelo menos um bloco — uma
  seleção sem conta nenhuma continua escrevendo `R$ 0,00`;
- **com uma moeda só, nada muda na tela**: um bloco, sem cabeçalho, idêntico ao
  que a tela sempre foi. O cabeçalho da moeda só aparece a partir do segundo
  bloco;
- os agregados **não** mudaram: continuam exigindo um conjunto de contas de uma
  moeda só. Quem mudou foi o chamador — a tela pede um total por moeda, uma
  chamada por bloco;
- `banking.services.currency_of_accounts` continua sendo a porta única dessa
  exigência: devolve a moeda comum e levanta
  `core.domain.finance.MixedCurrencyError` quando o conjunto atravessa moedas.
  Conjunto vazio vale a moeda base. Ela hoje não dispara em nenhuma tela, e é
  essa a intenção: é a rede para o próximo agregado escrito sem a regra;
- os agregados guardados por ela: `decimal_base_balance`, os totais assinados de
  lançamentos (por período e por mês) e a grade de planejamento anual;
- na tela, `core.htmx.recusa_moedas_misturadas` transforma o erro em aviso
  (HTTP 400 com o gatilho `app:moedas-misturadas`), nunca em 500;
- **o painel é a exceção**: ele é feito de gráficos, e duas moedas não cabem no
  mesmo eixo. Ele mostra uma moeda por vez, a do filtro global. Moeda pedida que
  não existe na seleção não vence: escolher a conta em dólar traz a moeda junto.
  Com "Todas" e mais de uma moeda no escopo, ele mostra a moeda base e avisa —
  nunca soma as duas;
- linha por conta não é agregação: relatórios detalhados continuam listando
  contas de moedas diferentes lado a lado, cada uma com o seu símbolo. O que não
  existe é o TOTAL delas — esse é um por moeda;
- uma transferência entre moedas aparece **nos dois blocos**, uma ponta em cada:
  é o mesmo dinheiro visto de cada lado, e não há total que junte os dois;
- o orçamento mensal compara apenas o realizado em moeda base, porque
  `MonthlyBudget.planned_amount` também é em moeda base.

## Lançamentos e saldos

- Valores monetários usam `Decimal`.
- `entry_amount` e `realized_amount`, quando informado, são positivos; o tipo
  `receita` ou `despesa` determina o sinal no saldo.
- Lançamento `realizado` tem data e valor de realização. A data é obrigatória
  porque o saldo realizado é filtrado por ela: sem data, o lançamento sumia de
  todos os saldos sem aviso (o #1236, achado em 17/09/2026). Valor realizado
  vazio grava o previsto do próprio lançamento, como o botão "Realizar" já
  fazia; decidido assim porque o vazio era lido como o previsto pelo saldo e
  como zero pelo planejamento anual. O serviço recusa a data vazia, e o banco
  tem o piso `ck_cash_flow_entry_realized_has_date_and_amount`. Lançamento em
  aberto não guarda realização: o serviço limpa a data e o valor.
- Os status de lançamentos e operações são `a_vencer`, `vencidos` e
  `realizado`.
- O saldo inicial cadastrado na conta integra a base dos cálculos.
- A visão `realizado` considera movimentos realizados. A visão `vencidos`
  combina realizados e abertos vencidos. A visão `a_vencer` combina realizados
  e movimentos projetados futuros.
- Transferências internas afetam as contas envolvidas, mas categorias internas
  são excluídas das receitas e despesas gerenciais.

`BankOperation` agrupa lançamentos relacionados. Parcelas, recorrências e as
duas pontas de transferências preservam o agrupamento durante criação, edição,
realização, exclusão e conciliação. Operações compostas são atômicas: uma falha
reverte o conjunto.

Uma transferência interna tem exatamente uma origem e uma contraparte por
ocorrência. Além do service, o PostgreSQL confere isso no commit por um gatilho
de restrição postergado: a gravação transitória da origem antes do destino é
permitida dentro da transação, mas nenhum par incompleto ou cruzado entre
operações é persistido.

A orientação do par é fixa: a **despesa é a origem** (sem `source_entry`) e a
receita aponta para ela; a despesa diz "Conta Destino: …" e a receita, "Conta
Origem: …". Vale ao criar, ao converter um lançamento simples e ao editar,
inclusive pela ponta que recebe (`transactions.services._orientar_par`). O
formulário descreve a ponta aberta para edição: a conta e o valor dele são dessa
ponta, e o "valor creditado no destino" é o da outra. Até 20/10/2026 editar pela
ponta que recebe aplicava a conta do formulário à origem, e as duas linhas
trocavam de conta.

Realizar é um fato de uma ocorrência, não do grupo. Criar um parcelado ou um
recorrente como realizado realiza só a primeira ocorrência, com a data
informada; as demais seguem o vencimento, como a projeção mensal já fazia. Na
edição em grupo ("todos" ou "este e os próximos"), status, data e valor
realizados do formulário valem só para a linha editada e a outra ponta dela;
as outras ocorrências mantêm a realização que têm, e as em aberto só
acompanham o vencimento. Decidido assim em 17/09/2026 porque o status pedido
era aplicado ao grupo inteiro: meses futuros nasciam realizados na mesma data,
o saldo realizado daquele dia perdia o valor uma vez por ocorrência, e editar o
grupo a partir de uma linha em aberto apagava a realização das já pagas. A
`BankOperation` resume o status das ocorrências também na criação.

### Vencimento na edição em grupo

O formulário de edição envia os campos da **linha editada**, e o escopo diz
até onde eles valem. Para os demais campos, "todos os registros do grupo"
significa repetir o valor; para o vencimento, não — cada ocorrência tem o mês
dela, e repetir a data gravaria todas no mesmo dia.

O que o grupo acompanha é a **diferença** entre o vencimento novo e o antigo da
linha editada: tantos meses, e o novo dia quando o dia muda. Ela se aplica à
data **de cada ocorrência**, não à posição dela na série. Disso decorre o que
uma edição de grupo nunca faz:

- editar sem tocar no vencimento não move vencimento nenhum;
- uma ocorrência adiantada ou adiada a mão — fim de semana, feriado —
  continua onde foi posta, e só acompanha o deslocamento;
- um mês removido no meio da série continua ausente; a ocorrência seguinte não
  ocupa o lugar dele.

Vale igualmente para "este registro e os próximos", que renumera o bloco
apagando e recriando as linhas: os ids mudam, os vencimentos são os antigos
deslocados. Um dia que o calendário já aparou (31 em fevereiro vira 28) viaja
aparado: o sistema desloca a data que existe, não uma intenção de "todo dia 31"
que ele não guarda.

Transferências internas exigem concessão explícita do usuário para a conta de
destino. Recorrências internas guardam um responsável; a projeção global só as
estende enquanto a concessão continuar válida. Legados sem responsável ficam
pausados até atribuição administrativa auditada.

### Transferência entre moedas

As duas pontas de uma transferência são espelhadas — o mesmo valor em cada uma —
enquanto as contas estão na mesma moeda. Quando não estão, o espelho seria o
defeito: gravar o valor em reais também na conta em dólar é escrever um número
que nunca existiu no extrato dela.

- o valor creditado no destino é **obrigatório** quando as moedas diferem e
  **recusado** quando são iguais — `transactions.services.counterparty_amount_for_transfer`
  é o único lugar que decide isso, e vale na criação, na edição e na conversão
  de um lançamento simples em transferência;
- **não há parcelamento nem recorrência** entre moedas diferentes: cada compra
  de moeda tem a taxa do seu dia, e repetir o mesmo par de valores registraria
  taxas que não existiram;
- realizar uma ponta **não** copia o valor para a outra quando as moedas
  diferem — cada lado realiza pelo próprio valor. Vale também para a
  conciliação de extrato, que realiza pelo valor da linha;
- a **taxa efetiva não é gravada**: é a divisão de uma ponta pela outra. Número
  derivado que se guarda é número que um dia discorda das pontas;
- na listagem de operações, o valor da operação é o da ponta de origem, na moeda
  dela: somar as duas pontas contaria o mesmo dinheiro duas vezes, e a maior das
  duas seria só a de número maior.

## Cartão de crédito

O cartão é uma conta com `account_kind = "cartao_credito"`. Ele segue as mesmas
regras das outras contas, com três diferenças de significado:

- **o saldo é dívida.** Compras são despesas na conta do cartão, na data da
  compra e com a categoria real; o saldo fica negativo, e esse negativo é a
  fatura em aberto. Um cartão negativo não é alerta de caixa;
- **pagar a fatura é transferência, não despesa.** O pagamento sai de uma ou
  mais contas comuns para o cartão, uma transferência de cada, e pode ser
  dividido entre contas. Lançar o pagamento como despesa contaria o mesmo gasto
  duas vezes: na compra e na fatura;
- **os dias guiam a projeção.** `card_closing_day` e `card_due_day` (1 a 31)
  são obrigatórios no cartão. A conta de pagamento padrão
  (`card_payment_account`) é opcional e só diz de onde sai a fatura projetada;
  ela tem de ser uma conta comum, na mesma moeda. Uma conta que paga algum
  cartão não pode virar cartão.

O banco garante que um cartão tem os dois dias e que uma conta comum não tem
nenhum dado de cartão (`ck_financial_account_card_fields`). Os contratos
patrimoniais publicam o tipo em cada conta (`tipo`), para o consumidor tratar o
saldo do cartão como passivo.

Uma conta também pode ser `account_kind = "aplicacao"` (CDB, caixinha,
Tesouro). Para o saldo ela é uma conta comum, sem nenhum dado de cartão (o
mesmo CHECK garante), e aplicar ou resgatar continua sendo transferência. O
tipo existe para o filtro global de grupos, descrito abaixo.

O modelo anterior -- a fatura inteira como uma despesa recorrente de valor
estimado na conta corrente -- continua válido para o histórico. Cada cartão
passa ao modelo novo a partir da primeira fatura importada, sem reescrever o
passado.

### Importação da fatura

A fatura em CSV (C6 e XP, reconhecidas pelo cabeçalho) entra por Bancos >
Importações, na conta do cartão, e passa por duas etapas:

1. **importar** grava só as linhas (`BankStatementLine`), com o sinal da conta:
   compra negativa, pagamento e estorno positivos -- o contrário do arquivo. A
   parcela recebe a data em que entra na fatura (a da compra mais N-1 meses) e
   guarda N, o total, a data da compra, o portador e a categoria do banco.
   Parcela cuja conta passaria do fechamento da própria fatura já veio com a
   data do lançamento (a anuidade da C6 é assim) e não é deslocada; o
   fechamento sai do dia de fechamento do cartão e da última data que com
   certeza é de lançamento (compra à vista, 1ª parcela ou pagamento).
   Reenviar o arquivo não duplica, pelo mesmo hash por conta dos extratos. Uma
   fatura enviada para conta comum, ou um extrato enviado para cartão, é
   recusado antes de gravar: os dois invertem o sinal de tudo;
2. **processar** mostra uma prévia e só então grava, tudo ou nada
   (`bank_statements/fatura.py`). Cada linha vira:
   - *já no saldo inicial*, se a data é anterior à do saldo inicial do cartão.
     O saldo soma todos os lançamentos, inclusive os anteriores a essa data, e
     lançar a linha contaria a dívida duas vezes. Se for parcela, são criadas
     as parcelas seguintes que caem a partir dessa data, "a vencer";
   - *pagamento*, casado com a transferência que chega ao cartão (mesmo valor,
     até 10 dias) e realizado nas duas pontas. Sem transferência, a linha fica
     pendente em Conciliação;
   - *parcela já lançada*, casada pela descrição e pela data (até 5 dias), não
     pelo número: o CB renumera parcelas quando o grupo é editado;
   - *compra parcelada nova*, que cria as parcelas N a M
     (`TransactionRequest.first_installment`) e realiza a N;
   - *compra já lançada* à mão (mesmo valor, até 3 dias), que é conciliada;
   - *compra* ou *estorno*, criados já realizados.

A categoria sugerida segue a mesma ordem do extrato de conta (`classificacao.py`,
ver "Plano do extrato de conta"): a mais frequente para a mesma descrição em
qualquer conta, depois a categoria escolhida antes para a mesma categoria do banco
(a prévia ensina as faturas seguintes), depois a categoria do banco quando ela tem
o nome de uma categoria cadastrada, e por fim "Outros". A prévia organiza as
linhas pelo nível de confiança (`fatura.organizar`):

- primeiro, **para conferir**, as linhas sem confiança alta. As compras da mesma
  loja, sinal e sugestão ficam juntas, e uma escolha vale para todas: os bilhetes
  de uma viagem da United eram 25 linhas. Aberto o grupo, cada compra pode ficar
  com outra categoria;
- recolhidas no fim, as de confiança alta, já com a categoria e ainda editáveis;
- e as que não pedem categoria (pagamento, parcela ou compra já lançada, saldo
  inicial).

Uma fatura inteira anterior ao saldo inicial não lança nada, e
a prévia avisa isso em destaque: para importar histórico, a data do saldo
inicial do cartão tem de ser anterior à primeira fatura. Quando o arquivo tem mais
de um portador, o nome de quem comprou vai para a descrição.

### Reclassificação em lote

Movimentação > Reclassificação (`bank_statements/reclassificacao.py`, permissão
`banking.reclassify`) troca a categoria de vários lançamentos gerenciais de uma
vez; transferência e movimentação ficam de fora. A prévia mostra tudo antes de
gravar:

- **iguais** -- a mesma descrição depois de tirar portador, valor em dólar e
  termos com número (`chave_da_descricao`; quando isso apagaria tudo, como em
  "UNITED01647204721164", sai só o número) -- entram junto, já marcadas;
- **parecidas** -- mesma primeira palavra, chave diferente -- só são sugeridas;
- **mesma categoria do banco** pode ser aplicada a todas as compras dela;
- parcelado e recorrente mudam inteiros.

Mês fechado só é atravessado com autorização explícita e com a permissão de
fechamento mensal: cada mês é reaberto com motivo, alterado e fechado de novo;
o saldo de fechamento é recalculado e, se diferir do anterior, nada é gravado.
A reclassificação é a forma de ensinar: o importador sugere a categoria mais
frequente para a mesma chave, em qualquer conta, então corrigir aqui muda as
próximas sugestões. As regras explícitas (`StatementRule`) ficam para o que o
histórico não alcança.

### Fatura projetada

Cada fatura futura, até o horizonte de projeção, é **parcelas já lançadas no
ciclo + gasto novo estimado** (`bank_statements/fatura_projetada.py`). O ciclo
vai do fechamento anterior (exclusive) ao fechamento; a contagem parte da
última fatura importada, então uma fatura já fechada e ainda não importada
também é estimada.

O gasto novo não pode contar de novo as parcelas. Para cada fatura importada,
soma-se só o que ela cobrou e ainda não era conhecido `k` fechamentos antes:
parcela N/M é conhecida desde a data em que a 1ª entrou na fatura (a da linha
menos N-1 meses), compra à vista desde a própria data. A estimativa da `k`-ésima
fatura futura é a mediana desse valor nas últimas 6 faturas (mínimo 3; com
menos, só entram as parcelas). Por isso a estimativa cresce nas faturas mais
distantes: nelas cabem também as parcelas seguintes de compras ainda não
feitas. Pagamentos e estornos ficam de fora, e a anuidade, que vem com a data
do lançamento, conta como parcela antiga. O gasto mensal fixado no cadastro do
cartão (`card_estimated_spend`) substitui a mediana.

A projeção vira lançamentos "a vencer": a despesa "Gasto estimado" no cartão,
na data do fechamento, na categoria "Cartão de Crédito"; e o pagamento, uma
transferência da conta de pagamento padrão no vencimento, pelo total
projetado. Sem conta de pagamento padrão, não há pagamento projetado. Uma
transferência para o cartão já agendada pelo usuário entre o fechamento e 10
dias depois do vencimento vale como pagamento daquela fatura, e a projeção não
cria outro. Os lançamentos são reconhecidos pela chave da `BankOperation`
(`cartao-estimativa:` e `cartao-pagamento:`) e refeitos inteiros ao processar
uma fatura, ao salvar o cartão ou os Parâmetros e a cada execução da projeção
de recorrências. Marcado como realizado, o lançamento projetado deixa de ser
projeção: a chave ganha o prefixo `realizado-` e ele fica.

Faturas e projeção (Movimentação › Importação, `/banking/cards/`) reúne, por cartão, o saldo realizado, as
últimas faturas importadas (com o link para cada uma) e as próximas faturas
projetadas.

Extratos importados (Movimentação › Importação, `/banking/statements/`) é o equivalente para as contas que não
são cartão: por conta, o saldo realizado e os últimos extratos importados, cada um
com as linhas por status (conciliadas, ignoradas, pendentes) e a conferência do
saldo do arquivo contra o do CB. O detalhe (`/banking/import/<id>/extrato/`) lista
as linhas do lote. Não há extrato projetado, e o lote de cartão é recusado: ele
vive em Faturas e projeção. É só leitura; quem importa e concilia são Importar
extratos e faturas e Conciliação.

Situação das Contas (Movimentação › Importação, `/banking/status/`) é a matriz conta × mês do que
já foi importado e conciliado (`bank_statements/situacao.py`). O mês da célula é o
da data da linha do extrato ou da fatura, não o da importação. Estados: *sem
importação* (nenhuma linha no mês), *com pendências* (alguma linha ainda "nova"),
*conciliado* (linhas, nenhuma pendente; ou nenhuma linha, mas um extrato importado
informa o saldo num dia do mês: o mês sem movimentação), *saldo informado* (sem linhas, mas com
lançamento de Saldo Aplicações no mês, o que resta de uma aplicação sem extrato
linha a linha), *mês fechado* e *não se aplica* (sem linhas e mês que termina antes do saldo
inicial da conta). Mês fechado conta como em dia: fechar é a conferência do
usuário, e vale também para o que estaria sem importação ou à espera do saldo
de fim de mês de uma aplicação; a descrição da célula diz o que faltava. Linha
de extrato pendente continua sendo pendência, mesmo com o mês fechado. O resumo conta as contas a que o mês de referência se aplica;
por padrão ele é o mês anterior, porque o corrente ainda está em andamento. Cada
célula leva ao que a resolve: Importar extratos e faturas, Conciliação (conta), a fatura
(cartão) ou o extrato. Ambas as telas exigem `banking.view`.

## Fechamento mensal

O fechamento pertence a uma conta e a um mês. Enquanto estiver ativo, bloqueia
criação, edição, exclusão, realização e conciliação de movimentos que atinjam o
período. A reabertura exige ação explícita, motivo e registro de auditoria.

## Extratos, conciliação e comprovantes

Extratos CSV, OFX, OFC e QFX são normalizados antes da importação. PDF é aceito
somente para instituições homologadas pelo código. A importação limita tamanho
e número de linhas, detecta duplicidades por conta e não preserva o arquivo de
extrato original como mídia. A fatura de cartão em CSV tem leitura e
processamento próprios, descritos em "Importação da fatura".

A conciliação verifica acesso à conta, tipo, valor, status, duplicidade e
fechamento do período. Um lançamento pode ter no máximo uma conciliação ativa,
restrição também garantida no PostgreSQL. Vincular uma linha a um lançamento que
já está realizado, na mesma data e valor, não muda saldo nem lançamento e por
isso vale em mês fechado (é o caso do histórico digitado à mão); realizar ou
mudar o lançamento continua exigindo o mês aberto.

Lançamento já realizado em outra data ou por outro valor também concilia: o
extrato é o fato, e escolher o lançamento é a autorização para trocar a data e o
valor realizados pelos da linha (o previsto fica). Numa transferência só a ponta
da conta do extrato muda de data; valor diferente numa transferência na mesma
moeda é recusado, porque as pontas são espelhadas. O botão Conciliar da linha
pode reabrir o mês fechado para isso, desde que o saldo de fechamento não mude
(na prática, só a data dentro do mesmo mês); "Conciliar selecionadas" e
"Aplicar sugestões" recusam e mandam usar o botão da linha.

Os PDFs com adapter são o da Genial, o do Mercado Pago e o da conta de
investimento da XP (`XpPdfStatementAdapter`). O da XP lê a geometria da tabela
(a descrição quebra em até três linhas, antes e depois da data), valida a cadeia
de saldos de linha a linha e informa como saldo o da linha mais recente na data
final do período. A instituição cadastrada como "SCP XP Investimestos" (sic) usa
o mesmo adapter, e a conta é reconhecida pelo número do rótulo "Conta:" do PDF.

O do Itaú (`ItauPdfStatementAdapter`) lê o "extrato conta / lançamentos": uma
linha por lançamento, com o sinal no valor. As linhas "SALDO DO DIA" não viram
lançamento; elas conferem, dia a dia, saldo anterior + lançamentos do dia =
saldo do dia, porque a ordem dentro do dia não é confiável. O formato é
reconhecido por "itau.com.br" e não pelo nome, que aparece em Pix e TED para o
Itaú no extrato de qualquer banco; a conta vem de "agência: ... conta: ...".

O da Avenue (`AvenuePdfStatementAdapter`) lê a conta brasileira, em reais: por
onde o dinheiro entra (Pix), sai para a conta em dólar (remessa de câmbio) e sai
o IOF. A data de cada linha é a da liquidação, quando o saldo muda; a coluna de
saldo confere linha a linha a partir do saldo inicial do resumo, e o saldo final
fecha a cadeia. Formato reconhecido por "www.avenue.us"; conta por "Nº conta".

A fatura de cartão quase sempre atravessa dois meses: a de outubro traz as
compras de meados de setembro em diante, e setembro pode já estar fechado no
cartão. O mês do cartão só fica completo quando chega a fatura seguinte. A
prévia mostra os meses fechados que a fatura toca e, com a autorização do
usuário, o processamento os reabre e fecha de novo com o saldo que a fatura
deixou. Entram também os meses fechados depois deles, porque o saldo de
fechamento é acumulado. Aqui o saldo de fechamento muda de propósito: a fatura é
a verdade sobre o mês. Reabertura e novo fechamento ficam na auditoria.

O rótulo "Conta Origem: …" / "Conta Destino: …" de cada ponta de transferência
acompanha o cadastro: renomear titular, instituição ou conta o refaz nas pontas
que apontam para ela, também em mês fechado, porque é o nome da conta e não um
fato do período (`transactions/rotulos.py`). Descrição digitada pelo usuário
numa transferência não muda. O comando `refazer_rotulos_de_transferencia`
corrige o que ficou para trás.

PDF protegido por senha (fatura e extrato costumam chegar assim) fica pendente
na tela de confirmação, sem detecção de conta, até o usuário digitar a senha
(`bank_statements/pdf_senha.py`). Com a senha, o arquivo pendente é regravado
sem a proteção e segue como qualquer PDF; a senha vale só naquela requisição e
não é gravada, nem em log. Confirmar a importação sem abrir o arquivo o descarta
com aviso.

### Plano do extrato de conta

A tela de Conciliação mostra, por linha pendente, o que ela vai virar, e
"Aplicar sugestões" executa exatamente isso (`bank_statements/extrato.py`; é o
que `fatura.planejar` faz para o cartão). Na ordem em que é decidido:

1. **ignorar**, quando uma regra explícita manda;
2. **conciliar** com o único lançamento candidato (mesma conta, sinal e valor,
   no mês do extrato); entre vários, o único na data da linha, e sem ele a
   escolha é manual. Um lançamento nunca é dado a duas linhas: o da data da
   linha fica com ela, e a outra segue sem candidato;
3. **transferência pareada**: outra linha pendente, em outra conta do usuário,
   de sinal oposto, mesmo valor e até dois dias de distância, com o nome de um
   titular no texto (ou cara de transferência nas duas) e par único dos dois
   lados. As duas linhas viram **uma** transferência, cada ponta na sua data,
   exigindo a permissão de destino de transferência;
4. **transferência por regra**: a regra aponta a conta de destino do mesmo
   titular e instituição (Rende Fácil, caixinha) e a outra ponta não tem extrato;
5. **concilia com valor diferente**: recorrência aberta da conta, mesmo sinal,
   valor até 25% do previsto e vencimento a até 5 dias. O lançamento é realizado
   pelo valor do extrato e o previsto fica como estava;
6. **transferência sem par**: o texto cita um titular e a outra ponta ainda não
   foi importada. Fica pendente, porque criar receita e despesa para uma
   transferência própria infla as duas pontas do mês;
7. **criar** lançamento com a categoria sugerida.

O que o plano não resolve, a linha resolve à mão. O seletor de categoria de cada
linha pertence ao formulário do lote: "Criar selecionadas", "Aplicar sugestões"
(nas linhas que o plano manda criar) e o "Criar" da própria linha usam a
categoria escolhida nele, e a sugestão só quando nada foi escolhido. Transferência
não está nesse seletor, porque tem outra ponta: **Transferir** lança a linha como
transferência para (saída) ou de (entrada) outra conta do usuário, as duas pontas
realizadas na data da linha, e concilia a ponta da conta do extrato
(`reconciliation.transfer_from_line`). É o caminho entre moedas diferentes (a
remessa de câmbio da conta em real para a conta em dólar), que o plano não faz:
o valor que a outra conta registrou, na moeda dela, é digitado, porque o sistema
não inventa taxa. Na mesma moeda as pontas são espelhadas e esse valor é recusado.

A categoria sugerida (`classificacao.py`) vem, nesta ordem, da regra explícita,
da categoria mais frequente que o usuário deu à mesma descrição (sem contar
"Outros"), da categoria dominante da conta quando a descrição só diz o meio de
pagamento ("Boleto", "DEBIT"; exige 5 lançamentos do mesmo tipo e 80% numa
categoria), da categoria do banco já escolhida antes, do prefixo do extrato e de
"Outros". A mesma descrição é procurada na descrição do lançamento **e** no texto
da linha de extrato conciliada com ele, um voto por lançamento: reescrever a
descrição ("Salário") não apaga o que o banco manda ("PAGTO SALARIO"). O prefixo
do PDF fica depois do histórico porque erra (a Genial chama o aluguel de ações de
"Rendimentos"). A regra explícita (`StatementRule`, `manage.py regras_de_extrato`)
descreve uma família de texto por instituição e sinal, nunca por id.

Cada sugestão tem um **nível de confiança**. É alta quando vem de regra ou de dois
ou mais casos anteriores, todos na mesma categoria, fora de intermediador (Mercado
Livre, Shopee, Amazon, MP*, PayGo, iFood: a mesma "loja" vende de tudo). Média
com 90% ou mais de concordância, baixa abaixo disso, e nenhuma quando cai em
"Outros". O critério vem do teste retroativo sobre os dados reais (17/10/2026):
a confiança alta acertou 99,4%, e o resto ficou entre 55% e 89%. A Conciliação
mostra primeiro as linhas que pedem atenção. No fim ficam as seguras: candidato
único, transferência pareada ou por regra, regra de ignorar e criação com
confiança alta. `manage.py medir_sugestoes [--desde AAAA-MM-DD]` refaz essa
medição. Cada linha usa só o histórico de antes do mês dela, e a medição roda numa
transação desfeita no fim. O comando lista também os lançamentos nascidos de uma
linha de extrato que destoam da mesma loja (3 ou mais compras, 70% numa
categoria), para corrigir em Reclassificação. Destoar só da categoria do banco não
conta: na primeira medição, os 5 casos assim eram escolhas mais específicas do
usuário. Lançamento digitado à mão também não entra, porque a categoria foi
escolhida junto com o texto.

O arquivo pode informar o saldo (`LEDGERBAL` do OFX, "Saldo final" da Genial e do
Mercado Pago, último "SALDO DO DIA" do período no Itaú, "Saldo final" da Avenue). Ele é guardado no lote e conferido, nas telas Importar extratos e faturas e Extratos importados, com o
saldo realizado do CB na mesma data; a diferença aponta linha faltando ou sobrando
em qualquer ponto do histórico. Não entra no hash da linha.

Arquivo sem movimento mas com saldo é uma importação: o mês não teve
movimentação (o BB exporta assim o OFX do mês parado). O lote entra sem linhas,
com o saldo conferido como o de qualquer outro, e o mês do saldo fica
*conciliado* na Situação das Contas, podendo ser fechado. Sem movimento e sem
saldo, o arquivo é recusado: não há o que importar. Fatura de cartão sempre
exige linhas.

### Saldo Aplicações (antes "Atualizar saldo")

Para o que o extrato não mostra linha a linha (rendimento de CDB, cofrinho,
conta remunerada), o usuário informa o saldo real de uma conta numa data e a
diferença para o saldo realizado do CB vira um lançamento realizado, com destino
explícito: *Rendimentos* ou *Ajuste assumido* quando o saldo real é maior;
*IR/IOF*, *Perda* ou *Ajuste assumido* quando é menor. Perda e ajuste assumido
exigem motivo, usam a categoria "Ajustes de Saldo" e aparecem na lista de
assunções. Se o saldo do CB mudou entre a prévia e o lançamento, nada é gravado.
A tela lista todas as atualizações de saldo lançadas (a descrição começa por
"Atualização de saldo"), com o destino de cada uma; as assunções aparecem
marcadas.

Dois destinos valem nos dois sentidos: *Marcação a mercado* (Tesouro e renda
fixa, que sobem e descem com o preço; categoria "Variação de mercado", do tipo
`valorizacao`) e *Investimentos* (o caixa de uma corretora que virou ativo ou
voltou dele; categoria de movimentação "Operações em Bolsa", que não é gasto nem
renda). Todo saldo
informado fica registrado por conta e dia (`fechamento.SaldoConferido`), com a
origem (print, myProfit, digitado) e o lançamento da diferença, se houve. Saldo
que já bate pode ser **registrado como conferido**, sem lançamento. Informar de
novo o mesmo dia pela mesma origem não duplica: o saldo do CB já inclui a primeira
diferença, e só um valor novo lança uma diferença nova.

**Uma fonte por conta.** O registro é por conta, dia **e origem**
(`fechamento.SaldoConferido`): outra origem para o mesmo dia acrescenta um
registro e nunca sobrescreve o anterior. Só a fonte declarada da conta (aba
Fontes, ou a deduzida) lança diferença: conta do myProfit aceita a origem myProfit,
conta de print aceita print ou digitado, e conta de extrato ou fatura não restringe.
O saldo de outra origem entra como **conferência** (`saldo.conferir`, botão
"Registrar como conferência"): fica registrado e não lança nada. Duas origens que
discordam no mesmo dia além da tolerância (o maior entre R$ 10,00 e 0,2% do maior
saldo, para arredondamento não virar pendência) aparecem no Roteiro de fechamento,
etapa Conferências, para decidir qual vale; a decisão não é um segundo ajuste.
Trocar a fonte de uma conta fica na auditoria (`account_source`). Foi assim que o
Tesouro Direto da XP, que recebia o preço oficial digitado e a posição do myProfit
nas mesmas datas, passou a ter o myProfit como fonte única (decidido em
21/10/2026). A mesma regra vale no CRV: repetir a mesma fonte substitui, e uma
fonte diferente acrescenta e é conferida (`docs/CONCEITOS_FINANCEIROS.md`). A view
`leitura.saldo_conferido` publica os registros por origem.

### Aplicação movimentada por conta corrente

Cofrinho, CDB, Caixinha, Rende Fácil e Tesouro Direto não têm extrato: o
dinheiro entra e sai por uma conta corrente do mesmo titular e moeda, a **conta
de movimento** da aplicação (`FinancialAccount.movement_account`, só para o tipo
aplicação). O rendimento do mês é saldo informado − (saldo anterior + entradas −
saídas), que é exatamente a diferença que Saldo Aplicações lança.

- **Transferências**: vêm do extrato da conta de movimento. A regra de ação
  "aplicação vinculada" (`StatementRule.action = "aplicacao"`) leva a linha para
  a única aplicação cuja conta de movimento é a da linha (filtrada pelo nome, se a
  regra tiver um); nenhuma ou mais de uma deixa a linha para decisão manual. É o
  que permite uma só regra para "EMISSÃO/RESGATE DE CDB" do C6, que é o "CDB" de
  um titular e a "Caixinha" do outro.
- **Saldo Aplicações** recusa o saldo de uma aplicação vinculada enquanto o
  extrato do mês da conta de movimento não foi importado, ou ainda tem linha
  pendente até a data: a transferência que falta viraria rendimento. Conta como
  importado até o fim do período que o arquivo declara (o `DTEND` do OFX), mesmo
  sem linha nos últimos dias.
- **Situação das Contas**: o mês da aplicação vinculada é conciliado quando a
  conta de movimento está conciliada no mês e o saldo foi informado no último dia
  do mês, ou quando ela terminou o mês zerada e sem movimento. Senão fica com
  pendências (dizendo qual falta) ou sem importação.
- **Fechamento em lote**: `manage.py fechar_meses_conciliados --usuario NOME
  [--aplicar]` fecha os meses conciliados (por esse critério e pelo das contas
  com extrato), fora o mês corrente e os já fechados; pula, listando, o mês cujo
  saldo de extrato diverge do CB.

### Ativo, tipo de renda e liquidação de pregão

O lançamento de uma conta de corretora (Genial, SCP XP, Avenue, Nomad, Revolut
são instituições do tipo "Corretora") guarda, além do valor, o que a descrição do
extrato diz sobre o papel (`EntryInvestmentDetail`; ver `docs/architecture.md`).
O parser lê, por palavra inteira e sem acento:

- **ativo**: o ticker escrito (`EALT4`; `S/ 6,300` não é ativo) ou o código tipo
  ISIN que a corretora imprime. A classe dá o final: `ACNOR` = 3, `ACNPR` = 4 e
  `CTF` = 11 (`Brraizacnpr6` = RAIZ4, `Brhodlctf005` = HODL11). Unit e BDR não têm
  regra e ficam sem ativo, em vez de um ticker chutado;
- **tipo de renda**: `aluguel` ("Taxa de Remuneração Emprestimo"), `jcp` ("Juros
  S/ Capital") ou `dividendo` ("Dividendos", "Cred Reembolso Jcp-Btc");
- **papel da linha**: `credito` é a renda que entrou. No aluguel de ações a conta
  também recebe `irrf_aluguel` ("Irrf S/Rendimentos Empréstimos de Ações"),
  `corretagem_aluguel` ("Corretagem Executor - Btc") e `taxa_aluguel` ("Taxa de
  Remuneração Btc", "Tx de Liquidação de Emprest."). O "Estorno * Prov * ..." é
  `estorno`, à parte, com o tipo da linha que ele desfaz;
- **liquidação de pregão** ("Operações Bolsa D+2 Pr 27/01/2026 Nc. 543216"): a
  data do pregão e o número da nota; nota mascarada (`Nc. *`) fica sem número.

Não recebem campos: o IRRF de pregão e de day trade ("Irrf S/ Resultado Bolsa",
"Irrf S/ Operações D+2", "Irrf S/ Day Trade"), que **não** é `irrf_aluguel`; a
corretagem e o ajuste de mini-contrato ("Operações Bm&F"); e o lançamento único
sem ativo ("Atualização de saldo: rendimentos"). O dado é só acréscimo: não muda
valor, data, categoria nem saldo, e vale para qualquer conta cuja descrição case.

### Dados já gravados

Dois comandos de manutenção, ambos com simulação por padrão e backup antes de
aplicar: `converter_pares_proprios` transforma em transferência os pares de
receita e despesa entre contas do mesmo titular (só natureza e vínculo mudam; o
saldo de cada conta e de cada mês fechado fica igual, e é isso que autoriza
reabrir o mês), e `reclassificar_familias` move famílias determinísticas (IRRF,
VA/VR, plano de saúde...) da categoria em que estão para a de destino. Nenhum dos
dois toca categoria que o usuário já escolheu fora da origem da família.

Comprovantes são arquivos distintos do registro relacional. O sistema valida
tamanho, extensão e assinatura, grava o arquivo sob `MEDIA_ROOT/attachments` e
mantém seus metadados no PostgreSQL. Downloads passam novamente pelo controle
de acesso ao lançamento.

## Roteiro de fechamento

Movimentação › Importação › Roteiro de fechamento (`/banking/closing/`,
`fechamento/`) diz, conta a conta, o que falta para conferir tudo até uma **data
de corte**: o dia 10, o 25, o último dia do mês, hoje ou outra. O corte não trava
nada e pode se repetir quantas vezes for preciso no mês; a trava continua sendo o
fechamento mensal, que o roteiro só sugere no corte do último dia. Concluir um
corte (tudo em dia e a data já passada) só o registra, para o histórico da aba
Cortes.

**Fonte de cada conta** (aba Fontes, `FonteDaConta`): extrato em arquivo, fatura,
print de saldo, myProfit ou "ainda não tenho", com o formato, a frequência (a
cada corte ou só no fim do mês) e onde obter. A conta sem cadastro tem a fonte
deduzida (`fechamento/fontes.py`): cartão é fatura; aplicação com "Tesouro" no
nome vem do myProfit, no fim do mês; outra aplicação é print do fim do mês; conta
com extrato importado é arquivo, no formato do último; a conta em dólar da Avenue
vem do myProfit; conta com saldo já informado é print; o resto, "ainda não tenho".

**Etapas e estados.** O extrato de hoje quase nunca existe, então a cobertura
exigida vai até a véspera do corte; o saldo de print vale até hoje. Corte no
futuro cobra só até hoje.

1. *Extratos e faturas*: o extrato cobre até a véspera e nada ficou por conciliar;
   no cartão, a fatura que fechou até o corte foi importada.
2. *Saldos sem extrato*: o saldo do corte foi informado (ou o do fim do mês
   anterior, para quem é conferido só no fim do mês). A aplicação com conta de
   movimento espera o extrato dela, como em Saldo Aplicações. Aplicação zerada e
   sem movimento está em dia; conta sem fonte e sem nada a conferir não se aplica.
3. *myProfit*: a coleta chegou até o corte e as contas que dependem dela têm o
   saldo lançado; mais o que o CRV diz de si (abaixo).
4. *Conferências*: possíveis duplicatas, fontes do saldo que não concordam, o saldo do último arquivo de cada conta
   contra o do CB, o que a coleta não resolveu e as conferências do CRV.
5. *Fechar o mês*: no corte do último dia, com o resto em dia.

Cada item tem um estado (em dia, falta fazer, pede decisão, espera outro passo,
sem fonte, não se aplica) e, quando há o que fazer, o formato, o período a pedir
ao banco e o link para onde se resolve. O **próximo passo** é o primeiro item a
fazer, na ordem das etapas.

**Reimportar é seguro.** Linha de extrato repetida é reconhecida pelo hash (ver
"Extratos, conciliação e comprovantes"); saldo informado de novo para o mesmo dia
só lança uma diferença nova; a coleta reaplicada só confere. O que escapa é a mesma
transação com outra cara na segunda exportação: **possível duplicata** é o par de
linhas da mesma conta e valor, até dois dias de distância, com descrições e lotes
diferentes (`fechamento/duplicatas.py`). O par que não é duplicata é descartado e
não volta.

**Coleta do myProfit** (`fechamento/myprofit.py`, tela e
`manage.py importar_coleta_myprofit <pacote> --usuario U [--gravar]`). O pacote
`myprofit-coleta/1` sai de `scripts/myprofit/coletar.js`, no repositório do CRV,
rodado na aba do myProfit já logada; ele só copia campos de uma lista fixa (nada
de nome, CPF, e-mail ou telefone). O CB usa a posição por corretora em cada data
do pacote e as notas de câmbio. Conta com fonte myProfit diz o que é lá
(`classe_myprofit`: Tesouro, renda fixa EUA ou caixa em dólar) e o nome da
corretora; a diferença para o saldo do CB segue Saldo Aplicações com origem
myProfit: Tesouro e renda fixa EUA como marcação a mercado; no caixa em dólar, os
proventos do período como rendimento e o resto como investimentos. Conta mensal
só recebe as datas de fim de mês. Fica de fora, como pendência: mês fechado,
conta de movimento sem extrato, posição sem conta no CB e, no caixa em dólar, a
data com remessa de câmbio que ainda não está no CB (sem ela, a remessa viraria
"investimentos"). A remessa confere com uma entrada na conta em dólar até quatro
dias e US$ 1,00 de distância.

**O CRV no roteiro** (`fechamento/crv.py`). O CRV publica
`GET /fechamento/status?ate=AAAA-MM-DD` (contrato `crv-fechamento/1`): itens já
avaliados por ele, com etapa, estado e texto. O CB os lê pela rede interna do VPS
(`CRV_FECHAMENTO_URL`), autenticado pelo token do vínculo CB ↔ CRV
(`PATRIMONIO_INTEGRATION_TOKEN` daqui, que o CRV conhece como
`cb_patrimonio_token`), e monta os links com `CRV_PUBLIC_URL`. Sem configuração,
ou com o CRV fora, o roteiro mostra um item "espera outro passo" com o motivo e o
resto segue.

## Projeção de recorrências

O horizonte e o dia mensal de execução são configurados em Parâmetros. A
projeção estende cada `BankOperation` recorrente até o fim do horizonte, a
partir da ocorrência de maior vencimento. Reexecutar para o mesmo horizonte é
idempotente e uma ocorrência removida no meio da série não é recriada.

A projeção só estende. Por isso, salvar os Parâmetros recolhe as séries ao
horizonte atual (`recolher_alem_do_horizonte`): as ocorrências recorrentes
não realizadas além do fim são apagadas, com auditoria, e a série não é
encerrada -- volta a crescer quando o horizonte avançar. Sem isso, diminuir o
horizonte deixava os meses além do novo fim com só as séries antigas, e o
saldo projetado desses meses perdia o sentido. Fica tudo até a última
ocorrência que recebeu atenção própria (conciliada, com comprovante, etiqueta
ou projeto, ou editada em "somente este"), para não abrir um buraco que a
extensão não preenche. Parcelas não são recolhidas: são dívida contratada. O
contrato de projeção publica `ultima_recorrencia` limitada ao fim do
horizonte.

Excluir uma recorrência com o escopo "este e os próximos", ou editá-la nesse
escopo desmarcando "recorrente", encerra a série: a `BankOperation` guarda o vencimento do corte em `recurrence_ended_on` e a
projeção deixa de estendê-la. Vale para a recorrente simples e para a
transferência interna recorrente, cujas duas pernas pertencem à mesma operação.
As ocorrências que restam mantêm `is_recurring`, porque o Planejamento anual
separa recorrente de não recorrente por esse campo e o histórico não muda de
classificação; na edição, as linhas do bloco ficam como lançamentos não
recorrentes da mesma operação. Hoje a interface não reabre uma série
encerrada; retomar a recorrência é criar um novo lançamento recorrente. Excluir
só uma ocorrência abre uma lacuna e não encerra nada. Desmarcar "recorrente"
em "somente este" também não encerra: a linha vira avulsa, e a projeção não
cria outra ocorrência num mês em que a operação já tenha linha, recorrente ou
não, mesmo que o dia tenha sido trocado. Linhas com `is_recurring` desligado à mão, como o contorno aplicado às
operações 162 e 164 em 23/09/2026, também ficam fora da projeção.
O middleware é o gatilho atual; um scheduler ou worker também é válido se
preservar idempotência, retry seguro, auditoria e coordenação entre processos.

`transactions.middleware.ProjecaoRecorrenteMensalMiddleware` verifica a
necessidade em requisições autenticadas. Cada processo consulta no máximo uma
vez ao dia até resolver o mês; a execução acontece no máximo uma vez no mês, a
partir do dia configurado. Se o dia não existir naquele mês, usa-se o último
dia do mês. O campo `last_projection_run` no PostgreSQL e um advisory lock
coordenam os workers. Falhas são registradas e não derrubam a resposta pedida
pelo usuário; uma verificação posterior tenta novamente.

O botão **Executar Projeção Agora** antecipa ou repete a operação a qualquer
momento. A mesma rotina idempotente é usada, e a mensagem informa quantos
lançamentos foram gerados. No desenho atual não há agendador externo: sem
requisições autenticadas após o dia configurado, a execução automática aguarda
o próximo acesso. Isso é uma decisão operacional atual, não uma restrição de
domínio.

## Datas

Datas de vencimento e realização são datas civis. Datas e horas de auditoria e
controle usam timezone e são persistidas pelo PostgreSQL com suporte a fuso;
`TIME_ZONE` é `America/Sao_Paulo` e `USE_TZ=True`.

## Grupos de conta (filtro global)

O filtro global de contas reparte **toda** conta em exatamente um grupo, e é
isso que torna a seleção múltipla legível (`core/account_group_filter.py`):

| Conta | Grupo |
|---|---|
| finalidade `administrada`, de qualquer tipo | Administradas |
| `cartao_credito`, em qualquer instituição | Cartões |
| `aplicacao`, em qualquer instituição | Aplicações |
| `conta` em instituição do tipo Banco | Bancos |
| `conta` em instituição do tipo Corretora | Corretoras |

A finalidade vence o tipo da conta, e o tipo da conta vence o da instituição: o
cartão emitido por um banco não aparece ao marcar só "Bancos". Conta
**administrada** é a que só recebe, gere e distribui dinheiro de terceiros (os
aluguéis do Jardim Iva); ela fica fora do fluxo pessoal por padrão. Dinheiro que
cruza a fronteira entre administrada e pessoal não é transferência: é repasse
(despesa) e renda (receita). Como a moeda, o filtro vive na URL
(`grupos=bancos,cartoes`) e não é gravado; ausente, valem **Bancos e
Corretoras** (com a moeda Real), e marcar só Administradas mostra o resultado
delas sozinho. Ele tira
contas dos números, deixa os seletores inteiros e cede à conta escolhida
explicitamente. No Planejamento anual, cujo seletor de
contas é o próprio escopo, ele restringe as opções.

Tirar um grupo tira as contas dele da seleção, e com elas o saldo: aplicar R$
500 no CDB baixa o saldo de "Bancos" em R$ 500 sem virar despesa, porque o
destino ficou fora do recorte.

Ele substituiu Configurações > Contas em análises, uma preferência gravada
por usuário que escondia contas soltas do Dashboard e de Projeções. A tela e
a tabela `user_account_visibility` saíram em 24/09/2026
(`accounts.0010_remover_contas_em_analises`): o recorte agora é por grupo, e
uma conta específica se vê escolhendo-a no filtro de conta.

## Grupos de categoria

A categoria tem um grupo opcional (`CashFlowCategory.group`), em exatamente dois
níveis: Saúde > Plano de saúde, Moradia > Energia. O lançamento continua
apontando para a categoria; o grupo só agrupa para ler o resultado. Importação,
reclassificação, fatura estimada e orçamento não o conhecem. O Dashboard pode
mostrar a distribuição **por grupo** (a fatia abre Lançamentos filtrado por
`filter_group`), e o Planejamento anual pode agrupar, com subtotal por grupo
(`agrupar=grupo`); o total geral não muda. O grupo "Sistema" (transferências,
movimentações, ajustes de saldo) tem `in_charts=False` e fica fora dos gráficos.
"Cartão de Crédito" continua sendo uma categoria com esse nome exato (a fatura
projetada a procura pelo nome); ela vive no grupo "Bancos e cartões".

Os grupos têm tela própria em Cadastros > Grupos de categoria; a tela de
Categorias lista cada categoria sob o seu grupo e filtra pelo tipo
(Gerencial, Movimentação, Transferência ou Variação de mercado).

### Variação de mercado (`valorizacao`)

Quando o valor de uma aplicação muda sem que dinheiro entre ou saia (marcação a
mercado de Tesouro, renda fixa, caixa em dólar), o saldo da conta muda, mas isso
**não é receita nem despesa**: é variação não realizada do patrimônio (a
definição está em `docs/CONCEITOS_FINANCEIROS.md`). A categoria "Variação de
mercado" é do tipo `valorizacao` (criada pela migração
`transactions/0012_categoria_valorizacao`, no grupo "Investimentos") e é o destino
da *Marcação a mercado* da Atualização de saldo. "Rendimentos" fica só para juro
que de fato foi creditado.

- fora de receita e despesa gerencial, como a transferência e a movimentação
  (`is_internal`), mas **sem** contraparte;
- na projeção mensal tem coluna própria ("Variação de mercado", com sinal), fora
  da geração de caixa e dos créditos/débitos internos; o saldo a inclui. Nas
  demais telas que separam "interno" (planejamento, posição por conta) ela segue
  junto com as movimentações internas, para que o saldo feche;
- o contrato `patrimonio/v4` só conhece três tipos, então a publica como
  `gerencial`, com `valuation: true` na categoria (acréscimo opcional de
  21/10/2026). Para o consolidador (Wealthfolio) a variação é retorno, e tratá-la
  como movimentação de capital a esconderia do resultado;
- o CB **não** mostra "resultado total de investimentos": ele só existe
  consolidado, somando o resultado realizado e a variação não realizada do CRV
  com a variação de mercado daqui.

`manage.py reclassificar_valorizacao --usuario NOME [--aplicar --autorizar-meses]`
move para a categoria nova o que já foi lançado como marcação a mercado em
"Rendimentos" (só a categoria muda; simula por padrão; mês fechado só reabre com
autorização e fecha de novo com o saldo conferido). Faça o backup antes de
aplicar.

`manage.py grupos_de_categoria semear` cria os grupos aprovados e liga as
categorias existentes sem grupo, sem nunca trocar um grupo já escolhido.

## Gestão gerencial: ciclo de vida

Tags, projetos/centros de custo e orçamentos podem ser excluídos somente se
não houver histórico dependente. Tag ou projeto com vínculo a lançamento é
arquivado/desativado, preservando a classificação já registrada e impedindo
novos vínculos. Orçamento com lançamento realizado no seu titular, categoria e
mês é arquivado; sem realizado, pode ser excluído. Itens arquivados continuam
visíveis no histórico, mas não aparecem nos seletores de novos vínculos.
