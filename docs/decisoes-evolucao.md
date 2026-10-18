# Evolução incremental — decisões de 18/10/2026

Manter Django, PostgreSQL e HTML/HTMX. Parsing reutilizado, conferência de saldos
agrupada, contratos tipados e testes de navegador resolvem custos concretos.
Não criar Repository genérico, microserviços, cache de saldos ou reescrita.

## Projeção mensal: manter o gatilho atual

A decisão continua no middleware de requisições autenticadas, com guarda mensal
persistida e advisory lock/idempotência na projeção. Não roda no health/login.
Depois de resolvido o mês, o processo não consulta o banco para essa decisão.

Medição com PostgreSQL real e dados sintéticos vazios: primeira execução,
**16 consultas**, projeção **92,4 ms**; **100 requisições seguintes: zero
consultas adicionais** dessa funcionalidade. O teste mede a rotina completa,
sem substituir services, consultas ou locks. O valor de tempo é uma amostra
de desenvolvimento, não representa volume real nem p95. A duração de cada
projeção automática passa a ser registrada com relógio monotônico, junto da
contagem já existente, sem valores financeiros ou identificação de titulares.

Decisão: não adicionar timer, scheduler ou worker por desempenho. O gatilho
atual só executa após acesso autenticado a partir do dia configurado e não
garante execução naquela data sem acesso. Essa característica fica explícita.
Se passar a ser necessário projetar antes do primeiro acesso ou num horário
garantido, substituir o gatilho por comando/timer preservando as mesmas
transações, locks, auditoria, idempotência e possibilidade de execução manual.
Se o tempo com volume representativo degradar a experiência, usar as métricas
para definir uma meta antes de mover o trabalho.

## Comprovantes e outras abstrações

O mantenedor informou que nunca usou comprovantes; a consulta local confirmou
zero anexos. Não implementar backup de mídia nesta rodada. O backup de banco
continua sem cobrir media_volume, como já documentado em operations.md.
Reavaliar a cobertura antes de adotar comprovantes importantes.

Nenhum banco real foi migrado ou alterado para estas medições. Não se unificam
os bancos/modelos de CB e CRV; os contratos publicados continuam a integração.
