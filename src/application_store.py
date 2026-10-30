"""Server-only Supabase persistence for completed, downloadable applications.

The browser never receives a database key. One caller-owned UUID identifies a
form session so retries and revisions update the same row atomically.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import uuid
from datetime import datetime
from urllib.parse import urlsplit

import httpx
import streamlit as st
from pydantic import ValidationError

from .config import supabase_settings
from .draft_schema import DocumentInput
from .errors import DocumentError
from .models import fingerprint
from .submission import validate_submission

TABLE = 'application_submissions'
MAX_PAYLOAD_BYTES = 512 * 1024
SAVE_FAILED = ('신청 정보 저장을 확인하지 못했습니다. 입력 내용은 유지됩니다. '
               '잠시 후 같은 화면에서 다시 내려받기를 눌러 주세요.')


def _settings() -> dict[str, str]:
    """Local environment first, then Streamlit root/nested server secrets."""
    config = dict(supabase_settings())
    config['SUPABASE_SECRET_KEY'] = config.get('SUPABASE_SECRET_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
    try:
        nested = st.secrets.get('supabase', {})
        for key, alias in [('SUPABASE_URL', 'url'), ('SUPABASE_SECRET_KEY', 'secret_key')]:
            if not config.get(key):
                config[key] = st.secrets.get(key, '') or nested.get(key, '') or nested.get(alias, '')
        if not config.get('SUPABASE_SECRET_KEY'):
            config['SUPABASE_SECRET_KEY'] = (st.secrets.get('SUPABASE_SERVICE_ROLE_KEY', '')
                                             or nested.get('service_role_key', ''))
    except (FileNotFoundError, KeyError, TypeError, AttributeError):
        pass
    return {key: value.strip() if isinstance(value, str) else '' for key, value in config.items()}


def _server_key(key: str) -> bool:
    """Reject accidental anon/publishable keys before sending customer data.

    Decoding a legacy JWT here is a configuration check, not authentication.
    Supabase verifies the actual signature and permissions on every request.
    """
    if not isinstance(key, str) or not key or any(word in key.upper() for word in ('REPLACE', 'YOUR_KEY', 'YOUR-KEY')):
        return False
    if key.startswith('sb_secret_'):
        return len(key) > len('sb_secret_')
    try:
        parts = key.split('.')
        if len(parts) != 3:
            return False
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        return isinstance(payload, dict) and payload.get('role') == 'service_role'
    except (ValueError, UnicodeError, TypeError):
        return False


def _valid_config(config: dict) -> bool:
    try:
        parsed = urlsplit(config.get('SUPABASE_URL', ''))
        return bool(parsed.scheme == 'https' and parsed.hostname
                    and not parsed.username and not parsed.password
                    and parsed.path in ('', '/') and not parsed.query and not parsed.fragment
                    and _server_key(config.get('SUPABASE_SECRET_KEY', '')))
    except (ValueError, TypeError):
        return False


def storage_ready() -> bool:
    """Check server configuration only; do not contact or initialize the DB."""
    return _valid_config(_settings())


def _joined(values) -> str:
    return ', '.join(dict.fromkeys(value for value in values if value))


def _payload(data: dict, submission_id: str, source_names) -> dict:
    try:
        submission_id = str(uuid.UUID(submission_id))
        current = DocumentInput.model_validate(copy.deepcopy(data)).model_dump()
        if not current['applicationDate']:
            raise DocumentError('신청일을 선택해 주세요.')
        validate_submission(current)
        if not isinstance(source_names, (list, tuple)) or len(source_names) > 50:
            raise ValueError
        if not all(isinstance(value, str) and len(value) <= 2000 for value in source_names):
            raise ValueError
        names = list(dict.fromkeys(source_names))
        company, contact, manager = current['company'], current['contact'], current['manager']
        products, plan = current['products'], current['plan']
        payload = {
            'id': submission_id,
            'input_fingerprint': fingerprint(current),
            'application_date': current['applicationDate'],
            'company_name': company['nameKo'],
            'company_name_en': company['nameEn'],
            'registration_number': company['registrationNumber'],
            'representative': company['representative'],
            'address': company['address'],
            'company_category': company['category'],
            'department': company['department'],
            'contact_name': contact['name'],
            'contact_phone': contact['phone'],
            'contact_email': contact['email'],
            'manager_name': manager['name'],
            'manager_phone': manager['phone'],
            'manager_email': manager['email'],
            'project_type': current['projectType'],
            'provider_name': current['provider']['name'],
            'product_count': len(products),
            'brands': _joined(p['brandKo'] or p['brandEn'] for p in products),
            'products': _joined(p['nameKo'] or p['nameEn'] for p in products),
            'export_countries': _joined(row['country'] for p in products for row in p['countries']),
            'certifications': _joined(p['certifications'] for p in products),
            'channels': _joined(plan['channels']),
            'counterfeit_risk': plan['counterfeitRisk'],
            'ip_defense': plan['ipDefense'],
            'plan_countries': plan['countries'],
            'channel_plan': plan['channelPlan'],
            'marketing_plan': plan['marketing'],
            'expected_effects': plan['expectedEffects'],
            'improvement_plan': plan['improvement'],
            'ip_history': plan['ipHistory'],
            'input_data': current,
            'source_names': names,
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if b'\\u0000' in encoded or len(encoded) > MAX_PAYLOAD_BYTES:
            raise ValueError
        return payload
    except DocumentError:
        raise
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        raise DocumentError('저장할 신청 정보의 형식이나 길이를 확인해 주세요. 내용을 잘라서 저장하지 않았습니다.') from None


def save_application(data: dict, submission_id: str, source_names=()) -> dict:
    """Atomically create/update one server-private row and verify its receipt."""
    config = _settings()
    if not _valid_config(config):
        raise DocumentError('신청 정보 저장 연결이 설정되지 않았습니다. 관리자에게 확인을 요청해 주세요.')
    payload = _payload(data, submission_id, source_names)
    secret = config['SUPABASE_SECRET_KEY']
    headers = {'apikey': secret, 'Prefer': 'resolution=merge-duplicates,return=representation',
               'Accept': 'application/json'}
    # New secret keys are not JWTs and belong only in the apikey header.
    if not secret.startswith('sb_secret_'):
        headers['Authorization'] = 'Bearer ' + secret
    try:
        with httpx.Client(timeout=20.0, follow_redirects=False, headers=headers) as client:
            response = client.post(config['SUPABASE_URL'].rstrip('/') + '/rest/v1/' + TABLE,
                params={'on_conflict': 'id', 'select': 'id,input_fingerprint,created_at,updated_at'}, json=payload)
            response.raise_for_status()
            rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError
        row = rows[0]
        if row['id'] != payload['id'] or row['input_fingerprint'] != payload['input_fingerprint']:
            raise ValueError
        for name in ('created_at', 'updated_at'):
            if not isinstance(row[name], str) or datetime.fromisoformat(row[name].replace('Z', '+00:00')).tzinfo is None:
                raise ValueError
        return {'id': row['id'], 'submission_id': row['id'], 'input_fingerprint': row['input_fingerprint'],
                'created_at': row['created_at'], 'updated_at': row['updated_at'], 'status': 'saved'}
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
        # Never show response bodies, URLs, request headers, or customer data.
        raise DocumentError(SAVE_FAILED) from None
