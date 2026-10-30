"""Single-screen application, explicit AI actions, and current-value downloads."""
import copy
import io
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.errors import DocumentError
from src.form_examples import PLAN_PLACEHOLDERS
from src.models import COUNTRIES, PLAN_FIELDS, apply_form_defaults, country_label, empty_data, sample_data, today_kst

ROOT = Path(__file__).resolve().parents[1]


def click(app, label):
    return next(button for button in app.button if button.label == label).click().run(timeout=30)


def ready_data():
    data = apply_form_defaults(sample_data())
    data['company'].update(registrationNumber='123-45-67890', address='서울특별시 강남구 테스트로 1')
    data['contact']['phone'] = '010-1234-5678'
    return data


def editor(data=None):
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
    if data is not None:
        app.session_state['data'] = copy.deepcopy(data)
    app.run()
    assert not app.exception
    return app


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: False)
    store = Mock(return_value={'status': 'saved'})
    monkeypatch.setattr('src.application_store.save_application', store)
    monkeypatch.setattr('src.agent.OpenAI', Mock(side_effect=AssertionError('No live API calls in tests.')))
    return store


@pytest.fixture
def download_bridge(monkeypatch):
    bridge = Mock()
    monkeypatch.setattr('src.download_ui.render_file_download', bridge)
    return bridge


def ai_result(data, **extra):
    return {'data': copy.deepcopy(data), 'source_notes': '', 'questions': [],
            'summary': '반영했습니다.', 'search_sources': [], **extra}


def test_first_screen_is_form_and_exact_requested_copy(no_network):
    app = editor()
    assert len(app.get('file_uploader')) == 1 and not app.tabs
    assert app.text_input(key='company_query').label == '회사명:'
    assert app.text_input(key='company_query').placeholder == '회사명 또는 브랜드명을 입력하세요'
    assert app.text_area(key='writing_request').label == 'AI에게 요청하기 (선택)'
    buttons = [button.label for button in app.button]
    assert '신청 내용 자동으로 채우기' in buttons
    assert '요청 반영하기' in buttons and '신청서 내려받기' in buttons
    assert not any(word in label for label in buttons for word in ('새 문서', '불러오기', '처음으로', '제출', '미리보기'))
    assert any('웹에서 회사 정보를 찾아' in item.value for item in app.caption)
    assert any('class="optional">(선택)</span>' in item.value for item in app.markdown)
    assert not app.get('link_button')
    assert not any('비밀번호' in item.label for item in app.text_input)
    assert not any('provider' in item.key for item in app.text_input)
    countries = app.multiselect(key='edit_0_product0_countries')
    assert len(countries.options) == 73 and countries.options == sorted(map(country_label, COUNTRIES))
    assert not app.get('download_button')
    no_network.assert_not_called()


def test_defaults_are_real_but_examples_are_only_placeholders():
    app = editor()
    data = app.session_state['data']
    assert data['provider'] == {'name': '이노프렌즈', 'contact': '', 'phone': ''}
    assert data['applicationDate'] == today_kst() and data['projectType'] == '라벨'
    assert app.selectbox(key='edit_0_contact_phone_prefix').value == '010'
    assert data['contact']['phone'] == ''
    assert data['company']['nameKo'] == data['products'][0]['brandKo'] == ''
    for name in PLAN_FIELDS:
        assert app.text_area(key=f'edit_0_plan_{name}').placeholder == PLAN_PLACEHOLDERS[name]
        assert data['plan'][name] == ''
    app.multiselect(key='edit_0_product0_countries').set_value(['인도']).run()
    row = app.session_state['data']['products'][0]['countries'][0]
    assert row['quantity'] == '100만장' and row['method'] == '라벨'


def test_download_one_action_creates_five_files_and_saves_database(download_bridge, no_network):
    app = editor(ready_data())
    click(app, '신청서 내려받기')
    assert not app.exception and not app.error
    result = app.session_state['result']
    assert len(result['files']) == 5
    with zipfile.ZipFile(io.BytesIO(result['zip'])) as archive:
        assert len(archive.namelist()) == 5
        assert sum(name.endswith('.hwpx') for name in archive.namelist()) == 4
        assert sum(name.endswith('.xlsx') for name in archive.namelist()) == 1
    download_bridge.assert_called_once()
    assert download_bridge.call_args.args == (result['zip'], 'K-브랜드_필작성_5종.zip')
    no_network.assert_called_once()
    assert no_network.call_args.args[0] == app.session_state['data']


def test_last_edit_and_repeat_click_deliver_latest_document_only(download_bridge):
    app = editor(ready_data())
    app.text_input(key='edit_0_company_nameKo').set_value('마지막 입력 회사')
    click(app, '신청서 내려받기')
    assert not app.error
    first = app.session_state['result']
    assert all('마지막 입력 회사' in item['name'] for item in first['files'])
    token = download_bridge.call_args.kwargs['request_id']
    app.run()
    assert download_bridge.call_count == 1
    click(app, '신청서 내려받기')
    assert download_bridge.call_count == 2
    assert download_bridge.call_args.kwargs['request_id'] != token
    assert download_bridge.call_args.args[0] == first['zip']
    app.text_input(key='edit_0_company_nameKo').set_value('다시 수정한 회사')
    click(app, '신청서 내려받기')
    assert not app.exception and not app.error
    assert all('다시 수정한 회사' in item['name'] for item in app.session_state['result']['files'])
    assert app.session_state['result']['fingerprint'] != first['fingerprint']


def test_required_fields_stop_download_before_generation(monkeypatch, download_bridge):
    generator = Mock()
    monkeypatch.setattr('src.service.generate_documents', generator)
    app = editor()
    click(app, '신청서 내려받기')
    assert not app.exception and '필수항목' in app.error[0].value
    generator.assert_not_called()
    download_bridge.assert_not_called()


def test_cleared_date_stops_download(monkeypatch, download_bridge):
    generator = Mock()
    monkeypatch.setattr('src.service.generate_documents', generator)
    app = editor(ready_data())
    app.date_input(key='edit_0_application_date').set_value(None).run()
    click(app, '신청서 내려받기')
    assert not app.exception and '신청일' in app.error[0].value
    generator.assert_not_called()
    download_bridge.assert_not_called()


def test_generation_failure_keeps_form_and_can_retry(monkeypatch, download_bridge):
    from src.service import generate_documents
    generator = Mock(side_effect=[DocumentError('파일 생성 시험 오류'), generate_documents(ready_data(), temporary=True)])
    monkeypatch.setattr('src.service.generate_documents', generator)
    app = editor(ready_data())
    before = copy.deepcopy(app.session_state['data'])
    click(app, '신청서 내려받기')
    assert not app.exception and app.error and app.session_state['data'] == before
    download_bridge.assert_not_called()
    click(app, '신청서 내려받기')
    assert not app.exception and not app.error
    download_bridge.assert_called_once()


def test_search_only_runs_on_click_and_does_not_use_query_as_legal_name(monkeypatch, no_network):
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    data = ready_data()
    result = copy.deepcopy(data)
    result['company']['nameEn'] = 'VERIFIED COMPANY'
    research = Mock(return_value=ai_result(result, search_sources=['https://example.com']))
    monkeypatch.setattr('src.company_research.research_company', research)
    app = editor(data)
    app.text_input(key='company_query').set_value('검색용 브랜드').run()
    research.assert_not_called()
    assert app.session_state['data']['company']['nameKo'] == data['company']['nameKo']
    click(app, '신청 내용 자동으로 채우기')
    assert not app.exception and not app.error
    research.assert_called_once()
    assert research.call_args.args[0] == '검색용 브랜드'
    assert app.session_state['data']['company']['nameEn'] == 'VERIFIED COMPANY'
    assert app.text_input(key='edit_1_company_nameEn').value == 'VERIFIED COMPANY'
    assert not app.get('link_button')
    no_network.assert_not_called()


def test_prompt_is_passed_and_last_edit_survives(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    def apply(data, materials, request, *args, **kwargs):
        assert data['company']['nameKo'] == '최신 회사명'
        assert request == '마케팅 문장을 간결하게 바꿔 주세요.'
        assert kwargs['allow_edits'] is True
        result = copy.deepcopy(data)
        result['plan']['marketing'] = '제품 포장과 온라인몰에 K라벨을 표시할 계획입니다.'
        return ai_result(result)
    compose = Mock(side_effect=apply)
    monkeypatch.setattr('src.agent.compose_from_materials', compose)
    app = editor(ready_data())
    app.text_area(key='writing_request').set_value('마케팅 문장을 간결하게 바꿔 주세요.')
    app.text_input(key='edit_0_company_nameKo').set_value('최신 회사명')
    click(app, '요청 반영하기')
    assert not app.exception and not app.error
    assert compose.call_count == 1
    assert app.session_state['data']['company']['nameKo'] == '최신 회사명'
    assert '제품 포장' in app.session_state['data']['plan']['marketing']


def test_search_failure_preserves_all_form_data_and_allows_retry(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    research = Mock(side_effect=DocumentError('검색 시험 오류'))
    monkeypatch.setattr('src.company_research.research_company', research)
    app = editor(ready_data())
    before = copy.deepcopy(app.session_state['data'])
    app.text_input(key='company_query').set_value('검색 기업').run()
    click(app, '신청 내용 자동으로 채우기')
    assert not app.exception and '검색 시험 오류' in app.error[0].value
    assert app.session_state['data'] == before
    assert app.text_input(key='company_query').value == '검색 기업'
    research.side_effect = None
    research.return_value = ai_result(before)
    app.session_state['last_ai_at'] = -1000
    click(app, '신청 내용 자동으로 채우기')
    assert not app.exception and not app.error and research.call_count == 2


def test_ambiguous_company_notice_does_not_replace_current_document(monkeypatch):
    monkeypatch.setattr('src.ai.ai_ready', lambda: True)
    data = ready_data()
    research = Mock(return_value=ai_result(data, questions=['회사명과 제품명을 함께 입력해 주세요.']))
    monkeypatch.setattr('src.company_research.research_company', research)
    app = editor(data)
    app.text_input(key='company_query').set_value('동명회사').run()
    click(app, '신청 내용 자동으로 채우기')
    assert app.session_state['data'] == data
    assert '회사명과 제품명' in app.info[0].value
    assert not app.get('link_button')


def test_independent_sessions_start_empty():
    app = editor(ready_data())
    other = editor()
    assert app.session_state['data']['company']['nameKo']
    assert other.session_state['data']['company']['nameKo'] == ''


def test_repeated_download_deduplicates_database_write_and_edits_update_same_id(no_network, download_bridge):
    app = editor(ready_data())
    click(app, '신청서 내려받기')
    submission_id = no_network.call_args.args[1]
    click(app, '신청서 내려받기')
    app.run()
    assert no_network.call_count == 1
    app.text_input(key='edit_0_company_nameKo').set_value('같은 기업의 수정된 상호')
    click(app, '신청서 내려받기')
    assert no_network.call_count == 2
    assert no_network.call_args.args[1] == submission_id
    app.text_input(key='edit_0_company_registrationNumber').set_value('987-65-43210')
    click(app, '신청서 내려받기')
    assert no_network.call_count == 3
    assert no_network.call_args.args[1] != submission_id


def test_database_failure_still_downloads_and_retries_same_row(no_network, download_bridge):
    no_network.side_effect = [DocumentError('DB 시험 오류'), {'status': 'saved'}]
    app = editor(ready_data())
    before = copy.deepcopy(app.session_state['data'])
    click(app, '신청서 내려받기')
    assert not app.exception and app.warning
    assert app.session_state['data'] == before
    assert download_bridge.call_count == 1
    assert 'saved_fingerprint' not in app.session_state
    row_id = no_network.call_args.args[1]
    click(app, '신청서 내려받기')
    assert not app.exception and not app.warning
    assert download_bridge.call_count == 2 and no_network.call_count == 2
    assert no_network.call_args.args[1] == row_id
