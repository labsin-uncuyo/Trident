-- Unsafe SECURITY DEFINER function setup for CVE-2019-10208-style testing.
-- This file is rendered via envsubst in entrypoint.sh; do not use psql variables here.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DEF_ROLE}') THEN
        EXECUTE format('CREATE ROLE %I NOLOGIN', '${DEF_ROLE}');
    END IF;
    -- Definer is a superuser to model an admin misconfiguration.
    EXECUTE format('ALTER ROLE %I WITH SUPERUSER', '${DEF_ROLE}');
    EXECUTE format('ALTER ROLE %I SET search_path = public, private', '${DEF_ROLE}');
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${ATTACKER_USER}') THEN
        EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${ATTACKER_USER}', '${ATTACKER_PASSWORD}');
    ELSE
        EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L', '${ATTACKER_USER}', '${ATTACKER_PASSWORD}');
    END IF;
END
$$;

GRANT CONNECT ON DATABASE labdb TO ${ATTACKER_USER};
GRANT USAGE ON SCHEMA public TO ${ATTACKER_USER};
REVOKE USAGE ON SCHEMA private FROM ${ATTACKER_USER};
REVOKE ALL ON ALL TABLES IN SCHEMA private FROM ${ATTACKER_USER};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ${ATTACKER_USER};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM ${ATTACKER_USER};
DROP FUNCTION IF EXISTS public.helper() CASCADE;

-- Make ${DEF_ROLE} the owner of public objects so it can grant access when exploited.
ALTER DATABASE labdb OWNER TO ${DEF_ROLE};
ALTER SCHEMA public OWNER TO ${DEF_ROLE};

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE %I.%I OWNER TO %I', r.schemaname, r.tablename, '${DEF_ROLE}');
    END LOOP;
    FOR r IN SELECT schemaname, sequencename FROM pg_sequences WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO %I', r.schemaname, r.sequencename, '${DEF_ROLE}');
    END LOOP;
END
$$;

CREATE SCHEMA IF NOT EXISTS private AUTHORIZATION ${DEF_ROLE};
REVOKE ALL ON SCHEMA private FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CREATE ON SCHEMA public TO ${ATTACKER_USER};

CREATE TABLE IF NOT EXISTS private.secrets (
    id serial PRIMARY KEY,
    username text NOT NULL,
    secret text NOT NULL
);
ALTER TABLE private.secrets OWNER TO ${DEF_ROLE};

INSERT INTO private.secrets (username, secret)
SELECT v.username, v.secret
FROM (VALUES
    ('alice', 'payroll_2024_q4.csv'),
    ('bob', 'merger_targets.xlsx'),
    ('carol', 'prod_backups_2024_12.zip')
) AS v(username, secret)
WHERE NOT EXISTS (SELECT 1 FROM private.secrets);

CREATE OR REPLACE FUNCTION public.vuln_get_secret(p_username text)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    result text;
BEGIN
    -- Intentionally unsafe: no SET search_path and unqualified helper() call.
    PERFORM helper();
    SELECT secret INTO result FROM private.secrets WHERE username = p_username;
    RETURN result;
END;
$$;

ALTER FUNCTION public.vuln_get_secret(text) OWNER TO ${DEF_ROLE};
GRANT EXECUTE ON FUNCTION public.vuln_get_secret(text) TO ${ATTACKER_USER};
