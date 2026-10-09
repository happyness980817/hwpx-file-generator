from pathlib import Path
from unittest.mock import Mock
import copy
import pytest
from streamlit.testing.v1 import AppTest
from src.errors import DocumentError
from src.models import sample_data, example_plan
from src.guest_work import WorkAccess

ROOT = Path(__file__).resolve().parents[1]


def click(app, label):
    return next(button for button in app.button if button.label == label).click().run(timeout=30)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: False)
    monkeypatch.setattr('src.guest_work.storage_ready', lambda: False)


def test_public_home_manual_dialog_and_downloads():
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
    assert not app.exception and not app.text_input
    assert not any(button.label == '로그인' for button in app.button)
    assert len(app.get('file_uploader')) == 1
    click(app, '가상 자료로 체험하기')
    click(app, '세부 정보 수정')
    name = next(field for field in app.text_input if field.label == '회사명 *')
    name.set_value('직접 수정한 회사')
    area = next(field for field in app.text_area if field.label == '수출 마케팅 전략')
    area.set_value('고객이 직접 정정한 마케팅 계획')
    click(app, '수정 내용 적용')
    assert not app.exception
    assert app.session_state['data']['company']['nameKo'] == '직접 수정한 회사'
    click(app, '한글파일 두 개 만들기')
    assert not app.exception and len(app.session_state['result']['files']) == 2
    assert len(app.get('download_button')) == 3
    click(app, '새 신청서')
    click(app, '새로 시작')
    assert not app.session_state['data']['company']['nameKo'] and 'result' not in app.session_state


def test_ai_consent_prompt_updates_and_failure_keep_draft(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    data = sample_data()
    data['plan'].update(example_plan(data))
    draft = Mock(return_value={'data': data, 'source_notes': '가상 자료', 'questions': ['상표 확인 필요'], 'summary': '초안을 작성했습니다.'})
    monkeypatch.setattr('src.agent.compose_from_materials', draft)
    app = AppTest.from_file(str(ROOT / 'app.py')).run()
    app.text_area(key='writing_request').set_value('가온식품의 과자를 일본에 수출하려고 합니다.')
    app.run()
    assert next(button for button in app.button if button.label == '자료에서 초안 만들기').disabled
    app.checkbox(key='ai_consent').check().run()
    click(app, '자료에서 초안 만들기')
    assert not app.exception and app.session_state['data'] == data
    draft.assert_called_once()
    old = copy.deepcopy(app.session_state['data'])
    draft.side_effect = DocumentError('시험 오류')
    app.session_state['last_ai_at'] = -1000
    app.chat_input[0].set_value('수출 실적은 없다고 정정').run()
    assert any('시험 오류' in error.value for error in app.error)
    assert app.session_state['data'] == old


def test_restore_requires_work_password_and_clears_other_materials(monkeypatch):
    monkeypatch.setattr('src.guest_work.storage_ready', lambda: True)
    access = WorkAccess('A'*24, 'long-confirmation-password')
    saved = {'data': sample_data(), 'messages': [], 'questions': [], 'source_notes': '저장한 자료', 'source_names': ['소개서.pdf']}
    restore = Mock(side_effect=DocumentError('작업번호와 확인 비밀번호를 확인해 주세요.'))
    monkeypatch.setattr('src.guest_work.load_work', restore)
    app = AppTest.from_file(str(ROOT / 'app.py')).run()
    click(app, '작업 열기')
    next(field for field in app.text_input if field.label == '작업번호').set_value(access.number)
    next(field for field in app.text_input if field.label == '확인 비밀번호').set_value('wrong-password')
    click(app, '작업 불러오기')
    assert app.error and not app.session_state['data']['company']['nameKo']
    restore.side_effect = None
    restore.return_value = (access, saved)
    next(field for field in app.text_input if field.label == '작업번호').set_value(access.number)
    next(field for field in app.text_input if field.label == '확인 비밀번호').set_value(access.password)
    click(app, '작업 불러오기')
    assert not app.exception and app.session_state['data'] == saved['data']
    assert app.session_state['uploader_revision'] == 1
    assert app.session_state['ai_consent'] is False
