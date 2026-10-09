# K-브랜드 신청서 도우미

고객이 회사소개서·제품 자료를 올리면 AI가 정보를 추출해 사용신청서와 도입 필요성 및 활용계획서의 초안을 작성하는 **Python + Streamlit** 사이트입니다. 가입·아이디 로그인은 없습니다.

## 사용자 흐름

1. 자료 업로드 또는 회사·제품 설명 입력 → 자료 전송 동의 → **자료에서 초안 만들기**.
2. 추출 결과와 확인 질문을 검토합니다. 대화로 수정을 요청하거나 **세부 정보 수정**에서 모든 항목을 직접 편집합니다.
3. **한글파일 두 개 만들기** → HWPX 개별 다운로드 또는 ZIP 다운로드.
4. 이어서 작성하려면 **작업 저장 · 확인 비밀번호 발급**을 누르고 작업번호와 비밀번호를 보관합니다. 재방문 시 **작업 열기**로 불러옵니다. 수정 후 다시 저장해야 합니다.

확인 비밀번호는 해당 작업에 접근하기 위한 비밀값이며 실명인증이 아닙니다. 이 정보를 분실하면 복구할 수 없습니다. 기존 sales01/admin 계정은 고객 사이트에서 사용하지 않으며 원격 Auth 계정을 삭제하지는 않습니다.

## 실행

```powershell
uv sync --locked
uv run streamlit run app.py
```

브라우저: http://127.0.0.1:8501. `dev.cmd`는 로컬 주소에서 실행합니다.

`.env` 또는 Streamlit Cloud **Settings → Secrets**에 아래 이름으로 설정합니다. Cloud는 TOML 형식의 최상위 항목으로 입력합니다.

```toml
OPENAI_API_KEY = "실제 키"
OPENAI_MODEL = "gpt-6-luna"
SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
SUPABASE_SECRET_KEY = "실제 서버 Secret 키"
```

기존 `.env`를 덮어쓰지 마세요. 새 Supabase 프로젝트에서 작업 보관함을 처음 준비할 때만 실행합니다.

```powershell
uv run python scripts/setup_guest_storage.py
```

이 명령은 비공개 `kbrand-guest-drafts` Storage 버킷만 준비합니다. 로그인용 테이블·계정이나 공개 Storage 정책은 만들지 않습니다. 기존 Publishable 키는 유지해도 되지만 이 사이트의 작업 저장에는 필요하지 않습니다. 저장 설정이 없더라도 자료 입력·문서 다운로드는 이용할 수 있습니다.

## 자료와 보관

- 지원: PDF, PNG/JPEG/WebP, DOCX, XLSX, PPTX, HWPX, TXT, CSV. HWP는 PDF/HWPX로 변환합니다.
- 파일당 10MB, 한 번에 5개, 합계 25MB. 압축 문서는 압축 해제 크기도 검사합니다.
- PDF·사진은 글자와 이미지를 모델에 전달합니다. Word/Excel/PowerPoint는 API가 읽는 텍스트·표를 바탕으로 작성하므로 포함된 사진·도표가 중요하면 PDF를 권장합니다.
- HWPX는 텍스트를 추출해 전달합니다. HWPX 안의 사진을 분석하려면 PDF로 올립니다.
- 원본 파일은 현재 접속 세션의 서버 메모리에서만 사용합니다. 서버 파일로 영구 저장하지 않습니다.
- 작업 저장 시 신청서 내용·자료에서 정리한 사실·최근 대화·확인 질문을 비밀번호 기반 AES-256-GCM으로 암호화해 비공개 Storage에 저장합니다. 비밀번호는 서버 저장물에 포함하지 않습니다. 작업번호만으로 읽거나 덮어쓸 수 없습니다.
- 생성 HWPX는 임시 폴더에서 검증 후 다운로드 바이트만 남기고 임시 폴더를 지웁니다. 저장한 작업을 다시 열어 문서를 재생성할 수 있습니다.
- 작업 열기 이후 원본 자료를 다시 분석하려면 파일을 다시 올립니다. 같은 작업을 여러 창에서 편집하면 마지막 저장 내용이 남습니다.
- AI API 요청은 버튼·대화 전송 때만 발생하며 `store=False`를 사용합니다. 작성 실패 시 기존 초안을 유지합니다.

## 코드와 검사

```text
app.py                 업로드·대화·초안·다운로드 화면
src/agent.py           자료 기반 추출과 대화 수정
src/materials.py       파일 형식·크기 검사와 HWPX 텍스트 추출
src/draft_schema.py    AI/수동 입력의 공통 데이터 구조
src/details_ui.py      기존 전체 입력 폼을 제공하는 세부 수정창
src/guest_work.py      작업번호·비밀번호 발급과 암호화 보관
src/service.py         임시 HWPX 생성과 ZIP 다운로드
src/hwpx.py            기존 원본 양식에 값 채우기·구조 검증
templates/             원본 HWPX 두 개
scripts/setup_guest_storage.py  비공개 작업 보관함 초기 설정
```

```powershell
uv run --locked pytest -q
```

테스트는 실제 API·계정을 변경하지 않습니다. 업로드 검사, 잘못된 작업 비밀번호 거절, 세션 간 격리, AI 실패 시 내용 보존, 세부 정보 편집과 HWPX 생성까지 확인합니다.

## 양식 범위

제품 1개, 국가 최대 3개, 공장 최대 4개입니다. 여러 제품이 있는 자료에서는 신청 대상을 요청사항으로 지정합니다. 자료에 없는 인증·실적 등을 임의로 만들지 않고 확인 질문을 남깁니다. 사진·서명·직인·동의는 자동 삽입하지 않습니다. 제출 전 고객 검토 및 실제 한글의 표·쪽 배치 확인이 필요합니다.

기존 `LOGIN_SETUP.md`, `SUPABASE_SETUP.md`, `supabase/` SQL은 이전 로그인 기반 설계 기록입니다. 현재 고객 사이트를 위해 실행할 필요가 없습니다.
