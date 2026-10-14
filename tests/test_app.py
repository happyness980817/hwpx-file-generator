"""Application submission boundaries and local draft preservation."""
import copy
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.errors import DocumentError
from src.form_examples import CERTIFICATIONS, PLAN_PLACEHOLDERS
from src.models import COUNTRIES, PLAN_FIELDS, apply_form_defaults, empty_data, sample_data, today_kst

ROOT = Path(__file__).resolve().parents[1]


def click(app, label):
    return next(button for button in app.button if button.label == label).click().run(timeout=30)


def fresh():
    return AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()


def ready_data():
    data = apply_form_defaults(sample_data())
    data['company'].update(registrationNumber='123-45-67890', address='서울특별시 강남구 테스트로 1')
    data['contact']['phone'] = '010-1234-5678'
    return data


def editor(data=None):
    app = fresh()
    app.session_state['page'] = 'editor'
    app.session_state['data'] = copy.deepcopy(data if data is not None else ready_data())
    app.run()
    assert not app.exception
    return app


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: False)
    monkeypatch.setattr('src.google_sheets.sheets_ready', lambda: True)
    store = Mock(return_value={'row': 2, 'status': 'created'})
    monkeypatch.setattr('src.google_sheets.submit_application', store)
    return store


def test_home_has_one_new_document_action_and_no_password_or_link_form(no_network):
    app = fresh()
    assert not app.exception
    assert [button.label for button in app.button] == ['새 문서 생성']
    assert not app.text_input and not app.text_area and not app.get('file_uploader')
    click(app, '새 문서 생성')
    assert not app.exception
    assert len(app.get('file_uploader')) == 1 and not app.tabs
    assert app.get('file_uploader')[0].proto.label == '상품관련 자료 및 회사 소개자료'
    labels = [item.label for item in [*app.text_input, *app.text_area, *app.checkbox]]
    assert not any(word in label for label in labels for word in ['비밀번호', '링크', '추가 요청', 'AI 자료 분석'])
    assert not any('provider' in item.key for item in app.text_input)
    countries = app.multiselect(key='edit_0_product0_countries')
    assert len(countries.options) == 73 and countries.options == sorted(COUNTRIES)
    no_network.assert_not_called()


def test_defaults_are_real_but_examples_are_only_placeholders(no_network):
    app = editor(empty_data())
    data = app.session_state['data']
    assert data['provider'] == {'name': '이노프렌즈', 'contact': '', 'phone': ''}
    assert data['applicationDate'] == today_kst()
    assert data['projectType'] == '라벨'
    assert app.selectbox(key='edit_0_application_projectType').value == '라벨'
    assert app.selectbox(key='edit_0_contact_phone_prefix').value == '010'
    assert data['contact']['phone'] == ''
    assert data['company']['nameKo'] == data['products'][0]['brandKo'] == ''
    assert app.text_input(key='edit_0_product0_brandKo').placeholder == '(예시) 삼성 갤럭시 S24'
    for name in PLAN_FIELDS:
        assert app.text_area(key=f'edit_0_plan_{name}').placeholder == PLAN_PLACEHOLDERS[name]
        assert data['plan'][name] == ''
    assert data['plan']['channels'] == [] and data['plan']['ipHistory'] == ''
    app.multiselect(key='edit_0_product0_countries').set_value(['인도']).run()
    row = app.session_state['data']['products'][0]['countries'][0]
    assert row['quantity'] == '100만장' and row['method'] == '라벨'
    no_network.assert_not_called()


def test_manual_preview_with_no_upload_creates_five_downloads_without_submitting(no_network):
    app = editor(empty_data())
    app.text_input(key='edit_0_company_nameKo').set_value('미리보기 기업').run()
    click(app, '미리보기 파일 만들기')
    assert not app.exception and not app.error
    assert len(app.session_state['result']['files']) == 5
    assert len(app.get('download_button')) == 6
    assert all(item.proto.ignore_rerun for item in app.get('download_button'))
    app.run()
    click(app, '처음으로')
    click(app, '작성 중인 내용으로 돌아가기')
    assert app.session_state['data']['company']['nameKo'] == '미리보기 기업'
    assert len(app.get('download_button')) == 6
    no_network.assert_not_called()


def test_explicit_submit_only_and_edit_resubmit_uses_same_id(no_network):
    app = editor()
    submission_id = app.session_state['submission_id']
    uuid.UUID(submission_id)
    app.text_input(key='edit_0_company_nameKo').set_value('제출 전 수정 기업').run()
    app.run()
    no_network.assert_not_called()
    click(app, '제출하기')
    assert not app.exception and not app.error and app.success
    assert len(app.session_state['result']['files']) == 5
    assert no_network.call_count == 1
    args = no_network.call_args.args
    assert args[0]['company']['nameKo'] == '제출 전 수정 기업'
    assert args[0]['contact']['phone'] == '010-1234-5678'
    assert args[1] == submission_id
    assert no_network.call_args.kwargs == {'source_names': []}
    assert next(button for button in app.button if button.label == '수정 내용 제출하기').disabled
    app.run()
    assert no_network.call_count == 1
    app.text_input(key='edit_0_company_nameKo').set_value('제출 후 수정 기업').run()
    assert no_network.call_count == 1
    assert not next(button for button in app.button if button.label == '수정 내용 제출하기').disabled
    click(app, '수정 내용 제출하기')
    assert not app.exception and no_network.call_count == 2
    assert no_network.call_args.args[1] == submission_id
    assert no_network.call_args.args[0]['company']['nameKo'] == '제출 후 수정 기업'


def test_submission_failure_keeps_input_and_files_then_retries_same_id(no_network):
    no_network.side_effect = [DocumentError('시트 저장 시험 오류'), {'row': 2, 'status': 'updated'}]
    app = editor()
    before = copy.deepcopy(app.session_state['data'])
    submission_id = app.session_state['submission_id']
    click(app, '제출하기')
    assert not app.exception and app.error
    assert app.session_state['data'] == before
    assert len(app.get('download_button')) == 6
    first_zip = app.session_state['result']['zip']
    assert 'receipt' not in app.session_state
    app.run()
    assert no_network.call_count == 1
    click(app, '제출하기')
    assert not app.exception and not app.error and app.success
    assert app.session_state['data'] == before
    assert app.session_state['result']['zip'] == first_zip
    assert [call.args[1] for call in no_network.call_args_list] == [submission_id, submission_id]


def test_required_fields_stop_submit_before_generation_or_store(monkeypatch, no_network):
    generator = Mock()
    monkeypatch.setattr('src.service.generate_documents', generator)
    app = editor(empty_data())
    click(app, '제출하기')
    assert not app.exception and app.error
    assert '필수항목' in app.error[0].value
    generator.assert_not_called()
    no_network.assert_not_called()


def test_unconfigured_sheet_disables_submit_but_preview_still_works(monkeypatch, no_network):
    monkeypatch.setattr('src.google_sheets.sheets_ready', lambda: False)
    app = editor()
    assert next(button for button in app.button if button.label == '제출하기').disabled
    click(app, '미리보기 파일 만들기')
    assert not app.exception and len(app.get('download_button')) == 6
    no_network.assert_not_called()


def test_ai_is_optional_and_result_defaults_keep_selected_date_and_fields(monkeypatch, no_network):
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    data = ready_data()
    data['applicationDate'] = '2026-11-03'
    result_data = copy.deepcopy(data)
    result_data['provider']['name'] = '모델이 바꾼 업체명'
    result_data['plan']['marketing'] = '선택한 수출국가의 온라인몰에서 제품을 소개합니다.'
    compose = Mock(return_value={'data': result_data, 'source_notes': '직접 입력',
        'questions': [], 'summary': '작성했습니다.', 'search_sources': []})
    monkeypatch.setattr('src.agent.compose_from_materials', compose)
    app = editor(data)
    click(app, 'AI로 초안 채우기')
    assert not app.exception and not app.error
    assert compose.call_count == 1 and compose.call_args.args[1] == []
    assert compose.call_args.args[0]['company'] == data['company']
    assert app.session_state['data']['provider']['name'] == '이노프렌즈'
    assert app.session_state['data']['applicationDate'] == '2026-11-03'
    assert app.session_state['data']['company'] == data['company']
    assert app.session_state['data']['plan']['marketing'] == result_data['plan']['marketing']
    no_network.assert_not_called()
    before = copy.deepcopy(app.session_state['data'])
    compose.side_effect = DocumentError('AI 시험 오류')
    app.session_state['last_ai_at'] = -1000
    click(app, 'AI로 초안 채우기')
    assert not app.exception and app.error and app.session_state['data'] == before


def test_product_country_identity_and_added_rows_survive_edits(no_network):
    data = ready_data()
    data['products'][0]['countries'] = [
        {'country': '일본', 'trademarkStatus': '출원중', 'trademarkNumberOrReason': 'JP-123', 'quantity': '100만장', 'method': '라벨'},
        {'country': '미국', 'trademarkStatus': '등록완료', 'trademarkNumberOrReason': 'US-456', 'quantity': '10만장', 'method': '맞춤제작'}]
    app = editor(data)
    app.multiselect(key='edit_0_product0_countries').set_value(['미국']).run()
    assert app.session_state['data']['products'][0]['countries'] == [data['products'][0]['countries'][1]]
    click(app, '세부 제품 추가')
    assert len(app.session_state['data']['products'][0]['variants']) == 2
    revision = app.session_state['revision']
    app.text_input(key=f'edit_{revision}_company_nameKo').set_value('편집 중 회사').run()
    assert len(app.session_state['data']['products'][0]['variants']) == 2
    click(app, '상품 추가')
    revision = app.session_state['revision']
    app.text_input(key=f'edit_{revision}_product1_nameKo').set_value('두 번째 상품').run()
    app.button(key='remove_product_0').click().run()
    assert not app.exception
    assert len(app.session_state['data']['products']) == 1
    assert app.session_state['data']['products'][0]['nameKo'] == '두 번째 상품'
    no_network.assert_not_called()


def test_channels_and_certificates_allow_multiple_and_custom_certificate(no_network):
    app = editor()
    certifications = app.multiselect(key='edit_0_product0_certifications')
    assert certifications.options == CERTIFICATIONS
    certifications.set_value(['식품 HACCP', '직접 입력한 인증']).run()
    app.multiselect(key='edit_0_plan_channels').set_value(['제품', '포장', '홈페이지/SNS']).run()
    data = app.session_state['data']
    assert data['products'][0]['certifications'] == '식품 HACCP, 직접 입력한 인증'
    assert data['products'][0]['certificationHeld'] == '유'
    assert data['plan']['channels'] == ['제품', '포장', '홈페이지/SNS']
    no_network.assert_not_called()


@pytest.mark.parametrize('action', ['미리보기 파일 만들기', '제출하기'])
def test_cleared_date_requires_selection_before_creating_files(action, monkeypatch, no_network):
    generator = Mock()
    monkeypatch.setattr('src.service.generate_documents', generator)
    app = editor()
    app.date_input(key='edit_0_application_date').set_value(None).run()
    click(app, action)
    assert not app.exception and app.error
    assert '신청일' in app.error[0].value
    generator.assert_not_called()
    no_network.assert_not_called()


def test_changed_source_names_require_explicit_resubmission_with_same_id(no_network):
    app = editor()
    click(app, '제출하기')
    submission_id = app.session_state['submission_id']
    app.session_state['source_names'] = ['고객사 제품자료.pdf']
    app.run()
    assert no_network.call_count == 1
    assert not next(button for button in app.button if button.label == '수정 내용 제출하기').disabled
    click(app, '수정 내용 제출하기')
    assert not app.exception and no_network.call_count == 2
    assert no_network.call_args.args[1] == submission_id
    assert no_network.call_args.kwargs == {'source_names': ['고객사 제품자료.pdf']}
