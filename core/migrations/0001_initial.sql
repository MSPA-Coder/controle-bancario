-- O que os modelos não descrevem: esquema `leitura` (contrato do FinancasMCP),
-- gatilhos da outbox do patrimônio, a checagem de transferência interna e os
-- dados iniciais. Gerado por pg_dump do banco que a cadeia antiga montava.
-- Não se edita: mudança vai numa migração nova. Ver 0001_initial.py.

CREATE SCHEMA leitura;

COMMENT ON SCHEMA leitura IS 'Contrato de leitura do CB: views versionadas pelas migrações. Quem lê o banco de fora usa só este esquema.';

CREATE FUNCTION leitura.hoje() RETURNS date
    LANGUAGE sql STABLE
    AS $$
    SELECT (now() AT TIME ZONE 'America/Sao_Paulo')::date
$$;

CREATE FUNCTION public.assert_internal_transfer_counterparty() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    changed_entry_id integer := COALESCE(NEW.id, OLD.id);
    new_operation_id integer := CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE NEW.bank_operation_id END;
    old_operation_id integer := CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.bank_operation_id END;
    invalid_entry_id integer;
BEGIN
    WITH candidates AS (
        SELECT entry.*
        FROM cash_flow_entry AS entry
        WHERE entry.operation_type = 'internal_transfer'
          AND (
              entry.id = changed_entry_id
              OR entry.source_entry_id = changed_entry_id
              OR entry.bank_operation_id = new_operation_id
              OR entry.bank_operation_id = old_operation_id
          )
    )
    SELECT entry.id
      INTO invalid_entry_id
      FROM candidates AS entry
      LEFT JOIN bank_operation AS operation ON operation.id = entry.bank_operation_id
     WHERE entry.bank_operation_id IS NULL
        OR operation.operation_type IS DISTINCT FROM 'internal_transfer'
        OR (
            entry.source_entry_id IS NULL
            AND (
                SELECT count(*)
                FROM cash_flow_entry AS destination
                WHERE destination.source_entry_id = entry.id
                  AND destination.bank_operation_id = entry.bank_operation_id
                  AND destination.operation_type = 'internal_transfer'
            ) <> 1
        )
        OR (
            entry.source_entry_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM cash_flow_entry AS origin
                WHERE origin.id = entry.source_entry_id
                  AND origin.bank_operation_id = entry.bank_operation_id
                  AND origin.operation_type = 'internal_transfer'
            )
        )
     LIMIT 1;

    IF invalid_entry_id IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            CONSTRAINT = 'ck_internal_transfer_has_counterparty',
            MESSAGE = 'Transferência interna exige uma única contraparte na mesma operação.',
            DETAIL = format('Lançamento inválido: %s.', invalid_entry_id);
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION public.patrimonio_v4_outbox_append(event_resource text, event_record bigint, event_operation text) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    next_cursor bigint;
BEGIN
INSERT INTO patrimonio_v4_change_counter (id, value)
    VALUES (1, 0)
    ON CONFLICT (id) DO NOTHING;

    UPDATE patrimonio_v4_change_counter
    SET value = value + 1
    WHERE id = 1
    RETURNING value INTO next_cursor;

    INSERT INTO patrimonio_v4_outbox (
        cursor, resource, source_record_id, operation, changed_at
    ) VALUES (
        next_cursor, event_resource, event_record, event_operation, clock_timestamp()
    );
END;
$$;

CREATE FUNCTION public.patrimonio_v4_outbox_emit() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    row_data jsonb;
    event_operation text;
BEGIN
    row_data := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    event_operation := CASE WHEN TG_OP = 'DELETE' THEN 'delete' ELSE 'upsert' END;

    IF TG_ARGV[0] = 'transfer' THEN
        IF TG_OP = 'UPDATE' AND (to_jsonb(OLD) ->> 'operation_type') = 'internal_transfer'
           AND (to_jsonb(NEW) ->> 'operation_type') <> 'internal_transfer' THEN
            row_data := to_jsonb(OLD);
            event_operation := 'delete';
        ELSIF row_data ->> 'operation_type' <> 'internal_transfer' THEN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END IF;
    END IF;

    PERFORM patrimonio_v4_outbox_append(
        TG_ARGV[0],
        (row_data ->> TG_ARGV[1])::bigint,
        event_operation
    );

    IF TG_ARGV[0] = 'cash_entry'
       AND row_data ->> 'operation_type' = 'internal_transfer'
       AND row_data ->> 'bank_operation_id' IS NOT NULL THEN
        PERFORM patrimonio_v4_outbox_append(
            'transfer',
            (row_data ->> 'bank_operation_id')::bigint,
            event_operation
        );
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.patrimonio_v4_outbox_emit_related_accounts() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    row_data jsonb;
    account_row record;
BEGIN
    row_data := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    FOR account_row IN
        SELECT id FROM financial_account
        WHERE (CASE TG_ARGV[0]
            WHEN 'owner_id' THEN owner_id
            WHEN 'institution_id' THEN institution_id
        END) = (row_data ->> 'id')::bigint
    LOOP
        PERFORM patrimonio_v4_outbox_append('account', account_row.id, 'upsert');
    END LOOP;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE VIEW leitura.extrato_importacao AS
 SELECT b.id,
    b.account_id AS conta_id,
    a.account_name AS conta,
    a.account_kind AS tipo_conta,
    b.source_filename AS arquivo,
    b.row_count AS linhas,
    b.status,
    b.created_at AS importada_em,
    b.statement_balance AS saldo_do_extrato,
    b.statement_balance_date AS data_do_saldo_do_extrato
   FROM (public.bank_statement_import b
     JOIN public.financial_account a ON ((a.id = b.account_id)));

COMMENT ON VIEW leitura.extrato_importacao IS 'Importações de extrato ou fatura. Em cartão de crédito, cada importação é uma fatura.';

CREATE VIEW leitura.extrato_linha AS
 SELECT id,
    import_id AS importacao_id,
    account_id AS conta_id,
    matched_entry_id AS lancamento_conciliado_id,
    statement_date AS data,
    description AS descricao,
    amount AS valor,
    status,
    bank_category AS categoria_do_banco,
    card_holder AS portador,
    installment_current AS parcela_atual,
    installment_total AS parcela_total,
    purchase_date AS data_da_compra
   FROM public.bank_statement_line l;

COMMENT ON VIEW leitura.extrato_linha IS 'Linhas importadas de extratos e faturas. valor tem sinal: negativo é saída. lancamento_conciliado_id liga ao lançamento.';

CREATE VIEW leitura.fechamento_mes AS
 SELECT m.id,
    m.account_id AS conta_id,
    a.account_name AS conta,
    m.year AS ano,
    m.month AS mes,
    m.closing_balance AS saldo_final,
    m.closed_at AS fechado_em,
    m.reopened_at AS reaberto_em,
    m.active AS ativo
   FROM (public.account_month_close m
     JOIN public.financial_account a ON ((a.id = m.account_id)));

COMMENT ON VIEW leitura.fechamento_mes IS 'Meses fechados por conta. Um mês fechado (ativo) não muda sem reabertura.';

CREATE VIEW leitura.lancamento AS
 SELECT e.id,
    e.account_id AS conta_id,
    a.account_name AS conta,
    ow.owner_name AS titular,
    a.currency AS moeda,
    e.category_id AS categoria_id,
    c.category_name AS categoria,
    c.kind AS natureza,
    g.group_name AS grupo_da_categoria,
        CASE
            WHEN ((e.status)::text = 'realizado'::text) THEN e.realized_date
            ELSE e.due_date
        END AS data,
        CASE
            WHEN ((e.status)::text = 'realizado'::text) THEN 'realizado'::text
            WHEN (e.due_date < leitura.hoje()) THEN 'vencidos'::text
            ELSE 'a_vencer'::text
        END AS status,
    e.status AS status_gravado,
    e.entry_type AS tipo,
        CASE
            WHEN ((e.entry_type)::text = 'receita'::text) THEN 1
            ELSE '-1'::integer
        END AS sinal,
        CASE
            WHEN ((e.status)::text = 'realizado'::text) THEN COALESCE(e.realized_amount, e.entry_amount)
            ELSE e.entry_amount
        END AS valor,
    e.entry_amount AS valor_previsto,
    e.realized_amount AS valor_realizado,
    e.description AS descricao,
        CASE
            WHEN (e.installments > 1) THEN ((e.current_installment || '/'::text) || e.installments)
            ELSE NULL::text
        END AS parcela,
    e.is_recurring AS recorrente,
    e.operation_type AS tipo_operacao,
    ((COALESCE(o.operation_key, ''::character varying))::text ~ '^cartao-(estimativa|pagamento):'::text) AS estimativa_de_fatura,
    ((COALESCE(o.operation_key, ''::character varying))::text ~~ 'cartao-estimativa:%'::text) AS gasto_estimado_do_cartao,
    e.due_date AS vencimento,
    e.realized_date AS realizado_em,
    e.bank_operation_id AS operacao_id,
    e.source_entry_id AS lancamento_de_origem_id
   FROM (((((public.cash_flow_entry e
     JOIN public.financial_account a ON ((a.id = e.account_id)))
     JOIN public.account_owner ow ON ((ow.id = a.owner_id)))
     JOIN public.cash_flow_category c ON ((c.id = e.category_id)))
     LEFT JOIN public.cash_flow_category_group g ON ((g.id = c.group_id)))
     LEFT JOIN public.bank_operation o ON ((o.id = e.bank_operation_id)));

COMMENT ON VIEW leitura.lancamento IS 'Lançamentos com status efetivo, data e valor que valem e sinal. Gasto/renda: natureza = gerencial. Transferência entre contas próprias não é gasto. Não some moedas diferentes.';

CREATE VIEW leitura.lancamento_etiqueta AS
 SELECT et.entry_id AS lancamento_id,
    t.tag_name AS etiqueta
   FROM (public.cash_flow_entry_tag et
     JOIN public.management_tag t ON ((t.id = et.tag_id)));

CREATE VIEW leitura.lancamento_projeto AS
 SELECT ep.entry_id AS lancamento_id,
    p.project_name AS projeto
   FROM (public.cash_flow_entry_project ep
     JOIN public.management_project p ON ((p.id = ep.project_id)));

CREATE VIEW leitura.operacao AS
 SELECT id,
    operation_key AS chave,
    operation_type AS tipo,
    description AS descricao,
    status,
    installment_total AS total_de_parcelas,
    recurrence_ended_on AS recorrencia_encerrada_em,
    created_at AS criada_em
   FROM public.bank_operation o;

COMMENT ON VIEW leitura.operacao IS 'Operações que agrupam lançamentos: parcelas, recorrências e transferências.';

CREATE VIEW leitura.orcamento_mensal AS
 SELECT b.id,
    ow.owner_name AS titular,
    b.category_id AS categoria_id,
    c.category_name AS categoria,
    b.year AS ano,
    b.month AS mes,
    b.planned_amount AS planejado,
    b.active AS ativo
   FROM ((public.monthly_budget b
     JOIN public.cash_flow_category c ON ((c.id = b.category_id)))
     JOIN public.account_owner ow ON ((ow.id = b.owner_id)));

COMMENT ON VIEW leitura.orcamento_mensal IS 'Orçamento (meta) por categoria, ano e mês, em moeda base (BRL). Só os registros com ativo = true valem.';

CREATE VIEW leitura.saldo_conferido AS
 SELECT s.id,
    s.account_id AS conta_id,
    a.account_name AS conta,
    s.data,
    s.valor,
    s.origem,
    s.lancamento_id
   FROM (public.fechamento_saldo_conferido s
     JOIN public.financial_account a ON ((a.id = s.account_id)));

COMMENT ON VIEW leitura.saldo_conferido IS 'Saldos informados por conta, dia e origem (manual, print ou myprofit). Mais de uma origem no mesmo dia é conferência; lancamento_id é o ajuste lançado, quando houve.';

CREATE VIEW leitura.categoria AS
 SELECT c.id,
    c.category_name AS categoria,
    c.kind AS natureza,
    g.group_name AS grupo,
    count(e.id) AS lancamentos,
    min(COALESCE(e.realized_date, e.due_date)) AS primeiro,
    max(COALESCE(e.realized_date, e.due_date)) AS ultimo
   FROM ((public.cash_flow_category c
     LEFT JOIN public.cash_flow_category_group g ON ((g.id = c.group_id)))
     LEFT JOIN public.cash_flow_entry e ON ((e.category_id = c.id)))
  GROUP BY c.id, g.group_name;

COMMENT ON VIEW leitura.categoria IS 'Categorias. natureza: gerencial (receita/despesa de verdade), transferencia (entre contas próprias), movimentacao (aporte/resgate) ou valorizacao (variação de mercado do que está aplicado: muda o saldo, não é receita nem despesa).';

CREATE VIEW leitura.conta AS
 SELECT a.id,
    a.account_name AS conta,
    ow.owner_name AS titular,
    i.institution_name AS instituicao,
    i.institution_type AS tipo_instituicao,
    a.currency AS moeda,
    a.account_kind AS tipo,
    a.purpose AS finalidade,
    a.card_closing_day AS dia_fechamento_cartao,
    a.card_due_day AS dia_vencimento_cartao,
    a.initial_balance AS saldo_inicial,
    a.initial_balance_date AS data_saldo_inicial,
    (a.initial_balance + COALESCE(sum(((l.sinal)::numeric * l.valor)) FILTER (WHERE ((l.status = 'realizado'::text) AND (l.realizado_em <= leitura.hoje()))), (0)::numeric)) AS saldo_realizado_hoje,
    COALESCE(sum(((l.sinal)::numeric * l.valor_previsto)) FILTER (WHERE ((l.status <> 'realizado'::text) AND (l.vencimento < leitura.hoje()))), (0)::numeric) AS vencido_em_aberto,
    (a.initial_balance + COALESCE(sum(((l.sinal)::numeric * l.valor)), (0)::numeric)) AS saldo_com_todo_previsto,
    max(l.vencimento) FILTER (WHERE (l.status <> 'realizado'::text)) AS ultimo_vencimento_previsto
   FROM (((public.financial_account a
     JOIN public.account_owner ow ON ((ow.id = a.owner_id)))
     JOIN public.financial_institution i ON ((i.id = a.institution_id)))
     LEFT JOIN leitura.lancamento l ON ((l.conta_id = a.id)))
  GROUP BY a.id, ow.owner_name, i.institution_name, i.institution_type;

COMMENT ON VIEW leitura.conta IS 'Contas com saldo realizado hoje, vencido em aberto e saldo com todo o previsto. Tipos: conta, cartao_credito, aplicacao.';


SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE CONSTRAINT TRIGGER ck_internal_transfer_has_counterparty AFTER INSERT OR DELETE OR UPDATE ON public.cash_flow_entry DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.assert_internal_transfer_counterparty();

CREATE TRIGGER patrimonio_v4_outbox_account_owner AFTER INSERT OR DELETE OR UPDATE ON public.account_owner FOR EACH ROW EXECUTE FUNCTION public.patrimonio_v4_outbox_emit_related_accounts('owner_id');

CREATE TRIGGER patrimonio_v4_outbox_bank_operation AFTER INSERT OR DELETE OR UPDATE ON public.bank_operation FOR EACH ROW EXECUTE FUNCTION public.patrimonio_v4_outbox_emit('transfer', 'id');

CREATE TRIGGER patrimonio_v4_outbox_cash_flow_category AFTER INSERT OR DELETE OR UPDATE ON public.cash_flow_category FOR EACH ROW EXECUTE FUNCTION public.patrimonio_v4_outbox_emit('category', 'id');

CREATE TRIGGER patrimonio_v4_outbox_cash_flow_entry AFTER INSERT OR DELETE OR UPDATE ON public.cash_flow_entry FOR EACH ROW EXECUTE FUNCTION public.patrimonio_v4_outbox_emit('cash_entry', 'id');

CREATE TRIGGER patrimonio_v4_outbox_cash_flow_entry_investment AFTER INSERT OR UPDATE ON public.cash_flow_entry_investment FOR EACH ROW EXECUTE FUNCTION public.patrimonio_v4_outbox_emit('cash_entry', 'entry_id');

CREATE TRIGGER patrimonio_v4_outbox_financial_account AFTER INSERT OR DELETE OR UPDATE ON public.financial_account FOR EACH ROW EXECUTE FUNCTION public.patrimonio_v4_outbox_emit('account', 'id');

CREATE TRIGGER patrimonio_v4_outbox_financial_institution AFTER INSERT OR DELETE OR UPDATE ON public.financial_institution FOR EACH ROW EXECUTE FUNCTION public.patrimonio_v4_outbox_emit_related_accounts('institution_id');

-- Dados iniciais. A categoria entra depois dos gatilhos, como na cadeia
-- antiga: o gatilho dela grava o primeiro evento da outbox.

INSERT INTO public.patrimonio_v4_change_counter (id, value) VALUES (1, 0);

INSERT INTO public.cash_flow_category (category_name, created_at, updated_at, kind, group_id) VALUES ('Variação de mercado', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'valorizacao', NULL);

INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (1, 'dashboard.view', 'Visualizar Dashboard', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (2, 'transactions.view', 'Visualizar lançamentos', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (3, 'transactions.create', 'Incluir lançamentos', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (4, 'transactions.update', 'Editar lançamentos', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (5, 'transactions.realize', 'Marcar lançamentos como realizados', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (7, 'transactions.delete', 'Excluir lançamentos', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (11, 'projections.view', 'Visualizar Projeções', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (12, 'reports.upcoming_movements.view', 'Visualizar Próximos movimentos', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (13, 'reports.account_position.view', 'Visualizar Posição por conta', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (14, 'management.view', 'Visualizar Gestão', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (15, 'management.manage', 'Gerenciar Gestão (tags, projetos, orçamento)', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (16, 'tables.view', 'Visualizar Cadastros', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (17, 'tables.owners.manage', 'Gerenciar titulares', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (18, 'tables.institutions.manage', 'Gerenciar instituições financeiras', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (19, 'tables.accounts.manage', 'Gerenciar contas', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (20, 'tables.categories.manage', 'Gerenciar categorias', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (22, 'banking.import', 'Importar extratos bancários', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (23, 'banking.reconcile', 'Conciliar extratos bancários', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (24, 'banking.attachments.manage', 'Gerenciar comprovantes de lançamentos', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (25, 'operations.view', 'Visualizar Operações (lançamentos agrupados)', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (26, 'settings.view', 'Visualizar Configurações', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (27, 'settings.theme.update', 'Atualizar perfil e visibilidade de contas', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (28, 'settings.audit.view', 'Visualizar trilha de auditoria', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (29, 'settings.monthly_close.manage', 'Fechar/reabrir mês pela tela de Configurações', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (30, 'settings.database.optimize', 'Executar diagnóstico e otimização do banco de dados', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (31, 'settings.projection.manage', 'Gerenciar projeção de lançamentos recorrentes', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (32, 'settings.password_policy.manage', 'Gerenciar política de senha e bloqueio de login', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (36, 'tables.users.manage', 'Gerenciar usuários', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (37, 'permissions.manage', 'Gerenciar permissões de usuários', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (21, 'banking.view', 'Visualizar módulo Instituições', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (38, 'reports.annual_planning.view', 'Visualizar Planejamento anual', CURRENT_TIMESTAMP);
INSERT INTO public.app_permission (id, permission_key, description, created_at) VALUES (39, 'banking.reclassify', 'Reclassificar categorias de lançamentos em lote', CURRENT_TIMESTAMP);
SELECT pg_catalog.setval('public.app_permission_id_seq', 39, true);
