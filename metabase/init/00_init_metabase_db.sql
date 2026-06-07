-- Runs once on Postgres first start (docker-entrypoint-initdb.d).
-- Creates a separate Metabase database so Metabase's internal state never
-- pollutes the project_ot schema.
CREATE DATABASE metabase;
CREATE DATABASE n8n;
