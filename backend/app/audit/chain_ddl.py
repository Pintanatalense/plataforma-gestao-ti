"""
Auditoria imutável no PostgreSQL (ADR-023; Plano de Evolução, Fase 0 PR 11; S4).

- gatilho ``audit_logs_guard``: a tabela é só de inserção. UPDATE só no selo (função ``audit_seal``) e DELETE só na
  retenção (função ``audit_purge``); TRUNCATE nunca. Vale também para o dono das tabelas;
- selo em cadeia de hash, **uma cadeia por categoria** (a retenção de cada uma apaga só o começo da própria cadeia):
  ``row_hash = sha256(prev_hash, campos do registro)``; ``audit_chain_state`` guarda o fim da cadeia e a âncora
  (o hash do último registro apagado pela retenção);
- ``audit_verify()`` recalcula a cadeia e aponta o primeiro problema (lacuna, elo ou conteúdo alterado).

As duas funções que escrevem são ``SECURITY DEFINER`` (rodam como o dono); a aplicação só recebe EXECUTE nelas
(``app/db_roles.py``). A aplicação não tem UPDATE/DELETE em ``audit_logs``.

**Versões congeladas:** a migration ``y5c6d7e8f9a0b`` aplica ``CHAIN_DDL_V1``. Mudou alguma função? Crie
``CHAIN_DDL_V2`` (com ``CREATE OR REPLACE``) numa migration nova e aponte ``CURRENT`` para ela; nunca edite a V1.
``CURRENT`` também é aplicada pelo ``create_all`` dos testes em PostgreSQL.
"""

CHAIN_LOCK_KEY = 0x6774695F61756474  # "gti_audt": serializa selo e retenção
GENESIS_HASH = "0" * 64

_HASH_ARGS = (
    "prev text, p_id uuid, p_event_type text, p_entity_type text, p_entity_id uuid, p_data jsonb, p_user_id uuid, "
    "p_actor_kind text, p_actor_email text, p_category text, p_ip text, p_request_id text, p_created_at timestamptz"
)
_HASH_CALL = (
    "{prev}, {r}.id, {r}.event_type, {r}.entity_type, {r}.entity_id, {r}.data, {r}.user_id, {r}.actor_kind, "
    "{r}.actor_email, {r}.category, {r}.ip, {r}.request_id, {r}.created_at"
)

CHAIN_DDL_V1: tuple[str, ...] = (
    f"""
    CREATE OR REPLACE FUNCTION audit_row_hash({_HASH_ARGS}) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $fn$
      SELECT encode(sha256(convert_to(concat_ws(chr(31),
        prev, p_id::text, p_event_type, coalesce(p_entity_type, ''), coalesce(p_entity_id::text, ''),
        coalesce(p_data::text, ''), coalesce(p_user_id::text, ''), coalesce(p_actor_kind, ''),
        coalesce(p_actor_email, ''), coalesce(p_category, ''), coalesce(p_ip, ''), coalesce(p_request_id, ''),
        to_char(p_created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')), 'UTF8')), 'hex')
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION audit_logs_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
    DECLARE
      mode text := coalesce(current_setting('gti.audit_mode', true), '');
    BEGIN
      IF TG_OP = 'INSERT' THEN
        IF NEW.chain_pos IS NOT NULL OR NEW.prev_hash IS NOT NULL OR NEW.row_hash IS NOT NULL THEN
          RAISE EXCEPTION 'audit_logs: o selo da cadeia é atribuído só pelo banco' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
      ELSIF TG_OP = 'UPDATE' THEN
        IF mode = 'seal' AND OLD.row_hash IS NULL AND NEW.row_hash IS NOT NULL
           AND (to_jsonb(NEW) - ARRAY['chain_pos', 'prev_hash', 'row_hash'])
             = (to_jsonb(OLD) - ARRAY['chain_pos', 'prev_hash', 'row_hash']) THEN
          RETURN NEW;
        END IF;
        RAISE EXCEPTION 'audit_logs é somente inserção: alteração recusada' USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF mode = 'retention' AND OLD.row_hash IS NOT NULL THEN
        RETURN OLD;
      END IF;
      RAISE EXCEPTION 'audit_logs é somente inserção: exclusão só pela retenção' USING ERRCODE = 'insufficient_privilege';
    END
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION audit_logs_no_truncate() RETURNS trigger
    LANGUAGE plpgsql AS $fn$
    BEGIN
      RAISE EXCEPTION 'audit_logs é somente inserção: TRUNCATE recusado' USING ERRCODE = 'insufficient_privilege';
    END
    $fn$
    """,
    "DROP TRIGGER IF EXISTS audit_logs_guard ON audit_logs",
    "CREATE TRIGGER audit_logs_guard BEFORE INSERT OR UPDATE OR DELETE ON audit_logs "
    "FOR EACH ROW EXECUTE FUNCTION audit_logs_guard()",
    "DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs",
    "CREATE TRIGGER audit_logs_no_truncate BEFORE TRUNCATE ON audit_logs "
    "FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_no_truncate()",
    f"""
    CREATE OR REPLACE FUNCTION audit_seal(p_limit integer DEFAULT 5000) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
    DECLARE
      r record;
      st record;
      h text;
      n integer := 0;
    BEGIN
      PERFORM pg_advisory_xact_lock({CHAIN_LOCK_KEY});
      PERFORM set_config('gti.audit_mode', 'seal', true);  -- só durante esta função (liberado no fim)
      FOR r IN SELECT * FROM audit_logs a WHERE a.row_hash IS NULL ORDER BY a.created_at, a.id
               LIMIT greatest(p_limit, 1) FOR UPDATE LOOP
        SELECT * INTO st FROM audit_chain_state s WHERE s.category = r.category FOR UPDATE;
        IF NOT FOUND THEN
          INSERT INTO audit_chain_state (category, last_pos, last_hash, anchor_pos, anchor_hash, updated_at)
          VALUES (r.category, 0, '{GENESIS_HASH}', 0, '{GENESIS_HASH}', now())
          RETURNING * INTO st;
        END IF;
        h := audit_row_hash({_HASH_CALL.format(prev="st.last_hash", r="r")});
        UPDATE audit_logs SET chain_pos = st.last_pos + 1, prev_hash = st.last_hash, row_hash = h WHERE id = r.id;
        UPDATE audit_chain_state SET last_pos = st.last_pos + 1, last_hash = h, updated_at = now()
         WHERE category = r.category;
        n := n + 1;
      END LOOP;
      PERFORM set_config('gti.audit_mode', '', true);
      RETURN n;
    END
    $fn$
    """,
    f"""
    CREATE OR REPLACE FUNCTION audit_purge(p_category text, p_days integer, p_max_pos bigint) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
    DECLARE
      min_days integer := CASE p_category WHEN 'security' THEN 1825 WHEN 'operational' THEN 30 END;
      cutoff timestamptz;
      st record;
      h text;
      n integer;
    BEGIN
      IF min_days IS NULL OR p_days IS NULL OR p_days < min_days THEN
        RAISE EXCEPTION 'retenção recusada: % exige pelo menos % dias', p_category, min_days
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      PERFORM pg_advisory_xact_lock({CHAIN_LOCK_KEY});
      cutoff := now() - make_interval(days => p_days);
      SELECT * INTO st FROM audit_chain_state s WHERE s.category = p_category FOR UPDATE;
      IF NOT FOUND OR p_max_pos <= st.anchor_pos OR p_max_pos > st.last_pos THEN
        RAISE EXCEPTION 'retenção recusada: posição % fora da cadeia %', p_max_pos, p_category;
      END IF;
      IF EXISTS (SELECT 1 FROM audit_logs a WHERE a.category = p_category AND a.chain_pos <= p_max_pos
                 AND a.created_at >= cutoff) THEN
        RAISE EXCEPTION 'retenção recusada: só registros vencidos (antes de %) podem sair', cutoff
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      SELECT a.row_hash INTO h FROM audit_logs a WHERE a.category = p_category AND a.chain_pos = p_max_pos;
      IF h IS NULL THEN
        RAISE EXCEPTION 'retenção recusada: posição % não encontrada', p_max_pos;
      END IF;
      PERFORM set_config('gti.audit_mode', 'retention', true);  -- só durante esta função (liberado no fim)
      DELETE FROM audit_logs a WHERE a.category = p_category AND a.chain_pos <= p_max_pos;
      GET DIAGNOSTICS n = ROW_COUNT;
      PERFORM set_config('gti.audit_mode', '', true);
      UPDATE audit_chain_state SET anchor_pos = p_max_pos, anchor_hash = h, updated_at = now()
       WHERE category = p_category;
      RETURN n;
    END
    $fn$
    """,
    f"""
    CREATE OR REPLACE FUNCTION audit_verify()
    RETURNS TABLE (chain_category text, checked bigint, chain_last_pos bigint, problem text)
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
    DECLARE
      st record;
      r record;
      exp_pos bigint;
      exp_prev text;
      n bigint;
      bad text;
    BEGIN
      FOR st IN SELECT * FROM audit_chain_state s ORDER BY s.category LOOP
        exp_pos := st.anchor_pos + 1;
        exp_prev := st.anchor_hash;
        n := 0;
        bad := NULL;
        FOR r IN SELECT * FROM audit_logs a WHERE a.category = st.category AND a.chain_pos IS NOT NULL
                 ORDER BY a.chain_pos LOOP
          IF r.chain_pos <> exp_pos THEN
            bad := format('posição %s ausente (a seguinte é %s)', exp_pos, r.chain_pos);
            EXIT;
          END IF;
          IF r.prev_hash IS DISTINCT FROM exp_prev THEN
            bad := format('posição %s: o elo com o registro anterior não confere', r.chain_pos);
            EXIT;
          END IF;
          IF r.row_hash IS DISTINCT FROM audit_row_hash({_HASH_CALL.format(prev="r.prev_hash", r="r")}) THEN
            bad := format('posição %s: conteúdo alterado', r.chain_pos);
            EXIT;
          END IF;
          exp_prev := r.row_hash;
          exp_pos := exp_pos + 1;
          n := n + 1;
        END LOOP;
        IF bad IS NULL AND (exp_pos - 1 <> st.last_pos OR exp_prev <> st.last_hash) THEN
          bad := format('fim da cadeia: esperado até a posição %s, encontrado até %s', st.last_pos, exp_pos - 1);
        END IF;
        chain_category := st.category;
        checked := n;
        chain_last_pos := st.last_pos;
        problem := bad;
        RETURN NEXT;
      END LOOP;
    END
    $fn$
    """,
    "REVOKE EXECUTE ON FUNCTION audit_seal(integer) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION audit_purge(text, integer, bigint) FROM PUBLIC",
)

CHAIN_DROP_V1: tuple[str, ...] = (
    "DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs",
    "DROP TRIGGER IF EXISTS audit_logs_guard ON audit_logs",
    "DROP FUNCTION IF EXISTS audit_verify()",
    "DROP FUNCTION IF EXISTS audit_purge(text, integer, bigint)",
    "DROP FUNCTION IF EXISTS audit_seal(integer)",
    "DROP FUNCTION IF EXISTS audit_logs_no_truncate()",
    "DROP FUNCTION IF EXISTS audit_logs_guard()",
    f"DROP FUNCTION IF EXISTS audit_row_hash({_HASH_ARGS})",
)

CURRENT = CHAIN_DDL_V1
