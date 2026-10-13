import copy
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.errors import DocumentError
from src.models import sample_data, example_plan
from src.password_documents import create_document, load_document
from src.web_materials import WebMaterial

ROOT = Path(__file__).resolve().parents[1]


def click(app, label):
    return next(button for button in app.button if button.label == label).click().run(timeout=30)


def fresh():
    return AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()


@pytest.fixture(autouse=True)
def no_network(monkeypatch, document_store):
    monkeypatch.setattr('src.ai.ai_ready', lambda: False)
    monkeypatch.setattr('src.guest_work.storage_ready', lambda: True)


def test_home_has_only_two_choices_and_open_has_only_password():
    app = fresh()
    assert not app.exception
    assert [button.label for button in app.button] == ['새 문서 생성', '작성한 문서 불러오기']
    assert not app.text_input and not app.text_area and not app.get('file_uploader')
    click(app, '작성한 문서 불러오기')
    assert [field.label for field in app.text_input] == ['비밀번호']
    assert not app.text_area and not app.get('file_uploader')
    click(app, '처음으로')
    click(app, '새 문서 생성')
    assert not app.exception
    assert [field.label for field in app.text_input] == ['문서 비밀번호']
    assert len(app.get('file_uploader')) == 1
    assert not app.tabs  # Link and file are both visible, not tabs.
    assert any(field.label == '회사·제품 링크' for field in app.text_area)


def test_manual_creation_requires_password_and_downloads_can_be_reopened():
    app = fresh()
    click(app, '새 문서 생성')
    click(app, '직접 입력')
    next(field for field in app.text_input if field.label == '회사명 *').set_value('직접 입력한 회사')
    click(app, '수정 내용 적용')
    assert not app.exception
    assert next(button for button in app.button if button.label == '문서 생성').disabled
    app.text_input(key='new_password').set_value('Test-password-123').run()
    click(app, '문서 생성')
    assert not app.exception and 'new_password' not in app.session_state
    assert load_document('Test-password-123', 'test-browser')[1]['data']['company']['nameKo'] == '직접 입력한 회사'
    click(app, '한글파일 만들기')
    assert len(app.get('download_button')) == 3
    assert len(app.session_state['result']['files']) == 2
    assert not any('발급' in button.label for button in app.button)
    click(app, '처음으로')
    assert 'work_access' not in app.session_state
    click(app, '작성한 문서 불러오기')
    app.text_input[0].set_value('Test-password-123')
    click(app, '불러오기')
    assert not app.exception and app.session_state['page'] == 'editor'
    assert not app.text_input
    assert app.session_state['data']['company']['nameKo'] == '직접 입력한 회사'
    click(app, '내용 수정')
    next(field for field in app.text_input if field.label == '회사명 *').set_value('수정하여 저장한 회사')
    click(app, '수정 내용 적용')
    assert load_document('Test-password-123', 'other-browser')[1]['data']['company']['nameKo'] == '수정하여 저장한 회사'


def test_open_wrong_password_keeps_form_and_success_clears_other_state():
    create_document('Test-password-123', {'data': sample_data(), 'source_names': ['https://example.com']})
    app = fresh()
    click(app, '작성한 문서 불러오기')
    app.text_input[0].set_value('Wrong-password-123')
    click(app, '불러오기')
    assert app.error and app.session_state['page'] == 'open'
    assert not app.session_state['data']['company']['nameKo']
    app.text_input[0].set_value('Test-password-123')
    click(app, '불러오기')
    assert not app.exception and app.session_state['data'] == sample_data()
    assert app.session_state['material_links'] == '' and not app.session_state['ai_consent']


def test_link_only_ai_creation_autosaves_without_password_in_model_input(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    material = WebMaterial('https://example.com/product', '가온식품', '회사·제품 소개')
    fetch = Mock(return_value=[material])
    monkeypatch.setattr('src.web_materials.prepare_links', fetch)
    data = sample_data()
    data['plan'].update(example_plan(data))
    draft = Mock(return_value={'data': data, 'source_notes': 'https://example.com/product', 'questions': ['상표 확인'], 'summary': '작성했습니다.'})
    monkeypatch.setattr('src.agent.compose_from_materials', draft)
    app = fresh()
    click(app, '새 문서 생성')
    app.text_area(key='material_links').set_value('https://example.com/product')
    app.text_input(key='new_password').set_value('Test-password-123')
    app.run()
    assert next(button for button in app.button if button.label == '문서 생성').disabled
    fetch.assert_not_called()
    app.checkbox(key='ai_consent').check().run()
    click(app, '문서 생성')
    assert not app.exception and app.session_state['data'] == data
    assert 'Test-password-123' not in repr(draft.call_args)
    assert draft.call_args.args[1] == [material]
    restored = load_document('Test-password-123', 'reopen-browser')[1]
    assert restored['data'] == data and restored['source_names'] == [material.name]
    old = copy.deepcopy(app.session_state['data'])
    draft.side_effect = DocumentError('시험 오류')
    app.session_state['last_ai_at'] = -1000
    app.chat_input[0].set_value('계획 수정').run()
    assert app.error and app.session_state['data'] == old


def test_duplicate_password_stops_before_ai_and_does_not_open_other_document(monkeypatch):
    create_document('Test-password-123', {'data': sample_data()})
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    draft = Mock()
    monkeypatch.setattr('src.agent.compose_from_materials', draft)
    app = fresh()
    click(app, '새 문서 생성')
    app.text_area(key='writing_request').set_value('가온식품의 제품으로 작성')
    app.text_input(key='new_password').set_value('Test-password-123')
    app.checkbox(key='ai_consent').check().run()
    click(app, '문서 생성')
    assert app.error and 'work_access' not in app.session_state
    assert not app.session_state['data']['company']['nameKo']
    draft.assert_not_called()


def test_save_failure_retains_edits_and_retry_saves(monkeypatch):
    import src.password_documents as documents
    create_document('Test-password-123', {'data': sample_data()})
    app = fresh()
    click(app, '작성한 문서 불러오기')
    app.text_input[0].set_value('Test-password-123')
    click(app, '불러오기')
    original_save = documents.save_document
    monkeypatch.setattr(documents, 'save_document', Mock(side_effect=DocumentError('저장 실패')))
    click(app, '내용 수정')
    next(field for field in app.text_input if field.label == '회사명 *').set_value('저장 재시도 회사')
    click(app, '수정 내용 적용')
    assert app.error and app.session_state['data']['company']['nameKo'] == '저장 재시도 회사'
    monkeypatch.setattr(documents, 'save_document', original_save)
    click(app, '저장')
    assert not app.exception and not app.error
    assert load_document('Test-password-123', 'check-browser')[1]['data']['company']['nameKo'] == '저장 재시도 회사'
