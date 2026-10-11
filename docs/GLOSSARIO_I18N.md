# Glossário de textos da interface (pt-BR e en)

Aprovado em 11/10/2026. Vale só para o que o usuário lê na tela. Valores gravados
(status, tipos, códigos) e dados digitados pelo usuário não mudam com o idioma.

O português é a língua-fonte: o texto em português é o `msgid`. Mudar a redação
de um texto em português muda o `msgid` e exige reabrir a tradução.

## Termos

| Conceito | Português (padrão) | Inglês | Evitar |
|---|---|---|---|
| Linha do fluxo de caixa (`CashFlowEntry`) | lançamento | entry | movimento, transação |
| Conjunto parcelado ou recorrente | operação | operation | — |
| Status `a_vencer` | A vencer | Upcoming | A Vencer |
| Status `vencidos` | Vencido (singular), Vencidos (filtro) | Overdue | atrasado |
| Status `realizado` | Realizado | Settled | — |
| Transferência entre contas próprias | transferência interna | internal transfer | Transf. Int., Mov. Internas |
| Quantidade | quantidade | quantity | Qtde. |
| Titular | titular | account holder | — |
| Instituição | instituição | institution | — |
| Fechamento mensal | fechamento mensal | monthly close | — |
| Conciliação | conciliação | reconciliation | — |
| Extrato | extrato | statement | — |
| Fatura | fatura | card statement | — |

## Padrões de redação (português)

- Títulos e rótulos em maiúscula só na primeira letra: "Situação das contas".
- Título da página: `Área • Tela` (ponto médio, nunca hífen). Sem prefixo quando a tela é a própria área.
  Marca: "Controle Bancário".
- Reticências com o caractere `…`; multiplicação com `×`; travessão `—` em frases.
- Aspas curvas “ ” em texto corrido.
- Toda mensagem completa termina com ponto; rótulos e botões não.
- Mensagens de sucesso sem "com sucesso" quando o verbo já diz o resultado ("Usuário excluído.").
- Recusa de permissão: "Acesso negado: você não tem permissão para <ação>."
- Tom: segunda pessoa do singular ("você"); "deve/precisa", não "tem de".
- Plural: `ngettext`, nunca "(s)".

## Padrões de redação (inglês)

- Sentence case nos rótulos e títulos ("Account holder").
- Botões com verbo no imperativo ("Save", "Cancel"); mensagens no passado ("User deleted.").
- Recusa: "Access denied: you do not have permission to <action>."
- Moeda e símbolo seguem a conta, não o idioma.

## Decisões de aplicação (F1)

- Título de página: `Área • Tela`, com a área sendo o **grupo de topo do menu** (Movimentação, Relatórios,
  Cadastros, Configurações, Segurança). "Importação" é subgrupo de Movimentação, não área.
- Nomes de tela do menu em sentence case ("Saldo aplicações", "Situação das contas", "Fechamento mensal").
- "Próximos movimentos" e "Movimento líquido" ficam: são nome de tela e de indicador, e "movimento" ali
  inclui transferências, não só lançamentos.
- `×` também vale para "cruzamento" em títulos de matriz ("Usuário × titular").
- Plural: `ngettext`, feito na marcação para tradução; não sobra "(s)" onde há contagem.

## Decisões de aplicação (inglês, F4)

Termos que os tradutores resolveram de modos diferentes e foram fixados na revisão:

| Português | Inglês |
|---|---|
| Movimentação (área do menu) | Activity |
| valor monetário | Amount |
| conta de movimento (da aplicação) | cash account |
| Gerencial, Controle gerencial, Gestão | Management |
| geração (de caixa) | cash generation |
| Cadastros | Records |
| realização | settlement |
| fatura | card statement (extrato = statement) |
| Recorte (filtro global) | filter |

Mensagens de resultado ficam no passado ("Recurrence projection ran."), sem jargão
("idempotente" vira "running it again does not duplicate entries").
