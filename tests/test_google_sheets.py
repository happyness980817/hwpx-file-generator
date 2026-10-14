import copy
import json
from urllib.parse import unquote

import httpx
import pytest

from src import google_sheets as sheets
from src.errors import DocumentError
from src.models import sample_data

SUBMISSION_ID = 'c62a11e5-c77e-4c24-9cdd-10cb123ab123'
CONFIG = {'client_id': 'test-client', 'client_secret': 'private-client-secret',
          'refresh_token': 'private-refresh-token', 'spreadsheet_id': 'test-sheet', 'sheet_name': '참여기업'}


class FakeSheets:
    def __init__(self, exists=True):
        self.exists = exists
        self.rows = {}
        self.headers = list(sheets.HEADERS)
        self.calls = []
        self.row_count = 1_000
        self.append_count = 0
        self.update_count = 0
        self.timeout_after_append = False
        self.token_failure = False

    def respond(self, request):
        self.calls.append(request)
        body = json.loads(request.content) if request.content.startswith(b'{') else {}
        path = unquote(request.url.path)
        if str(request.url) == sheets.TOKEN_URL:
            assert b'private-refresh-token' in request.content
            assert 'Authorization' not in request.headers
            if self.token_failure:
                return httpx.Response(400, json={'error': 'private-client-secret private-refresh-token'})
            return httpx.Response(200, json={'access_token': 'private-access-token'})
        assert request.headers['Authorization'] == 'Bearer private-access-token'
        if request.method == 'GET' and path.endswith('/test-sheet'):
            props = [{'properties': {'sheetId': 0, 'title': '시트1', 'gridProperties': {'rowCount': 1_000, 'columnCount': 26}}}]
            if self.exists:
                props.append({'properties': {'sheetId': 42, 'title': '참여기업',
                              'gridProperties': {'rowCount': self.row_count, 'columnCount': len(sheets.HEADERS)}}})
            return httpx.Response(200, json={'sheets': props})
        if path.endswith(':batchUpdate'):
            assert not self.exists
            add, header = body['requests']
            properties = add['addSheet']['properties']
            assert properties['title'] == '참여기업'
            assert properties['gridProperties']['frozenRowCount'] == 1
            assert header['updateCells']['start']['sheetId'] == properties['sheetId']
            assert [value['userEnteredValue']['stringValue'] for value in header['updateCells']['rows'][0]['values']] == sheets.HEADERS
            self.exists = True
            return httpx.Response(200, json={})
        assert "'시트1'!" not in path
        a1 = path.split('/values/', 1)[1]
        if request.method == 'GET':
            if a1.endswith('1:AI1'):
                return httpx.Response(200, json={'values': [self.headers]})
            start, end = map(lambda value: int(value.removeprefix('A')), a1.split('!')[1].split(':'))
            assert end - start < sheets.ID_CHUNK
            return httpx.Response(200, json={'values': [[self.rows[row][0]] if row in self.rows else [] for row in range(start, end + 1)]})
        assert request.url.params['valueInputOption'] == 'RAW'
        if request.method == 'POST' and path.endswith(':append'):
            self.append_count += 1
            number = max(self.rows, default=1) + 1
            self.rows[number] = body['values'][0]
            if self.timeout_after_append:
                self.timeout_after_append = False
                raise httpx.ReadTimeout('private-access-token private-response', request=request)
            return httpx.Response(200, json={'updates': {'updatedRange': f"'참여기업'!A{number}:AI{number}", 'updatedRows': 1}})
        if request.method == 'PUT':
            self.update_count += 1
            number = int(a1.split('!A')[1].split(':')[0])
            assert number in self.rows
            self.rows[number] = body['values'][0]
            return httpx.Response(200, json={'updatedRange': a1, 'updatedRows': 1})
        raise AssertionError((request.method, path))


@pytest.fixture
def fake(monkeypatch):
    api = FakeSheets()
    real_client = httpx.Client
    monkeypatch.setattr(sheets, '_settings', lambda: copy.deepcopy(CONFIG))
    monkeypatch.setattr(sheets.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(api.respond), **kwargs))
    return api


def test_ready_is_read_only_and_missing_config_stops_before_network(fake, monkeypatch):
    assert sheets.sheets_ready()
    assert not fake.calls
    monkeypatch.setattr(sheets, '_settings', lambda: {})
    assert not sheets.sheets_ready()
    with pytest.raises(DocumentError, match='설정되지'):
        sheets.submit_application(sample_data(), SUBMISSION_ID)
    assert not fake.calls


def test_default_title_and_empty_secrets_are_handled_without_network(monkeypatch):
    monkeypatch.setattr(sheets.st, 'secrets', {'google_sheets': {key: value for key, value in CONFIG.items() if key != 'sheet_name'}})
    assert sheets._settings()['sheet_name'] == '참여기업'
    monkeypatch.setattr(sheets.st, 'secrets', {})
    assert not sheets.sheets_ready()


def test_new_submission_is_raw_and_retains_all_input(fake):
    data = sample_data()
    data['company'].update(nameKo='=HYPERLINK("https://example.com")', registrationNumber='001-01-00001')
    data['contact']['phone'] = '010-0123-0001'
    data['extra_input'] = {'preserved': '전체 내용'}
    result = sheets.submit_application(data, SUBMISSION_ID.replace('-', ''), source_names=['회사 소개.pdf'])
    assert result['submission_id'] == SUBMISSION_ID and result['row_number'] == 2 and not result['updated']
    assert '#gid=42' in result['spreadsheet_url']
    row = dict(zip(sheets.HEADERS, fake.rows[2]))
    assert row['회사명'].startswith('=HYPERLINK')
    assert row['사업자등록번호'] == '001-01-00001' and row['연락처'] == '010-0123-0001'
    assert json.loads(row['전체 입력(JSON)']) == data
    assert json.loads(row['상품 상세(JSON)']) == data['products']
    assert json.loads(row['첨부 자료명(JSON)']) == ['회사 소개.pdf']
    assert row['제출일시(KST)'].endswith('+09:00')


def test_same_id_edit_updates_row_and_search_is_chunked(fake):
    fake.row_count = 2_500
    fake.rows[2_101] = [SUBMISSION_ID]
    data = sample_data()
    data['company']['nameKo'] = '수정 회사'
    result = sheets.submit_application(data, SUBMISSION_ID)
    assert result['updated'] and result['row_number'] == 2_101
    assert fake.update_count == 1 and fake.append_count == 0
    assert fake.rows[2_101][sheets.HEADERS.index('회사명')] == '수정 회사'
    id_requests = [request for request in fake.calls if request.method == 'GET' and '/values/' in request.url.path]
    assert any('A2002:A2500' in unquote(str(request.url)) for request in id_requests)


def test_timeout_after_committed_append_retry_finds_existing_id(fake):
    fake.timeout_after_append = True
    with pytest.raises(DocumentError) as error:
        sheets.submit_application(sample_data(), SUBMISSION_ID)
    assert 'private' not in str(error.value)
    assert len(fake.rows) == 1
    result = sheets.submit_application(sample_data(), SUBMISSION_ID)
    assert result['updated'] and fake.append_count == 1 and fake.update_count == 1
    assert len(fake.rows) == 1


def test_duplicate_ids_stop_before_any_write(fake):
    fake.rows[2] = [SUBMISSION_ID]
    fake.rows[900] = [SUBMISSION_ID]
    with pytest.raises(DocumentError, match='여러 번'):
        sheets.submit_application(sample_data(), SUBMISSION_ID)
    assert fake.update_count == fake.append_count == 0


def test_only_missing_participant_tab_is_created_with_frozen_header(fake):
    fake.exists = False
    sheets.submit_application(sample_data(), SUBMISSION_ID)
    assert fake.exists and len(fake.rows) == 1
    sheets.submit_application(sample_data(), SUBMISSION_ID)
    creates = [request for request in fake.calls if request.url.path.endswith(':batchUpdate')]
    assert len(creates) == 1
    assert not any("'시트1'!" in unquote(str(request.url)) for request in fake.calls)


def test_changed_header_stops_without_overwriting_existing_sheet(fake):
    fake.headers[0] = '기존 다른 자료'
    with pytest.raises(DocumentError, match='열 제목'):
        sheets.submit_application(sample_data(), SUBMISSION_ID)
    assert fake.append_count == fake.update_count == 0


def test_token_failure_is_sanitized_and_no_sheet_request_runs(fake):
    fake.token_failure = True
    with pytest.raises(DocumentError, match='인증') as error:
        sheets.submit_application(sample_data(), SUBMISSION_ID)
    assert 'private' not in str(error.value)
    assert len(fake.calls) == 1


@pytest.mark.parametrize('value', ['x' * 50_001, '😀' * 25_001], ids=['ascii_limit', 'utf16_limit'])
def test_oversized_cells_fail_before_network_without_truncation(fake, value):
    data = sample_data()
    data['plan']['marketing'] = value
    with pytest.raises(DocumentError, match='잘라서 저장하지'):
        sheets.submit_application(data, SUBMISSION_ID)
    assert data['plan']['marketing'] == value and not fake.calls


def test_invalid_submission_id_and_non_json_input_stop_before_network(fake):
    with pytest.raises(DocumentError, match='제출번호'):
        sheets.submit_application(sample_data(), 'not-an-id')
    data = sample_data()
    data['extra'] = float('nan')
    with pytest.raises(DocumentError, match='형식'):
        sheets.submit_application(data, SUBMISSION_ID)
    assert not fake.calls
