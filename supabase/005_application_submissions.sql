-- Run once in Supabase SQL Editor as postgres, or apply through migrations.
-- Adds a separate anonymous-form submission store. No existing rows/tables change.
-- For CSV export use public.application_submissions_csv, not the raw JSON table.
begin;

do $$
begin
  if to_regclass('public.application_submissions') is not null
     or to_regclass('public.application_submissions_csv') is not null
     or to_regnamespace('kbrand_application_private') is not null then
    raise exception 'Application submission objects already exist. Inspect the installed migration; do not drop existing data.';
  end if;
end $$;

create schema kbrand_application_private;
revoke all on schema kbrand_application_private from public, anon, authenticated;
grant usage on schema kbrand_application_private to service_role;

create table public.application_submissions (
  id uuid primary key,
  input_fingerprint text not null check (input_fingerprint ~ '^[0-9a-f]{64}$'),
  application_date date not null,
  company_name text not null check (length(btrim(company_name)) between 1 and 80),
  company_name_en text not null default '',
  registration_number text not null check (length(btrim(registration_number)) > 0),
  representative text not null check (length(btrim(representative)) > 0),
  address text not null check (length(btrim(address)) > 0),
  company_category text not null default '',
  department text not null default '',
  contact_name text not null check (length(btrim(contact_name)) > 0),
  contact_phone text not null check (length(btrim(contact_phone)) > 0),
  contact_email text not null check (length(btrim(contact_email)) > 0),
  manager_name text not null default '',
  manager_phone text not null default '',
  manager_email text not null default '',
  project_type text not null default '',
  provider_name text not null default '',
  product_count integer not null check (product_count between 1 and 20),
  brands text not null default '',
  products text not null default '',
  export_countries text not null default '',
  certifications text not null default '',
  channels text not null default '',
  counterfeit_risk text not null default '',
  ip_defense text not null default '',
  plan_countries text not null default '',
  channel_plan text not null default '',
  marketing_plan text not null default '',
  expected_effects text not null default '',
  improvement_plan text not null default '',
  ip_history text not null default '',
  input_data jsonb not null check (jsonb_typeof(input_data) = 'object'
                                  and octet_length(input_data::text) <= 1048576),
  source_names jsonb not null default '[]'::jsonb
    check (jsonb_typeof(source_names) = 'array' and jsonb_array_length(source_names) <= 50),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index application_submissions_updated_idx on public.application_submissions(updated_at desc);
create index application_submissions_company_idx on public.application_submissions(company_name);
create index application_submissions_registration_idx on public.application_submissions(registration_number);

create function kbrand_application_private.touch_submission()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.created_at = old.created_at;
  if (to_jsonb(new) - 'created_at' - 'updated_at') is distinct from
     (to_jsonb(old) - 'created_at' - 'updated_at') then
    new.updated_at = now();
  else
    new.updated_at = old.updated_at;
  end if;
  return new;
end $$;

create trigger application_submissions_touch before update on public.application_submissions
for each row execute function kbrand_application_private.touch_submission();

-- Prevent spreadsheet formulas when an administrator opens the exported CSV.
-- The source table and input_data retain the exact unescaped submitted values.
create function kbrand_application_private.csv_cell(value text)
returns text language sql immutable parallel safe set search_path = '' as $$
  select case
    when coalesce(value, '') ~ '^[[:space:]]*[=+@-]'
      or left(coalesce(value, ''), 1) in (chr(9), chr(10), chr(13))
    then chr(39) || value
    else coalesce(value, '')
  end
$$;

alter table public.application_submissions enable row level security;
alter table public.application_submissions force row level security;
revoke all on public.application_submissions from public, anon, authenticated;
grant usage on schema public to service_role;
grant select, insert, update on public.application_submissions to service_role;
-- No anon/authenticated policies: only the server secret/service_role can use it.

create view public.application_submissions_csv with (security_invoker = true) as
select
  id as "접수번호",
  to_char(created_at at time zone 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') as "최초저장일시(KST)",
  to_char(updated_at at time zone 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') as "수정일시(KST)",
  application_date as "신청일",
  kbrand_application_private.csv_cell(company_name) as "회사명",
  kbrand_application_private.csv_cell(company_name_en) as "영문회사명",
  kbrand_application_private.csv_cell(registration_number) as "사업자등록번호",
  kbrand_application_private.csv_cell(representative) as "대표자",
  kbrand_application_private.csv_cell(address) as "주소",
  kbrand_application_private.csv_cell(company_category) as "기업구분",
  kbrand_application_private.csv_cell(department) as "담당부서",
  kbrand_application_private.csv_cell(contact_name) as "담당자",
  kbrand_application_private.csv_cell(contact_phone) as "연락처",
  kbrand_application_private.csv_cell(contact_email) as "이메일",
  kbrand_application_private.csv_cell(manager_name) as "부서장",
  kbrand_application_private.csv_cell(manager_phone) as "부서장 연락처",
  kbrand_application_private.csv_cell(manager_email) as "부서장 이메일",
  kbrand_application_private.csv_cell(project_type) as "사업과제",
  kbrand_application_private.csv_cell(provider_name) as "수행업체",
  product_count as "상품 수",
  kbrand_application_private.csv_cell(brands) as "브랜드명",
  kbrand_application_private.csv_cell(products) as "대상제품",
  kbrand_application_private.csv_cell(export_countries) as "수출국가",
  kbrand_application_private.csv_cell(certifications) as "보유 인증",
  kbrand_application_private.csv_cell(channels) as "활용채널",
  kbrand_application_private.csv_cell(counterfeit_risk) as "위조 피해·우려",
  kbrand_application_private.csv_cell(ip_defense) as "해외 지식재산권·방어역량",
  kbrand_application_private.csv_cell(plan_countries) as "활용국가",
  kbrand_application_private.csv_cell(channel_plan) as "활용채널 상세 계획",
  kbrand_application_private.csv_cell(marketing_plan) as "수출 마케팅 전략",
  kbrand_application_private.csv_cell(expected_effects) as "기대효과",
  kbrand_application_private.csv_cell(improvement_plan) as "개선계획",
  kbrand_application_private.csv_cell(ip_history) as "분쟁 이력",
  (input_data -> 'products')::text as "상품 상세(JSON)",
  input_data::text as "전체 입력(JSON)",
  source_names::text as "첨부 자료명(JSON)"
from public.application_submissions;

revoke all on public.application_submissions_csv from public, anon, authenticated;
grant select on public.application_submissions_csv to service_role;
revoke all on all functions in schema kbrand_application_private from public, anon, authenticated;
grant execute on function kbrand_application_private.csv_cell(text) to service_role;

comment on table public.application_submissions is '서버가 저장하는 K-브랜드 신청서. 고객 로그인 및 공개 조회 없음.';
comment on view public.application_submissions_csv is '관리자 CSV 내보내기용 한글 열. 수식으로 해석될 수 있는 문자열은 작은따옴표로 보호.';

notify pgrst, 'reload schema';
commit;
