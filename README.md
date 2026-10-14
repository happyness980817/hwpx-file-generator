# K-브랜드 신청서 도우미

회사·상품 정보를 직접 입력하거나 자료 파일에서 AI가 빈칸을 보완하는 Python + Streamlit 사이트입니다. 로그인·문서 비밀번호 없이 이용합니다.

## 사용 흐름

1. **새 문서 생성**을 누릅니다.
2. 회사와 상품 정보를 입력합니다. **상품관련 자료 및 회사 소개자료** 첨부는 선택사항입니다.
3. 필요한 경우 **AI로 초안 채우기**를 누르고 내용을 검토합니다. 예시는 회색 플레이스홀더이며 실제 데이터로 제출되지 않습니다.
4. **제출하기**를 누르면 필수항목을 확인하고 문서 5종을 만든 뒤 지정한 Google 스프레드시트의 **참여기업** 탭에 저장합니다.
5. 한글 4종과 엑셀 상품리스트를 ZIP 또는 개별 파일로 다운로드합니다.

입력 변경·AI 분석·미리보기·다운로드만으로는 시트에 저장하지 않습니다. 같은 화면에서 수정한 뒤 다시 제출하면 같은 행을 갱신합니다. 시트 저장 실패 시 입력과 생성 파일이 유지되며, 같은 제출 ID로 재시도합니다. 새 문서를 시작하거나 브라우저 세션이 끝나면 다른 제출로 취급합니다. 문서 다시 불러오기 기능은 없습니다.

**미리보기 파일 만들기**는 회사명만 있어도 가능합니다. 비어 있는 문서 칸은 노란색으로 표시됩니다. 서명·직인·동의 및 제품사진은 직접 확인·첨부해야 합니다. 사이트의 접수는 담당자용 시트 저장이며 한국지식재산보호원에 서류를 전송하지 않습니다.

## 실행

```powershell
uv sync --locked
uv run streamlit run app.py
```

개발 화면은 http://127.0.0.1:8501 입니다. `dev.cmd`도 사용할 수 있습니다.

## 배포 설정

Streamlit Cloud **Settings → Secrets**에 기존 OpenAI 설정과 Google Sheets 설정을 함께 둡니다. 로컬 OpenAI 설정은 `.env`, Google 설정은 Git에서 제외된 `.streamlit/secrets.toml`을 사용합니다. 인증 정보는 저장소에 올리지 않습니다.

```toml
OPENAI_API_KEY = "실제 키"
OPENAI_MODEL = "gpt-6-astra"
OPENAI_REASONING_EFFORT = "high"

[google_sheets]
client_id = "OAuth 클라이언트 ID"
client_secret = "OAuth 클라이언트 Secret"
refresh_token = "승인 후 발급된 Refresh Token"
spreadsheet_id = "192vVKcrNFH4iD7-eASl_HY4tln_N88jRtj0SyzJZPRE"
sheet_name = "참여기업"
```

Google 계정과 Streamlit/GitHub 계정은 달라도 됩니다. Google 계정에 대상 스프레드시트 편집 권한이 필요합니다. 현재 승인 계정은 managergoal@iyouproject.com입니다. Sheets API와 OAuth 인증은 설정되어 있으며, 기존 인증을 재사용합니다. Supabase 설정은 현재 화면에서 사용하지 않습니다.

재인증이 필요할 때만 다음 도우미를 사용합니다. 기존 파일을 덮어쓰지 않으므로 새 출력 경로를 지정합니다.

```powershell
uv run python scripts/authorize_google_sheets.py --client-json data/google_oauth/client.json --output data/google_oauth/sheets-secrets-new.toml
```

OAuth 웹 클라이언트의 승인된 리디렉션 URI는 `http://localhost:8765/oauth/callback`입니다. 승인 결과 중 `[google_sheets]`를 로컬·Cloud Secrets에 반영하고 `sheet_name`을 `참여기업`으로 설정합니다.

## 저장 내용과 범위

회사·담당자·상품 요약, 수출국가, 활용계획 및 전체 입력 내용을 보관합니다. 기존 **시트1**의 예시는 변경하지 않습니다. `참여기업` 탭은 최초 제출 시 없으면 생성합니다. 제출 ID로 재시도·수정을 구별하고 값은 수식으로 실행하지 않고 텍스트로 기록합니다. 시트 헤더가 변경되거나 내용이 셀 한도를 넘으면 덮어쓰기·잘라내기 대신 오류를 표시합니다.

첨부 파일명은 저장하지만 **원본 첨부와 생성 파일 자체는 Drive에 업로드하지 않습니다.** 첨부 파일과 다운로드 결과는 접속 세션의 메모리에서 사용하며, 파일 생성용 임시 폴더는 처리 후 정리됩니다. 여러 서버 인스턴스의 동시 쓰기를 전역 트랜잭션으로 보장하는 구조는 아닙니다.

## 입력 기본값

- 사용방식: 라벨 (권장), 단일 선택. 수행업체명은 이노프렌즈입니다.
- 신규 국가별 부착 예정수량: 100만장. 고객이 변경할 수 있는 계획값입니다.
- 신청일: 한국 시간 기준 오늘. 수정할 수 있습니다.
- 수출국가: 제공된 별첨의 73개국, 가나다순 복수 선택.
- 인증: 별첨2에서 확인한 26종 및 직접 입력.
- 상표 상태: 출원예정·출원중·출원완료·등록예정·등록중·등록완료.

국가·인증·상표·활용채널·피해사례·성장률은 예시를 기본값으로 넣지 않습니다.

## AI와 파일

파일당 10MB, 최대 5개, 합계 25MB입니다. PDF, PNG/JPEG/WebP, DOCX, XLSX, PPTX, HWPX, TXT, CSV를 지원합니다. HWP는 PDF/HWPX로 변환해 첨부합니다.

AI 기본 모델은 gpt-6-astra, 추론 강도는 high입니다. 모델은 기존 입력을 보존하고 모르는 사실은 빈칸으로 두도록 지시받습니다. 부족한 공개 회사·상품 정보는 웹검색으로 보완할 수 있습니다. 자료 분석 버튼을 누르면 입력과 첨부가 OpenAI API에 전달됩니다. `store=False`를 사용합니다. AI 실패 시 현재 내용은 유지됩니다.

생성기는 원본 양식 해시와 ZIP/XML 구조를 검사합니다. 법적 확약 본문은 유지하며 빈칸을 노랗게 표시합니다. 상품 최대20개, 상품별 국가73개, 공장4개, 세부 제품50개를 지원합니다. 자동 검사는 한컴에서의 최종 페이지 배치나 내용의 사실성을 보증하지 않습니다.

## 검사와 주요 코드

```powershell
uv run --locked pytest -q
```

- `app.py`: 화면·AI 실행·명시적 제출·다운로드
- `src/form_ui.py`, `src/form_examples.py`: 입력칸과 표시 전용 예시
- `src/google_sheets.py`: OAuth 토큰 갱신과 제출 저장
- `src/submission.py`: 제출 필수항목 검사
- `src/service.py`, `src/hwpx.py`, `src/product_list.py`: 문서5종 생성
- `src/document_prompt.txt`, `src/draft_schema.py`: AI 작성 규칙과 구조

테스트는 실제 고객 시트에 쓰지 않습니다. 이전 로그인/비밀번호 보관 관련 파일은 기존 자료의 유지보수를 위해 남아 있으며 현재 앱 경로에서는 호출하지 않습니다.
