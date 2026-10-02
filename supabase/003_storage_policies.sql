-- FIRST create generated-documents as a PRIVATE bucket in the Storage dashboard.
-- Files are uploaded by the trusted server, not directly by sales accounts.
begin;
do $$
begin
  if not exists(select 1 from storage.buckets where id = 'generated-documents' and not public) then
    raise exception 'Create a PRIVATE generated-documents bucket in Storage first.';
  end if;
end $$;

create function kbrand_private.can_read_file(object_path text)
returns boolean language sql stable security definer set search_path = ''
as $$
  select exists(
    select 1 from public.documents d
    join public.document_jobs j on j.id = d.job_id and j.owner_id = d.owner_id
    where d.storage_bucket = 'generated-documents' and d.storage_path = object_path
      and j.status = 'succeeded' and kbrand_private.can_access_owner(d.owner_id)
  )
$$;
revoke all on function kbrand_private.can_read_file(text) from public, anon, authenticated;
grant execute on function kbrand_private.can_read_file(text) to authenticated, service_role;

create policy kbrand_files_read on storage.objects for select to authenticated
using (bucket_id = 'generated-documents' and kbrand_private.can_read_file(name));

-- Restrictive guards prevent older broad permissive policies from opening this bucket.
-- They do not grant new access to any other bucket.
create policy kbrand_files_read_guard on storage.objects as restrictive for select to authenticated
using (bucket_id <> 'generated-documents' or kbrand_private.can_read_file(name));
create policy kbrand_files_anon_guard on storage.objects as restrictive for select to anon
using (bucket_id <> 'generated-documents');
create policy kbrand_files_insert_guard on storage.objects as restrictive for insert to authenticated, anon
with check (bucket_id <> 'generated-documents');
create policy kbrand_files_update_guard on storage.objects as restrictive for update to authenticated, anon
using (bucket_id <> 'generated-documents') with check (bucket_id <> 'generated-documents');
create policy kbrand_files_delete_guard on storage.objects as restrictive for delete to authenticated, anon
using (bucket_id <> 'generated-documents');

commit;
select '003 OK - private file policies installed; no files uploaded' as result;
