"""Explicit participant submissions to one configured Google Sheets tab.

Only submit_application writes. UUID reconciliation and a process lock protect
same-instance retries; Sheets does not provide a cross-instance unique key.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import streamlit as st

from .errors import DocumentError

TOKEN_URL = 'https://oauth2.googleapis.com/token'
API_ROOT = 'https://sheets.googleapis.com/v4/spreadsheets'
DEFAULT_SHEET = '참여기업'
KST = timezone(timedelta(hours=9))
MAX_CELL_UNITS = 50_000
ID_CHUNK = 1_000
MAX_ROWS = 1_000_000
_lock = threading.Lock()

HEADERS = [
    '제출ID', '제출일시(KST)', '신청일', '회사명', '영문회사명', '사업자등록번호',
    '대표자', '주소', '기업구분', '담당부서', '담당자', '연락처', '이메일',
    '부서장', '부서장 연락처', '부서장 이메일', '사업과제', '수행업체',
    '상품 수', '브랜드명', '대상제품', '수출국가', '보유 인증', '활용채널',
    '위조 피해·우려', '해외 지식재산권·방어역량', '활용국가',
    '활용채널 상세 계획', '수출 마케팅 전략', '기대효과', '개선계획', '분쟁 이력',
    '상품 상세(JSON)', '전체 입력(JSON)', '첨부 자료명(JSON)',
]


def _settings() -> dict[str, str]:
    try:
        raw = st.secrets.get('google_sheets', {})
        config = {key: str(raw.get(key, '')).strip() for key in
                  ('client_id', 'client_secret', 'refresh_token', 'spreadsheet_id', 'sheet_name')}
    except (FileNotFoundError, KeyError, TypeError, AttributeError):
        return {}
    config['sheet_name'] = config['sheet_name'] or DEFAULT_SHEET
    return config


def _valid_config(config: dict) -> bool:
    return all(config.get(key) for key in ('client_id', 'client_secret', 'refresh_token', 'spreadsheet_id'))


def sheets_ready() -> bool:
    """Configuration presence only; no network requests or writes."""
    return bool(_valid_config(_settings()))


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return _json(value)
    return str(value)


def _joined(values) -> str:
    return ', '.join(dict.fromkeys(_text(value) for value in values if value))


def _row(data: dict, submission_id: str, source_names: list[str] | None) -> list[str]:
    try:
        company, contact = data.get('company', {}), data.get('contact', {})
        manager, provider = data.get('manager', {}), data.get('provider', {})
        products, plan = data.get('products', []), data.get('plan', {})
        if not isinstance(products, list) or not all(isinstance(p, dict) for p in products):
            raise ValueError
        if source_names is not None and (not isinstance(source_names, list) or
                                        not all(isinstance(name, str) for name in source_names)):
            raise ValueError
        cells = [submission_id, datetime.now(KST).isoformat(timespec='seconds'), data.get('applicationDate', '')]
        cells += [company.get(key, '') for key in ('nameKo', 'nameEn', 'registrationNumber',
                  'representative', 'address', 'category', 'department')]
        cells += [group.get(key, '') for group in (contact, manager) for key in ('name', 'phone', 'email')]
        cells += [data.get('projectType', ''), provider.get('name', ''), str(len(products)),
                  _joined(p.get('brandKo') or p.get('brandEn') for p in products),
                  _joined(p.get('nameKo') or p.get('nameEn') for p in products),
                  _joined(r.get('country') for p in products for r in p.get('countries', [])),
                  _joined(p.get('certifications') for p in products), _joined(plan.get('channels', []))]
        cells += [plan.get(key, '') for key in ('counterfeitRisk', 'ipDefense', 'countries',
                  'channelPlan', 'marketing', 'expectedEffects', 'improvement', 'ipHistory')]
        cells += [_json(products), _json(data), _json(source_names or [])]
        result = [_text(cell) for cell in cells]
        if len(result) != len(HEADERS):
            raise ValueError
        if any(len(cell.encode('utf-16-le')) // 2 > MAX_CELL_UNITS for cell in result):
            raise DocumentError('입력 내용이 시트의 한 칸에 저장할 수 있는 길이를 넘었습니다. 내용을 줄인 뒤 제출해 주세요. 내용은 잘라서 저장하지 않았습니다.')
        return result
    except DocumentError:
        raise
    except (AttributeError, TypeError, ValueError, UnicodeError, RecursionError):
        raise DocumentError('제출할 입력 형식을 확인해 주세요. 시트에 저장하지 않았습니다.') from None


def _column(number: int) -> str:
    result = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _range(title: str, cells: str) -> str:
    return "'" + title.replace("'", "''") + "'!" + cells


def _request(client, method: str, url: str, **kwargs) -> dict:
    try:
        response = client.request(method, url, **kwargs)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (httpx.HTTPError, ValueError):
        raise DocumentError('시트 저장 결과를 확인하지 못했습니다. 입력은 유지됩니다. 잠시 후 같은 화면에서 다시 제출해 주세요.') from None


def _access_token(client, config: dict) -> str:
    try:
        response = client.post(TOKEN_URL, data={
            'client_id': config['client_id'], 'client_secret': config['client_secret'],
            'refresh_token': config['refresh_token'], 'grant_type': 'refresh_token',
        })
        response.raise_for_status()
        token = response.json().get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError
        return token
    except (httpx.HTTPError, ValueError, AttributeError):
        raise DocumentError('Google 시트 인증을 확인하지 못했습니다. 관리자에게 연결 상태 확인을 요청해 주세요.') from None


def _get_values(client, base: str, title: str, cells: str) -> list:
    result = _request(client, 'GET', base + '/values/' + quote(_range(title, cells), safe=''),
                      params={'valueRenderOption': 'UNFORMATTED_VALUE'})
    values = result.get('values', [])
    if not isinstance(values, list) or not all(isinstance(row, list) for row in values):
        raise DocumentError('참여기업 시트의 데이터 형식을 확인해 주세요.')
    return values


def _get_sheet(client, base: str, title: str) -> dict:
    result = _request(client, 'GET', base,
                      params={'fields': 'sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))'})
    try:
        sheets = [item['properties'] for item in result.get('sheets', [])]
        matches = [item for item in sheets if item['title'] == title]
        if len(matches) > 1:
            raise ValueError
        if matches:
            sheet = matches[0]
        else:
            used_ids = {item['sheetId'] for item in sheets}
            sheet_id = secrets.randbelow(2**31 - 1)
            while sheet_id in used_ids:
                sheet_id = secrets.randbelow(2**31 - 1)
            sheet = {'sheetId': sheet_id, 'title': title,
                     'gridProperties': {'rowCount': 1_000, 'columnCount': len(HEADERS), 'frozenRowCount': 1}}
            # Atomic creation and fixed string headers: an ambiguous response is
            # reconciled by the next submission's metadata/header read.
            _request(client, 'POST', base + ':batchUpdate', json={'requests': [
                {'addSheet': {'properties': sheet}},
                {'updateCells': {'start': {'sheetId': sheet_id, 'rowIndex': 0, 'columnIndex': 0},
                 'rows': [{'values': [{'userEnteredValue': {'stringValue': value},
                           'userEnteredFormat': {'textFormat': {'bold': True}}} for value in HEADERS]}],
                 'fields': 'userEnteredValue,userEnteredFormat.textFormat.bold'}},
            ]})
        rows = sheet['gridProperties']['rowCount']
        if not isinstance(rows, int) or not 1 <= rows <= MAX_ROWS:
            raise ValueError
        if sheet['gridProperties']['columnCount'] < len(HEADERS):
            raise ValueError
        if _get_values(client, base, title, f'A1:{_column(len(HEADERS))}1') != [HEADERS]:
            raise DocumentError('참여기업 시트의 열 제목이 예상 형식과 다릅니다. 기존 내용을 보호하기 위해 저장하지 않았습니다.')
        return sheet
    except (KeyError, TypeError, ValueError):
        raise DocumentError('참여기업 시트의 구성 또는 크기를 확인해 주세요. 기존 내용을 변경하지 않았습니다.') from None


def _find_row(client, base: str, title: str, row_count: int, submission_id: str) -> int | None:
    found = []
    for start in range(2, row_count + 1, ID_CHUNK):
        end = min(start + ID_CHUNK - 1, row_count)
        for offset, row in enumerate(_get_values(client, base, title, f'A{start}:A{end}')):
            if row and row[0] == submission_id:
                found.append(start + offset)
                if len(found) > 1:
                    raise DocumentError('같은 제출번호가 시트에 여러 번 기록되어 있습니다. 관리자에게 확인을 요청해 주세요.')
    return found[0] if found else None


def submit_application(data: dict, submission_id: str, *, source_names: list[str] | None = None) -> dict:
    """Create/update one row only after the user explicitly submits the form."""
    config = _settings()
    if not _valid_config(config):
        raise DocumentError('Google 시트 저장 연결이 설정되지 않았습니다. 관리자에게 확인을 요청해 주세요.')
    try:
        submission_id = str(uuid.UUID(submission_id))
    except (ValueError, TypeError, AttributeError):
        raise DocumentError('제출번호가 올바르지 않습니다. 새 신청서에서 다시 시도해 주세요.') from None
    row = _row(data, submission_id, source_names)
    title = config.get('sheet_name') or DEFAULT_SHEET
    base = API_ROOT + '/' + quote(config['spreadsheet_id'], safe='')
    with _lock, httpx.Client(timeout=30.0, follow_redirects=False) as client:
        token = _access_token(client, config)
        client.headers['Authorization'] = 'Bearer ' + token
        sheet = _get_sheet(client, base, title)
        number = _find_row(client, base, title, sheet['gridProperties']['rowCount'], submission_id)
        updated = number is not None
        if updated:
            target = _range(title, f'A{number}:{_column(len(HEADERS))}{number}')
            result = _request(client, 'PUT', base + '/values/' + quote(target, safe=''),
                              params={'valueInputOption': 'RAW'}, json={'values': [row]})
            saved_range = result.get('updatedRange', target)
        else:
            target = _range(title, f'A1:{_column(len(HEADERS))}{sheet["gridProperties"]["rowCount"]}')
            result = _request(client, 'POST', base + '/values/' + quote(target, safe='') + ':append',
                              params={'valueInputOption': 'RAW', 'insertDataOption': 'INSERT_ROWS'},
                              json={'values': [row]})
            saved_range = result.get('updates', {}).get('updatedRange', '')
        confirmation = result if updated else result.get('updates', {})
        if confirmation.get('updatedRows') != 1 or not isinstance(saved_range, str):
            raise DocumentError('시트 저장 결과를 확인하지 못했습니다. 같은 화면에서 다시 제출하면 기존 제출번호를 먼저 확인합니다.')
        match = re.search(r'!\$?A\$?(\d+):', saved_range)
        if not updated and match:
            number = int(match.group(1))
        return {'submission_id': submission_id, 'updated': updated, 'range': saved_range,
                'row_number': number, 'sheet_name': title,
                'spreadsheet_url': f'https://docs.google.com/spreadsheets/d/{config["spreadsheet_id"]}/edit#gid={sheet["sheetId"]}'}
