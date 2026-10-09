> 이전 로그인 기반 설계 기록입니다. 2026-10-09부터 고객 사이트는 회원가입 없이 사용하며 작업번호·확인 비밀번호로 작업을 보관합니다. 현재 운영 방법은 README.md와 FRONTEND.md를 참고하세요. 이 문서의 계정/SQL 설치 절차는 현재 사이트에 필요하지 않습니다.

# 아이디·비밀번호 로그인 설정

현재 앱에는 `sales01` 같은 아이디 로그인, 로그아웃, 최초 비밀번호 변경이 구현되어 있습니다. 로그인 전에는 고객 입력·AI 작성·파일 생성 화면을 사용할 수 없습니다. 고객 DB 저장과 Storage 업로드는 아직 연결하지 않았습니다.

## 현재 프로젝트: 로그인 준비 완료 (2026-10-02)

`public.profiles`가 준비된 것을 확인했고, 실제 Supabase Auth에 다음 세 계정을 발급·연결했습니다. **현재 프로젝트에서는 아래 초기 설치 SQL을 다시 실행할 필요가 없습니다.** 아래 1~4단계는 새 환경이나 계정 추가 시 참고용입니다.

| 아이디 | 역할 | 첫 로그인 |
|---|---|---|
| `admin` | 관리자 | 비밀번호 변경 필요 |
| `sales01` | 영업 담당자 1 | 비밀번호 변경 필요 |
| `sales02` | 영업 담당자 2 | 비밀번호 변경 필요 |

초기 비밀번호는 이 PC의 `C:\notion-workspace-writer-agent\data\login-credentials.json`에서 확인합니다. `accounts` 배열의 각 `username`에 해당하는 `initial_password`를 사용하세요. 이 파일은 Git에서 제외되어 있으며, 계정 전달·비밀번호 변경을 마친 후 삭제할 수 있습니다. 공용 문서나 채팅에는 비밀번호를 복사하지 않습니다.

각 계정에는 `아이디@login.fxcvlugggfxsjastrguy.invalid` 형태의 **인증용 내부 이메일**을 사용했습니다. 실제 이메일 수신 주소가 아니며, 사용자에게는 아이디와 비밀번호만 전달하면 됩니다. 이메일을 통한 비밀번호 복구가 필요해지면 실제 주소 연결과 SMTP 설정을 별도로 해야 합니다. 이번 발급 과정에서 이메일은 발송하지 않았습니다.

실제 검증 완료: 세 계정 로그인·로그아웃, 본인 프로필만 조회, 사용자 권한 수정 거절, 비회원 조회 거절, 최초 비밀번호 변경, Streamlit 화면에서 HWPX 두 개와 ZIP 다운로드 준비. 검증에 사용한 계정도 전달 전 비밀번호 변경 필요 상태로 되돌렸습니다. 고객 DB와 Storage에는 자료를 쓰지 않았습니다.

현재 채팅에 새 MCP 도구가 노출되지 않아, 계정 발급과 검증에는 프로젝트에 설정된 공식 Supabase Python SDK/API를 사용했습니다. MCP 등록·OAuth 상태는 별도로 확인했습니다.


## 1. 환경설정

기존 `.env`의 다음 값을 사용합니다. 이미 입력되어 있다면 그대로 두세요.

```dotenv
SUPABASE_URL=https://실제프로젝트ref.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_실제값
SUPABASE_SECRET_KEY=sb_secret_실제값
```

Publishable key는 비밀번호 인증에, Secret key는 서버 내부에서 아이디에 연결된 이메일을 찾고 최초 비밀번호 변경 완료를 기록하는 데 사용합니다. Secret key와 세션 토큰은 화면·다운로드 파일·로그에 표시하지 않습니다. 비밀번호는 Supabase Auth에서 관리하며 `profiles`에 저장하지 않습니다.

## 2. 로그인 테이블만 만들기

1. [Supabase Dashboard](https://supabase.com/dashboard)에서 프로젝트를 선택합니다.
2. 왼쪽 **SQL Editor → New query**를 누릅니다.
3. 프로젝트의 [supabase/login_only.sql](supabase/login_only.sql)을 열고 **파일 전체를 복사**합니다.
4. 웹사이트 SQL 입력칸에 붙여넣고 **Run**을 누릅니다. 마크다운 백틱은 붙여넣지 않습니다.
5. `Login profile table created...` 메시지를 확인합니다.

이 SQL은 로그인용 `profiles` 한 개와 본인 프로필 읽기 정책만 만듭니다. 고객·작업·파일 테이블과 버킷은 만들지 않습니다. 이미 이전 `001_schema.sql`을 실행하여 `profiles`가 있다면 이 단계는 건너뛰세요. 기존 테이블이 있으면 덮어쓰지 않고 오류로 중단합니다.

**`login_only.sql`과 기존 `001_schema.sql`은 둘 중 하나로 초기 설정합니다.** 로그인 전용 설정 후 고객 DB까지 확장할 때는 기존 테이블을 지우거나 `001`을 그대로 실행하지 않고, 추가 마이그레이션을 작성해야 합니다.

## 3. 비밀번호 계정 발급

1. **Authentication → Sign In / Providers**에서 이메일 인증을 켭니다.
2. 관리자가 계정을 발급하는 운영이면 **Allow new users to sign up**을 끕니다. 확인 당시에는 켜져 있었으며 이번 작업에서 설정을 바꾸지는 않았습니다. 앱 자체에는 회원가입 버튼이 없습니다.
3. **Authentication → Users → Add user → Create new user**를 엽니다.
4. 담당자의 실제 이메일과 초기 비밀번호를 입력합니다.
5. 발급 대상의 신원을 확인한 뒤 해당 계정의 **Auto Confirm User / Confirm email**을 선택하고 생성합니다. 이메일 확인 정책 전체를 끌 필요는 없습니다.

이메일은 내부 인증에 사용됩니다. 팀원은 아래에서 연결한 `sales01`과 비밀번호로 로그인합니다. 초기 비밀번호는 SQL·Git·채팅에 넣지 말고 해당 담당자에게 별도로 전달합니다.

## 4. sales01 아이디 연결

1. [supabase/register_login.sql](supabase/register_login.sql)을 엽니다.
2. 파일 위쪽의 아래 세 값만 수정합니다.

```sql
account_email text := 'REPLACE_EMAIL@example.com';
account_username text := 'sales01';
account_display_name text := '영업 담당자 1';
```

`account_email`에는 방금 만든 Auth 계정의 이메일을 정확히 입력합니다. 아이디는 영문 소문자로 시작하는 3~32자의 소문자·숫자·밑줄을 사용합니다.

3. **수정한 파일 전체**를 SQL Editor의 새 쿼리에 붙여넣고 Run 합니다.
4. 결과에 `sales01`, `active=true`, `must_change_password=true`가 있는지 확인합니다.
5. 두 번째 담당자는 Auth 계정을 따로 발급하고 이 파일의 이메일·아이디·표시 이름을 `sales02`에 맞춰 바꾼 후 전체 실행합니다.

동일 아이디나 Auth 계정은 중복 등록하지 않습니다. 이전 `002_register_accounts.sql`로 이미 등록했다면 이 단계를 반복하지 않습니다. `register_login.sql`은 기본 `sales` 역할로 한 명씩 등록합니다. 현재 앱에는 별도 관리자 화면이 없고, 역할 변경 기능도 없습니다.

## 5. 실행과 확인

```powershell
cd C:\notion-workspace-writer-agent
uv sync
uv run streamlit run app.py
```

1. <http://127.0.0.1:8501>에 접속합니다.
2. 아이디 `sales01`과 Auth에서 발급한 초기 비밀번호를 입력합니다.
3. 첫 로그인에서는 **10자 이상의 새 비밀번호**로 변경해야 문서 화면으로 넘어갑니다. 프로젝트의 비밀번호 정책도 충족해야 합니다.
4. 가상 고객 자료 → 예시 문안 → HWPX 생성·다운로드를 시험합니다. 이 과정에는 OpenAI 키가 필요하지 않습니다.
5. **로그아웃** 후에는 화면의 고객 정보·문안·다운로드 데이터가 지워집니다. `result/`에 이미 저장한 파일이나 다운로드한 파일은 삭제하지 않습니다.

브라우저 새로고침·탭 재접속·서버 재시작 후에는 재로그인이 필요할 수 있습니다. 토큰은 해당 Streamlit 서버 세션의 메모리에만 보관하며 영구 로그인 쿠키를 만들지 않습니다. 만료가 가까우면 SDK가 갱신하고, 갱신·사용자 검증·프로필 활성 상태 확인이 실패하면 문서 화면을 차단합니다.

## 문제 해결

| 화면 메시지 / 상황 | 확인할 내용 |
|---|---|
| 로그인 테이블이 준비되지 않았습니다 | 2단계 SQL 적용, 프로젝트 주소, public 스키마 노출 여부 |
| 아이디 또는 비밀번호를 확인해 주세요 | 아이디 연결, 비밀번호, 개별 이메일 확인, `active=true` 여부 |
| 로그인 정보를 확인하지 못했습니다 | Publishable/Secret key 구분, 프로필 읽기 권한과 RLS |
| 로그인 시도가 많습니다 | 동일 아이디에 대해 이 앱 프로세스에서 1분간 최대 5회 시도 가능. Supabase의 추가 제한도 적용 |
| 비밀번호 변경 실패 | 10자 이상인지, 이전과 다른지, Supabase 비밀번호 정책·재인증 요구 여부 확인 |
| 비밀번호는 변경되었으나 상태 저장 실패 | 새 비밀번호로 재로그인 후 다시 변경하거나 관리자에게 문의. 변경 완료 플래그를 자동 우회하지 않음 |
| 로그인 뒤 새로고침하면 다시 로그인 화면 | 현재는 브라우저 세션 기반이며 영구 로그인 미구현 |

같은 사용자의 다른 브라우저 세션까지 로그아웃시키지는 않습니다. Supabase에서 이미 발급된 접근 토큰은 만료 전까지 유효할 수 있습니다. 앱의 로그아웃은 현재 화면 상태와 세션을 제거합니다.

아이디 시도 제한은 단일 Python 프로세스용입니다. 여러 서버로 배포할 때는 공유 저장소 기반 제한이 필요합니다. 웹앱 외부 공개 시 HTTPS 호스팅과 기존 매뉴얼의 배포 설정을 적용하세요.

## 구현 및 검증 범위

- `src/auth.py`: 아이디 조회, 별도 사용자 클라이언트, Auth 검증, 프로필 활성 상태 확인, 최초 비밀번호 변경, 로그아웃.
- `src/auth_ui.py`: 로그인 전 차단, 비밀번호 변경 화면, 로그아웃 시 세션·입력 위젯·생성 결과 정리.
- `app.py`: 모든 문서 화면보다 먼저 인증 검사.
- 자동 테스트는 실제 SDK를 모의 HTTP 서버에 연결하며, 실제 계정이나 비밀번호를 변경하지 않습니다. 현재 프로젝트에서는 실제 계정으로 로그인·권한·비밀번호 변경·문서 생성·로그아웃까지 별도 검증했습니다. 이후 새 환경에서는 위 설정 후 브라우저에서도 확인하세요.
- 고객 저장·문서 이력·Storage·계정 관리 화면·메일 비밀번호 재설정·MFA는 이번 구현에 포함하지 않습니다.

공식 참고: [Python SDK](https://supabase.com/docs/reference/python/introduction), [비밀번호 로그인](https://supabase.com/docs/reference/python/auth-signinwithpassword), [서버의 사용자 확인](https://supabase.com/docs/reference/python/auth-getuser), [관리자 사용자 조회](https://supabase.com/docs/reference/python/auth-admin-getuserbyid), [비밀번호 변경](https://supabase.com/docs/reference/python/auth-updateuser), [로그아웃](https://supabase.com/docs/reference/python/auth-signout).
