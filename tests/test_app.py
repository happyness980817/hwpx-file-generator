from pathlib import Path
from unittest.mock import patch

import pytest

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def authenticated_document_tests(monkeypatch):
    # Document UI tests run behind a mocked successful login; actual login gates
    # and the SDK's network contract are tested separately.
    monkeypatch.setattr("src.auth_ui.require_login", lambda: {"username": "test-user"})


def click(app, label):
    return next(b for b in app.button if b.label == label).click().run(timeout=30)


def test_frontend_without_api_or_database(tmp_path):
    from src.service import generate_documents
    with patch("src.ai.ai_ready", return_value=False), patch("src.service.generate_documents", side_effect=lambda data: generate_documents(data, tmp_path)):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        assert not app.exception
        click(app, "가상 고객 자료로 시작")
        assert app.text_input(key="field_company_nameKo").value == "가온식품(테스트)"
        click(app, "고객 정보 저장 → 문안 검토")
        assert not app.exception
        assert next(b for b in app.button if b.label == "AI로 문안 작성").disabled
        click(app, "테스트 예시 문안 넣기")
        app.text_area(key="plan_marketing").set_value("직접 수정한 마케팅 문안")
        click(app, "문안 저장 → 파일 다운로드")
        click(app, "HWPX 파일 두 개 생성")
        assert not app.exception
        assert len(app.session_state["result"]["files"]) == 2
        assert app.session_state["data"]["plan"]["marketing"] == "직접 수정한 마케팅 문안"
        assert any("두 문서 ZIP" in b.label for b in app.get("download_button"))
        app.run()
        assert len(app.session_state["result"]["files"]) == 2
        click(app, "입력 초기화")
        assert app.session_state["data"]["company"]["nameKo"] == ""
        assert not app.exception


def test_required_company():
    app = AppTest.from_file(str(ROOT / "app.py")).run()
    click(app, "고객 정보 저장 → 문안 검토")
    assert any("회사명" in e.value for e in app.error)
    assert not app.exception
