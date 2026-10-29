# Travas de banco

Inventário das travas (`select_for_update`, `pg_advisory_xact_lock`) que protegem saldo, lançamento, fatura,
fechamento e acesso, e de **qual teste ou qual outra garantia** responde por cada uma. A regra está em
`docs/TESTES.md` (T7 e T11): trava nova nasce com teste de disputa que falha quando ela é retirada, ou com uma
linha aqui dizendo qual garantia a cobre.

Medido em 29/10/2026 retirando cada trava numa cópia do commit e rodando os arquivos de disputa 3 a 5 vezes
(receita em T11). "Detectada" quer dizer que o teste falhou em todas as repetições sem a trava.

Os testes de `tests/test_travas_postgres.py` seguem um padrão: uma "primeira operação" muda o estado e fica aberta
(sem confirmar); a operação testada precisa esperar por ela e então enxergar o estado confirmado. A primeira só
libera quando a segunda já esperou ou terminou, então o resultado não depende de sorte de tempo.

## A trava da conta esconde as de dentro

`transactions/services.py::_lock_accounts` (linha 132) é o recurso de coordenação entre lançamento e fechamento
mensal: todo serviço que muda lançamento ou cria fechamento a toma **antes** de olhar o período. As travas de
operação e de lançamento que vêm depois (`_lock_entry_graph`) ficam atrás dela para quem passa por ela, e por isso
retirar só uma das de dentro não derruba os testes de concorrência da trava de conta. Elas valem para o escritor
que **não** toma a trava da conta (conciliação, importação); os testes de `test_travas_postgres.py` provam isso
com uma transação "de fora" segurando o lançamento.

## Tabela

| Trava | Protege | Cobertura |
|---|---|---|
| `transactions/services.py:132` `_lock_accounts` | lançamento × fechamento mensal | `test_concorrencia_financeira_postgres.py::test_fechamentos_simultaneos_criam_um_unico_registro` (detectada) |
| `transactions/services.py:193` e `:200` `_lock_entry_graph` (lançamentos) | realizar, desfazer, editar e excluir sobre o estado já confirmado | `test_travas_postgres.py::test_realizar_parcela_espera_os_lancamentos_da_operacao_e_recusa_a_ja_realizada` (193) e `test_realizar_espera_o_lancamento_e_recusa_o_que_outra_transacao_realizou` (200) (detectadas) |
| `transactions/services.py:186` `_lock_entry_graph` (operação) | ordem de aquisição conta → operação → lançamentos | **Sem efeito observável isolado**: o lançamento é travado em seguida (193/200), e a operação só é atualizada no fim, onde o `UPDATE` já espera a linha. A trava existe para a ordem global (evitar impasse). Sem teste. |
| `transactions/services.py:398` e `:453` `close_month`/`reopen_month` (`AccountMonthClose`) | fechar e reabrir o mesmo mês | **Coberta por** `_lock_accounts` (132), tomada antes na mesma função. Esses dois métodos são os únicos que gravam `AccountMonthClose`. Retiradas, nenhum teste falha. Sem teste próprio. |
| `transactions/recurring_projection.py:370` e `:508` (advisory 81288431) | extensão e recolhimento da projeção não se atravessam | `test_travas_postgres.py::test_projecao_recorrente_espera_a_outra_rotina_terminar[extensao/recolhimento]` (detectadas) |
| `transactions/recurring_projection.py:522` (lançamentos candidatos ao recolhimento) | não apagar a ocorrência que outra transação acabou de realizar | `test_travas_postgres.py::test_recolhimento_espera_o_lancamento_e_nao_apaga_o_que_outra_transacao_realizou` (detectada) |
| `transactions/recurring_projection.py:521` (operações) | ordem de aquisição | **Sem efeito observável isolado**, como a 186: o recolhimento trava as contas antes e os lançamentos depois. Sem teste. |
| `bank_statements/reconciliation.py:293` (linhas do extrato) | linha ignorada por outra transação não vira lançamento | `test_travas_postgres.py::test_linha_ignorada_por_outra_transacao_nao_vira_lancamento` (detectada) |
| `bank_statements/reconciliation.py:326` (lançamento a conciliar) | duas linhas não realizam o mesmo lançamento | `test_concorrencia_financeira_postgres.py::test_duas_linhas_concorrentes_nao_realizam_o_mesmo_lancamento_duas_vezes` (detectada) |
| `bank_statements/reconciliation.py:674` (desfazer importação) | desfazer espera a conciliação em andamento | `test_travas_postgres.py::test_desfazer_importacao_espera_a_conciliacao_em_andamento_e_a_desfaz` (detectada) |
| `bank_statements/extrato.py:518` `_linha_travada` | aplicar plano sobre linha ainda disponível | `test_travas_postgres.py::test_linha_travada_do_extrato_espera_e_recusa_a_linha_ignorada_por_outra_transacao` (detectada) |
| `bank_statements/extrato.py:580` (lançamento que vira transferência) | recusar se o lançamento mudou desde a prévia | `test_travas_postgres.py::test_transferir_com_lancamento_espera_o_lancamento_e_recusa_o_que_outra_transacao_mudou` (detectada) |
| `bank_statements/services.py:137` (advisory) | reimportações simultâneas contam duplicatas sem erro | `test_concorrencia_financeira_postgres.py::test_reimportacoes_simultaneas_contam_duplicatas_sem_erro` (detectada) |
| `bank_statements/fatura.py:583` (linhas novas do lote) | fatura processada ao mesmo tempo grava uma vez | `test_fatura_concorrencia_postgres.py::test_fatura_processada_ao_mesmo_tempo_grava_uma_vez` (detectada) |
| `bank_statements/fatura_projetada.py:335` (conta do cartão) | ler a conta do cartão travada | **Coberta por** `_lock_accounts(ids_contas)`, chamado duas linhas acima na mesma transação com todas as contas. É a mesma linha travada duas vezes. Sem teste. |
| `banking/services.py:296` (advisory, conta única) | dois cadastros iguais criam uma conta só | `test_conta_unica_concorrencia_postgres.py::test_mesmo_nome_ao_mesmo_tempo_cria_uma_conta_so` (detectada) |
| `accounts/login_lockout.py:71` (falha de login) | duas falhas simultâneas não perdem a contagem | `test_travas_postgres.py::test_falha_de_login_espera_a_outra_e_nao_perde_a_contagem` (detectada) |
| `accounts/login_lockout.py:90` (limpar falhas) | zerar a contagem após o login correto | **Sem efeito observável**: o método grava constantes (`failure_count = 0`, `locked_until_ts = None`), então o resultado é o mesmo com ou sem a trava. Sem teste. |
| `transactions/management/commands/reconciliar_status_operacoes.py:34` | comando de manutenção que recalcula o status das operações | **Coberta por** `_lock_accounts(contas)` tomada antes, com todas as contas das operações. Comando manual, fora do fluxo do dia a dia. Sem teste. |
| `core/views.py:328` (atribuir responsável da recorrência) | dois administradores atribuindo o responsável da mesma operação | **Sem proteção de teste.** Ação administrativa rara; o pior caso é o segundo administrador sobrescrever o primeiro. Pendente. |

## Pendências declaradas

- `core/views.py:328` não tem teste de disputa nem garantia que a cubra, por escolha de custo: a tela é de uso
  administrativo raro e o pior resultado é um responsável sobrescrito, não saldo.
- As linhas marcadas "sem efeito observável" ou "coberta por" dependem do raciocínio escrito aqui. Se um escritor
  novo de `AccountMonthClose` ou de `CashFlowEntry` surgir **sem** passar por `_lock_accounts`, as travas de dentro
  passam a ser a única proteção e pedem teste.
