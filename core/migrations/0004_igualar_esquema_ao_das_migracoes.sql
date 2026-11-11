-- Leva um banco criado antes da conversão para Django ao esquema que as
-- migrações montam até a `core/0003`. Motivo, prova e o que fica de fora estão
-- em `0004_igualar_esquema_ao_das_migracoes.py`.
--
-- As listas `alvo_*` saíram do catálogo de um banco montado pelas migrações
-- (`pg_get_indexdef`, `pg_get_constraintdef`), só das tabelas do projeto. Não
-- se edita: mudança de esquema vai numa migração nova.

SET LOCAL lock_timeout = '5s';
-- O PostgreSQL recusa ALTER TABLE com evento de chave adiada pendente.
SET CONSTRAINTS ALL IMMEDIATE;

CREATE TEMP TABLE alvo_tipo (tabela text, coluna text, tipo text) ON COMMIT DROP;
INSERT INTO alvo_tipo VALUES
    ('account_month_close', 'account_id', 'bigint'),
    ('account_month_close', 'closed_by_user_id', 'bigint'),
    ('account_month_close', 'id', 'bigint'),
    ('account_month_close', 'reopened_by_user_id', 'bigint'),
    ('account_owner', 'id', 'bigint'),
    ('app_permission', 'description', 'text'),
    ('app_permission', 'id', 'bigint'),
    ('app_setting', 'id', 'bigint'),
    ('app_user', 'id', 'bigint'),
    ('app_user', 'password', 'character varying(128)'),
    ('audit_log', 'id', 'bigint'),
    ('audit_log', 'user_id', 'bigint'),
    ('bank_operation', 'id', 'bigint'),
    ('bank_statement_import', 'account_id', 'bigint'),
    ('bank_statement_import', 'id', 'bigint'),
    ('bank_statement_line', 'account_id', 'bigint'),
    ('bank_statement_line', 'id', 'bigint'),
    ('bank_statement_line', 'import_id', 'bigint'),
    ('bank_statement_line', 'matched_entry_id', 'bigint'),
    ('cash_flow_category', 'id', 'bigint'),
    ('cash_flow_entry', 'account_id', 'bigint'),
    ('cash_flow_entry', 'bank_operation_id', 'bigint'),
    ('cash_flow_entry', 'category_id', 'bigint'),
    ('cash_flow_entry', 'id', 'bigint'),
    ('cash_flow_entry', 'source_entry_id', 'bigint'),
    ('cash_flow_entry_project', 'entry_id', 'bigint'),
    ('cash_flow_entry_project', 'id', 'bigint'),
    ('cash_flow_entry_project', 'project_id', 'bigint'),
    ('cash_flow_entry_tag', 'entry_id', 'bigint'),
    ('cash_flow_entry_tag', 'id', 'bigint'),
    ('cash_flow_entry_tag', 'tag_id', 'bigint'),
    ('entry_attachment', 'entry_id', 'bigint'),
    ('entry_attachment', 'id', 'bigint'),
    ('financial_account', 'id', 'bigint'),
    ('financial_account', 'institution_id', 'bigint'),
    ('financial_account', 'owner_id', 'bigint'),
    ('financial_institution', 'id', 'bigint'),
    ('login_lockout', 'id', 'bigint'),
    ('management_project', 'id', 'bigint'),
    ('management_tag', 'id', 'bigint'),
    ('monthly_budget', 'category_id', 'bigint'),
    ('monthly_budget', 'id', 'bigint'),
    ('monthly_budget', 'owner_id', 'bigint'),
    ('user_owner_access', 'id', 'bigint'),
    ('user_owner_access', 'owner_id', 'bigint'),
    ('user_owner_access', 'user_id', 'bigint'),
    ('user_permission', 'id', 'bigint'),
    ('user_permission', 'permission_id', 'bigint'),
    ('user_permission', 'user_id', 'bigint');

CREATE TEMP TABLE alvo_indice (tabela text, nome text, unico boolean, definicao text) ON COMMIT DROP;
INSERT INTO alvo_indice VALUES
    ('account_month_close', 'account_mon_account_d74e4e_idx', 'f', 'USING btree (account_id, year, month)'),
    ('account_month_close', 'account_month_close_account_id_37b83921', 'f', 'USING btree (account_id)'),
    ('account_month_close', 'account_month_close_closed_by_user_id_0f852e3f', 'f', 'USING btree (closed_by_user_id)'),
    ('account_month_close', 'account_month_close_reopened_by_user_id_0c04a9a4', 'f', 'USING btree (reopened_by_user_id)'),
    ('account_owner', 'uq_account_owner_name_ci', 't', 'USING btree (lower((owner_name)::text))'),
    ('app_permission', 'app_permission_permission_key_a75e2f11_like', 'f', 'USING btree (permission_key varchar_pattern_ops)'),
    ('app_setting', 'app_setting_setting_key_0b8eafda_like', 'f', 'USING btree (setting_key varchar_pattern_ops)'),
    ('app_user', 'app_user_user_ty_35760d_idx', 'f', 'USING btree (user_type)'),
    ('app_user', 'app_user_username_9d6296ff_like', 'f', 'USING btree (username varchar_pattern_ops)'),
    ('app_user_groups', 'app_user_groups_appuser_id_7bb08f1f', 'f', 'USING btree (appuser_id)'),
    ('app_user_groups', 'app_user_groups_group_id_e774d92c', 'f', 'USING btree (group_id)'),
    ('app_user_user_permissions', 'app_user_user_permissions_appuser_id_3404e502', 'f', 'USING btree (appuser_id)'),
    ('app_user_user_permissions', 'app_user_user_permissions_permission_id_4ef8e133', 'f', 'USING btree (permission_id)'),
    ('audit_log', 'audit_log_user_id_a1b3392d', 'f', 'USING btree (user_id)'),
    ('audit_log', 'ix_audit_log_created_at', 'f', 'USING btree (created_at)'),
    ('audit_log', 'ix_audit_log_entity', 'f', 'USING btree (entity_name, entity_id)'),
    ('audit_log', 'ix_audit_log_user', 'f', 'USING btree (user_id)'),
    ('bank_operation', 'bank_operat_legacy__079fe1_idx', 'f', 'USING btree (legacy_operation_id)'),
    ('bank_operation', 'bank_operat_operati_aeaa75_idx', 'f', 'USING btree (operation_type, status)'),
    ('bank_operation', 'bank_operation_operation_key_9c34a03a_like', 'f', 'USING btree (operation_key varchar_pattern_ops)'),
    ('bank_operation', 'bank_operation_responsible_user_id_30ce0dd6', 'f', 'USING btree (responsible_user_id)'),
    ('bank_statement_import', 'bank_statem_account_9e538c_idx', 'f', 'USING btree (account_id)'),
    ('bank_statement_import', 'bank_statem_created_d3578a_idx', 'f', 'USING btree (created_at)'),
    ('bank_statement_import', 'bank_statement_import_account_id_48fbe5e7', 'f', 'USING btree (account_id)'),
    ('bank_statement_line', 'bank_statem_account_a5fa76_idx', 'f', 'USING btree (account_id, statement_date)'),
    ('bank_statement_line', 'bank_statem_import__79616d_idx', 'f', 'USING btree (import_id)'),
    ('bank_statement_line', 'bank_statem_matched_eaa62f_idx', 'f', 'USING btree (matched_entry_id)'),
    ('bank_statement_line', 'bank_statem_status_c3a475_idx', 'f', 'USING btree (status)'),
    ('bank_statement_line', 'bank_statement_line_account_id_a32c0345', 'f', 'USING btree (account_id)'),
    ('bank_statement_line', 'bank_statement_line_import_id_63ac0e8b', 'f', 'USING btree (import_id)'),
    ('bank_statement_line', 'bank_statement_line_matched_entry_id_e6ad3316', 'f', 'USING btree (matched_entry_id)'),
    ('bank_statement_line', 'uq_bank_statement_line_active_matched_entry', 't', 'USING btree (matched_entry_id) WHERE ((matched_entry_id IS NOT NULL) AND ((status)::text = ''conciliado''::text))'),
    ('cash_flow_category', 'cash_flow_c_kind_51270d_idx', 'f', 'USING btree (kind)'),
    ('cash_flow_category', 'cash_flow_category_category_name_24ebfcae_like', 'f', 'USING btree (category_name varchar_pattern_ops)'),
    ('cash_flow_category', 'cash_flow_category_group_id_f7d18410', 'f', 'USING btree (group_id)'),
    ('cash_flow_category_group', 'cash_flow_category_group_group_name_c8d4f53a_like', 'f', 'USING btree (group_name varchar_pattern_ops)'),
    ('cash_flow_entry', 'cash_flow_e_account_a69989_idx', 'f', 'USING btree (account_id, due_date)'),
    ('cash_flow_entry', 'cash_flow_e_account_d0e6a6_idx', 'f', 'USING btree (account_id, realized_date)'),
    ('cash_flow_entry', 'cash_flow_e_bank_op_65cc45_idx', 'f', 'USING btree (bank_operation_id)'),
    ('cash_flow_entry', 'cash_flow_e_categor_4bd7a1_idx', 'f', 'USING btree (category_id, due_date)'),
    ('cash_flow_entry', 'cash_flow_e_entry_t_35524d_idx', 'f', 'USING btree (entry_type, due_date)'),
    ('cash_flow_entry', 'cash_flow_e_operati_60d3fd_idx', 'f', 'USING btree (operation_type)'),
    ('cash_flow_entry', 'cash_flow_e_source__2bb4eb_idx', 'f', 'USING btree (source_entry_id)'),
    ('cash_flow_entry', 'cash_flow_e_status_b1ed23_idx', 'f', 'USING btree (status, due_date)'),
    ('cash_flow_entry', 'cash_flow_entry_account_id_3c7d31c8', 'f', 'USING btree (account_id)'),
    ('cash_flow_entry', 'cash_flow_entry_bank_operation_id_33cd3b8f', 'f', 'USING btree (bank_operation_id)'),
    ('cash_flow_entry', 'cash_flow_entry_category_id_923c5e63', 'f', 'USING btree (category_id)'),
    ('cash_flow_entry', 'cash_flow_entry_operation_type_cb8fe618', 'f', 'USING btree (operation_type)'),
    ('cash_flow_entry', 'cash_flow_entry_operation_type_cb8fe618_like', 'f', 'USING btree (operation_type varchar_pattern_ops)'),
    ('cash_flow_entry', 'cash_flow_entry_source_entry_id_0b244368', 'f', 'USING btree (source_entry_id)'),
    ('cash_flow_entry_project', 'cash_flow_e_entry_i_9d12cd_idx', 'f', 'USING btree (entry_id)'),
    ('cash_flow_entry_project', 'cash_flow_e_project_ce7689_idx', 'f', 'USING btree (project_id)'),
    ('cash_flow_entry_project', 'cash_flow_entry_project_entry_id_5813a93f', 'f', 'USING btree (entry_id)'),
    ('cash_flow_entry_project', 'cash_flow_entry_project_project_id_32d8933d', 'f', 'USING btree (project_id)'),
    ('cash_flow_entry_submission', 'cash_flow_entry_submission_created_at_01cb4b43', 'f', 'USING btree (created_at)'),
    ('cash_flow_entry_submission', 'cash_flow_entry_submission_token_e9760682_like', 'f', 'USING btree (token varchar_pattern_ops)'),
    ('cash_flow_entry_tag', 'cash_flow_e_entry_i_6649ec_idx', 'f', 'USING btree (entry_id)'),
    ('cash_flow_entry_tag', 'cash_flow_e_tag_id_ef71b8_idx', 'f', 'USING btree (tag_id)'),
    ('cash_flow_entry_tag', 'cash_flow_entry_tag_entry_id_f3d4cb61', 'f', 'USING btree (entry_id)'),
    ('cash_flow_entry_tag', 'cash_flow_entry_tag_tag_id_870387d1', 'f', 'USING btree (tag_id)'),
    ('entry_attachment', 'entry_attac_entry_i_bb47db_idx', 'f', 'USING btree (entry_id)'),
    ('entry_attachment', 'entry_attachment_entry_id_4e5997c6', 'f', 'USING btree (entry_id)'),
    ('fechamento_coleta_myprofit', 'fechamento_coleta_myprofit_importada_por_id_10c176a9', 'f', 'USING btree (importada_por_id)'),
    ('fechamento_coleta_myprofit', 'fechamento_coleta_myprofit_sha256_d95c17db_like', 'f', 'USING btree (sha256 varchar_pattern_ops)'),
    ('fechamento_corte', 'fechamento_corte_user_id_91ac85ea', 'f', 'USING btree (user_id)'),
    ('fechamento_duplicata_descartada', 'fechamento_duplicata_descartada_descartada_por_id_64744b93', 'f', 'USING btree (descartada_por_id)'),
    ('fechamento_duplicata_descartada', 'fechamento_duplicata_descartada_linha_a_id_9879c373', 'f', 'USING btree (linha_a_id)'),
    ('fechamento_duplicata_descartada', 'fechamento_duplicata_descartada_linha_b_id_bd03bc62', 'f', 'USING btree (linha_b_id)'),
    ('fechamento_fonte', 'fechamento_fonte_updated_by_id_76a71005', 'f', 'USING btree (updated_by_id)'),
    ('fechamento_saldo_conferido', 'fechamento_saldo_conferido_account_id_a539bf92', 'f', 'USING btree (account_id)'),
    ('fechamento_saldo_conferido', 'fechamento_saldo_conferido_created_by_id_52c6ef4e', 'f', 'USING btree (created_by_id)'),
    ('fechamento_saldo_conferido', 'fechamento_saldo_conferido_lancamento_id_b421f89f', 'f', 'USING btree (lancamento_id)'),
    ('financial_account', 'financial_a_institu_5cc945_idx', 'f', 'USING btree (institution_id)'),
    ('financial_account', 'financial_a_is_defa_1e20db_idx', 'f', 'USING btree (is_default)'),
    ('financial_account', 'financial_a_owner_i_7633fc_idx', 'f', 'USING btree (owner_id)'),
    ('financial_account', 'financial_account_card_payment_account_id_fc5546f6', 'f', 'USING btree (card_payment_account_id)'),
    ('financial_account', 'financial_account_institution_id_4ba0c52a', 'f', 'USING btree (institution_id)'),
    ('financial_account', 'financial_account_movement_account_id_acfb4a8e', 'f', 'USING btree (movement_account_id)'),
    ('financial_account', 'financial_account_owner_id_68e52b51', 'f', 'USING btree (owner_id)'),
    ('financial_institution', 'financial_i_institu_8bfbaa_idx', 'f', 'USING btree (institution_type)'),
    ('financial_institution', 'uq_financial_institution_name_ci', 't', 'USING btree (lower((institution_name)::text))'),
    ('login_lockout', 'login_locko_locked__fbd36a_idx', 'f', 'USING btree (locked_until_ts)'),
    ('management_project', 'management__active_cb596e_idx', 'f', 'USING btree (active)'),
    ('management_project', 'management_project_project_name_b37f6e77_like', 'f', 'USING btree (project_name varchar_pattern_ops)'),
    ('management_tag', 'management__active_6f4382_idx', 'f', 'USING btree (active)'),
    ('management_tag', 'management_tag_tag_name_cec12670_like', 'f', 'USING btree (tag_name varchar_pattern_ops)'),
    ('monthly_budget', 'monthly_bud_active_b87bbb_idx', 'f', 'USING btree (active)'),
    ('monthly_budget', 'monthly_bud_owner_i_86cda3_idx', 'f', 'USING btree (owner_id, year, month)'),
    ('monthly_budget', 'monthly_budget_category_id_c19acfc4', 'f', 'USING btree (category_id)'),
    ('monthly_budget', 'monthly_budget_owner_id_d73261d7', 'f', 'USING btree (owner_id)'),
    ('patrimonio_v4_outbox', 'ix_patrimonio_v4_outbox_cursor', 'f', 'USING btree (cursor)'),
    ('pending_statement_upload', 'pending_sta_uploade_548878_idx', 'f', 'USING btree (uploaded_by_id)'),
    ('pending_statement_upload', 'pending_statement_upload_detected_account_id_fa386244', 'f', 'USING btree (detected_account_id)'),
    ('pending_statement_upload', 'pending_statement_upload_uploaded_by_id_ac9012ea', 'f', 'USING btree (uploaded_by_id)'),
    ('statement_rule', 'statement_rule_category_id_45c50b01', 'f', 'USING btree (category_id)'),
    ('statement_rule', 'statement_rule_destination_institution_id_74fc182e', 'f', 'USING btree (destination_institution_id)'),
    ('statement_rule', 'statement_rule_institution_id_2bc32258', 'f', 'USING btree (institution_id)'),
    ('user_owner_access', 'user_owner__user_id_23b631_idx', 'f', 'USING btree (user_id, owner_id)'),
    ('user_owner_access', 'user_owner_access_owner_id_94f1f15e', 'f', 'USING btree (owner_id)'),
    ('user_owner_access', 'user_owner_access_user_id_d09b3f1a', 'f', 'USING btree (user_id)'),
    ('user_permission', 'user_permis_permiss_0999ee_idx', 'f', 'USING btree (permission_id)'),
    ('user_permission', 'user_permis_user_id_281a2f_idx', 'f', 'USING btree (user_id)'),
    ('user_permission', 'user_permission_permission_id_e75c2bfd', 'f', 'USING btree (permission_id)'),
    ('user_permission', 'user_permission_user_id_094cc8c7', 'f', 'USING btree (user_id)'),
    ('user_transfer_destination_access', 'user_transf_user_id_b19060_idx', 'f', 'USING btree (user_id, destination_account_id)'),
    ('user_transfer_destination_access', 'user_transfer_destination__destination_account_id_2006c025', 'f', 'USING btree (destination_account_id)'),
    ('user_transfer_destination_access', 'user_transfer_destination_access_user_id_56f39884', 'f', 'USING btree (user_id)');

CREATE TEMP TABLE alvo_chave (tabela text, coluna text, nome text) ON COMMIT DROP;
INSERT INTO alvo_chave VALUES
    ('account_month_close', 'account_id', 'account_month_close_account_id_37b83921_fk_financial_account_id'),
    ('account_month_close', 'closed_by_user_id', 'account_month_close_closed_by_user_id_0f852e3f_fk_app_user_id'),
    ('account_month_close', 'reopened_by_user_id', 'account_month_close_reopened_by_user_id_0c04a9a4_fk_app_user_id'),
    ('app_user_groups', 'appuser_id', 'app_user_groups_appuser_id_7bb08f1f_fk_app_user_id'),
    ('app_user_groups', 'group_id', 'app_user_groups_group_id_e774d92c_fk_auth_group_id'),
    ('app_user_user_permissions', 'appuser_id', 'app_user_user_permissions_appuser_id_3404e502_fk_app_user_id'),
    ('app_user_user_permissions', 'permission_id', 'app_user_user_permis_permission_id_4ef8e133_fk_auth_perm'),
    ('audit_log', 'user_id', 'audit_log_user_id_a1b3392d_fk_app_user_id'),
    ('bank_operation', 'responsible_user_id', 'bank_operation_responsible_user_id_30ce0dd6_fk_app_user_id'),
    ('bank_statement_import', 'account_id', 'bank_statement_impor_account_id_48fbe5e7_fk_financial'),
    ('bank_statement_line', 'account_id', 'bank_statement_line_account_id_a32c0345_fk_financial_account_id'),
    ('bank_statement_line', 'import_id', 'bank_statement_line_import_id_63ac0e8b_fk_bank_stat'),
    ('bank_statement_line', 'matched_entry_id', 'bank_statement_line_matched_entry_id_e6ad3316_fk_cash_flow'),
    ('cash_flow_category', 'group_id', 'cash_flow_category_group_id_f7d18410_fk_cash_flow'),
    ('cash_flow_entry', 'account_id', 'cash_flow_entry_account_id_3c7d31c8_fk_financial_account_id'),
    ('cash_flow_entry', 'bank_operation_id', 'cash_flow_entry_bank_operation_id_33cd3b8f_fk_bank_operation_id'),
    ('cash_flow_entry', 'category_id', 'cash_flow_entry_category_id_923c5e63_fk_cash_flow_category_id'),
    ('cash_flow_entry', 'source_entry_id', 'cash_flow_entry_source_entry_id_0b244368_fk_cash_flow_entry_id'),
    ('cash_flow_entry_investment', 'entry_id', 'cash_flow_entry_inve_entry_id_81342280_fk_cash_flow'),
    ('cash_flow_entry_project', 'entry_id', 'cash_flow_entry_project_entry_id_5813a93f_fk_cash_flow_entry_id'),
    ('cash_flow_entry_project', 'project_id', 'cash_flow_entry_proj_project_id_32d8933d_fk_managemen'),
    ('cash_flow_entry_tag', 'entry_id', 'cash_flow_entry_tag_entry_id_f3d4cb61_fk_cash_flow_entry_id'),
    ('cash_flow_entry_tag', 'tag_id', 'cash_flow_entry_tag_tag_id_870387d1_fk_management_tag_id'),
    ('entry_attachment', 'entry_id', 'entry_attachment_entry_id_4e5997c6_fk_cash_flow_entry_id'),
    ('fechamento_coleta_myprofit', 'importada_por_id', 'fechamento_coleta_my_importada_por_id_10c176a9_fk_app_user_'),
    ('fechamento_corte', 'user_id', 'fechamento_corte_user_id_91ac85ea_fk_app_user_id'),
    ('fechamento_duplicata_descartada', 'descartada_por_id', 'fechamento_duplicata_descartada_por_id_64744b93_fk_app_user_'),
    ('fechamento_duplicata_descartada', 'linha_a_id', 'fechamento_duplicata_linha_a_id_9879c373_fk_bank_stat'),
    ('fechamento_duplicata_descartada', 'linha_b_id', 'fechamento_duplicata_linha_b_id_bd03bc62_fk_bank_stat'),
    ('fechamento_fonte', 'account_id', 'fechamento_fonte_account_id_2a2312be_fk_financial_account_id'),
    ('fechamento_fonte', 'updated_by_id', 'fechamento_fonte_updated_by_id_76a71005_fk_app_user_id'),
    ('fechamento_saldo_conferido', 'account_id', 'fechamento_saldo_con_account_id_a539bf92_fk_financial'),
    ('fechamento_saldo_conferido', 'created_by_id', 'fechamento_saldo_con_created_by_id_52c6ef4e_fk_app_user_'),
    ('fechamento_saldo_conferido', 'lancamento_id', 'fechamento_saldo_con_lancamento_id_b421f89f_fk_cash_flow'),
    ('financial_account', 'card_payment_account_id', 'financial_account_card_payment_account_fc5546f6_fk_financial'),
    ('financial_account', 'institution_id', 'financial_account_institution_id_4ba0c52a_fk_financial'),
    ('financial_account', 'movement_account_id', 'financial_account_movement_account_id_acfb4a8e_fk_financial'),
    ('financial_account', 'owner_id', 'financial_account_owner_id_68e52b51_fk_account_owner_id'),
    ('monthly_budget', 'category_id', 'monthly_budget_category_id_c19acfc4_fk_cash_flow_category_id'),
    ('monthly_budget', 'owner_id', 'monthly_budget_owner_id_d73261d7_fk_account_owner_id'),
    ('pending_statement_upload', 'detected_account_id', 'pending_statement_up_detected_account_id_fa386244_fk_financial'),
    ('pending_statement_upload', 'uploaded_by_id', 'pending_statement_upload_uploaded_by_id_ac9012ea_fk_app_user_id'),
    ('statement_rule', 'category_id', 'statement_rule_category_id_45c50b01_fk_cash_flow_category_id'),
    ('statement_rule', 'destination_institution_id', 'statement_rule_destination_institut_74fc182e_fk_financial'),
    ('statement_rule', 'institution_id', 'statement_rule_institution_id_2bc32258_fk_financial'),
    ('user_owner_access', 'owner_id', 'user_owner_access_owner_id_94f1f15e_fk_account_owner_id'),
    ('user_owner_access', 'user_id', 'user_owner_access_user_id_d09b3f1a_fk_app_user_id'),
    ('user_permission', 'permission_id', 'user_permission_permission_id_e75c2bfd_fk_app_permission_id'),
    ('user_permission', 'user_id', 'user_permission_user_id_094cc8c7_fk_app_user_id'),
    ('user_transfer_destination_access', 'destination_account_id', 'user_transfer_destin_destination_account__2006c025_fk_financial'),
    ('user_transfer_destination_access', 'user_id', 'user_transfer_destin_user_id_56f39884_fk_app_user_');

-- `definicao` e como o catalogo mostra o check; `criar`, como o Django o escreve.
-- O PostgreSQL guarda `IN (...)` de outro jeito quando recebe o texto do catalogo.
CREATE TEMP TABLE alvo_check (tabela text, nome text, definicao text, criar text) ON COMMIT DROP;
INSERT INTO alvo_check VALUES
    ('account_month_close', 'ck_account_month_close_month_range', 'CHECK (((month >= 1) AND (month <= 12)))', E'CHECK (("month" >= 1 AND "month" <= 12))'),
    ('account_month_close', 'ck_account_month_close_year_range', 'CHECK (((year >= 2000) AND (year <= 2100)))', E'CHECK (("year" >= 2000 AND "year" <= 2100))'),
    ('app_user', 'ck_app_user_language_valid', 'CHECK (((language)::text = ANY ((ARRAY[''pt-br''::character varying, ''en''::character varying])::text[])))', E'CHECK ("language" IN (''pt-br'', ''en''))'),
    ('app_user', 'ck_app_user_regional_format_valid', 'CHECK (((regional_format)::text = ANY ((ARRAY[''auto''::character varying, ''br''::character varying, ''us''::character varying])::text[])))', E'CHECK ("regional_format" IN (''auto'', ''br'', ''us''))'),
    ('app_user', 'ck_app_user_table_scroll_rows_range', 'CHECK (((table_scroll_rows >= 5) AND (table_scroll_rows <= 200)))', E'CHECK (("table_scroll_rows" >= 5 AND "table_scroll_rows" <= 200))'),
    ('app_user', 'ck_app_user_ui_theme_valid', 'CHECK (((ui_theme)::text = ANY ((ARRAY[''light''::character varying, ''dark''::character varying, ''solarized_light''::character varying, ''solarized_dark''::character varying, ''dracula''::character varying, ''nord''::character varying, ''monokai''::character varying, ''gray''::character varying, ''soft_light''::character varying, ''soft_dark''::character varying, ''corporate_blue''::character varying, ''emerald''::character varying])::text[])))', E'CHECK ("ui_theme" IN (''light'', ''dark'', ''solarized_light'', ''solarized_dark'', ''dracula'', ''nord'', ''monokai'', ''gray'', ''soft_light'', ''soft_dark'', ''corporate_blue'', ''emerald''))'),
    ('app_user', 'ck_app_user_user_type_valid', 'CHECK (((user_type)::text = ANY ((ARRAY[''administrator''::character varying, ''super user''::character varying, ''user''::character varying])::text[])))', E'CHECK ("user_type" IN (''administrator'', ''super user'', ''user''))'),
    ('audit_log', 'ck_audit_log_action_not_blank', 'CHECK ((NOT ((action)::text = ''''::text)))', E'CHECK (NOT ("action" = ''''))'),
    ('audit_log', 'ck_audit_log_entity_name_not_blank', 'CHECK ((NOT ((entity_name)::text = ''''::text)))', E'CHECK (NOT ("entity_name" = ''''))'),
    ('bank_operation', 'ck_bank_operation_installment_total_positive', 'CHECK ((installment_total >= 1))', E'CHECK ("installment_total" >= 1)'),
    ('bank_operation', 'ck_bank_operation_key_not_blank', E'CHECK (((operation_key)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("operation_key"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('bank_operation', 'ck_bank_operation_status_valid', 'CHECK (((status)::text = ANY ((ARRAY[''a_vencer''::character varying, ''vencidos''::character varying, ''realizado''::character varying])::text[])))', E'CHECK ("status" IN (''a_vencer'', ''vencidos'', ''realizado''))'),
    ('bank_operation', 'ck_bank_operation_type_valid', 'CHECK (((operation_type)::text = ANY ((ARRAY[''single''::character varying, ''installment''::character varying, ''recurring''::character varying, ''internal_transfer''::character varying])::text[])))', E'CHECK ("operation_type" IN (''single'', ''installment'', ''recurring'', ''internal_transfer''))'),
    ('bank_statement_import', 'ck_bank_statement_import_filename_not_blank', E'CHECK (((source_filename)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("source_filename"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('bank_statement_import', 'ck_bank_statement_import_status_valid', 'CHECK (((status)::text = ANY ((ARRAY[''importado''::character varying, ''processado''::character varying, ''erro''::character varying])::text[])))', E'CHECK ("status" IN (''importado'', ''processado'', ''erro''))'),
    ('bank_statement_line', 'bank_statement_line_installment_current_check', 'CHECK ((installment_current >= 0))', 'CHECK ((installment_current >= 0))'),
    ('bank_statement_line', 'bank_statement_line_installment_total_check', 'CHECK ((installment_total >= 0))', 'CHECK ((installment_total >= 0))'),
    ('bank_statement_line', 'ck_bank_statement_line_amount_non_zero', 'CHECK ((NOT (amount = (0)::numeric)))', E'CHECK (NOT ("amount" = 0))'),
    ('bank_statement_line', 'ck_bank_statement_line_installment_valid', 'CHECK ((((installment_current IS NULL) AND (installment_total IS NULL)) OR ((installment_current >= 1) AND (installment_current IS NOT NULL) AND (installment_current <= installment_total) AND (installment_total IS NOT NULL))))', E'CHECK ((("installment_current" IS NULL AND "installment_total" IS NULL) OR ("installment_current" >= 1 AND "installment_current" IS NOT NULL AND "installment_current" <= ("installment_total") AND "installment_total" IS NOT NULL)))'),
    ('bank_statement_line', 'ck_bank_statement_line_status_valid', 'CHECK (((status)::text = ANY ((ARRAY[''novo''::character varying, ''conciliado''::character varying, ''ignorado''::character varying])::text[])))', E'CHECK ("status" IN (''novo'', ''conciliado'', ''ignorado''))'),
    ('cash_flow_category', 'ck_cash_flow_category_kind_valid', 'CHECK (((kind)::text = ANY ((ARRAY[''gerencial''::character varying, ''transferencia''::character varying, ''movimentacao''::character varying, ''valorizacao''::character varying])::text[])))', E'CHECK ("kind" IN (''gerencial'', ''transferencia'', ''movimentacao'', ''valorizacao''))'),
    ('cash_flow_category', 'ck_cash_flow_category_name_not_blank', E'CHECK (((category_name)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("category_name"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('cash_flow_category_group', 'cash_flow_category_group_position_check', 'CHECK (("position" >= 0))', 'CHECK (("position" >= 0))'),
    ('cash_flow_category_group', 'ck_cash_flow_category_group_name_not_blank', E'CHECK (((group_name)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("group_name"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('cash_flow_entry', 'ck_cash_flow_entry_amount_positive', 'CHECK ((entry_amount > (0)::numeric))', E'CHECK ("entry_amount" > 0)'),
    ('cash_flow_entry', 'ck_cash_flow_entry_current_installment_positive', 'CHECK ((current_installment >= 1))', E'CHECK ("current_installment" >= 1)'),
    ('cash_flow_entry', 'ck_cash_flow_entry_current_lte_total', 'CHECK ((current_installment <= installments))', E'CHECK ("current_installment" <= ("installments"))'),
    ('cash_flow_entry', 'ck_cash_flow_entry_installments_positive', 'CHECK ((installments >= 1))', E'CHECK ("installments" >= 1)'),
    ('cash_flow_entry', 'ck_cash_flow_entry_operation_type_valid', 'CHECK (((operation_type)::text = ANY ((ARRAY[''single''::character varying, ''installment''::character varying, ''recurring''::character varying, ''internal_transfer''::character varying])::text[])))', E'CHECK ("operation_type" IN (''single'', ''installment'', ''recurring'', ''internal_transfer''))'),
    ('cash_flow_entry', 'ck_cash_flow_entry_realized_amount_positive', 'CHECK (((realized_amount IS NULL) OR (realized_amount > (0)::numeric)))', E'CHECK (("realized_amount" IS NULL OR "realized_amount" > 0))'),
    ('cash_flow_entry', 'ck_cash_flow_entry_realized_has_date_and_amount', 'CHECK (((NOT ((status)::text = ''realizado''::text)) OR ((realized_amount IS NOT NULL) AND (realized_date IS NOT NULL))))', E'CHECK ((NOT ("status" = ''realizado'') OR ("realized_amount" IS NOT NULL AND "realized_date" IS NOT NULL)))'),
    ('cash_flow_entry', 'ck_cash_flow_entry_source_not_self', 'CHECK (((source_entry_id IS NULL) OR (NOT ((source_entry_id = id) AND (source_entry_id IS NOT NULL)))))', E'CHECK (("source_entry_id" IS NULL OR NOT ("source_entry_id" = ("id") AND "source_entry_id" IS NOT NULL)))'),
    ('cash_flow_entry', 'ck_cash_flow_entry_status_valid', 'CHECK (((status)::text = ANY ((ARRAY[''a_vencer''::character varying, ''vencidos''::character varying, ''realizado''::character varying])::text[])))', E'CHECK ("status" IN (''a_vencer'', ''vencidos'', ''realizado''))'),
    ('cash_flow_entry', 'ck_cash_flow_entry_type_valid', 'CHECK (((entry_type)::text = ANY ((ARRAY[''receita''::character varying, ''despesa''::character varying])::text[])))', E'CHECK ("entry_type" IN (''receita'', ''despesa''))'),
    ('cash_flow_entry_investment', 'ck_entry_investment_income_kind_valid', 'CHECK (((income_kind IS NULL) OR ((income_kind)::text = ANY ((ARRAY[''aluguel''::character varying, ''jcp''::character varying, ''dividendo''::character varying, ''cupom''::character varying])::text[]))))', E'CHECK (("income_kind" IS NULL OR "income_kind" IN (''aluguel'', ''jcp'', ''dividendo'', ''cupom'')))'),
    ('cash_flow_entry_investment', 'ck_entry_investment_income_role_valid', 'CHECK (((income_role IS NULL) OR ((income_role)::text = ANY ((ARRAY[''credito''::character varying, ''irrf_aluguel''::character varying, ''corretagem_aluguel''::character varying, ''taxa_aluguel''::character varying, ''estorno''::character varying])::text[]))))', E'CHECK (("income_role" IS NULL OR "income_role" IN (''credito'', ''irrf_aluguel'', ''corretagem_aluguel'', ''taxa_aluguel'', ''estorno'')))'),
    ('cash_flow_entry_investment', 'ck_entry_investment_settlement_quantity_positive', 'CHECK (((settlement_quantity IS NULL) OR (settlement_quantity > (0)::numeric)))', E'CHECK (("settlement_quantity" IS NULL OR "settlement_quantity" > 0))'),
    ('entry_attachment', 'ck_entry_attachment_filename_not_blank', E'CHECK (((original_filename)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("original_filename"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('fechamento_coleta_myprofit', 'fechamento_coleta_myprofit_remessas_check', 'CHECK ((remessas >= 0))', 'CHECK ((remessas >= 0))'),
    ('fechamento_coleta_myprofit', 'fechamento_coleta_myprofit_saldos_check', 'CHECK ((saldos >= 0))', 'CHECK ((saldos >= 0))'),
    ('fechamento_corte', 'fechamento_corte_em_dia_check', 'CHECK ((em_dia >= 0))', 'CHECK ((em_dia >= 0))'),
    ('fechamento_corte', 'fechamento_corte_total_check', 'CHECK ((total >= 0))', 'CHECK ((total >= 0))'),
    ('fechamento_duplicata_descartada', 'ck_fechamento_duplicata_ordem', 'CHECK ((linha_a_id < linha_b_id))', E'CHECK ("linha_a_id" < ("linha_b_id"))'),
    ('fechamento_fonte', 'ck_fechamento_classe_so_no_myprofit', 'CHECK ((((classe_myprofit)::text = ''''::text) OR ((fonte)::text = ''myprofit''::text)))', E'CHECK (("classe_myprofit" = '''' OR "fonte" = ''myprofit''))'),
    ('fechamento_fonte', 'ck_fechamento_fonte_valida', 'CHECK (((fonte)::text = ANY ((ARRAY[''arquivo''::character varying, ''fatura''::character varying, ''print''::character varying, ''myprofit''::character varying, ''nenhuma''::character varying])::text[])))', E'CHECK ("fonte" IN (''arquivo'', ''fatura'', ''print'', ''myprofit'', ''nenhuma''))'),
    ('fechamento_fonte', 'ck_fechamento_frequencia_valida', 'CHECK (((frequencia)::text = ANY ((ARRAY[''corte''::character varying, ''mensal''::character varying])::text[])))', E'CHECK ("frequencia" IN (''corte'', ''mensal''))'),
    ('fechamento_saldo_conferido', 'ck_fechamento_saldo_origem_valida', 'CHECK (((origem)::text = ANY ((ARRAY[''print''::character varying, ''myprofit''::character varying, ''manual''::character varying])::text[])))', E'CHECK ("origem" IN (''print'', ''myprofit'', ''manual''))'),
    ('financial_account', 'ck_financial_account_card_fields', 'CHECK (((((account_kind)::text = ''cartao_credito''::text) AND (card_closing_day >= 1) AND (card_closing_day IS NOT NULL) AND (card_closing_day <= 31) AND (card_due_day >= 1) AND (card_due_day IS NOT NULL) AND (card_due_day <= 31) AND ((card_estimated_spend IS NULL) OR (card_estimated_spend >= (0)::numeric))) OR (((account_kind)::text = ANY ((ARRAY[''conta''::character varying, ''aplicacao''::character varying])::text[])) AND (card_closing_day IS NULL) AND (card_due_day IS NULL) AND (card_estimated_spend IS NULL) AND (card_payment_account_id IS NULL))))', E'CHECK ((("account_kind" = ''cartao_credito'' AND "card_closing_day" >= 1 AND "card_closing_day" IS NOT NULL AND "card_closing_day" <= 31 AND "card_due_day" >= 1 AND "card_due_day" IS NOT NULL AND "card_due_day" <= 31 AND ("card_estimated_spend" IS NULL OR "card_estimated_spend" >= 0)) OR ("account_kind" IN (''conta'', ''aplicacao'') AND "card_closing_day" IS NULL AND "card_due_day" IS NULL AND "card_estimated_spend" IS NULL AND "card_payment_account_id" IS NULL)))'),
    ('financial_account', 'ck_financial_account_currency_valid', 'CHECK (((currency)::text = ANY ((ARRAY[''BRL''::character varying, ''USD''::character varying])::text[])))', E'CHECK ("currency" IN (''BRL'', ''USD''))'),
    ('financial_account', 'ck_financial_account_kind_valid', 'CHECK (((account_kind)::text = ANY ((ARRAY[''conta''::character varying, ''cartao_credito''::character varying, ''aplicacao''::character varying])::text[])))', E'CHECK ("account_kind" IN (''conta'', ''cartao_credito'', ''aplicacao''))'),
    ('financial_account', 'ck_financial_account_name_not_blank', E'CHECK (((account_name)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("account_name"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('financial_account', 'ck_financial_account_purpose_valid', 'CHECK (((purpose)::text = ANY ((ARRAY[''pessoal''::character varying, ''administrada''::character varying])::text[])))', E'CHECK ("purpose" IN (''pessoal'', ''administrada''))'),
    ('financial_account', 'financial_account_card_closing_day_check', 'CHECK ((card_closing_day >= 0))', 'CHECK ((card_closing_day >= 0))'),
    ('financial_account', 'financial_account_card_due_day_check', 'CHECK ((card_due_day >= 0))', 'CHECK ((card_due_day >= 0))'),
    ('financial_institution', 'ck_financial_institution_name_not_blank', E'CHECK (((institution_name)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("institution_name"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('financial_institution', 'ck_financial_institution_type_valid', 'CHECK (((institution_type)::text = ANY ((ARRAY[''Banco''::character varying, ''Corretora''::character varying])::text[])))', E'CHECK ("institution_type" IN (''Banco'', ''Corretora''))'),
    ('management_project', 'ck_management_project_name_not_blank', E'CHECK (((project_name)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("project_name"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('management_tag', 'ck_management_tag_name_not_blank', E'CHECK (((tag_name)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("tag_name"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('monthly_budget', 'ck_monthly_budget_amount_non_negative', 'CHECK ((planned_amount >= (0)::numeric))', E'CHECK ("planned_amount" >= 0)'),
    ('monthly_budget', 'ck_monthly_budget_month_range', 'CHECK (((month >= 1) AND (month <= 12)))', E'CHECK (("month" >= 1 AND "month" <= 12))'),
    ('monthly_budget', 'ck_monthly_budget_year_range', 'CHECK (((year >= 2000) AND (year <= 2100)))', E'CHECK (("year" >= 2000 AND "year" <= 2100))'),
    ('patrimonio_v4_change_counter', 'ck_patrimonio_v4_counter_non_negative', 'CHECK ((value >= 0))', E'CHECK ("value" >= 0)'),
    ('patrimonio_v4_change_counter', 'ck_patrimonio_v4_counter_singleton', 'CHECK ((id = 1))', E'CHECK ("id" = 1)'),
    ('patrimonio_v4_outbox', 'ck_patrimonio_v4_outbox_operation', 'CHECK (((operation)::text = ANY ((ARRAY[''upsert''::character varying, ''delete''::character varying])::text[])))', E'CHECK ("operation" IN (''upsert'', ''delete''))'),
    ('patrimonio_v4_outbox', 'ck_patrimonio_v4_outbox_resource', 'CHECK (((resource)::text = ANY ((ARRAY[''account''::character varying, ''category''::character varying, ''cash_entry''::character varying, ''transfer''::character varying])::text[])))', E'CHECK ("resource" IN (''account'', ''category'', ''cash_entry'', ''transfer''))'),
    ('pending_statement_upload', 'ck_pending_statement_upload_filename_not_blank', E'CHECK (((original_filename)::text ~ ''^\\s*.+\\s*$''::text))', E'CHECK ("original_filename"::text ~  E''^\\\\s*.+\\\\s*$'')'),
    ('statement_rule', 'ck_statement_rule_action_fields', E'CHECK (((((action)::text = ''categoria''::text) AND (category_id IS NOT NULL)) OR (((action)::text = ''transferencia''::text) AND ((destination_account_name)::text ~ ''^\\s*.+\\s*$''::text)) OR ((action)::text = ''ignorar''::text) OR ((action)::text = ''aplicacao''::text)))', E'CHECK ((("action" = ''categoria'' AND "category_id" IS NOT NULL) OR ("action" = ''transferencia'' AND "destination_account_name"::text ~  E''^\\\\s*.+\\\\s*$'') OR "action" = ''ignorar'' OR "action" = ''aplicacao''))'),
    ('statement_rule', 'ck_statement_rule_action_valid', 'CHECK (((action)::text = ANY ((ARRAY[''categoria''::character varying, ''transferencia''::character varying, ''ignorar''::character varying, ''aplicacao''::character varying])::text[])))', E'CHECK ("action" IN (''categoria'', ''transferencia'', ''ignorar'', ''aplicacao''))'),
    ('statement_rule', 'ck_statement_rule_pattern_min_length', E'CHECK (((pattern)::text ~ ''^\\s*.{3,}\\s*$''::text))', E'CHECK ("pattern"::text ~  E''^\\\\s*.{3,}\\\\s*$'')'),
    ('statement_rule', 'ck_statement_rule_sign_valid', 'CHECK (((sign)::text = ANY ((ARRAY[''qualquer''::character varying, ''credito''::character varying, ''debito''::character varying])::text[])))', E'CHECK ("sign" IN (''qualquer'', ''credito'', ''debito''))');

CREATE TEMP TABLE alvo_unico (tabela text, nome text, colunas text) ON COMMIT DROP;
INSERT INTO alvo_unico VALUES
    ('account_month_close', 'uq_account_month_close_account_period', 'account_id, year, month'),
    ('app_permission', 'app_permission_permission_key_key', 'permission_key'),
    ('app_setting', 'app_setting_setting_key_key', 'setting_key'),
    ('app_user', 'app_user_username_key', 'username'),
    ('app_user_groups', 'app_user_groups_appuser_id_group_id_3e9171d9_uniq', 'appuser_id, group_id'),
    ('app_user_user_permissions', 'app_user_user_permission_appuser_id_permission_id_ebb11b17_uniq', 'appuser_id, permission_id'),
    ('bank_operation', 'bank_operation_operation_key_key', 'operation_key'),
    ('bank_statement_line', 'uq_bank_statement_line_account_hash', 'account_id, line_hash'),
    ('cash_flow_category', 'cash_flow_category_category_name_key', 'category_name'),
    ('cash_flow_category_group', 'cash_flow_category_group_group_name_key', 'group_name'),
    ('cash_flow_entry_investment', 'cash_flow_entry_investment_entry_id_key', 'entry_id'),
    ('cash_flow_entry_project', 'uq_cash_flow_entry_project_entry', 'entry_id'),
    ('cash_flow_entry_submission', 'cash_flow_entry_submission_token_key', 'token'),
    ('cash_flow_entry_tag', 'uq_cash_flow_entry_tag_entry_tag', 'entry_id, tag_id'),
    ('fechamento_coleta_myprofit', 'fechamento_coleta_myprofit_sha256_key', 'sha256'),
    ('fechamento_corte', 'uq_fechamento_corte_usuario_data', 'user_id, data'),
    ('fechamento_duplicata_descartada', 'uq_fechamento_duplicata_par', 'linha_a_id, linha_b_id'),
    ('fechamento_fonte', 'fechamento_fonte_account_id_key', 'account_id'),
    ('fechamento_saldo_conferido', 'uq_fechamento_saldo_conta_data_origem', 'account_id, data, origem'),
    ('login_lockout', 'uq_login_lockout_identity_key', 'identity_key'),
    ('management_project', 'management_project_project_name_key', 'project_name'),
    ('management_tag', 'management_tag_tag_name_key', 'tag_name'),
    ('monthly_budget', 'uq_monthly_budget_owner_category_period', 'owner_id, category_id, year, month'),
    ('user_owner_access', 'uq_user_owner_access_user_owner', 'user_id, owner_id'),
    ('user_permission', 'uq_user_permission_user_permission', 'user_id, permission_id'),
    ('user_transfer_destination_access', 'uq_user_transfer_destination_access', 'user_id, destination_account_id');

-- Índices que só o banco antigo tem e que não viram nenhum do alvo.
CREATE TEMP TABLE indice_antigo (nome text) ON COMMIT DROP;
INSERT INTO indice_antigo VALUES
    ('app_user_groups_appuser_id_group_id_uniq'),
    ('app_user_groups_appuser_id_idx'),
    ('app_user_groups_group_id_idx'),
    ('app_user_user_permissions_appuser_id_idx'),
    ('app_user_user_permissions_appuser_id_permission_id_uniq'),
    ('app_user_user_permissions_permission_id_idx'),
    ('ix_account_month_close_account_id'),
    ('ix_account_month_close_account_period'),
    ('ix_app_permission_permission_key'),
    ('ix_audit_log_user_id'),
    ('ix_bank_operation_legacy_operation_id'),
    ('ix_bank_operation_type_status'),
    ('ix_bank_statement_import_account_id'),
    ('ix_bank_statement_line_account_date'),
    ('ix_bank_statement_line_account_id'),
    ('ix_bank_statement_line_import_id'),
    ('ix_bank_statement_line_matched_entry_id'),
    ('ix_cash_flow_entry_account_due_date'),
    ('ix_cash_flow_entry_account_realized_date'),
    ('ix_cash_flow_entry_bank_operation'),
    ('ix_cash_flow_entry_bank_operation_id'),
    ('ix_cash_flow_entry_category_due_date'),
    ('ix_cash_flow_entry_operation_type'),
    ('ix_cash_flow_entry_project_entry_id'),
    ('ix_cash_flow_entry_project_project_id'),
    ('ix_cash_flow_entry_source_entry_id'),
    ('ix_cash_flow_entry_status_due_date'),
    ('ix_cash_flow_entry_tag_entry_id'),
    ('ix_cash_flow_entry_tag_tag_id'),
    ('ix_cash_flow_entry_type_due_date'),
    ('ix_entry_attachment_entry_id'),
    ('ix_financial_account_institution_id'),
    ('ix_financial_account_owner_id'),
    ('ix_login_lockout_locked_until_ts'),
    ('ix_monthly_budget_category_id'),
    ('ix_monthly_budget_owner_id'),
    ('ix_monthly_budget_owner_period'),
    ('ix_user_owner_access_owner_id'),
    ('ix_user_owner_access_user_id'),
    ('ix_user_permission_permission_id'),
    ('ix_user_permission_user_id');

-- 1. O que sobrou de antes da conversão e nenhum modelo usa. A
-- `alembic_version` guarda uma linha (a revisão do Alembic) e a
-- `django_admin_log` está vazia: o admin do Django nunca foi instalado.
DROP TABLE IF EXISTS public.alembic_version;
DROP TABLE IF EXISTS public.django_admin_log;
ALTER TABLE public.app_permission DROP COLUMN IF EXISTS updated_at;
ALTER TABLE public.user_owner_access DROP COLUMN IF EXISTS updated_at;
-- Este check só existe no banco antigo; a `banking/0002` o recria pelo modelo.
ALTER TABLE public.account_owner DROP CONSTRAINT IF EXISTS ck_account_owner_owner_name_not_blank;
ALTER TABLE public.app_user
    ALTER COLUMN date_joined DROP DEFAULT,
    ALTER COLUMN email DROP DEFAULT,
    ALTER COLUMN first_name DROP DEFAULT,
    ALTER COLUMN last_name DROP DEFAULT,
    ALTER COLUMN is_active DROP DEFAULT,
    ALTER COLUMN is_staff DROP DEFAULT,
    ALTER COLUMN is_superuser DROP DEFAULT;

-- 2. Tipos de coluna. O PostgreSQL não muda o tipo de coluna lida por view:
-- as do esquema `leitura` são guardadas (definição, dono, comentários e
-- concessões), apagadas e recriadas iguais depois da mudança.
DO $$
DECLARE
    v record;
    r record;
    passo integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM alvo_tipo a
        JOIN pg_attribute c ON c.attrelid = format('public.%I', a.tabela)::regclass AND c.attname = a.coluna
        WHERE format_type(c.atttypid, c.atttypmod) <> a.tipo
    ) THEN
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('v', 'm') AND n.nspname NOT IN ('leitura', 'pg_catalog', 'information_schema')
    ) THEN
        RAISE EXCEPTION 'ha view fora do esquema leitura; esta migracao so sabe recriar as dele';
    END IF;

    CREATE TEMP TABLE view_guardada ON COMMIT DROP AS
    SELECT c.oid AS ordem, c.relname AS nome, pg_get_viewdef(c.oid) AS definicao,
           pg_get_userbyid(c.relowner) AS dono, obj_description(c.oid, 'pg_class') AS comentario,
           c.reloptions AS opcoes, false AS recriada,
           ARRAY(
               SELECT format('GRANT %s ON leitura.%I TO %s', g.privilege_type, c.relname,
                             CASE WHEN g.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(g.grantee)) END)
               FROM aclexplode(c.relacl) g WHERE g.grantee <> c.relowner
           ) AS concessoes,
           ARRAY(
               SELECT format('COMMENT ON COLUMN leitura.%I.%I IS %L', c.relname, a.attname, d.description)
               FROM pg_description d
               JOIN pg_attribute a ON a.attrelid = d.objoid AND a.attnum = d.objsubid
               WHERE d.objoid = c.oid AND d.classoid = 'pg_class'::regclass AND d.objsubid > 0
           ) AS comentarios_de_coluna
    FROM pg_class c
    WHERE c.relnamespace = 'leitura'::regnamespace AND c.relkind = 'v';

    FOR v IN SELECT nome FROM view_guardada LOOP
        EXECUTE format('DROP VIEW IF EXISTS leitura.%I CASCADE', v.nome);
    END LOOP;

    FOR r IN
        SELECT a.tabela, string_agg(format('ALTER COLUMN %I TYPE %s', a.coluna, a.tipo), ', ' ORDER BY a.coluna) AS alteracoes
        FROM alvo_tipo a
        JOIN pg_attribute c ON c.attrelid = format('public.%I', a.tabela)::regclass AND c.attname = a.coluna
        WHERE format_type(c.atttypid, c.atttypmod) <> a.tipo
        GROUP BY a.tabela
        ORDER BY a.tabela
    LOOP
        EXECUTE format('ALTER TABLE public.%I %s', r.tabela, r.alteracoes);
    END LOOP;

    -- Uma view pode ler outra: tenta em rodadas até todas existirem.
    FOR passo IN 1..20 LOOP
        FOR v IN SELECT * FROM view_guardada WHERE NOT recriada ORDER BY ordem LOOP
            BEGIN
                EXECUTE format('CREATE VIEW leitura.%I AS %s', v.nome, v.definicao);
            EXCEPTION WHEN undefined_table THEN
                CONTINUE;
            END;
            EXECUTE format('ALTER VIEW leitura.%I OWNER TO %I', v.nome, v.dono);
            IF v.opcoes IS NOT NULL THEN
                EXECUTE format('ALTER VIEW leitura.%I SET (%s)', v.nome, array_to_string(v.opcoes, ', '));
            END IF;
            IF v.comentario IS NOT NULL THEN
                EXECUTE format('COMMENT ON VIEW leitura.%I IS %L', v.nome, v.comentario);
            END IF;
            FOR r IN SELECT unnest(v.concessoes || v.comentarios_de_coluna) AS comando LOOP
                EXECUTE r.comando;
            END LOOP;
            UPDATE view_guardada SET recriada = true WHERE nome = v.nome;
        END LOOP;
        EXIT WHEN NOT EXISTS (SELECT 1 FROM view_guardada WHERE NOT recriada);
    END LOOP;
    IF EXISTS (SELECT 1 FROM view_guardada WHERE NOT recriada) THEN
        RAISE EXCEPTION 'nao foi possivel recriar as views do esquema leitura';
    END IF;
END $$;

-- 3. Chave `serial` (sequência solta com DEFAULT nextval) vira coluna de
-- identidade, como o Django cria. A sequência nova retoma do ponto em que a
-- antiga parou e recebe as mesmas concessões.
DO $$
DECLARE
    r record;
    ultimo bigint;
    chamado boolean;
    concessao text;
BEGIN
    FOR r IN
        SELECT c.relname AS tabela, a.attname AS coluna, s.relname AS sequencia,
               ARRAY(
                   SELECT format('GRANT %s ON SEQUENCE public.%I TO %s', g.privilege_type, s.relname,
                                 CASE WHEN g.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(g.grantee)) END)
                   FROM aclexplode(s.relacl) g WHERE g.grantee <> s.relowner
               ) AS concessoes
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        JOIN pg_depend dep ON dep.refobjid = c.oid AND dep.refobjsubid = a.attnum
                          AND dep.classid = 'pg_class'::regclass AND dep.deptype = 'a'
        JOIN pg_class s ON s.oid = dep.objid AND s.relkind = 'S'
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND a.attidentity = ''
          AND pg_get_expr(d.adbin, d.adrelid) LIKE 'nextval(%'
          AND c.relname IN (SELECT tabela FROM alvo_chave UNION SELECT tabela FROM alvo_check
                            UNION SELECT tabela FROM alvo_indice UNION SELECT tabela FROM alvo_tipo)
        ORDER BY c.relname
    LOOP
        EXECUTE format('SELECT last_value, is_called FROM public.%I', r.sequencia) INTO ultimo, chamado;
        EXECUTE format('ALTER TABLE public.%I ALTER COLUMN %I DROP DEFAULT', r.tabela, r.coluna);
        EXECUTE format('DROP SEQUENCE public.%I', r.sequencia);
        EXECUTE format(
            'ALTER TABLE public.%I ALTER COLUMN %I ADD GENERATED BY DEFAULT AS IDENTITY (SEQUENCE NAME public.%I)',
            r.tabela, r.coluna, r.sequencia
        );
        PERFORM setval(format('public.%I', r.sequencia)::regclass, ultimo, chamado);
        FOREACH concessao IN ARRAY r.concessoes LOOP
            EXECUTE concessao;
        END LOOP;
    END LOOP;
END $$;

-- 4. Restrições: nome das chaves estrangeiras, redação dos checks e as
-- unicidades que no banco antigo eram só índice.
DO $$
DECLARE
    r record;
    indice text;
BEGIN
    FOR r IN
        SELECT a.tabela, a.nome, k.conname
        FROM alvo_chave a
        JOIN pg_constraint k ON k.conrelid = format('public.%I', a.tabela)::regclass
                            AND k.contype = 'f' AND cardinality(k.conkey) = 1
        JOIN pg_attribute c ON c.attrelid = k.conrelid AND c.attnum = k.conkey[1] AND c.attname = a.coluna
        WHERE k.conname <> a.nome
    LOOP
        EXECUTE format('ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I', r.tabela, r.conname, r.nome);
    END LOOP;

    FOR r IN
        SELECT a.tabela, a.nome, a.criar, k.oid IS NOT NULL AS existe
        FROM alvo_check a
        LEFT JOIN pg_constraint k ON k.conrelid = format('public.%I', a.tabela)::regclass
                                 AND k.contype = 'c' AND k.conname = a.nome
        WHERE k.oid IS NULL OR pg_get_constraintdef(k.oid) <> a.definicao
        ORDER BY a.tabela, a.nome
    LOOP
        IF r.existe THEN
            EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', r.tabela, r.nome);
        END IF;
        EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s', r.tabela, r.nome, r.criar);
    END LOOP;

    FOR r IN
        SELECT a.* FROM alvo_unico a
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_constraint k
            WHERE k.conrelid = format('public.%I', a.tabela)::regclass AND k.conname = a.nome
        )
    LOOP
        SELECT i.relname INTO indice
        FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        WHERE x.indrelid = format('public.%I', r.tabela)::regclass
          AND x.indisunique AND NOT x.indisprimary AND x.indpred IS NULL AND x.indexprs IS NULL
          AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = x.indexrelid)
          AND r.colunas = (
              SELECT string_agg(quote_ident(c.attname), ', ' ORDER BY u.ord)
              FROM unnest(x.indkey::int2[]) WITH ORDINALITY u(num, ord)
              JOIN pg_attribute c ON c.attrelid = x.indrelid AND c.attnum = u.num
          )
        LIMIT 1;
        IF indice IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I UNIQUE USING INDEX %I', r.tabela, r.nome, indice);
        ELSE
            EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I UNIQUE (%s)', r.tabela, r.nome, r.colunas);
        END IF;
    END LOOP;
END $$;

-- 5. Índices: o que já existe com outro nome é renomeado, o que falta é
-- criado e o que só o banco antigo tinha sai.
DO $$
DECLARE
    a record;
    atual record;
    candidato text;
BEGIN
    FOR a IN SELECT * FROM alvo_indice ORDER BY tabela, nome LOOP
        SELECT x.indisunique AS unico,
               regexp_replace(pg_get_indexdef(x.indexrelid), '^CREATE (UNIQUE )?INDEX \S+ ON \S+ ', '') AS definicao
        INTO atual
        FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        WHERE x.indrelid = format('public.%I', a.tabela)::regclass AND i.relname = a.nome;
        IF FOUND AND atual.definicao = a.definicao AND atual.unico = a.unico THEN
            CONTINUE;
        END IF;
        IF FOUND THEN
            EXECUTE format('DROP INDEX public.%I', a.nome);
        END IF;

        SELECT i.relname INTO candidato
        FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        WHERE x.indrelid = format('public.%I', a.tabela)::regclass
          AND x.indisunique = a.unico
          AND regexp_replace(pg_get_indexdef(x.indexrelid), '^CREATE (UNIQUE )?INDEX \S+ ON \S+ ', '') = a.definicao
          AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = x.indexrelid)
          AND NOT EXISTS (SELECT 1 FROM alvo_indice o WHERE o.tabela = a.tabela AND o.nome = i.relname)
        ORDER BY i.relname
        LIMIT 1;
        IF candidato IS NOT NULL THEN
            EXECUTE format('ALTER INDEX public.%I RENAME TO %I', candidato, a.nome);
        ELSE
            EXECUTE format(
                'CREATE %sINDEX %I ON public.%I %s',
                CASE WHEN a.unico THEN 'UNIQUE ' ELSE '' END, a.nome, a.tabela, a.definicao
            );
        END IF;
    END LOOP;

    FOR a IN
        SELECT i.relname AS nome
        FROM indice_antigo v
        JOIN pg_class i ON i.relname = v.nome AND i.relnamespace = 'public'::regnamespace AND i.relkind = 'i'
        WHERE NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = i.oid)
    LOOP
        EXECUTE format('DROP INDEX public.%I', a.nome);
    END LOOP;
END $$;

-- 6. Conferência: se alguma tabela do projeto ainda se afasta do alvo, a
-- migração falha e nada do que ela fez fica.
DO $$
DECLARE
    falta text;
BEGIN
    SELECT string_agg(item, '; ' ORDER BY item) INTO falta FROM (
        SELECT format('tipo de %s.%s', a.tabela, a.coluna) AS item
        FROM alvo_tipo a
        JOIN pg_attribute c ON c.attrelid = format('public.%I', a.tabela)::regclass AND c.attname = a.coluna
        WHERE format_type(c.atttypid, c.atttypmod) <> a.tipo
        UNION ALL
        SELECT format('indice %s', a.nome)
        FROM alvo_indice a
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
            WHERE x.indrelid = format('public.%I', a.tabela)::regclass AND i.relname = a.nome
              AND x.indisunique = a.unico
              AND regexp_replace(pg_get_indexdef(x.indexrelid), '^CREATE (UNIQUE )?INDEX \S+ ON \S+ ', '') = a.definicao
        )
        UNION ALL
        SELECT format('chave %s', a.nome)
        FROM alvo_chave a
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_constraint k
            WHERE k.conrelid = format('public.%I', a.tabela)::regclass AND k.contype = 'f' AND k.conname = a.nome
        )
        UNION ALL
        SELECT format('check %s', a.nome)
        FROM alvo_check a
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_constraint k
            WHERE k.conrelid = format('public.%I', a.tabela)::regclass AND k.contype = 'c'
              AND k.conname = a.nome AND pg_get_constraintdef(k.oid) = a.definicao
        )
        UNION ALL
        SELECT format('unicidade %s', a.nome)
        FROM alvo_unico a
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_constraint k
            WHERE k.conrelid = format('public.%I', a.tabela)::regclass AND k.contype = 'u' AND k.conname = a.nome
        )
        UNION ALL
        SELECT format('indice a mais %s', i.relname)
        FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_class t ON t.oid = x.indrelid
        WHERE t.relnamespace = 'public'::regnamespace
          AND t.relname IN (SELECT tabela FROM alvo_indice)
          AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = x.indexrelid)
          AND NOT EXISTS (SELECT 1 FROM alvo_indice a WHERE a.tabela = t.relname AND a.nome = i.relname)
        UNION ALL
        SELECT format('sequencia solta em %s', c.relname)
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
          AND pg_get_expr(d.adbin, d.adrelid) LIKE 'nextval(%'
          AND c.relname IN (SELECT tabela FROM alvo_indice)
    ) itens;
    IF falta IS NOT NULL THEN
        RAISE EXCEPTION 'o esquema nao chegou ao das migracoes: %', falta;
    END IF;
END $$;
