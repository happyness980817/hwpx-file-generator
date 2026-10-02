-- Create ONE confirmed email/password account in Authentication > Users first.
-- Replace the email, username and display name below. Never put a password here.
-- Run the WHOLE file in SQL Editor / postgres. Safe to stop on duplicate accounts.
begin;
do $$
declare
  account_email text := 'REPLACE_EMAIL@example.com';
  account_username text := 'sales01';
  account_display_name text := '영업 담당자 1';
  account_id uuid;
begin
  if account_email ilike '%REPLACE_%' or account_email ilike '%@example.com' then
    raise exception 'Replace account_email with the email of the confirmed Auth user.';
  end if;
  if (select count(*) from auth.users where lower(email) = lower(account_email) and email_confirmed_at is not null) <> 1 then
    raise exception 'Expected exactly one confirmed Auth user. Check Authentication > Users.';
  end if;
  select id into strict account_id from auth.users
    where lower(email) = lower(account_email) and email_confirmed_at is not null;
  insert into public.profiles (user_id, username, display_name, role)
    values (account_id, lower(btrim(account_username)), account_display_name, 'sales');
end $$;
commit;

select username, display_name, active, must_change_password from public.profiles order by username;
