# Supabase 연동 실습 매뉴얼

작성일: 2026-10-02 · 대상 프로젝트: `C:\notion-workspace-writer-agent`

**이 문서는 고객·작업·파일까지 포함하는 전체 초기 설계입니다. 현재 원격 프로젝트의 로그인용 profiles와 세 계정은 준비되어 있습니다. 001~004 전체가 적용되었다는 의미는 아니며, 기존 테이블이 있으면 초기 설치 SQL을 반복 실행하지 마세요.**

현재 아이디·비밀번호 로그인 코드는 구현되어 있습니다. **로그인만 먼저 설정하려면 [LOGIN_SETUP.md](LOGIN_SETUP.md)를 따르세요.** 이 문서의 001~004는 고객·작업·파일까지 포함하는 전체 초기 설계입니다. 로그인 전용 SQL로 profiles를 이미 만들었다면 001을 그대로 실행하지 말고 후속 마이그레이션을 작성해야 합니다. 고객 저장·Storage 연결은 여전히 후속 구현 범위입니다.

## 0. 무엇을 어디에서 하는지

| 작업 | 실행 장소 | 사용할 내용 |
|---|---|---|
| 회원가입 차단·이메일 로그인 설정 | Supabase 웹사이트 → Authentication | 토글 설정 |
| 고객·작업·파일 메타데이터 테이블 생성 | Supabase 웹사이트 → SQL Editor | `001_schema.sql` 전체 |
| 실제 로그인 계정 세 개 생성 | Supabase 웹사이트 → Authentication → Users | 이메일·초기 비밀번호 |
| `admin`, `sales01`, `sales02`와 실제 계정 연결 | Supabase 웹사이트 → SQL Editor | 이메일을 수정한 `002_register_accounts.sql` 전체 |
| 파일 보관 공간 생성 | Supabase 웹사이트 → Storage | 비공개 버킷 생성 |
| 파일 다운로드 권한 설정 | Supabase 웹사이트 → SQL Editor | `003_storage_policies.sql` 전체 |
| 생성 결과 확인 | Supabase 웹사이트 → SQL Editor | `004_verify.sql`의 SELECT 문 |
| 웹앱 실행 | 내 PC의 CMD 또는 PowerShell | `uv run streamlit run app.py` |

여기서 말하는 **SQL Editor는 VS Code 터미널이 아니라 Supabase 웹사이트 왼쪽 메뉴**입니다. 터미널에 `create table`을 입력하지 않습니다. Markdown의 코드 경계인 세 개의 백틱은 SQL Editor에 붙여넣지 않습니다.

### 준비된 파일

- [supabase/001_schema.sql](supabase/001_schema.sql): 테이블·관계·권한·RLS 생성. **수정하지 않고 실행**합니다.
- [supabase/002_register_accounts.sql](supabase/002_register_accounts.sql): 계정 세 개 연결. **이메일 세 곳을 바꾸고 실행**합니다.
- [supabase/003_storage_policies.sql](supabase/003_storage_policies.sql): 비공개 다운로드 정책. **버킷 생성 후 수정 없이 실행**합니다.
- [supabase/004_verify.sql](supabase/004_verify.sql): 결과 조회. **수정 없이 여러 번 실행 가능**합니다.

`001`과 `003`은 최초 설치용입니다. 이미 적용했다면 반복 실행하지 않습니다. 기존 데이터를 지우거나 동일 이름의 테이블을 덮어쓰지 않고 오류로 중단하도록 구성했습니다. `002`도 기존 계정의 역할을 덮어쓰지 않습니다.

## 1. 프로젝트와 .env 확인

1. [Supabase Dashboard](https://supabase.com/dashboard)에 로그인합니다.
2. 기존 프로젝트를 선택합니다. 이 대화에서 확인한 프로젝트 ref는 `fxcvlugggfxsjastrguy`입니다. 본인 프로젝트가 맞는지 URL로 확인합니다.
3. 프로젝트의 **Connect**에서 Project URL을, **Settings → API Keys**에서 Publishable key와 Secret key를 확인합니다.
4. PC의 `C:\notion-workspace-writer-agent\.env`에 아래 이름으로 설정합니다. **기존 값을 유지하고, 아래 예시로 덮어쓰지 마세요.**

```dotenv
SUPABASE_URL=https://실제프로젝트ref.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_실제값
SUPABASE_SECRET_KEY=sb_secret_실제값
```

| 변수 | 용도 |
|---|---|
| `SUPABASE_URL` | 내 프로젝트의 API 주소 |
| `SUPABASE_PUBLISHABLE_KEY` | 비밀번호 로그인, 사용자 토큰을 함께 사용하는 DB·파일 조회 |
| `SUPABASE_SECRET_KEY` | 서버의 계정 관리·아이디 조회·문서 업로드. **RLS를 우회하므로 서버에서만 사용** |

DB 비밀번호, Supabase 계정 비밀번호, JWT signing secret, MCP 로그인 토큰을 위 키 자리에 넣지 않습니다. `.env`는 이미 `.gitignore`에 등록되어 있습니다. `.env.example`에는 실제 키를 넣지 않습니다. MCP 연결은 개발 도구 연결이며, 웹앱의 인증·DB 연결을 대신하지 않습니다.

## 2. 공개 회원가입을 끄고 이메일·비밀번호 로그인 유지

1. 왼쪽 **Authentication → Sign In / Providers**를 엽니다. UI 버전에 따라 Configuration 아래에 있을 수 있습니다.
2. 다음 상태로 설정하고 **Save**를 누릅니다.

| 항목 | 설정 | 이유 |
|---|---|---|
| Email provider / Email sign-in | **ON** | 비밀번호 로그인을 사용 |
| Allow new users to sign up | **OFF** | 공개 가입 차단. 이미 발급한 계정은 로그인 가능 |
| Allow anonymous sign-ins | **OFF** | 비회원 계정 생성 미사용 |
| Google 등 소셜 provider | 미사용 | 이 프로젝트는 ID/PW 방식 |
| Confirm Email | **ON 유지** | 아래에서 신원을 확인한 발급 계정만 개별 확인 처리 |

Email provider 설정에 Password minimum length가 있으면 **10자 이상**을 권장합니다. 이 값은 이번 서비스의 권장값이지 Supabase 필수값은 아닙니다.

**아이디를 `sales01`로 쓰는 방법:** Supabase 자체 비밀번호 인증은 이메일/전화번호 기반입니다. 서버 코드가 `sales01 → profiles.user_id → Auth의 실제 이메일`을 찾은 뒤 비밀번호를 검증하도록 구현합니다. 사용자는 이메일을 외우지 않아도 됩니다. 비밀번호는 Supabase Auth에서 관리하며 `profiles`에 저장하지 않습니다.

공식 문서: [인증 설정](https://supabase.com/docs/guides/auth/general-configuration), [비밀번호 인증](https://supabase.com/docs/guides/auth/passwords)

## 3. SQL Editor에서 테이블 만들기

### 3-1. 붙여넣고 실행하는 공통 방법

1. Supabase 왼쪽 **SQL Editor**를 누릅니다.
2. **New query / +**로 새 쿼리를 엽니다.
3. 프로젝트의 [001_schema.sql](supabase/001_schema.sql)을 VS Code 등으로 엽니다.
4. **Ctrl+A → Ctrl+C**로 파일 전체를 복사합니다.
5. 웹사이트 쿼리 입력칸을 클릭하고 **Ctrl+V**로 붙여넣습니다.
6. 실행 대상은 현재 프로젝트의 Primary database, 역할은 **postgres**를 사용합니다.
7. 코드 중 일부를 선택해 놓지 말고, 아래의 **Run** 버튼으로 전체를 실행합니다.
8. 결과에 다음 메시지가 나오면 성공입니다.

```text
001 OK - 4 tables created; RLS enabled; no accounts or files created
```

SQL 파일에는 `begin;`과 `commit;`이 들어 있습니다. 중간에 오류가 나면 해당 트랜잭션의 변경은 반영되지 않습니다. `current transaction is aborted`가 이어지면 새 쿼리에서 `rollback;`을 한 번 실행하고 원래 오류를 확인합니다. 테이블을 삭제해 해결하지 마세요.

### 3-2. 생성되는 테이블

| 테이블 | 담는 정보 | 예 |
|---|---|---|
| `profiles` | Auth 사용자 UUID, 로그인 아이디, 역할, 사용 여부, 최초 비밀번호 변경 여부 | `sales01`, `sales`, `active=true` |
| `clients` | 담당자 UUID, 회사명, 기존 입력 자료 JSON | `input.json`에 넣던 회사·제품·계획 내용 |
| `document_jobs` | 고객 UUID, 입력 스냅샷, 중복방지 키, 진행 상태 | `queued → running → succeeded / failed` |
| `documents` | 문서 종류, Storage 경로, 파일명, 크기, SHA-256 | 신청서·활용계획서·ZIP |

`kbrand_private`는 RLS 보조 함수용입니다. **Data API의 Exposed schemas에 추가하지 않습니다.** `public` 스키마는 Data API 조회 대상이어야 합니다. 고객 자료는 사용자 JWT와 RLS로 접근을 제한합니다.

### 3-3. 접근 권한 설계

- 담당자는 본인 고객·작업·문서만 조회합니다. 고객 정보 수정·보관 처리도 본인 자료만 가능합니다.
- 관리자 계정은 전체 자료를 조회하고 고객 내용을 수정합니다. 계정 발급·역할 변경·담당자 재배정은 별도 관리자 코드로 처리합니다.
- 일반 사용자는 `role`, `active`, `must_change_password`, `owner_id`, 작업 성공 여부를 직접 바꿀 수 없습니다. 컬럼 권한과 RLS를 함께 제한합니다.
- 고객 삭제 대신 `archived=true`로 보관 처리합니다. 파일과 기록이 남아 있는 고객을 임의 삭제하지 않습니다.
- `must_change_password=true`인 새 계정은 자기 프로필만 확인할 수 있고 고객 자료에는 접근하지 못합니다. 나중에 앱에서 비밀번호 변경 성공 후 서버가 false로 바꿉니다.
- `active=false`인 계정은 기존 JWT가 남아 있어도 RLS로 자료 접근이 차단됩니다. 이미 다운로드한 로컬 파일까지 회수되는 것은 아닙니다.

공식 문서: [RLS와 테이블 권한](https://supabase.com/docs/guides/database/postgres/row-level-security)

## 4. 관리자 1명 + 영업 담당자 2명 계정 만들기

### 4-1. Auth 계정부터 생성

1. **Authentication → Users → Add user → Create new user**를 엽니다. UI에서 이름이 다르면 초대메일 발송이 아닌 사용자 직접 생성 기능을 선택합니다.
2. 관리자 실제 이메일과 초기 비밀번호를 입력합니다.
3. 신원을 확인한 계정이면 **Auto Confirm User / Confirm email** 항목을 선택하여 해당 계정을 확인 처리합니다. Confirm Email 정책 전체를 끄는 작업과는 다릅니다.
4. **Create user**를 누릅니다.
5. 영업 담당자 두 명도 서로 다른 실제 이메일로 생성합니다. 소셜로그인 계정을 만드는 작업이 아닙니다.
6. Users 목록에서 계정 세 개가 있고 이메일 확인이 완료되었는지 확인합니다.

초기 비밀번호는 각 담당자에게 별도로 전달합니다. **SQL Editor, 이 매뉴얼, Git, 채팅에 비밀번호를 적지 않습니다.** 초기 운영은 관리자 발급·관리자 재설정 방식이므로 SMTP 메일 서버 설정을 먼저 할 필요는 없습니다.

### 4-2. 로그인 아이디와 연결

[002_register_accounts.sql](supabase/002_register_accounts.sql)을 열고, 아래 **이메일 세 곳**을 방금 만든 계정 이메일과 정확히 일치하도록 수정합니다. 이름도 원하시는 표시 이름으로 바꿀 수 있습니다.

```sql
insert into kbrand_initial_accounts (email, username, display_name, role) values
  ('REPLACE_ADMIN@example.com', 'admin', '관리자', 'admin'),
  ('REPLACE_SALES01@example.com', 'sales01', '영업 담당자 1', 'sales'),
  ('REPLACE_SALES02@example.com', 'sales02', '영업 담당자 2', 'sales');
```

**위 INSERT 부분만 단독 실행하지 마세요.** 이 파일에는 임시 테이블 생성과 오류 검사가 함께 들어 있습니다. 수정한 **002 파일 전체**를 SQL Editor의 새 쿼리에 붙여넣고 Run 합니다.

결과는 아래처럼 세 줄이어야 합니다.

| username | role | active | must_change_password |
|---|---|---|---|
| admin | admin | true | true |
| sales01 | sales | true | true |
| sales02 | sales | true | true |

`username`은 영문 소문자로 시작하는 3~32자의 소문자·숫자·밑줄만 사용합니다. SQL이 실제 이메일과 Auth UUID를 연결하므로 UUID를 직접 복사할 필요는 없습니다. `profiles`에는 이메일이나 비밀번호를 저장하지 않습니다.

`002`는 **첫 세 계정을 등록하는 용도**입니다. 나중에 네 번째 사용자를 추가하거나 기존 역할을 변경할 때 재사용하지 말고 관리자 기능 또는 별도 쿼리를 작성합니다.

공식 문서: [사용자 관리](https://supabase.com/docs/guides/auth/managing-user-data), [관리자 사용자 생성 API](https://supabase.com/docs/reference/python/auth-admin-createuser)

## 5. HWPX 저장 버킷 만들고 다운로드 정책 적용

### 5-1. Storage 화면에서 버킷 생성

1. **Storage → New bucket**을 누릅니다.
2. 아래 값으로 설정하고 **Create bucket**을 누릅니다.

| 항목 | 입력값 |
|---|---|
| Name / Bucket ID | `generated-documents` |
| Public bucket | **OFF** |
| File size limit | **20 MB** (DB 기준 최대 20,971,520 bytes) |
| Allowed MIME types | 초기에는 비워둠 |

대시보드에 제한 입력란이 없으면 버킷 생성 후 Settings에서 설정합니다. `Public ON`으로 만들지 마세요. HWPX는 업로드 클라이언트에 따라 `application/hwp+zip` 또는 `application/octet-stream`이 사용될 수 있어, 처음부터 MIME 제한을 좁게 설정하지 않습니다.

### 5-2. 권한 SQL 적용

1. [003_storage_policies.sql](supabase/003_storage_policies.sql)을 열고 전체를 복사합니다.
2. **SQL Editor → New query**에 붙여넣고 Run 합니다.
3. 아래 메시지를 확인합니다.

```text
003 OK - private file policies installed; no files uploaded
```

이 정책은 사용자 직접 업로드·수정·삭제를 막고, **서버가 생성한 문서 중 본인 소유이며 작업이 성공한 파일**만 읽도록 합니다. 관리자는 성공한 전체 문서를 읽을 수 있습니다. 서버의 Secret key 업로드는 RLS를 우회하므로 서버에서 요청자의 권한을 먼저 확인해야 합니다.

파일 경로는 아래 규칙으로 고정합니다. 다운로드 표시 이름은 기존 한국어 파일명을 그대로 사용할 수 있습니다.

```text
generated-documents/                  ← 버킷, path 문자열에는 포함하지 않음
  사용자_UUID/
    작업_UUID/
      application.hwpx
      plan.hwpx
      bundle.zip
```

예: `documents.storage_bucket = 'generated-documents'`, `documents.storage_path = '사용자_UUID/작업_UUID/application.hwpx'`.

**Storage 화면에서 파일을 수동으로 올렸다고 담당자에게 바로 보이지는 않습니다.** `documents`에 경로가 등록되고 해당 `document_jobs.status`가 `succeeded`여야 합니다. 파일 업로드와 DB 등록 코드는 8단계에서 구현합니다.

초기 다운로드 방식은 사용자 JWT로 비공개 파일을 읽어 Streamlit 다운로드 버튼으로 전달하는 것으로 정합니다. 장시간 유효한 공개·서명 URL은 생성하지 않습니다. 이미 브라우저에 전달한 파일 바이트는 로그아웃으로 회수되지 않습니다.

**storage.objects / storage.buckets의 파일 메타데이터를 직접 INSERT·DELETE하지 마세요.** 파일의 업로드·삭제는 Storage API 또는 대시보드로 합니다. 003은 정책만 만들며 파일 행을 조작하지 않습니다.

공식 문서: [비공개 버킷](https://supabase.com/docs/guides/storage/buckets/fundamentals), [Storage 접근 정책](https://supabase.com/docs/guides/storage/security/access-control), [Storage 메타데이터 주의사항](https://supabase.com/docs/guides/storage/schema/design)

## 6. SQL Editor에서 결과 확인

[004_verify.sql](supabase/004_verify.sql)을 새 쿼리에 붙여넣습니다. 결과가 마지막 표만 보이면 파일의 **A~E SELECT를 하나씩 선택하여 Run** 합니다.

| 검사 | 정상 결과 |
|---|---|
| A. 테이블·RLS | `profiles`, `clients`, `document_jobs`, `documents` 네 줄 모두 `rls_enabled=true` |
| B. 사용자 | admin 1명, sales 2명. 활성 상태이며 최초 비밀번호 변경은 대기 |
| C. 버킷 | `generated-documents`, `public=false`, 크기 제한 설정 |
| D. 정책 | public 테이블 정책 7개 + `kbrand_files_` 정책 6개 |
| E. 보호된 컬럼 권한 | 모든 결과가 `true` |

핵심 확인 쿼리는 이것입니다. 다른 코드를 실행하지 않고 이 쿼리만 여러 번 실행해도 됩니다.

```sql
select username, role, active, must_change_password
from public.profiles
order by username;
```

**SQL Editor의 postgres는 RLS를 우회합니다.** 여기서 모든 고객이 조회된다는 이유로 권한이 잘못되었다고 판단하지 않습니다. 실제 권한 검증은 앱 연결 후 서로 다른 두 계정의 사용자 JWT로 수행해야 합니다.

## 7. 자주 만나는 오류와 조치

| 오류·상황 | 원인·조치 |
|---|---|
| `K-brand objects already exist` / `already exists` | 최초 설치 SQL을 다시 실행했거나 동명 테이블이 있음. 삭제하지 말고 004로 상태 확인 후 차이 검토 |
| `Replace the three example emails...` | 002의 예시 이메일이 남아 있음. 실제 이메일로 수정 |
| `Expected exactly 3 matching Auth users` | Auth 사용자를 만들지 않았거나 이메일 오타. Users 화면 확인 |
| `An Auth email is unconfirmed` | 개별 발급 계정의 이메일 확인이 미완료. 해당 계정 확인 처리 |
| `An account is already registered` | 기존 프로필을 덮어쓰지 않도록 중단한 것. 002 반복 실행 불필요 |
| `Create a PRIVATE generated-documents bucket...` | 버킷 이름이 다르거나 Public이 켜져 있음 |
| `current transaction is aborted` | 앞선 SQL 오류로 트랜잭션이 중단됨. `rollback;` 후 원래 오류 수정 |
| 로그인은 되는데 고객 0건 | 신규 계정이면 정상. `must_change_password`, `active`, 담당자 UUID, RLS도 확인 |
| `permission denied` / `violates row-level security` | 키·사용자 JWT·허용 컬럼·소유자를 확인. RLS를 끄거나 전부 true 정책을 추가하지 않음 |
| 수동 업로드 파일 다운로드 불가 | 문서 메타데이터와 성공한 작업 연결이 없으면 의도된 차단 |
| SQL을 실행했는데 Streamlit 화면은 동일 | 정상. DB 준비와 앱 코드 구현은 별도 단계 |

## 8. 구현 현황과 후속 코드

8-1의 인증 모듈은 구현했고, 8-2 이후의 고객·작업·Storage 연동은 아직 구현하지 않았습니다. SQL과 실제 계정은 별도로 준비해야 합니다.

### 8-1. 인증 모듈 (구현 완료)

- `src/auth.py`와 `src/auth_ui.py`에서 별도 아이디 → 프로필 UUID → Auth 이메일 → 비밀번호 인증을 처리합니다.
- Secret key 조회용 클라이언트와 사용자 Publishable key 인증 클라이언트를 분리합니다.
- 사용자 JWT와 프로필 활성 상태를 화면 진입 때 확인하고, 최초 비밀번호 변경 전에는 문서 화면을 차단합니다.
- 로그인 시도는 단일 프로세스 기준 동일 아이디에 대해 1분간 5회로 제한합니다. 다중 서버 공유 제한은 후속 구현입니다.
- 로그아웃 시 해당 브라우저의 인증·고객 입력·문안·다운로드 상태를 제거합니다. 이미 생성한 로컬 파일은 유지됩니다.
- 상세 설정과 현재 한계는 [LOGIN_SETUP.md](LOGIN_SETUP.md)를 참고하세요.

### 8-2. 고객·작업 저장

- 고객 저장은 사용자 JWT로 `clients(company_name, input_data)`에 INSERT/UPDATE합니다. `owner_id`는 DB 기본값 `auth.uid()`로 결정합니다.
- 고객 JSON에는 기존 생성기용 `data`와 추가 자료·요청사항을 함께 보관합니다. 예: `{"data": {...}, "notes": "...", "request": "..."}`. 생성기에는 `data`만 전달합니다.
- 문서 생성 요청 시 입력 전체를 `document_jobs.input_snapshot`에 복사합니다. UUID `request_key`를 재사용하여 중복 클릭을 막고, 별도의 요청에만 새 키를 발급합니다.
- Secret key를 쓰는 작업 처리 코드는 DB에서 요청 소유자와 프로필 상태를 재확인한 뒤 실행합니다. 관리자 기능도 서버에서 관리자 여부를 검증한 후 수행합니다.
- 진행 상태는 서버가 변경하며 사용자에게 `status='succeeded'` 쓰기 권한을 주지 않습니다.

### 8-3. 파일 저장·다운로드

- Python HWPX 생성기로 HWPX 두 개와 ZIP을 만듭니다.
- Storage API로 고정된 UUID 경로에 업로드 → `documents` 세 행 등록 → 파일 검증이 끝난 뒤 작업을 succeeded로 전환합니다.
- 중간 실패 시 failed로 기록합니다. 부분 업로드 파일은 다시 시도하거나 Storage API로 정리합니다. 실패 작업 파일은 담당자에게 제공하지 않습니다.
- 다운로드 요청 시 사용자 인증을 다시 확인하고 사용자 JWT로 파일을 읽습니다. 재다운로드는 OpenAI나 생성기를 다시 호출하지 않습니다.
- 고객 보관·계정 비활성화·보존기간에 따른 파일 삭제를 관리자 기능으로 구현합니다.

### 8-4. 창을 닫아도 실행되게 하려면

현재 로컬 Streamlit은 생성이 끝날 때까지 화면에서 기다리는 구조입니다. Supabase 테이블만 만들어서는 백그라운드 실행이 생기지 않습니다. 별도 작업 프로세스에서 DB 대기열 선점·lease 갱신·재시도·중단 복구를 구현해야 합니다. 이번 SQL의 attempts/lease_until은 그 구현을 위한 필드이며 자체적으로 실행되는 스케줄러가 아닙니다.

## 9. 테스트·외부 배포 순서

코드 연결 후 프로젝트 폴더에서 실행합니다.

```cmd
cd C:\notion-workspace-writer-agent
uv sync
uv run streamlit run app.py
```

1. admin 로그인 → 최초 비밀번호 변경 → 전체 고객 조회 확인.
2. sales01 로그인 → 최초 비밀번호 변경 → 가상 고객 A 저장·문서 생성.
3. 다른 브라우저 또는 시크릿 창에서 sales02 로그인 → 고객 A·파일이 보이지 않는지 확인.
4. 사용자 JWT로 고객 A의 UUID·Storage 경로를 직접 요청해도 거절되는지 확인. 화면에서 숨기는 것만으로 끝내지 않습니다.
5. sales01의 자료를 다시 열고 파일을 재다운로드합니다. 이때 AI가 다시 호출되지 않아야 합니다.
6. 관리자 도구로 sales01을 비활성화한 뒤 기존 세션에서도 새 조회·다운로드가 차단되는지 확인합니다.
7. 양쪽 계정 동시 생성, 업로드 실패, 중복 클릭, 토큰 만료를 시험합니다.
8. 최종 HWPX는 실제 한글 프로그램에서 표·쪽 배치를 검수합니다.

실제 영업용으로 공개하려면 Python을 실행할 수 있는 HTTPS 호스팅에 배포하고, 서버 환경변수에 Supabase/OpenAI 키를 등록해야 합니다. Supabase는 이 앱의 Streamlit 화면과 Python HWPX 생성기를 대신 실행하지 않습니다. 현재 `.streamlit/config.toml`의 127.0.0.1 설정은 로컬 전용이며, 배포 시 해당 호스팅의 포트·바인딩 방식으로 별도 설정합니다.

메일로 비밀번호를 재설정하는 기능을 도입할 때만 다음을 추가합니다.

- **Authentication → URL Configuration**: Site URL은 운영 사이트 주소, Redirect URLs는 앱에서 구현한 비밀번호 재설정 콜백 주소.
- **Authentication → SMTP Settings**: 발송 서비스의 Host·Port·계정·비밀번호·발신 주소 등록 및 테스트.
- Streamlit에 복구 링크의 인증 정보를 처리하는 콜백과 비밀번호 재설정 화면 구현. URL 설정만으로 복구 화면이 생기지는 않습니다.

공식 문서: [Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls), [SMTP 설정](https://supabase.com/docs/guides/auth/auth-smtp)

## 10. 이번 작업의 검증 범위

- SQL과 설명 파일만 준비합니다. 원격 Supabase에 대한 DDL·계정 생성·버킷 생성은 실행하지 않습니다.
- 초기 SQL은 기존 객체가 있으면 중단합니다. 적용 후 변경 사항은 별도 migration으로 작성합니다.
- 로컬 PostgreSQL 호환 엔진(PGlite)에서 Supabase Auth·Storage의 최소 스키마를 모사하여 **29개 검사 통과**: SQL 설치·재실행 차단, 계정 누락·미확인 이메일 차단, 담당자 간 자료 분리, 관리자 조회, 최초 비밀번호 변경 전 차단, 권한 상승·소유자 변경 차단, 중복 요청 차단, 익명·비활성 계정 차단, 실패 작업 파일 차단 등. 기존의 넓은 Storage 정책이 있어도 이 버킷의 제한이 유지되는지도 확인했습니다. 실제 Supabase의 로그인·Storage API·대시보드 동작까지 검증한 것은 아닙니다.
- 실제 프로젝트 적용 후 004의 구조 확인과 9단계의 사용자별 접근 테스트를 모두 통과해야 연동 완료입니다.
