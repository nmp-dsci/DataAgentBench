-- DataAgentBench: one schema, two roles. Idempotent; runs unchanged against the
-- central Postgres when the data migrates there (plan s01 §8, M8).
--
--   dab_owner  loads and writes: the benchmark tables, the app-state tables.
--   dab_agent  what the agent's query_db connects as: SELECT on the schema only,
--              a 60 s statement timeout, no privilege anywhere else.
--
-- Passwords are local-only defaults (DATABASE_URL / AGENT_DATABASE_URL override).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dab_owner') THEN
    CREATE ROLE dab_owner LOGIN PASSWORD 'dab_owner';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dab_agent') THEN
    CREATE ROLE dab_agent LOGIN PASSWORD 'dab_agent';
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS dataagentbench AUTHORIZATION dab_owner;

GRANT USAGE ON SCHEMA dataagentbench TO dab_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA dataagentbench TO dab_agent;
ALTER DEFAULT PRIVILEGES FOR ROLE dab_owner IN SCHEMA dataagentbench
  GRANT SELECT ON TABLES TO dab_agent;

-- The agent role sees the schema by default and cannot run long or write anywhere.
ALTER ROLE dab_agent SET search_path = dataagentbench;
ALTER ROLE dab_agent SET statement_timeout = '60s';
ALTER ROLE dab_agent SET default_transaction_read_only = on;
REVOKE CREATE ON SCHEMA public FROM dab_agent;
REVOKE ALL ON SCHEMA public FROM dab_agent;
ALTER ROLE dab_owner SET search_path = dataagentbench, public;

-- The question set's copy (`dab data load-questions`) lives apart from the benchmark
-- data: every question, its gold answer and its validator. dataagentbench grants SELECT
-- to dab_agent by default, so a gold table there would hand the agent the answers. This
-- schema grants nothing, and dab_agent's search_path above does not include it.
CREATE SCHEMA IF NOT EXISTS dataagentbench_meta AUTHORIZATION dab_owner;
REVOKE ALL ON SCHEMA dataagentbench_meta FROM PUBLIC;
REVOKE ALL ON SCHEMA dataagentbench_meta FROM dab_agent;
ALTER DEFAULT PRIVILEGES FOR ROLE dab_owner IN SCHEMA dataagentbench_meta
  REVOKE SELECT ON TABLES FROM dab_agent;
