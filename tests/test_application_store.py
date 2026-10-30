"""Mocked PostgREST tests: no network, real accounts, or customer DB writes."""
import base64
import copy
import json
from pathlib import Path

import httpx
import pytest

from src import application_store as store
from src.errors import DocumentError
from src.models import apply_form_defaults, fingerprint, sample_data

SUBMISSION_ID = 'c62a11e5-c77e-4c24-9cdd-10cb123ab123'
SECRET = 'sb_secret_test_server_key_only'
CONFIG = {'SUPABASE_URL': 'https://test-project.supabase.co', 'SUPABASE_SECRET_KEY': SECRET}
read_settings = store._settings


def valid_data():
    data = apply_form_defaults(sample_data())
    data['company'].update(registrationNumber='001-01-00001', address='서울특별시 테스트로 1')
    data['contact']['phone'] = '010-0123-0001'
    return data


class FakeDB:
    def __init__(self):
        self.requests = []
        self.rows = {}
        self.timeout_after_commit = False
        self.response_override = None

    def respond(self, request):
        self.requests.append(request)
        assert request.method == 'POST'
        assert request.url.path == '/rest/v1/application_submissions'
        assert request.url.params['on_conflict'] == 'id'
        assert request.url.params['select'] == 'id,input_fingerprint,created_at,updated_at'
        assert request.headers['Prefer'] == 'resolution=merge-duplicates,return=representation'
        assert request.headers['apikey'] == SECRET
        if SECRET.startswith('sb_secret_'):
            assert 'Authorization' not in request.headers
        if self.response_override is not None:
            return self.response_override(request)
        payload = json.loads(request.content)
        self.rows[payload['id']] = payload
        if self.timeout_after_commit:
            self.timeout_after_commit = False
            raise httpx.ReadTimeout('private-secret private-customer-data', request=request)
        return httpx.Response(200, json=[{
            'id': payload['id'], 'input_fingerprint': payload['input_fingerprint'],
            'created_at': '2026-10-30T03:00:00+00:00', 'updated_at': '2026-10-30T03:10:00+00:00',
        }])


@pytest.fixture
def fake(monkeypatch):
    db = FakeDB()
    client = httpx.Client
    monkeypatch.setattr(store, '_settings', lambda: copy.deepcopy(CONFIG))
    monkeypatch.setattr(store.httpx, 'Client', lambda **kwargs: client(transport=httpx.MockTransport(db.respond), **kwargs))
    return db


def test_storage_ready_is_read_only_and_requires_server_key(fake, monkeypatch):
    assert store.storage_ready()
    assert not fake.requests
    monkeypatch.setattr(store, '_settings', lambda: {**CONFIG, 'SUPABASE_SECRET_KEY': 'sb_publishable_public_key'})
    assert not store.storage_ready()
    with pytest.raises(DocumentError, match='설정되지'):
        store.save_application(valid_data(), SUBMISSION_ID)
    assert not fake.requests


def test_secret_fallback_uses_streamlit_root_or_nested_settings(monkeypatch):
    monkeypatch.setattr(store, 'supabase_settings', lambda: {})
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    monkeypatch.setattr(store.st, 'secrets', dict(CONFIG))
    assert read_settings()['SUPABASE_SECRET_KEY'] == SECRET
    monkeypatch.setattr(store.st, 'secrets', {'supabase': {'url': CONFIG['SUPABASE_URL'], 'secret_key': SECRET}})
    assert read_settings()['SUPABASE_SECRET_KEY'] == SECRET
    assert read_settings()['SUPABASE_URL'] == CONFIG['SUPABASE_URL']
    monkeypatch.setattr(store.st, 'secrets', {})
    assert read_settings()['SUPABASE_SECRET_KEY'] == ''


def test_environment_settings_take_precedence_over_streamlit(monkeypatch):
    monkeypatch.setattr(store, 'supabase_settings', lambda: dict(CONFIG))
    monkeypatch.setattr(store.st, 'secrets', {'SUPABASE_SECRET_KEY': 'sb_secret_other'})
    assert read_settings()['SUPABASE_SECRET_KEY'] == SECRET


@pytest.mark.parametrize('url', ['http://test.supabase.co', 'https://user:pass@test.supabase.co',
    'https://test.supabase.co/rest/v1', 'https://test.supabase.co?key=x', 'https://test.supabase.co#x'])
def test_invalid_or_credential_bearing_urls_are_not_ready(fake, monkeypatch, url):
    monkeypatch.setattr(store, '_settings', lambda: {**CONFIG, 'SUPABASE_URL': url})
    assert not store.storage_ready()
    assert not fake.requests


def test_saved_row_retains_original_values_and_complete_product_data(fake):
    data = valid_data()
    data['company']['nameKo'] = '=HYPERLINK("https://example.com")'
    data['products'][0]['variants'] = [{'name': '오리지널', 'specification': '100g'}]
    before = copy.deepcopy(data)
    receipt = store.save_application(data, SUBMISSION_ID.replace('-', ''), ['제품자료.pdf', '제품자료.pdf'])
    row = fake.rows[SUBMISSION_ID]
    assert row['input_data'] == before and data == before
    assert row['company_name'] == data['company']['nameKo']  # CSV view escapes, raw data does not.
    assert row['registration_number'] == '001-01-00001'
    assert row['contact_phone'] == '010-0123-0001'
    assert row['brands'] == '가온' and row['products'] == '현미 과자(테스트)'
    assert row['export_countries'] == '일본'
    assert row['channels'] == '포장, 온라인몰'
    assert row['source_names'] == ['제품자료.pdf']
    assert row['input_fingerprint'] == fingerprint(before)
    assert receipt['submission_id'] == SUBMISSION_ID and receipt['status'] == 'saved'
    assert SECRET not in str(receipt) and 'input_data' not in receipt


def test_repeated_download_and_edit_upsert_same_row(fake):
    data = valid_data()
    store.save_application(data, SUBMISSION_ID)
    store.save_application(data, SUBMISSION_ID)
    assert len(fake.rows) == 1
    data['plan']['marketing'] = '수정한 해외 마케팅 계획'
    store.save_application(data, SUBMISSION_ID)
    assert len(fake.rows) == 1
    assert fake.rows[SUBMISSION_ID]['marketing_plan'] == data['plan']['marketing']
    assert fake.rows[SUBMISSION_ID]['input_fingerprint'] == fingerprint(data)


def test_timeout_after_committed_upsert_can_retry_without_duplicate(fake):
    fake.timeout_after_commit = True
    with pytest.raises(DocumentError) as error:
        store.save_application(valid_data(), SUBMISSION_ID)
    assert 'private-secret' not in str(error.value)
    assert 'private-customer-data' not in str(error.value)
    assert len(fake.rows) == 1
    store.save_application(valid_data(), SUBMISSION_ID)
    assert len(fake.rows) == 1


@pytest.mark.parametrize('changes', [
    lambda d: d['company'].update(nameKo=''),
    lambda d: d['contact'].update(phone='not a phone'),
    lambda d: d.update(applicationDate=''),
    lambda d: d.update(unexpected_field='must not silently disappear'),
    lambda d: d['company'].update(nameKo='bad\x00name'),
])
def test_invalid_or_incomplete_input_never_reaches_db(fake, changes):
    data = valid_data()
    changes(data)
    with pytest.raises(DocumentError):
        store.save_application(data, SUBMISSION_ID)
    assert not fake.requests


@pytest.mark.parametrize('submission_id,sources', [('not-a-uuid', ()), (SUBMISSION_ID, 'a string'),
    (SUBMISSION_ID, [None]), (SUBMISSION_ID, ['x' * 2001]), (SUBMISSION_ID, ['x'] * 51)])
def test_invalid_identity_or_source_metadata_rejected(fake, submission_id, sources):
    with pytest.raises(DocumentError):
        store.save_application(valid_data(), submission_id, sources)
    assert not fake.requests


@pytest.mark.parametrize('result', [[], {}, [{'id': SUBMISSION_ID, 'input_fingerprint': 'wrong'}]])
def test_unconfirmed_response_does_not_report_success(fake, result):
    fake.response_override = lambda request: httpx.Response(200, json=result)
    with pytest.raises(DocumentError, match='저장을 확인하지 못'):
        store.save_application(valid_data(), SUBMISSION_ID)


def test_response_error_never_exposes_secret_or_database_details(fake):
    fake.response_override = lambda request: httpx.Response(403, json={'message': SECRET + ' private-client-address'})
    with pytest.raises(DocumentError) as error:
        store.save_application(valid_data(), SUBMISSION_ID)
    assert SECRET not in str(error.value) and 'private-client-address' not in str(error.value)
    assert error.value.__suppress_context__


def test_legacy_key_must_be_service_role_and_uses_bearer(monkeypatch):
    def jwt(role):
        payload = base64.urlsafe_b64encode(json.dumps({'role': role}).encode()).decode().rstrip('=')
        return 'eyJhbGciOiJIUzI1NiJ9.' + payload + '.test-signature'
    assert not store._server_key(jwt('anon'))
    assert not store._server_key(jwt('authenticated'))
    key = jwt('service_role')
    assert store._server_key(key)
    monkeypatch.setattr(store, '_settings', lambda: {**CONFIG, 'SUPABASE_SECRET_KEY': key})
    requests = []
    def respond(request):
        requests.append(request)
        assert request.headers['apikey'] == key
        assert request.headers['Authorization'] == 'Bearer ' + key
        body = json.loads(request.content)
        return httpx.Response(200, json=[{'id': body['id'], 'input_fingerprint': body['input_fingerprint'],
            'created_at': '2026-10-30T00:00:00Z', 'updated_at': '2026-10-30T00:00:00Z'}])
    client = httpx.Client
    monkeypatch.setattr(store.httpx, 'Client', lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    store.save_application(valid_data(), SUBMISSION_ID)
    assert len(requests) == 1


def test_migration_keeps_public_access_closed_and_separates_csv_view():
    sql = (Path(__file__).resolve().parents[1] / 'supabase/005_application_submissions.sql').read_text(encoding='utf-8')
    assert 'alter table public.application_submissions enable row level security;' in sql
    assert 'revoke all on public.application_submissions from public, anon, authenticated;' in sql
    assert 'revoke all on public.application_submissions_csv from public, anon, authenticated;' in sql
    assert 'grant select, insert, update on public.application_submissions to service_role;' in sql
    assert 'with (security_invoker = true)' in sql
    assert 'create policy' not in sql.lower()
    assert 'create function kbrand_application_private.csv_cell' in sql
    assert "then chr(39) || value" in sql
    assert 'drop table' not in sql.lower() and 'delete from' not in sql.lower()
