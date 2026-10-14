import copy
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.errors import DocumentError
from src.models import COUNTRIES, sample_data, example_plan
from src.password_documents import create_document, load_document

ROOT = Path(__file__).resolve().parents[1]


def click(app, label):
    return next(button for button in app.button if button.label == label).click().run(timeout=30)


def field(app, label):
    return next(item for item in app.text_input if item.label == label)


def fresh():
    return AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()


@pytest.fixture(autouse=True)
def no_network(monkeypatch, document_store):
    monkeypatch.setattr('src.ai.ai_ready', lambda: False)
    monkeypatch.setattr('src.guest_work.storage_ready', lambda: True)


def test_home_two_choices_open_password_and_file_only_inline_editor():
    app = fresh()
    assert not app.exception
    assert [button.label for button in app.button] == ['새 문서 생성', '작성한 문서 불러오기']
    assert not app.text_input and not app.text_area and not app.get('file_uploader')
    click(app, '작성한 문서 불러오기')
    assert [item.label for item in app.text_input] == ['비밀번호']
    assert not app.text_area and not app.get('file_uploader')
    click(app, '처음으로')
    click(app, '새 문서 생성')
    assert not app.exception
    assert {'회사명', '대표자', '브랜드명', '대상제품', '문서 비밀번호'} <= {item.label for item in app.text_input}
    assert len(app.get('file_uploader')) == 1 and not app.tabs
    assert not any('링크' in item.label for item in [*app.text_input, *app.text_area])
    countries = next(item for item in app.multiselect if item.label == '수출국가')
    assert len(countries.options) == 73 and countries.options == COUNTRIES


def test_manual_creation_downloads_five_files_and_reopen_autosaves():
    app = fresh()
    click(app, '새 문서 생성')
    field(app, '회사명').set_value('직접 입력한 회사').run()
    assert next(button for button in app.button if button.label == '문서 생성').disabled
    app.text_input(key='new_password').set_value('Test-password-123').run()
    click(app, '문서 생성')
    assert not app.exception and 'new_password' not in app.session_state
    assert load_document('Test-password-123', 'test-browser')[1]['data']['company']['nameKo'] == '직접 입력한 회사'
    assert len(app.get('download_button')) == 6
    assert len(app.session_state['result']['files']) == 5
    app.run()
    assert len(app.get('download_button')) == 6
    click(app, '처음으로')
    assert 'work_access' not in app.session_state
    click(app, '작성한 문서 불러오기')
    app.text_input[0].set_value('Test-password-123')
    click(app, '불러오기')
    assert not app.exception and app.session_state['page'] == 'editor'
    assert not any(item.label == '문서 비밀번호' for item in app.text_input)
    assert field(app, '회사명').value == '직접 입력한 회사'
    field(app, '회사명').set_value('수정하여 저장한 회사').run()
    assert load_document('Test-password-123', 'other-browser')[1]['data']['company']['nameKo'] == '수정하여 저장한 회사'


def test_product_country_identity_and_unfinished_rows_survive_edits():
    data = sample_data()
    data['products'][0]['countries'] = [
        {'country':'일본', 'trademarkStatus':'출원중', 'trademarkNumberOrReason':'JP-123', 'quantity':'100', 'method':'라벨'},
        {'country':'미국', 'trademarkStatus':'등록완료', 'trademarkNumberOrReason':'US-456', 'quantity':'200', 'method':'맞춤제작'}]
    create_document('Test-password-123', {'data': data})
    app = fresh()
    click(app, '작성한 문서 불러오기')
    app.text_input[0].set_value('Test-password-123')
    click(app, '불러오기')
    country = next(item for item in app.multiselect if item.label == '수출국가')
    country.set_value(['미국']).run()
    assert app.session_state['data']['products'][0]['countries'] == [data['products'][0]['countries'][1]]
    click(app, '세부 제품 추가')
    assert len(app.session_state['data']['products'][0]['variants']) == 2
    field(app, '회사명').set_value('편집 중 회사').run()
    assert len(app.session_state['data']['products'][0]['variants']) == 2
    click(app, '상품 추가')
    assert len(app.session_state['data']['products']) == 2
    assert app.session_state['data']['products'][0]['countries'][0]['quantity'] == '200'
    revision = app.session_state['revision']
    app.text_input(key=f'edit_{revision}_product1_nameKo').set_value('두 번째 상품').run()
    app.button(key='remove_product_0').click().run()
    assert not app.exception
    assert len(app.session_state['data']['products']) == 1
    assert app.session_state['data']['products'][0]['nameKo'] == '두 번째 상품'
    restored = load_document('Test-password-123', 'other-browser')[1]['data']
    assert restored['products'][0]['nameKo'] == '두 번째 상품'


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
    assert not app.exception and app.session_state['data']['company'] == sample_data()['company']
    assert not app.session_state['ai_consent'] and app.session_state['writing_request'] == ''


def test_ai_creation_autosaves_without_password_and_failed_retry_preserves_data(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    data = sample_data()
    data['plan'].update(example_plan(data))
    draft = Mock(return_value={'data': data, 'source_notes': '공식 자료', 'search_sources': ['https://example.com/company'], 'questions': ['상표 확인'], 'summary': '작성했습니다.'})
    monkeypatch.setattr('src.agent.compose_from_materials', draft)
    app = fresh()
    click(app, '새 문서 생성')
    app.text_area(key='writing_request').set_value('가온식품 회사와 상품 정보로 작성')
    app.text_input(key='new_password').set_value('Test-password-123').run()
    assert next(button for button in app.button if button.label == '문서 생성').disabled
    app.checkbox(key='ai_consent').check().run()
    click(app, '문서 생성')
    assert not app.exception and app.session_state['data']['company'] == data['company']
    assert 'Test-password-123' not in repr(draft.call_args)
    assert len(app.get('download_button')) == 6
    app.run()
    assert len(app.get('download_button')) == 6
    restored = load_document('Test-password-123', 'reopen-browser')[1]
    assert restored['data']['company'] == data['company']
    assert restored['source_names'] == ['https://example.com/company']
    old = copy.deepcopy(app.session_state['data'])
    draft.side_effect = DocumentError('시험 오류')
    app.session_state['last_ai_at'] = -1000
    app.text_area(key='writing_request').set_value('계획 수정').run()
    click(app, '자료로 자동 채우기')
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
    field(app, '회사명').set_value('저장 재시도 회사').run()
    assert app.session_state['save_error'] and app.session_state['data']['company']['nameKo'] == '저장 재시도 회사'
    app.run()
    assert app.error
    monkeypatch.setattr(documents, 'save_document', original_save)
    click(app, '다시 저장')
    assert not app.exception and not app.error
    assert load_document('Test-password-123', 'check-browser')[1]['data']['company']['nameKo'] == '저장 재시도 회사'
