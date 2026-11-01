CREATE ROLE supabase_auth_admin LOGIN PASSWORD 'unused';
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN BYPASSRLS;
CREATE SCHEMA auth AUTHORIZATION supabase_auth_admin;
GRANT ALL ON DATABASE journeys TO supabase_auth_admin;
GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
