"""Exercise the real Supabase SDK over mocked HTTP, never the live project."""
import copy
import json
import time

import httpx
import pytest

from src import auth

UID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
CONFIG = {
    'SUPABASE_URL': 'https://test.supabase.co',
    'SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_test',
    'SUPABASE_SECRET_KEY': 'sb_secret_test',
}


class AuthServer:
    def __init__(self):
        self.profile = dict(user_id=UID, username='sales01', display_name='시험 담당자', role='sales', active=True, must_change_password=False)
        self.user = dict(id=UID, email='test@example.com', app_metadata={}, user_metadata={}, aud='authenticated', created_at='2026-01-01T00:00:00Z', email_confirmed_at='2026-01-01T00:00:00Z')
        self.calls = []
        self.clients = []
        self.reject_password = False
        self.reject_refresh = False
        self.reject_user = False
        self.fail_lookup = False
        self.fail_password = False
        self.fail_flag = False
        self.network_down = False
        self.mismatch_user = False

    def session_json(self, token='access-private'):
        return dict(access_token=token, refresh_token='refresh-private', token_type='bearer', expires_in=3600, expires_at=int(time.time()) + 3600, user=self.user)

    def handle(self, request):
        self.calls.append(request)
        if self.network_down:
            raise httpx.ConnectError('secret diagnostic must never appear', request=request)
        path = request.url.path
        if path == '/rest/v1/profiles':
            if self.fail_lookup:
                return httpx.Response(404, json={'code': 'PGRST205', 'message': 'private diagnostic', 'hint': None, 'details': None})
            if request.method == 'PATCH':
                assert request.headers['apikey'] == CONFIG['SUPABASE_SECRET_KEY']
                assert request.url.params['user_id'] == f'eq.{UID}'
                assert request.url.params['active'] == 'eq.true'
                assert json.loads(request.content) == {'must_change_password': False}
                if self.fail_flag:
                    return httpx.Response(403, json={'code': '42501', 'message': 'private diagnostic', 'hint': None, 'details': None})
                self.profile['must_change_password'] = False
                return httpx.Response(200, json=[self.profile])
            if 'username' in request.url.params:
                assert request.headers['apikey'] == CONFIG['SUPABASE_SECRET_KEY']
                rows = [self.profile] if request.url.params['username'] == 'eq.sales01' else []
            else:
                assert request.headers['apikey'] == CONFIG['SUPABASE_PUBLISHABLE_KEY']
                assert request.headers['authorization'].startswith('Bearer access-')
                rows = [self.profile] if request.url.params['user_id'] == f'eq.{UID}' else []
            return httpx.Response(200, json=rows)
        if path == f'/auth/v1/admin/users/{UID}':
            assert request.headers['apikey'] == CONFIG['SUPABASE_SECRET_KEY']
            return httpx.Response(200, json=self.user)
        if path == '/auth/v1/token':
            assert request.headers['apikey'] == CONFIG['SUPABASE_PUBLISHABLE_KEY']
            grant = request.url.params['grant_type']
            if grant == 'password':
                assert json.loads(request.content)['email'] == 'test@example.com'
                if self.reject_password:
                    return httpx.Response(400, json={'code': 'invalid_credentials', 'msg': 'private diagnostic'})
                return httpx.Response(200, json=self.session_json())
            assert grant == 'refresh_token'
            if self.reject_refresh:
                return httpx.Response(400, json={'code': 'refresh_token_not_found', 'msg': 'private diagnostic'})
            return httpx.Response(200, json=self.session_json('access-refreshed'))
        if path == '/auth/v1/user':
            if self.reject_user:
                return httpx.Response(401, json={'code': 'bad_jwt', 'msg': 'private diagnostic'})
            if request.method == 'PUT':
                assert json.loads(request.content).keys() == {'password'}
                if self.fail_password:
                    return httpx.Response(422, json={'code': 'same_password', 'msg': 'private diagnostic'})
            return httpx.Response(200, json=dict(self.user, id=OTHER) if self.mismatch_user else self.user)
        if path == '/auth/v1/logout':
            assert request.url.params['scope'] == 'local'
            return httpx.Response(204)
        raise AssertionError(f'Unexpected auth request: {request.method} {path}')


@pytest.fixture
def server(monkeypatch):
    server = AuthServer()
    real_client = httpx.Client

    def client(**kwargs):
        client = real_client(transport=httpx.MockTransport(server.handle), **kwargs)
        server.clients.append(client)
        return client

    monkeypatch.setattr(auth, 'supabase_settings', lambda: CONFIG.copy())
    monkeypatch.setattr(auth.httpx, 'Client', client)
    monkeypatch.setattr(auth, '_limiter', auth.LoginLimiter())
    yield server
    for client in server.clients:
        client.close()


def test_username_login_refresh_and_local_logout(server):
    session = auth.sign_in(' SALES01 ', 'test-password-only')
    assert session.user_id == UID
    assert auth.current_profile(session)['username'] == 'sales01'
    assert 'private' not in repr(session)
    session.client.auth.get_session().expires_at = int(time.time()) - 1
    assert auth.current_profile(session)['user_id'] == UID
    assert any(r.url.params.get('grant_type') == 'refresh_token' for r in server.calls)
    auth.sign_out(session)
    assert session.transport.is_closed
    assert session.client.auth.get_session() is None


def test_wrong_password_and_unknown_username_have_same_error(server):
    server.reject_password = True
    for username in ('sales01', 'unknown'):
        with pytest.raises(auth.AuthError) as exc:
            auth.sign_in(username, 'test-password-only')
        assert str(exc.value) == auth.LOGIN_FAILED
    assert all(client.is_closed for client in server.clients)


def test_inactive_account_cannot_sign_in_or_keep_session(server):
    session = auth.sign_in('sales01', 'test-password-only')
    server.profile['active'] = False
    with pytest.raises(auth.AuthError):
        auth.current_profile(session)
    before = len(server.calls)
    with pytest.raises(auth.AuthError):
        auth.sign_in('sales01', 'test-password-only')
    assert not any(r.url.path.endswith('/token') for r in server.calls[before:])


def test_no_fallback_when_profile_table_missing(server):
    server.fail_lookup = True
    with pytest.raises(auth.AuthError, match='로그인 테이블'):
        auth.sign_in('sales01', 'test-password-only')


def test_verified_user_must_match_profile_and_connections_close(server):
    server.mismatch_user = True
    with pytest.raises(auth.AuthError):
        auth.sign_in('sales01', 'test-password-only')
    assert all(client.is_closed for client in server.clients)


def test_sessions_are_not_shared(server):
    first = auth.sign_in('sales01', 'test-password-only')
    second = auth.sign_in('sales01', 'test-password-only')
    assert first.client is not second.client
    assert first.transport is not second.transport
    auth.sign_out(first)
    assert second.client.auth.get_session() is not None


def test_expired_refresh_token_blocks_access(server):
    session = auth.sign_in('sales01', 'test-password-only')
    session.client.auth.get_session().expires_at = int(time.time()) - 1
    server.reject_refresh = True
    with pytest.raises(auth.AuthError, match='만료'):
        auth.current_profile(session)


def test_network_error_is_sanitized_and_logout_closes(server):
    session = auth.sign_in('sales01', 'test-password-only')
    server.network_down = True
    with pytest.raises(auth.AuthError) as exc:
        auth.current_profile(session)
    assert 'private' not in str(exc.value) and 'secret' not in str(exc.value)
    with pytest.raises(auth.AuthError):
        auth.sign_out(session)
    assert session.transport.is_closed


@pytest.mark.parametrize('password', ['Abcdef12!?', 'Abcdef123!?', 'Abcdef1234!?'])
def test_first_password_change_updates_only_verified_profile(server, password):
    server.profile['must_change_password'] = True
    session = auth.sign_in('sales01', 'initial-password')
    auth.change_initial_password(session, password, password)
    assert not auth.current_profile(session)['must_change_password']
    changes = [(r.method, r.url.path) for r in server.calls if r.method in ('PUT', 'PATCH')]
    assert changes == [('PUT', '/auth/v1/user'), ('PATCH', '/rest/v1/profiles')]


@pytest.mark.parametrize('password, confirmation', [('short', 'short'), ('Abcde12!?', 'Abcde12!?'), ('long-enough-test', 'different-value')])
def test_invalid_password_change_does_not_write(server, password, confirmation):
    server.profile['must_change_password'] = True
    session = auth.sign_in('sales01', 'initial-password')
    with pytest.raises(auth.AuthError):
        auth.change_initial_password(session, password, confirmation)
    assert not any(r.method in ('PUT', 'PATCH') for r in server.calls)


def test_failed_password_change_keeps_gate(server):
    server.profile['must_change_password'] = True
    server.fail_password = True
    session = auth.sign_in('sales01', 'initial-password')
    with pytest.raises(auth.AuthError):
        auth.change_initial_password(session, 'new-test-password', 'new-test-password')
    assert server.profile['must_change_password']
    assert not any(r.method == 'PATCH' for r in server.calls)


def test_failed_profile_update_reports_partial_password_change(server):
    server.profile['must_change_password'] = True
    server.fail_flag = True
    session = auth.sign_in('sales01', 'initial-password')
    with pytest.raises(auth.AuthError, match='비밀번호는 변경되었으나'):
        auth.change_initial_password(session, 'new-test-password', 'new-test-password')
    assert server.profile['must_change_password']


def test_rate_limit_applies_before_account_lookup(server):
    server.reject_password = True
    for _ in range(5):
        with pytest.raises(auth.AuthError, match='아이디 또는 비밀번호'):
            auth.sign_in('sales01', 'wrong-password')
    count = len(server.calls)
    with pytest.raises(auth.AuthError, match='1분 후'):
        auth.sign_in(' SALES01 ', 'wrong-password')
    assert len(server.calls) == count


def test_missing_config_and_swapped_key_fail_closed(monkeypatch):
    monkeypatch.setattr(auth, 'supabase_settings', lambda: dict.fromkeys(CONFIG, ''))
    assert 'SUPABASE_URL' in auth.configuration_error()
    monkeypatch.setattr(auth, 'supabase_settings', lambda: dict(CONFIG, SUPABASE_PUBLISHABLE_KEY='sb_secret_wrong'))
    assert 'Publishable' in auth.configuration_error()
