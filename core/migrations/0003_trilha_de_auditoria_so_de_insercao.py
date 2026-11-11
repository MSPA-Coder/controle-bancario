"""A trilha de auditoria aceita inserção; alterar e apagar ficam com o administrador.

O papel da aplicação tinha UPDATE e DELETE em `audit_log` (o `db-provision`
concede DML em todas as tabelas, a cada subida, então um REVOKE não duraria).
Nunca usou: até 10/11/2026 a tabela tinha zero alterações e zero exclusões. Mas
um defeito, ou alguém com a sessão da aplicação, podia apagar o próprio rastro.

O gatilho recusa UPDATE e DELETE de quem não é superusuário. Uma exceção: a
chave `user_id` é `SET NULL`, e apagar um usuário precisa anular a referência
nos registros dele. Essa alteração, e só ela, passa; `actor_id` e `actor_name`
continuam dizendo quem fez.

O papel administrativo (o do `migrate`, do backup e da suíte) é superusuário e
não é afetado: expurgo e correção da trilha continuam possíveis, por ele.
"""

from django.db import migrations

SQL = """
CREATE FUNCTION public.audit_log_somente_insercao() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.user_id IS NULL
            AND to_jsonb(NEW) - 'user_id' = to_jsonb(OLD) - 'user_id' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_log aceita apenas insercao (papel %)', current_user
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER audit_log_somente_insercao
    BEFORE UPDATE OR DELETE ON public.audit_log
    FOR EACH ROW EXECUTE FUNCTION public.audit_log_somente_insercao();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_log_somente_insercao ON public.audit_log;
DROP FUNCTION IF EXISTS public.audit_log_somente_insercao();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_alinhar_esquema_de_producao'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
    ]
