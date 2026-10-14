"""Bounded, sanitized HTTP error details for private server logs only."""
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)
HEADER_NAMES = ('Server', 'Content-Type', 'Content-Encoding', 'Via', 'X-Cache',
                'X-Amz-Cf-Pop', 'X-Amz-Cf-Id', 'CF-Ray', 'CF-Mitigated',
                'X-Amzn-Waf-Action', 'Retry-After')


def _redact(value):
    text = str(value)
    text = re.sub(r'https?://\S+', '[URL]', text, flags=re.I)
    text = re.sub(r'[\w.+-]+@[\w.-]+', '[EMAIL]', text)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[IP]', text)
    text = re.sub(r'(?i)\b(?:bearer\s+\S+|sk-[\w-]+|sb_secret_[\w-]+|eyJ[\w.-]+)', '[SECRET]', text)
    text = re.sub(r'(?i)\b(token|password|secret|api[_-]?key|cookie|authorization)\s*[:=]\s*[^\s;,]+', r'\1=[REDACTED]', text)
    return re.sub(r'\s+', ' ', text).strip()


def log_http_failure(url, response):
    """Diagnostics must never replace the original HTTP error or expose cookies."""
    record = {'event': 'KBRAND_LINK_HTTP_ERROR',
              'at': datetime.now(timezone.utc).isoformat(),
              'host': urlsplit(url).hostname,
              'url_fingerprint': hashlib.sha256(url.encode()).hexdigest()[:12],
              'status': response.status,
              'headers': {name: _redact(response.getheader(name))[:300]
                          for name in HEADER_NAMES if response.getheader(name)}}
    try:
        mime = response.getheader('Content-Type', '').split(';', 1)[0].lower().strip()
        encoding = response.getheader('Content-Encoding', 'identity').lower().strip()
        if mime not in ('', 'text/html', 'text/plain', 'application/xhtml+xml', 'application/json') or encoding not in ('', 'identity'):
            record['body_excerpt'] = '[Non-text or compressed error body omitted]'
        else:
            body = response.read1(4096)
            soup = BeautifulSoup(body.decode('utf-8', errors='replace'), 'html.parser')
            for node in soup(['script', 'style', 'form', 'input', 'textarea']):
                node.decompose()
            record['body_excerpt'] = _redact(soup.get_text(' ', strip=True))[:1200]
            record['body_may_be_truncated'] = len(body) == 4096
    except Exception:
        record['body_excerpt'] = '[Error body unavailable]'
    LOGGER.warning('%s', json.dumps(record, ensure_ascii=True))
