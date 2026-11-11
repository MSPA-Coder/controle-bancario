"""Migração nova não repete nome que a produção já registra como aplicado.

Em 03/11/2026 as 60 migrações viraram uma base por app. O `django_migrations`
de produção continua guardando os nomes antigos, desde agosto. Se uma migração
nova nascer com um desses nomes, o Django a dá por aplicada e não a roda: a
suíte, que parte de um banco vazio, aplica e passa; a produção pula calada, e o
código passa a esperar um esquema que nunca chegou.

A lista abaixo é o que a produção registrava em 10/11/2026 para os apps deste
repositório. Os nomes da base atual estão nela de propósito: são os que a
produção precisava já ter. Qualquer outro arquivo de migração tem de ter nome
novo.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db.migrations.loader import MigrationLoader

# Base de 03/11/2026: reaproveita, de propósito, nomes já registrados.
BASE = {
    ("accounts", "0001_initial"),
    ("accounts", "0002_initial"),
    ("bank_statements", "0001_initial"),
    ("banking", "0001_initial"),
    ("core", "0001_initial"),
    ("fechamento", "0001_initial"),
    ("management", "0001_initial"),
    ("transactions", "0001_initial"),
}

JA_REGISTRADAS = {
    "accounts": {
        "0001_initial",
        "0002_initial",
        "0003_remove_appuser_ck_app_user_user_type_valid_and_more",
        "0003_seed_permission_catalog",
        "0004_create_missing_auth_m2m_tables",
        "0004_rename_banking_permission_description",
        "0005_remove_accountowner_document_alter_accountowner_name",
        "0005_remover_permissoes_orfas",
        "0006_add_annual_planning_permission",
        "0006_seed_permission_catalog",
        "0007_alter_apppermission_name_column",
        "0007_remover_permissoes_orfas_de_agosto",
        "0008_accountowner_name_ci_unique",
        "0008_seed_banking_permissions",
        "0009_seed_banking_reconcile_permission",
        "0009_user_transfer_destination_access",
        "0010_remover_contas_em_analises",
        "0010_seed_operations_and_attachments_permissions",
        "0011_appuser_regional_format",
        "0011_fix_userpermission_visibility_lockout_columns",
        "0012_appuser_language_regional_auto",
        "0012_seed_settings_and_permissions_catalog",
        "0013_add_banking_reclassify_permission",
        "0013_seed_management_permissions",
        "0014_drop_legacy_login_lockout_last_failure_at",
        "0015_drop_legacy_app_user_user_name",
        "0016_seed_missing_permission_catalog_entries",
        "0017_drop_legacy_password_hash_column",
    },
    "bank_statements": {
        "0001_initial",
        "0002_entryattachment",
        "0002_fatura_de_cartao",
        "0003_fix_import_batch_db_column",
        "0003_pendingstatementupload",
        "0004_fix_import_batch_index_state",
        "0004_regras_e_saldo_do_extrato",
        "0005_regra_com_instituicao_de_destino",
        "0006_regra_para_aplicacao_vinculada",
        "0007_fim_do_periodo_do_extrato",
        "0008_pdf_com_senha",
        "0009_carteira_do_extrato",
    },
    "banking": {
        "0001_initial",
        "0002_alter_financialaccount_institution_and_more",
        "0002_financialinstitution_homologada",
        "0003_financialinstitution_name_ci_unique",
        "0004_conta_moeda_e_data_do_saldo_inicial",
        "0005_conta_tipo_cartao_de_credito",
        "0006_cartao_gasto_estimado",
        "0007_conta_tipo_aplicacao",
        "0008_mercadopago_homologada",
        "0009_financialaccount_statement_identifier",
        "0010_finalidade_da_conta",
        "0011_xp_investimentos_homologada",
        "0012_itau_homologada",
        "0013_conta_de_movimento_da_aplicacao",
        "0014_avenue_homologada",
    },
    "core": {
        "0001_initial",
        "0002_auditlog_request_context",
        "0002_datetime_columns_with_time_zone",
        "0003_patrimonio_v4_outbox",
        "0004_esquema_leitura",
        "0005_leitura_saldo_conferido",
        "0006_leitura_categoria_valorizacao",
    },
    "fechamento": {
        "0001_initial",
        "0002_saldo_conferido_por_origem",
    },
    "management": {
        "0001_initial",
        "0002_managementtag_active_monthlybudget_active_and_more",
        "0002_remove_monthlybudget_actual_amount",
    },
    "transactions": {
        "0001_initial",
        "0002_remove_bankoperation_ck_bank_operation_status_valid_and_more",
        "0002_remover_status_cancelado",
        "0003_alter_cashflowentry_account_and_more",
        "0003_bankoperation_responsible_user",
        "0004_categoria_tipo",
        "0004_drop_legacy_operation_id_column",
        "0005_realizado_exige_data",
        "0006_encerramento_da_recorrencia",
        "0007_remover_contadores_da_operacao",
        "0008_integridade_da_transferencia",
        "0009_grupos_de_categoria",
        "0010_envio_de_lancamento",
        "0011_detalhe_de_investimento",
        "0012_categoria_valorizacao",
        "0013_cupom_no_detalhe_de_investimento",
        "0014_quantidade_da_liquidacao",
    },
}


def test_migracao_nova_nao_repete_nome_ja_registrado_em_producao():
    # Sem conexão: só os arquivos interessam, não o que este banco já aplicou.
    loader = MigrationLoader(None, ignore_no_migrations=True)

    repetidas = sorted(
        f"{app}/{nome}"
        for app, nome in loader.disk_migrations
        if nome in JA_REGISTRADAS.get(app, ()) and (app, nome) not in BASE
    )

    assert not repetidas, (
        "A produção já registra estes nomes como aplicados e não rodaria as migrações: "
        + ", ".join(repetidas)
        + ". Renomeie o arquivo."
    )


IGUALA_O_ESQUEMA = ("core", "0004_igualar_esquema_ao_das_migracoes")

# Anteriores à `core/0004` por construção: a base e as duas que ela pressupõe.
ANTERIORES_A_IGUALACAO = BASE | {
    ("core", "0002_alinhar_esquema_de_producao"),
    ("core", "0003_trilha_de_auditoria_so_de_insercao"),
    IGUALA_O_ESQUEMA,
}


def test_migracao_do_projeto_depende_da_que_iguala_o_esquema():
    """A `core/0004` confere, no fim, se o esquema é exatamente o alvo.

    Num banco novo, uma migração do projeto que rodasse antes dela deixaria o
    esquema fora do alvo e a `0004` falharia. Por isso toda migração dos apps
    deste repositório, fora a base e as duas primeiras do `core`, a tem como
    ancestral.
    """
    # Sem conexão: o grafo vem dos arquivos.
    loader = MigrationLoader(None, ignore_no_migrations=True)
    raiz = settings.BASE_DIR.resolve()
    # Apps do projeto: os que moram sob a pasta do repositório (e não em site-packages).
    apps_do_projeto = {
        config.label
        for config in apps.get_app_configs()
        if Path(config.path).resolve().is_relative_to(raiz)
        and "site-packages" not in Path(config.path).parts
    }

    sem_ancestral = sorted(
        f"{app}/{nome}"
        for app, nome in loader.disk_migrations
        if app in apps_do_projeto
        and (app, nome) not in ANTERIORES_A_IGUALACAO
        and IGUALA_O_ESQUEMA not in loader.graph.forwards_plan((app, nome))
    )

    assert not sem_ancestral, (
        "Estas migrações não dependem da core/0004_igualar_esquema_ao_das_migracoes: "
        + ", ".join(sem_ancestral)
        + ". Acrescente essa migração (ou outra que já dependa dela) às `dependencies`."
    )


def test_a_base_e_so_o_que_a_producao_ja_tinha():
    """Se a base ganhar um nome que a produção não registra, ela rodaria lá do zero."""
    fora = sorted(f"{app}/{nome}" for app, nome in BASE if nome not in JA_REGISTRADAS.get(app, ()))

    assert not fora, f"nomes da base que a produção não registra: {fora}"
