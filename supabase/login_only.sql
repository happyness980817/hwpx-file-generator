-- Supabase SQL Editor, postgres. Run ONLY if public.profiles does not exist.
-- If 001_schema.sql has already been applied, skip this file.
begin;

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete restrict,
  username text not null unique check (username ~ '^[a-z][a-z0-9_]{2,31}$'),
  display_name text not null check (length(display_name) between 1 and 80),
  role text not null default 'sales' check (role in ('admin', 'sales')),
  active boolean not null default true,
  must_change_password boolean not null default true,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;
revoke all on public.profiles from public, anon, authenticated;
grant select on public.profiles to authenticated;
grant all on public.profiles to service_role;

-- Reading one's own status is allowed even before the first password change.
-- The application blocks inactive accounts and gates the document UI.
create policy profiles_read_self on public.profiles
for select to authenticated using (user_id = (select auth.uid()));

commit;
select 'Login profile table created. Create an Auth user, then run register_login.sql.' as result;
