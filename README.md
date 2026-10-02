# K-브랜드 문서 작업실

고객사 정보를 입력하고 활용계획서 문안을 검토한 뒤, 원본 양식에 채운 HWPX 두 개와 ZIP을 다운로드하는 **Python + Streamlit** 앱입니다. HWPX 생성에는 Python 표준 라이브러리만 사용하므로 Node.js와 한글 프로그램 설치가 필요하지 않습니다.

## 시작하기

`C:\notion-workspace-writer-agent`에서 실행합니다.

```powershell
uv sync
uv run streamlit run app.py
```

브라우저: <http://127.0.0.1:8501>. Windows에서는 `dev.cmd`로도 실행할 수 있습니다. 종료는 실행 터미널에서 `Ctrl+C`입니다. 포트가 사용 중이면 기존 서버를 종료하거나 `uv run streamlit run app.py --server.port 8502`로 실행하세요.

현재 프로젝트에는 `admin`, `sales01`, `sales02` 로그인이 준비되어 있습니다. 초기 비밀번호 위치와 새 환경 설정은 [로그인 설정 매뉴얼](LOGIN_SETUP.md)을 참고하세요. 로그인 후에는 OpenAI API 키 없이도 가상 고객 자료 → 테스트 예시 문안 → 파일 생성·다운로드를 시험할 수 있습니다. 현재 이 PC의 OpenAI 연결도 설정되어 있으며 `gpt-6-luna`로 실제 문안 작성과 HWPX 두 개·ZIP 생성을 검증했습니다(2026-10-02). 화면에서 자료 전송에 동의한 뒤 **AI로 문안 작성**을 누르시면 됩니다. 새 환경에서는 `.env`의 `OPENAI_API_KEY`, `OPENAI_MODEL`을 설정합니다. 기존 `.env`를 덮어쓰지 마세요. 새 설치라면 `.env.example`을 `.env`로 복사합니다.

- 화면 사용 및 테스트: [FRONTEND.md](FRONTEND.md)
- 추후 고객 DB·Storage 연결 매뉴얼: [SUPABASE_SETUP.md](SUPABASE_SETUP.md)

## 코드 구조

```text
app.py                              Streamlit 화면과 세션 상태
src/
  auth.py                           아이디 인증·세션·최초 비밀번호 변경
  auth_ui.py                        로그인 화면과 문서 접근 차단
  models.py                         입력 구조·가상 자료·예시 문안
  ai.py                             선택적 AI 문안 작성
  service.py                        작업 폴더·파일 검증·다운로드 ZIP
  hwpx.py                           원본 양식에 입력·HWPX 구조 검증
  config.py                         경로·환경 설정
  errors.py                         화면에 표시할 오류
templates/                          원본 HWPX 두 개 (수정 금지)
tests/                              생성기 및 화면 회귀 테스트
supabase/                           향후 연동용 SQL 예시
result/                             실행별 입력 JSON·문서·검증 보고서
pyproject.toml / uv.lock             Python 의존성 및 잠금 파일
```

화면 → `service.py` → `hwpx.py`가 모두 같은 Python 프로세스에서 실행됩니다. AI는 문안 작성 버튼을 누를 때만 호출하며, 직접 작성한 문안으로도 HWPX를 생성할 수 있습니다. 다운로드 ZIP은 메모리에서 준비하고, 개별 HWPX·미리보기 TXT·검증 JSON은 요청마다 별도 `result/<UUID>/` 하위에 저장합니다.

이전 Notion 웹훅·Express 예제, JavaScript 생성기와 npm 설정은 제거했습니다. `data/`의 과거 기록과 기존 결과는 보존하지만 현재 앱에서는 과거 웹훅 기록을 사용하지 않습니다. 별도 프로젝트인 `C:\dev-project\file-generator`는 변경하지 않았습니다.

## 검증

```powershell
uv run pytest
```

테스트는 실제 API나 DB에 연결하지 않습니다. 기존 JavaScript 생성기로 만든 가상 입력 3종의 문서 XML·본문·경고와 Python 출력을 비교합니다. 참조값은 `tests/fixtures/generator_reference.json`에 보관하며 정상 코드에 맞추기 위해 임의로 갱신하지 않습니다. 양식을 교체할 때는 셀 매핑·스타일·원본 해시를 함께 검증해야 합니다.

## 현재 지원 범위

- 제품 1개, 국가 최대 3개, 공장 최대 4개. 초과 입력은 중단합니다.
- 미확인 필수값은 ‘확인 필요’로 표시하고, 결과는 검토용으로 생성합니다.
- 사진 삽입·개인정보 동의 체크·서명·직인은 자동 작성하지 않습니다.
- Supabase 아이디·비밀번호 로그인, 로그아웃, 최초 비밀번호 변경을 지원합니다. 실제 사용에는 로그인 테이블과 발급 계정이 필요합니다.
- 고객 DB 저장·Storage·백그라운드 작업 큐는 아직 구현하지 않았습니다. 현재는 로컬 개발용입니다.
- ZIP/XML·스타일 참조·셀 값 검증은 자동으로 수행합니다. 실제 한글의 표·쪽 배치는 별도로 열어 확인해야 합니다.
