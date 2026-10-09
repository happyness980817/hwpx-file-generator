"""Password-encrypted drafts in private Storage. No Supabase Auth accounts."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from storage3.exceptions import StorageApiError
from supabase import create_client
from supabase.client import ClientOptions

from .config import supabase_settings
from .draft_schema import DocumentInput
from .errors import DocumentError

BUCKET = 'kbrand-guest-drafts'
MAX_BYTES = 256 * 1024
MAGIC = b'KBRAND01'
OPEN_FAILED = '작업번호와 확인 비밀번호를 확인해 주세요.'


@dataclass
class WorkAccess:
    number: str
    password: str = field(repr=False)


def storage_ready():
    config = supabase_settings()
    return bool(config['SUPABASE_URL'] and config['SUPABASE_SECRET_KEY'] and 'REPLACE' not in config['SUPABASE_SECRET_KEY'])


@contextmanager
def storage_client():
    config = supabase_settings()
    if not storage_ready():
        raise DocumentError('작업 보관 기능이 아직 연결되지 않았습니다. 현재 화면에서 작성·다운로드는 계속하실 수 있습니다.')
    with httpx.Client(timeout=20) as transport:
        yield create_client(config['SUPABASE_URL'], config['SUPABASE_SECRET_KEY'], options=ClientOptions(auto_refresh_token=False, persist_session=False, httpx_client=transport))


def normalize_access(number, password):
    number = number.strip().upper().replace('-', '')
    if not re.fullmatch(r'[A-F0-9]{24}', number) or not 10 <= len(password) <= 128:
        raise DocumentError(OPEN_FAILED)
    return WorkAccess(number, password)


def _key(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 260000, dklen=32)


def encode_payload(payload, access):
    DocumentInput.model_validate(payload['data'])
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    if len(raw) > MAX_BYTES - 100:
        raise DocumentError('보관할 작업 내용이 너무 큽니다. 대화 내용을 정리한 뒤 다시 저장해 주세요.')
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    encrypted = AESGCM(_key(access.password, salt)).encrypt(nonce, raw, access.number.encode('ascii'))
    return MAGIC + salt + nonce + encrypted


def decode_payload(blob, access):
    try:
        if not 52 <= len(blob) <= MAX_BYTES or blob[:8] != MAGIC:
            raise ValueError()
        raw = AESGCM(_key(access.password, blob[8:24])).decrypt(blob[24:36], blob[36:], access.number.encode('ascii'))
        payload = json.loads(raw)
        DocumentInput.model_validate(payload['data'])
        if not isinstance(payload.get('messages', []), list) or not isinstance(payload.get('source_notes', ''), str):
            raise ValueError()
        return payload
    except (InvalidTag, ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise DocumentError(OPEN_FAILED) from exc


def save_work(payload, access=None):
    """New credentials are returned only after a successful private upload."""
    new = access is None
    access = access or WorkAccess(secrets.token_hex(12).upper(), secrets.token_urlsafe(15))
    access = normalize_access(access.number, access.password)
    payload = dict(payload, saved_at=datetime.now(timezone.utc).isoformat())
    encrypted = encode_payload(payload, access)
    try:
        with storage_client() as client:
            bucket = client.storage.get_bucket(BUCKET)
            if bucket.public:
                raise DocumentError('작업 보관함의 공개 설정을 운영자가 확인해야 합니다. 저장을 중단했습니다.')
            store = client.storage.from_(BUCKET)
            path = f'{access.number}.bin'
            if not new:
                # Possession of a work number alone must never allow overwriting it.
                decode_payload(store.download(path), access)
            store.upload(path, encrypted, {'content-type': 'application/octet-stream', 'upsert': 'false' if new else 'true', 'cache-control': '0'})
        return access
    except (StorageApiError, httpx.HTTPError) as exc:
        raise DocumentError('작업을 보관하지 못했습니다. 현재 내용은 화면에 남아 있습니다. 잠시 후 다시 저장해 주세요.') from exc


def load_work(number, password):
    access = normalize_access(number, password)
    try:
        with storage_client() as client:
            blob = client.storage.from_(BUCKET).download(f'{access.number}.bin')
        return access, decode_payload(blob, access)
    except (StorageApiError, httpx.HTTPError) as exc:
        raise DocumentError(OPEN_FAILED) from exc
