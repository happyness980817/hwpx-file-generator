"""Password-only document access, with atomic creation and encrypted storage."""
from collections import deque
from datetime import datetime, timezone
import hashlib
import threading
import time

import httpx
from storage3.exceptions import StorageApiError

from .errors import DocumentError
from .guest_work import BUCKET, WorkAccess, encode_payload, decode_payload, storage_client

OPEN_FAILED = '비밀번호를 확인해 주세요.'
_attempts = {}
_attempt_lock = threading.Lock()


def validate_password(password):
    if (not 10 <= len(password) <= 128 or len(password.strip()) < 10
            or not any(char.isalpha() for char in password)
            or not any(char.isdigit() for char in password)
            or password.casefold() in {'password123', 'password1234', 'qwerty12345', 'abc1234567'}):
        raise DocumentError('비밀번호는 문자와 숫자를 섞어 10자 이상 입력해 주세요.')


def password_access(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise DocumentError(OPEN_FAILED)
    # No service-key dependency: rotating Supabase keys does not lose documents.
    locator = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                 b'KBRAND-DOCUMENT-LOOKUP-V2', 260000, dklen=12)
    return WorkAccess(locator.hex().upper(), password)


def document_path(access):
    if password_access(access.password).number != access.number:
        raise DocumentError(OPEN_FAILED)
    return f'documents/{access.number}.bin'


def _write(payload, access, *, create):
    path = document_path(access)
    encoded = encode_payload(dict(payload, saved_at=datetime.now(timezone.utc).isoformat()), access)
    try:
        with storage_client() as client:
            if client.storage.get_bucket(BUCKET).public:
                raise DocumentError('문서 보관함 설정을 확인해 주세요.')
            store = client.storage.from_(BUCKET)
            if not create:
                decode_payload(store.download(path), access)
            # Never overwrite another document when the same password is chosen.
            store.upload(path, encoded, {'content-type': 'application/octet-stream',
                         'upsert': 'false' if create else 'true', 'cache-control': '0'})
    except StorageApiError as exc:
        if create and (str(exc.status) in ('409', '400') and exc.code.lower() in ('duplicate', 'resourcealreadyexists', 'keyalreadyexists')):
            raise DocumentError('이 비밀번호는 사용할 수 없습니다. 다른 비밀번호를 입력해 주세요.') from exc
        raise DocumentError('문서를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.') from exc
    except httpx.HTTPError as exc:
        raise DocumentError('문서를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.') from exc
    return access


def create_document(password, payload):
    validate_password(password)
    return _write(payload, password_access(password), create=True)


def save_document(payload, access):
    return _write(payload, access, create=False)


def _start_attempt(client_id):
    # Per-process guard for anonymous password entry. No passwords are retained.
    key = hashlib.sha256(str(client_id).encode()).hexdigest()
    now = time.monotonic()
    with _attempt_lock:
        for old_key in list(_attempts):
            if not _attempts[old_key] or now - _attempts[old_key][-1] >= 60:
                del _attempts[old_key]
        if len(_attempts) >= 4096 and key not in _attempts:
            raise DocumentError('잠시 후 다시 시도해 주세요.')
        recent = _attempts.setdefault(key, deque())
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= 8 or sum(len(items) for items in _attempts.values()) >= 120:
            raise DocumentError('입력 횟수를 초과했습니다. 1분 후 다시 시도해 주세요.')
        recent.append(now)
    return key


def load_document(password, client_id='unknown'):
    attempt_key = _start_attempt(client_id)
    access = password_access(password)
    try:
        with storage_client() as client:
            if client.storage.get_bucket(BUCKET).public:
                raise DocumentError('문서 보관함 설정을 확인해 주세요.')
            blob = client.storage.from_(BUCKET).download(document_path(access))
        try:
            payload = decode_payload(blob, access)
        except DocumentError as exc:
            raise DocumentError(OPEN_FAILED) from exc
    except StorageApiError as exc:
        if str(exc.status) in ('400', '404'):
            raise DocumentError(OPEN_FAILED) from exc
        raise DocumentError('문서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.') from exc
    except httpx.HTTPError as exc:
        raise DocumentError('문서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.') from exc
    with _attempt_lock:
        _attempts.pop(attempt_key, None)
    return access, payload
