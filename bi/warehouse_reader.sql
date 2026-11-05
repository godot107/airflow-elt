-- Cube connects as a read-only role that can see the published marts and nothing else (no raw, no staging,
-- no audit). Default privileges cover tables dbt re-creates on every run. Idempotent; make bi-up runs it.
do $$
begin
    if not exists (select from pg_roles where rolname = 'cube_reader') then
        create role cube_reader login;
    end if;
end $$;
alter role cube_reader password :'pw';
grant connect on database warehouse to cube_reader;
create schema if not exists marts;
grant usage on schema marts to cube_reader;
grant select on all tables in schema marts to cube_reader;
alter default privileges for role warehouse in schema marts grant select on tables to cube_reader;
