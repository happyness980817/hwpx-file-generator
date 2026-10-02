-- FIRST create three confirmed email/password users in Authentication > Users.
-- Replace ONLY the three example emails and display names below.
-- Never put passwords or API keys into SQL Editor.
begin;
create temporary table kbrand_initial_accounts (
  email text primary key,
  username text not null unique,
  display_name text not null,
  role text not null
) on commit drop;

insert into kbrand_initial_accounts (email, username, display_name, role) values
  ('managergoal@iyouproject.com', 'admin', '관리자', 'admin'),
  ('REPLACE_SALES01@example.com', 'sales01', '영업 담당자 1', 'sales'),
  ('REPLACE_SALES02@example.com', 'sales02', '영업 담당자 2', 'sales');

do $$
begin
  if exists(select 1 from kbrand_initial_accounts where email ilike '%REPLACE_%' or email ilike '%@example.com') then
    raise exception 'Replace the three example emails with the actual Auth user emails first.';
  end if;
  if (select count(*) from kbrand_initial_accounts i join auth.users u on lower(u.email) = lower(i.email)) <> 3 then
    raise exception 'Expected exactly 3 matching Auth users. Create users in Authentication > Users and check emails.';
  end if;
  if exists(select 1 from kbrand_initial_accounts i join auth.users u on lower(u.email) = lower(i.email) where u.email_confirmed_at is null) then
    raise exception 'An Auth email is unconfirmed. Confirm the issued account before registering its profile.';
  end if;
  if exists(select 1 from public.profiles p join kbrand_initial_accounts i on p.username = i.username)
     or exists(select 1 from public.profiles p join auth.users u on u.id = p.user_id join kbrand_initial_accounts i on lower(i.email) = lower(u.email)) then
    raise exception 'An account is already registered. No roles were changed. Check 004_verify.sql instead of rerunning.';
  end if;
end $$;

insert into public.profiles (user_id, username, display_name, role)
select u.id, i.username, i.display_name, i.role
from kbrand_initial_accounts i join auth.users u on lower(u.email) = lower(i.email);
commit;

select username, display_name, role, active, must_change_password
from public.profiles order by username;
