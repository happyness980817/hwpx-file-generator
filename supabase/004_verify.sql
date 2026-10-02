-- READ ONLY. Run each SELECT separately if your SQL Editor only shows the last result.

-- A. Expect exactly four rows and rls_enabled=true on each.
select c.relname as table_name, c.relrowsecurity as rls_enabled
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname in ('profiles','clients','document_jobs','documents')
order by c.relname;

-- B. After 002: admin/admin, sales01/sales, sales02/sales; all active=true.
-- must_change_password=true is expected until the password-change code is implemented and used.
select username, display_name, role, active, must_change_password
from public.profiles order by username;

-- C. Expect public=false, file_size_limit=20971520 (20 MiB), MIME types NULL/empty.
select id, public, file_size_limit, allowed_mime_types
from storage.buckets where id = 'generated-documents';

-- D. Expect seven public-table policies plus six storage policies after 001 and 003.
select schemaname, tablename, policyname, permissive, roles, cmd
from pg_policies
where (schemaname = 'public' and tablename in ('profiles','clients','document_jobs','documents'))
   or (schemaname = 'storage' and policyname like 'kbrand_files_%')
order by schemaname, tablename, policyname;

-- E. All expected true. Table-level grants must not open protected columns.
select
  not has_table_privilege('anon', 'public.clients', 'SELECT') as anonymous_read_blocked,
  not has_column_privilege('authenticated', 'public.profiles', 'role', 'UPDATE') as role_edit_blocked,
  not has_column_privilege('authenticated', 'public.clients', 'owner_id', 'UPDATE') as ownership_edit_blocked,
  not has_column_privilege('authenticated', 'public.document_jobs', 'status', 'UPDATE') as status_edit_blocked,
  has_column_privilege('authenticated', 'public.clients', 'company_name', 'INSERT') as client_create_allowed,
  has_table_privilege('service_role', 'public.documents', 'INSERT') as server_metadata_write_allowed;

-- IMPORTANT: SQL Editor's postgres role bypasses RLS.
-- Seeing all rows here does NOT prove that sales accounts can see all rows.
