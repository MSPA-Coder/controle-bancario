# Travas de banco

Inventário das travas (`select_for_update`, `pg_advisory_xact_lock`) que protegem saldo, lançamento, fatura,
fechamento e acesso, e de **qual teste ou qual outra garantia** responde por cada uma. A regra está em
`docs/TESTES.md` (T7 e T14): trava nova nasce com teste de disputa que falha quando ela é retirada, ou com uma
linha aqui dizendo qual garantia a cobre.

Cada trava é citada por `arquivo::função`, que não envelhece como número de linha (T12). O código tem 25 pontos de
trava fora de `tests/` e a tabela os cobre todos; `rg -n "select_for_update|pg_advisory_xact_lock"` confere.

Medido em 29/10/2026 retirando cada trava numa cópia do commit e rodando os arquivos de disputa 3 a 5 vezes
(receita em T14). "Detectada" quer dizer que o teste falhou em todas as repetições sem a trava. As travas
acrescentadas depois (`regras::salvar` e `_devolver_linha_da_outra_ponta`) não foram medidas.

Os testes de `tests/test_travas_postgres.py` seguem um padrão: uma "primeira operação" muda o estado e fica aberta
(sem confirmar); a operação testada precisa esperar por ela e então enxergar o estado confirmado. A primeira só
libera quando a segunda já esperou ou terminou, então o resultado não depende de sorte de tempo.

## A trava da conta esconde as de dentro

`transactions/services.py::lock_accounts` é o recurso de coordenação entre lançamento e fechamento
mensal: todo serviço que muda lançamento ou cria fechamento a toma **antes** de olhar o período. As travas de
operação e de lançamento que vêm depois (`_lock_entry_graph`) ficam atrás dela para quem passa por ela, e por isso
retirar só uma das de dentro não derruba os testes de concorrência da trava de conta. Elas valem para o escritor
que **não** toma a trava da conta (conciliação, importação); os testes de `test_travas_postgres.py` provam isso
com uma transação "de fora" segurando o lançamento.

## Tabela

| Trava | Protege | Cobertura |
|---|---|---|
| `transactions/services.py::lock_accounts` | lançamento × fechamento mensal | `test_concorrencia_financeira_postgres.py::test_fechamentos_simultaneos_criam_um_unico_registro` (detectada) |
| `transactions/services.py::_lock_entry_graph`, lançamentos (ramo da operação e ramo do lançamento avulso) | realizar, desfazer, editar e excluir sobre o estado já confirmado | `test_travas_postgres.py::test_realizar_parcela_espera_os_lancamentos_da_operacao_e_recusa_a_ja_realizada` (ramo da operação) e `test_realizar_espera_o_lancamento_e_recusa_o_que_outra_transacao_realizou` (ramo avulso) (detectadas) |
| `transactions/services.py::_lock_entry_graph`, operação (`BankOperation`) | ordem de aquisição conta → operação → lançamentos | **Sem efeito observável isolado**: o lançamento é travado em seguida, e a operação só é atualizada no fim, onde o `UPDATE` já espera a linha. A trava existe para a ordem global (evitar impasse). Sem teste. |
| `transactions/services.py::close_month` e `::reopen_month` (`AccountMonthClose`) | fechar e reabrir o mesmo mês | **Coberta por** `lock_accounts`, tomada antes na mesma função. Esses dois métodos são os únicos que gravam `AccountMonthClose`. Retiradas, nenhum teste falha. Sem teste próprio. |
| `transactions/recurring_projection.py::ensure_recurring_projection_horizon` e `::recolher_alem_do_horizonte` (advisory 81288431) | extensão e recolhimento da projeção não se atravessam | `test_travas_postgres.py::test_projecao_recorrente_espera_a_outra_rotina_terminar[extensao/recolhimento]` (detectadas) |
| `transactions/recurring_projection.py::recolher_alem_do_horizonte`, lançamentos candidatos ao recolhimento | não apagar a ocorrência que outra transação acabou de realizar | `test_travas_postgres.py::test_recolhimento_espera_o_lancamento_e_nao_apaga_o_que_outra_transacao_realizou` (detectada) |
| `transactions/recurring_projection.py::recolher_alem_do_horizonte`, operações | ordem de aquisição | **Sem efeito observável isolado**, como a da operação em `_lock_entry_graph`: o recolhimento trava as contas antes e os lançamentos depois. Sem teste. |
| `bank_statements/reconciliation.py::_get_line_in_scope` (linhas do extrato) | linha ignorada por outra transação não vira lançamento | `test_travas_postgres.py::test_linha_ignorada_por_outra_transacao_nao_vira_lancamento` (detectada) |
| `bank_statements/reconciliation.py::_locked_entry_for_update` (lançamento a conciliar) | duas linhas não realizam o mesmo lançamento | `test_concorrencia_financeira_postgres.py::test_duas_linhas_concorrentes_nao_realizam_o_mesmo_lancamento_duas_vezes` (detectada) |
| `bank_statements/reconciliation.py::undo_statement_import` (linhas do lote) | desfazer espera a conciliação em andamento | `test_travas_postgres.py::test_desfazer_importacao_espera_a_conciliacao_em_andamento_e_a_desfaz` (detectada) |
| `bank_statements/reconciliation.py::_devolver_linha_da_outra_ponta` (linha conciliada com a outra ponta da transferência) | desfazer a realização de uma ponta não corre com quem concilia, ignora ou desfaz a linha da outra | **Sem teste de disputa** (não medida). `undo_reconciliation` trava só o lançamento (`_locked_entry_for_update`), não o da contraparte: a trava das linhas é a única proteção nesse ponto. Pendente. |
| `bank_statements/extrato.py::_linha_travada` | aplicar plano sobre linha ainda disponível | `test_travas_postgres.py::test_linha_travada_do_extrato_espera_e_recusa_a_linha_ignorada_por_outra_transacao` (detectada) |
| `bank_statements/extrato.py::_aplicar_com_lancamento` (lançamento que vira transferência) | recusar se o lançamento mudou desde a prévia | `test_travas_postgres.py::test_transferir_com_lancamento_espera_o_lancamento_e_recusa_o_que_outra_transacao_mudou` (detectada) |
| `bank_statements/services.py::import_statement_file` (advisory) | reimportações simultâneas contam duplicatas sem erro | `test_concorrencia_financeira_postgres.py::test_reimportacoes_simultaneas_contam_duplicatas_sem_erro` (detectada) |
| `bank_statements/fatura.py::processar` (linhas novas do lote) | fatura processada ao mesmo tempo grava uma vez | `test_fatura_concorrencia_postgres.py::test_fatura_processada_ao_mesmo_tempo_grava_uma_vez` (detectada) |
| `bank_statements/fatura_projetada.py::atualizar` (conta do cartão) | ler a conta do cartão travada | **Coberta por** `lock_accounts(ids_contas)`, chamado logo acima na mesma transação com todas as contas. É a mesma linha travada duas vezes. Sem teste. |
| `bank_statements/regras.py::salvar` (`StatementRule`) | duas edições da mesma regra não se sobrepõem a meio | **Sem teste de disputa** (não medida). Edição manual e rara de regra de extrato; o pior resultado é a segunda gravação vencer a primeira, não saldo. Pendente. |
| `banking/services.py::_assert_account_unique` (advisory, conta única) | dois cadastros iguais criam uma conta só | `test_conta_unica_concorrencia_postgres.py::test_mesmo_nome_ao_mesmo_tempo_cria_uma_conta_so` (detectada) |
| `accounts/login_lockout.py::register_failed_login_attempt` (falha de login) | duas falhas simultâneas não perdem a contagem | `test_travas_postgres.py::test_falha_de_login_espera_a_outra_e_nao_perde_a_contagem` (detectada) |
| `accounts/login_lockout.py::clear_login_failures` (limpar falhas) | zerar a contagem após o login correto | **Sem efeito observável**: o método grava constantes (`failure_count = 0`, `locked_until_ts = None`), então o resultado é o mesmo com ou sem a trava. Sem teste. |
| `transactions/management/commands/reconciliar_status_operacoes.py::handle` | comando de manutenção que recalcula o status das operações | **Coberta por** `lock_accounts(contas)` tomada antes, com todas as contas das operações. Comando manual, fora do fluxo do dia a dia. Sem teste. |
| `core/views.py::permissions_view`, ação `assign_operation_responsible` | dois administradores atribuindo o responsável da mesma operação | **Sem proteção de teste.** Ação administrativa rara; o pior caso é o segundo administrador sobrescrever o primeiro. Pendente. |

## Pendências declaradas

- `core/views.py::permissions_view` (ação `assign_operation_responsible`), `bank_statements/regras.py::salvar` e
  `bank_statements/reconciliation.py::_devolver_linha_da_outra_ponta` não têm teste de disputa nem garantia que as
  cubra, por escolha de custo: são ações de uso raro e o pior resultado é um responsável ou uma regra sobrescrita
  (no último caso, uma linha de extrato que fica conciliada com lançamento já fora do saldo).
- As linhas marcadas "sem efeito observável" ou "coberta por" dependem do raciocínio escrito aqui. Se um escritor
  novo de `AccountMonthClose` ou de `CashFlowEntry` surgir **sem** passar por `lock_accounts`, as travas de dentro
  passam a ser a única proteção e pedem teste.
