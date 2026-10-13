"""Read explicitly supplied public pages, without cookies or browser execution."""
from contextlib import closing
from dataclasses import dataclass
import gzip
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .errors import DocumentError

MAX_LINKS = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 30000
MAX_REDIRECTS = 3
FETCH_SECONDS = 20
FALLBACK = '해당 페이지를 PDF로 저장해 파일 첨부로 올려 주세요.'


@dataclass(frozen=True)
class WebMaterial:
    name: str  # Final source URL; also retained in the saved draft's sources.
    title: str
    text: str
    truncated: bool = False

    def input_part(self):
        return {'type': 'input_text', 'text': json.dumps({
            'source_type': 'webpage', 'source_url': self.name,
            'title': self.title, 'page_text': self.text,
            'truncated': self.truncated,
        }, ensure_ascii=False)}


def normalize_url(value):
    value = value.strip()
    if not value or len(value) > 2000 or re.search(r'[\x00-\x20\x7f\\]', value):
        raise DocumentError('올바른 링크를 한 줄에 하나씩 입력해 주세요.')
    if '://' not in value:
        value = 'https://' + value
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').encode('idna').decode('ascii').lower().rstrip('.')
        port = parts.port
        if (parts.scheme not in ('http', 'https') or not host or '%' in host
                or parts.username is not None or parts.password is not None
                or port not in (None, 80 if parts.scheme == 'http' else 443)):
            raise ValueError()
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        authority = f'[{host}]' if ':' in host else host
        return urlunsplit((parts.scheme, authority,
                          quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~"),
                          quote(parts.query, safe="%=&?/:@!$'()*+,;~-._"), ''))
    except (ValueError, UnicodeError) as exc:
        raise DocumentError('로그인 정보나 별도 포트가 없는 공개 http/https 링크를 입력해 주세요.') from exc


def parse_links(value):
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) > MAX_LINKS:
        raise DocumentError('링크는 한 번에 최대 3개까지 입력해 주세요.')
    return list(dict.fromkeys(normalize_url(line) for line in lines))


def _public_endpoints(host, port):
    """Resolve once, reject mixed/private answers, then connect to these exact IPs."""
    endpoints = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not endpoints:
        raise DocumentError('링크의 주소를 찾지 못했습니다. 주소를 확인해 주세요.')
    for _, _, _, _, endpoint in endpoints:
        address = ipaddress.ip_address(endpoint[0])
        safe = address.is_global and not address.is_multicast
        if address.version == 6:
            # DNS64 networks legitimately synthesize these for public IPv4 hosts.
            # Check the embedded destination too, so internal IPv4 remains blocked.
            translated = address.ipv4_mapped
            if address in ipaddress.ip_network('64:ff9b::/96'):
                translated = ipaddress.IPv4Address(int(address) & 0xffffffff)
            if translated:
                safe = safe and translated.is_global and not translated.is_multicast
            safe = safe and not (address.sixtofour or address.teredo)
        if not safe:
            raise DocumentError('공개 인터넷 페이지의 링크만 사용할 수 있습니다.')
    return endpoints


class _PublicConnection(http.client.HTTPConnection):
    """Pinned sockets preserve the original Host and TLS SNI/verification name."""
    def __init__(self, parts, endpoints, deadline):
        super().__init__(parts.hostname, 443 if parts.scheme == 'https' else 80, timeout=8)
        self.endpoints = endpoints
        self.deadline = deadline
        self.secure = parts.scheme == 'https'

    def connect(self):
        last_error = None
        for family, socktype, proto, _, endpoint in self.endpoints[:3]:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            sock = socket.socket(family, socktype, proto)
            try:
                sock.settimeout(min(8, remaining))
                sock.connect(endpoint)
                if self.secure:
                    context = ssl.create_default_context()
                    context.set_alpn_protocols(['http/1.1'])
                    sock = context.wrap_socket(sock, server_hostname=self.host)
                self.sock = sock
                return
            except OSError as exc:
                sock.close()
                last_error = exc
        raise last_error or OSError('No reachable public address')


def _read_body(response, deadline):
    if int(response.getheader('Content-Length', '0')) > MAX_RESPONSE_BYTES:
        raise DocumentError('페이지 크기가 너무 큽니다. ' + FALLBACK)
    chunks, size = [], 0
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError()
        chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise DocumentError('페이지 크기가 너무 큽니다. ' + FALLBACK)
        chunks.append(chunk)
    body = b''.join(chunks)
    encoding = response.getheader('Content-Encoding', 'identity').lower().strip()
    if encoding == 'gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as decoded:
            body = decoded.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise DocumentError('페이지 크기가 너무 큽니다. ' + FALLBACK)
    elif encoding not in ('', 'identity'):
        raise DocumentError('이 페이지의 전송 형식을 읽을 수 없습니다. ' + FALLBACK)
    return body


def extract_page(url, body, content_type):
    mime = content_type.split(';', 1)[0].lower().strip()
    if mime not in ('', 'text/html', 'application/xhtml+xml', 'text/plain'):
        raise DocumentError('링크는 웹페이지를 지원합니다. PDF·사진·문서는 파일 첨부로 직접 올려 주세요.')
    charset = re.search(r'charset\s*=\s*[\"\']?([\w-]+)', content_type, re.I)
    soup = BeautifulSoup(body, 'html.parser', from_encoding=charset[1] if charset else None)
    title = soup.title.get_text(' ', strip=True) if soup.title else urlsplit(url).hostname
    if re.search(r'^(just a moment|access denied|attention required|robot check|접근 거부)', title, re.I):
        raise DocumentError('사이트에서 자동 접근을 제한하고 있습니다. ' + FALLBACK)
    descriptions = [node.get('content', '') for node in soup.find_all('meta')
                    if node.get('name', '').lower() == 'description'
                    or node.get('property', '').lower() in ('og:title', 'og:description')]
    for node in soup(['script', 'style', 'noscript', 'template', 'svg', 'head', 'form', 'nav']):
        node.decompose()
    for node in soup.select('[hidden], [aria-hidden="true"]'):
        node.decompose()
    lines = [re.sub(r'\s+', ' ', line).strip() for line in soup.get_text('\n', strip=True).splitlines()]
    text = '\n'.join(dict.fromkeys(line for line in lines + descriptions if line))
    if len(re.sub(r'\s+', '', text)) < 60:
        raise DocumentError('페이지에서 읽을 본문이 부족합니다. 로그인이나 화면 실행이 필요한 페이지일 수 있습니다. ' + FALLBACK)
    return WebMaterial(url, title[:300], text[:MAX_TEXT_CHARS], len(text) > MAX_TEXT_CHARS)


def fetch_page(url):
    url = normalize_url(url)
    deadline = time.monotonic() + FETCH_SECONDS
    try:
        for hop in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            endpoints = _public_endpoints(parts.hostname, 443 if parts.scheme == 'https' else 80)
            with closing(_PublicConnection(parts, endpoints, deadline)) as connection:
                connection.request('GET', parts.path + ('?' + parts.query if parts.query else ''), headers={
                    'User-Agent': 'KBrandDraftReader/1.0',
                    'Accept': 'text/html,application/xhtml+xml,text/plain',
                    'Accept-Encoding': 'identity', 'Connection': 'close',
                })
                with closing(connection.getresponse()) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.getheader('Location')
                        if not location or hop == MAX_REDIRECTS:
                            raise DocumentError('페이지 이동이 너무 많거나 올바르지 않습니다. 최종 페이지 주소를 입력해 주세요.')
                        url = normalize_url(urljoin(url, location))
                        continue
                    if response.status != 200:
                        raise DocumentError(f'페이지에 접근할 수 없습니다(HTTP {response.status}). 주소와 공개 여부를 확인해 주세요. ' + FALLBACK)
                    content_type = response.getheader('Content-Type', '')
                    return extract_page(url, _read_body(response, deadline), content_type)
    except (OSError, http.client.HTTPException, ValueError, EOFError) as exc:
        raise DocumentError('링크를 읽지 못했습니다. 주소와 접속 상태를 확인하거나 파일로 올려 주세요.') from exc


def prepare_links(value):
    materials = []
    for index, url in enumerate(parse_links(value), start=1):
        try:
            materials.append(fetch_page(url))
        except DocumentError as exc:
            raise DocumentError(f'{index}번째 링크: {exc}') from exc
    return materials
