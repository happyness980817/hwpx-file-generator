"""Username/password authentication. Credentials and tokens stay on the server.

Admin clients are short lived and used only for username lookup and the
first-password-change flag. A user's client is never shared between sessions.
"""
from collections import OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
import hashlib
import re
import time
from urllib.parse import urlparse

import httpx
from postgrest.exceptions import APIError
from supabase import Client, create_client
from supabase.client import ClientOptions
from supabase_auth.errors import AuthError as SupabaseAuthError

from .config import supabase_settings

MIN_PASSWORD_LENGTH = 10

LOGIN_FAILED = '아이디 또는 비밀번호를 확인해 주세요.'
CONNECTION_FAILED = '로그인 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'
PROFILE_COLUMNS = 'user_id,username,display_name,role,active,must_change_password'


class AuthError(Exception):
    """Safe, user-facing error; never display raw SDK errors."""


class LoginLimiter:
    """Bounded, process-local throttle shared across browser sessions."""

    def __init__(self):
        self.attempts = OrderedDict()
        self.lock = Lock()

    def check(self, username):
        now = time.monotonic()
        key = hashlib.sha256(username.encode()).hexdigest()
        with self.lock:
            attempts = self.attempts.setdefault(key, deque())
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= 5:
                raise AuthError('로그인 시도가 많습니다. 1분 후 다시 시도해 주세요.')
            attempts.append(now)
            self.attempts.move_to_end(key)
            while len(self.attempts) > 1024:
                self.attempts.popitem(last=False)


_limiter = LoginLimiter()


def checked_config():
    config = supabase_settings()
    if any(not value or 'REPLACE' in value or 'YOUR_PROJECT' in value for value in config.values()):
        raise AuthError('.env의 SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SECRET_KEY를 설정해 주세요.')
    url = urlparse(config['SUPABASE_URL'])
    local = url.hostname in ('localhost', '127.0.0.1')
    if not url.hostname or url.username or url.password or url.query or url.fragment or (url.scheme != 'https' and not (local and url.scheme == 'http')):
        raise AuthError('SUPABASE_URL에 올바른 프로젝트 주소를 설정해 주세요.')
    if config['SUPABASE_PUBLISHABLE_KEY'].startswith('sb_secret_'):
        raise AuthError('SUPABASE_PUBLISHABLE_KEY에는 Publishable key를 설정해 주세요.')
    return config


def configuration_error():
    try:
        checked_config()
        return None
    except AuthError as exc:
        return str(exc)


def _client(config, key, transport):
    return create_client(
        config['SUPABASE_URL'], config[key],
        options=ClientOptions(
            persist_session=False, auto_refresh_token=False,
            httpx_client=transport,
        ),
    )


@contextmanager
def _admin_client():
    config = checked_config()
    with httpx.Client(timeout=15) as transport:
        yield _client(config, 'SUPABASE_SECRET_KEY', transport)


def _profile(client, column, value):
    rows = client.table('profiles').select(PROFILE_COLUMNS).eq(column, value).limit(2).execute().data
    if len(rows) != 1:
        raise AuthError(LOGIN_FAILED)
    profile = rows[0]
    if (profile.get('active') is not True or profile.get('role') not in ('admin', 'sales')
            or not isinstance(profile.get('must_change_password'), bool)):
        raise AuthError(LOGIN_FAILED)
    return profile


def _database_error(exc):
    if exc.code in ('PGRST205', '42P01', '42703', 'PGRST204'):
        return AuthError('로그인 테이블이 준비되지 않았습니다. 관리자가 LOGIN_SETUP.md의 SQL 설정을 완료해야 합니다.')
    return AuthError('로그인 정보를 확인하지 못했습니다. 관리자에게 Supabase 설정 확인을 요청해 주세요.')


@dataclass
class LoginSession:
    user_id: str
    client: Client = field(repr=False)
    transport: httpx.Client = field(repr=False)

    def close(self):
        self.transport.close()


def sign_in(username: str, password: str) -> LoginSession:
    username = username.strip().lower()
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,31}', username) or not password:
        raise AuthError(LOGIN_FAILED)
    _limiter.check(username)
    config = checked_config()
    transport = None
    verified = False
    try:
        with _admin_client() as admin:
            profile = _profile(admin, 'username', username)
            user = admin.auth.admin.get_user_by_id(profile['user_id']).user
            if not user or user.id != profile['user_id'] or not user.email or not user.email_confirmed_at:
                raise AuthError(LOGIN_FAILED)
            email = user.email
        transport = httpx.Client(timeout=15)
        client = _client(config, 'SUPABASE_PUBLISHABLE_KEY', transport)
        response = client.auth.sign_in_with_password({'email': email, 'password': password})
        if not response.session or not response.user or response.user.id != profile['user_id']:
            raise AuthError(LOGIN_FAILED)
        login = LoginSession(response.user.id, client, transport)
        # Recheck with the authenticated user's own JWT, never the admin client.
        current_profile(login)
        verified = True
        return login
    except APIError as exc:
        raise _database_error(exc) from None
    except SupabaseAuthError as exc:
        if getattr(exc, 'status', None) == 429:
            raise AuthError('로그인 시도가 많습니다. 잠시 후 다시 시도해 주세요.') from None
        raise AuthError(LOGIN_FAILED) from None
    except httpx.HTTPError:
        raise AuthError(CONNECTION_FAILED) from None
    finally:
        # Keep the connection only when returning a fully verified session.
        if transport is not None and not verified:
            transport.close()


def current_profile(login: LoginSession):
    try:
        # SDK get_session refreshes near-expired tokens synchronously. No timer,
        # disk persistence or cross-user cache is used.
        session = login.client.auth.get_session()
        if not session:
            raise AuthError('로그인이 만료되었습니다. 다시 로그인해 주세요.')
        result = login.client.auth.get_user(session.access_token)
        if not result or not result.user or result.user.id != login.user_id or result.user.is_anonymous:
            raise AuthError('로그인을 확인하지 못했습니다. 다시 로그인해 주세요.')
        return _profile(login.client, 'user_id', result.user.id)
    except APIError as exc:
        raise _database_error(exc) from None
    except SupabaseAuthError:
        raise AuthError('로그인이 만료되었거나 계정 접근이 해제되었습니다. 다시 로그인해 주세요.') from None
    except httpx.HTTPError:
        raise AuthError(CONNECTION_FAILED) from None


def change_initial_password(login: LoginSession, password: str, confirmation: str):
    if password != confirmation:
        raise AuthError('새 비밀번호와 확인 입력이 일치하지 않습니다.')
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f'새 비밀번호는 {MIN_PASSWORD_LENGTH}자 이상으로 입력해 주세요.')
    profile = current_profile(login)
    if not profile['must_change_password']:
        raise AuthError('최초 비밀번호 변경이 이미 완료되었습니다.')
    try:
        result = login.client.auth.update_user({'password': password})
        if not result.user or result.user.id != login.user_id:
            raise AuthError('비밀번호 변경 결과를 확인하지 못했습니다.')
        # Never accept a browser-supplied UUID or change any role/active field.
        with _admin_client() as admin:
            rows = admin.table('profiles').update({'must_change_password': False}).eq('user_id', login.user_id).eq('active', 'true').execute().data
            if len(rows) != 1 or rows[0].get('must_change_password') is not False:
                raise AuthError('비밀번호는 변경되었으나 계정 상태를 갱신하지 못했습니다. 관리자에게 문의해 주세요.')
    except APIError:
        raise AuthError('비밀번호는 변경되었으나 계정 상태를 저장하지 못했습니다. 변경한 비밀번호로 재로그인한 뒤 다시 변경하거나 관리자에게 문의해 주세요.') from None
    except SupabaseAuthError:
        raise AuthError('비밀번호를 변경하지 못했습니다. 기존과 다른 비밀번호를 입력하고 계정의 비밀번호 정책을 확인해 주세요.') from None
    except httpx.HTTPError:
        raise AuthError('변경 결과를 확인하지 못했습니다. 다시 로그인하여 계정 상태를 확인해 주세요.') from None


def sign_out(login: LoginSession):
    try:
        login.client.auth.sign_out({'scope': 'local'})
    except (SupabaseAuthError, httpx.HTTPError):
        raise AuthError('이 화면에서는 로그아웃했습니다. 서버 연결 문제로 세션 종료 확인은 완료하지 못했습니다.') from None
    finally:
        login.close()
