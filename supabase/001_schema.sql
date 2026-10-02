-- Supabase SQL Editor / postgres role. Initial installation only.
-- Creates four tables and a private helper schema. Does not delete existing data.
begin;

do $$
begin
  if to_regclass('public.profiles') is not null
     or to_regclass('public.clients') is not null
     or to_regclass('public.document_jobs') is not null
     or to_regclass('public.documents') is not null
     or to_regnamespace('kbrand_private') is not null then
    raise exception 'K-brand objects already exist. Do not delete them or rerun this initial script; use 004_verify.sql and review a migration.';
  end if;
end $$;

create schema kbrand_private;
revoke all on schema kbrand_private from public, anon, authenticated;
grant usage on schema kbrand_private to authenticated, service_role;

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete restrict,
  username text not null unique check (username ~ '^[a-z][a-z0-9_]{2,31}$'),
  display_name text not null check (length(display_name) between 1 and 80),
  role text not null default 'sales' check (role in ('admin', 'sales')),
  active boolean not null default true,
  must_change_password boolean not null default true,
  created_at timestamptz not null default now()
);

create table public.clients (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references public.profiles(user_id) on delete restrict,
  company_name text not null check (length(btrim(company_name)) between 1 and 80),
  input_data jsonb not null default '{}'::jsonb check (jsonb_typeof(input_data) = 'object'),
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, owner_id)
);

create table public.document_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references public.profiles(user_id) on delete restrict,
  client_id uuid not null,
  request_key uuid not null default gen_random_uuid(),
  input_snapshot jsonb not null check (jsonb_typeof(input_snapshot) = 'object'),
  status text not null default 'queued' check (status in ('queued', 'running', 'succeeded', 'failed')),
  attempts integer not null default 0 check (attempts >= 0),
  lease_until timestamptz,
  error_message text,
  template_version text,
  prompt_version text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id, request_key),
  unique (id, owner_id),
  foreign key (client_id, owner_id) references public.clients(id, owner_id) on delete restrict
);

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete restrict,
  job_id uuid not null,
  kind text not null check (kind in ('application', 'plan', 'bundle')),
  storage_bucket text not null default 'generated-documents' check (storage_bucket = 'generated-documents'),
  storage_path text not null unique,
  filename text not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  byte_size bigint not null check (byte_size > 0 and byte_size <= 20971520),
  created_at timestamptz not null default now(),
  unique (job_id, kind),
  foreign key (job_id, owner_id) references public.document_jobs(id, owner_id) on delete restrict,
  check (split_part(storage_path, '/', 1) = owner_id::text
     and split_part(storage_path, '/', 2) = job_id::text
     and split_part(storage_path, '/', 3) in ('application.hwpx', 'plan.hwpx', 'bundle.zip')
     and array_length(string_to_array(storage_path, '/'), 1) = 3)
);

create index clients_owner_updated_idx on public.clients(owner_id, updated_at desc);
create index document_jobs_owner_created_idx on public.document_jobs(owner_id, created_at desc);
create index document_jobs_client_idx on public.document_jobs(client_id);
create index document_jobs_queue_idx on public.document_jobs(status, created_at) where status in ('queued', 'running');
create index documents_owner_job_idx on public.documents(owner_id, job_id);

-- These narrowly scoped helpers avoid recursive RLS on profiles.
-- Do not expose kbrand_private in Data API settings.
create function kbrand_private.is_active()
returns boolean language sql stable security definer set search_path = ''
as $$ select exists(select 1 from public.profiles p where p.user_id = auth.uid() and p.active) $$;

create function kbrand_private.is_admin()
returns boolean language sql stable security definer set search_path = ''
as $$ select exists(select 1 from public.profiles p where p.user_id = auth.uid()
      and p.active and not p.must_change_password and p.role = 'admin') $$;

create function kbrand_private.can_access_owner(target_owner uuid)
returns boolean language sql stable security definer set search_path = ''
as $$ select exists(select 1 from public.profiles p where p.user_id = auth.uid()
      and p.active and not p.must_change_password
      and (p.user_id = target_owner or p.role = 'admin')) $$;

create function kbrand_private.touch_updated_at()
returns trigger language plpgsql set search_path = ''
as $$ begin new.updated_at = now(); return new; end $$;

create trigger clients_touch before update on public.clients
for each row execute function kbrand_private.touch_updated_at();
create trigger jobs_touch before update on public.document_jobs
for each row execute function kbrand_private.touch_updated_at();

revoke all on all functions in schema kbrand_private from public, anon, authenticated;
grant execute on function kbrand_private.is_active(), kbrand_private.is_admin(),
  kbrand_private.can_access_owner(uuid) to authenticated, service_role;

alter table public.profiles enable row level security;
alter table public.clients enable row level security;
alter table public.document_jobs enable row level security;
alter table public.documents enable row level security;

-- Remove inherited/default grants before granting the intended column privileges.
revoke all on public.profiles, public.clients, public.document_jobs, public.documents from public, anon, authenticated;
grant usage on schema public to authenticated, service_role;
grant all on public.profiles, public.clients, public.document_jobs, public.documents to service_role;
grant select on public.profiles, public.clients, public.document_jobs, public.documents to authenticated;
grant insert (company_name, input_data) on public.clients to authenticated;
grant update (company_name, input_data, archived) on public.clients to authenticated;
grant insert (client_id, request_key, input_snapshot) on public.document_jobs to authenticated;

create policy profiles_read on public.profiles for select to authenticated
using (kbrand_private.is_active() and (user_id = (select auth.uid()) or kbrand_private.is_admin()));
create policy clients_read on public.clients for select to authenticated
using (kbrand_private.can_access_owner(owner_id));
create policy clients_insert on public.clients for insert to authenticated
with check (owner_id = (select auth.uid()) and kbrand_private.can_access_owner(owner_id));
create policy clients_update on public.clients for update to authenticated
using (kbrand_private.can_access_owner(owner_id)) with check (kbrand_private.can_access_owner(owner_id));
create policy jobs_read on public.document_jobs for select to authenticated
using (kbrand_private.can_access_owner(owner_id));
create policy jobs_insert on public.document_jobs for insert to authenticated
with check (owner_id = (select auth.uid()) and kbrand_private.can_access_owner(owner_id)
  and exists (select 1 from public.clients c where c.id = client_id and c.owner_id = (select auth.uid()) and not c.archived));
create policy documents_read on public.documents for select to authenticated
using (kbrand_private.can_access_owner(owner_id));

-- No user INSERT/UPDATE of profiles, no client ownership transfer,
-- no user status/metadata writes, and no hard DELETE. Server admin code is required.
commit;

select '001 OK - 4 tables created; RLS enabled; no accounts or files created' as result;
