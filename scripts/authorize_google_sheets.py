"""One-time Google Sheets OAuth consent; no application or sheet mutations.

Keep the downloaded web-client JSON and generated TOML in the ignored data/
directory. Run this on the computer whose browser will approve the consent.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost:8765/oauth/callback"
CALLBACK_PATH = "/oauth/callback"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DEFAULT_SPREADSHEET_ID = "192vVKcrNFH4iD7-eASl_HY4tln_N88jRtj0SyzJZPRE"
PORT = 8765


class AuthorizationError(Exception):
    """A fixed, safe-to-display authorization failure."""


class InvalidCallback(AuthorizationError):
    """Ignore unrelated or invalid local requests and keep waiting."""


def read_client_config(path: Path) -> dict[str, str]:
    try:
        if path.stat().st_size > 65_536:
            raise ValueError
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        client = payload["web"]
        client_id = client["client_id"]
        client_secret = client["client_secret"]
        if not isinstance(client_id, str) or not re.fullmatch(
            r"[A-Za-z0-9.-]+\.apps\.googleusercontent\.com", client_id
        ):
            raise ValueError
        if not isinstance(client_secret, str) or not client_secret or len(client_secret) > 4096:
            raise ValueError
        if client.get("auth_uri") not in {
            AUTH_URL, "https://accounts.google.com/o/oauth2/auth"
        } or client.get("token_uri") != TOKEN_URL:
            raise ValueError
        redirect_uris = client.get("redirect_uris", [])
        if not isinstance(redirect_uris, list) or REDIRECT_URI not in redirect_uris:
            raise ValueError
        return {"client_id": client_id, "client_secret": client_secret}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise AuthorizationError(
            "클라이언트 JSON을 확인해 주세요. 웹 애플리케이션 유형과 "
            f"리디렉션 URI {REDIRECT_URI}가 필요합니다."
        ) from None


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(client_id: str, state: str, verifier: str, login_hint: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return AUTH_URL + "?" + urlencode(params)


def parse_callback(target: str, expected_state: str) -> str:
    if len(target) > 8192:
        raise InvalidCallback("유효하지 않은 인증 응답입니다.")
    try:
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or parts.fragment or parts.path != CALLBACK_PATH:
            raise ValueError
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=12)
        if any(len(values) != 1 for values in query.values()):
            raise ValueError
        actual_state = query.get("state", [""])[0]
        if not actual_state or not hmac.compare_digest(actual_state.encode(), expected_state.encode()):
            raise ValueError
    except (ValueError, UnicodeError):
        raise InvalidCallback("유효하지 않은 인증 응답입니다.") from None
    if "error" in query:
        # Do not echo error_description or any other untrusted callback data.
        raise AuthorizationError("Google 인증이 승인되지 않았습니다. 연결 도구를 다시 실행해 주세요.")
    code = query.get("code", [""])[0]
    if not code or len(code) > 4096:
        raise InvalidCallback("유효하지 않은 인증 응답입니다.")
    return code


def make_callback_handler(expected_state: str, outcome: dict):
    class CallbackHandler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format, *args):
            # The request URL contains a short-lived authorization code.
            pass

        def reply(self, status: int, message: str):
            body = ("<!doctype html><meta charset='utf-8'><title>Google Sheets 연결</title>"
                    f"<p>{message}</p>").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def send_error(self, code, message=None, explain=None):
            self.reply(code, "이 요청은 처리할 수 없습니다.")

        def do_GET(self):
            if self.headers.get("Host") not in {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}:
                self.reply(400, "이 요청은 처리할 수 없습니다.")
                return
            try:
                code = parse_callback(self.path, expected_state)
            except InvalidCallback:
                self.reply(400, "유효하지 않은 인증 응답입니다. 원래 승인 화면을 이용해 주세요.")
            except AuthorizationError as error:
                outcome["error"] = error
                self.reply(400, "인증이 승인되지 않았습니다. 연결 도구를 다시 실행해 주세요.")
            else:
                outcome["code"] = code
                self.reply(200, "승인 응답을 받았습니다. 이 탭을 닫고 연결 도구의 완료 결과를 확인해 주세요.")

        def do_POST(self):
            self.reply(405, "이 요청은 처리할 수 없습니다.")

    return CallbackHandler


def receive_code(client_id: str, state: str, verifier: str, login_hint: str, timeout: int) -> str:
    outcome: dict = {}
    try:
        server = HTTPServer(("127.0.0.1", PORT), make_callback_handler(state, outcome))
    except OSError:
        raise AuthorizationError(f"로컬 인증 서버를 열 수 없습니다. 포트 {PORT} 사용 여부를 확인해 주세요.") from None
    with server:
        print("다음 주소를 이 컴퓨터의 브라우저에서 열어 사용할 회사 계정으로 승인해 주세요.", flush=True)
        print(authorization_url(client_id, state, verifier, login_hint), flush=True)
        deadline = time.monotonic() + timeout
        while not outcome:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AuthorizationError("인증 대기 시간이 끝났습니다. 연결 도구를 다시 실행해 주세요.")
            server.timeout = min(0.5, remaining)
            server.handle_request()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["code"]


def exchange_code(client: dict[str, str], code: str, verifier: str) -> str:
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as session:
            response = session.post(TOKEN_URL, data={
                **client,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            })
        if response.status_code != 200:
            raise AuthorizationError("Google 토큰 발급에 실패했습니다. 클라이언트 설정을 확인한 뒤 다시 승인해 주세요.")
        payload = response.json()
        refresh_token = payload.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 16_384:
            raise AuthorizationError("자동 갱신용 인증 정보가 발급되지 않았습니다. 연결 도구를 다시 실행하여 승인해 주세요.")
        if "scope" in payload and SCOPE not in str(payload["scope"]).split():
            raise AuthorizationError("Google Sheets 접근 권한이 승인되지 않았습니다.")
        return refresh_token
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise AuthorizationError("Google 인증 응답을 처리하지 못했습니다. 네트워크와 클라이언트 설정을 확인해 주세요.") from None


def toml_string(value: str) -> str:
    value.encode("utf-8")  # Reject invalid surrogate characters before writing.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def secrets_toml(client: dict[str, str], refresh_token: str, spreadsheet_id: str, sheet_name: str) -> str:
    fields = {**client, "refresh_token": refresh_token, "spreadsheet_id": spreadsheet_id, "sheet_name": sheet_name}
    return "[google_sheets]\n" + "".join(f"{name} = {toml_string(value)}\n" for name, value in fields.items())


def validate_output_path(path: Path) -> Path:
    output = path.expanduser().resolve()
    private_root = (PROJECT_ROOT / "data").resolve()
    if not output.is_relative_to(private_root) or output.suffix.lower() != ".toml":
        raise AuthorizationError("출력 파일은 이 프로젝트의 Git 제외 폴더 data/ 아래에 .toml 형식으로 지정해 주세요.")
    if output.exists():
        raise AuthorizationError("출력 파일이 이미 있습니다. 기존 인증 정보 보호를 위해 새 파일명을 지정해 주세요.")
    return output


def write_secrets(output: Path, content: str):
    # O_EXCL prevents overwriting an existing file or following a file symlink.
    # Mode 0600 applies on POSIX; on Windows the user's directory ACL applies.
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as destination:
        destination.write(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Google Sheets 자동 저장용 회사 계정 인증 정보 발급")
    parser.add_argument("--client-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Git 제외 폴더 data/ 아래의 새 .toml 파일")
    parser.add_argument("--spreadsheet-id", default=DEFAULT_SPREADSHEET_ID)
    parser.add_argument("--sheet-name", default="시트1")
    parser.add_argument("--login-hint", default="managergoal@iyouproject.com")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        if not 30 <= args.timeout_seconds <= 1800:
            raise AuthorizationError("대기 시간은 30~1800초 사이로 지정해 주세요.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.spreadsheet_id) or not args.sheet_name.strip():
            raise AuthorizationError("스프레드시트 ID와 시트 이름을 확인해 주세요.")
        output = validate_output_path(args.output)
        client = read_client_config(args.client_json)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        code = receive_code(client["client_id"], state, verifier, args.login_hint, args.timeout_seconds)
        refresh_token = exchange_code(client, code, verifier)
        write_secrets(output, secrets_toml(client, refresh_token, args.spreadsheet_id, args.sheet_name))
        print(f"Google Sheets 인증 정보를 저장했습니다: {output}")
        print("스프레드시트 내용은 변경하지 않았습니다. 인증 파일은 GitHub에 올리지 마세요.")
        return 0
    except AuthorizationError as error:
        print(f"연결 실패: {error}", file=sys.stderr)
    except (OSError, UnicodeError):
        print("연결 실패: 인증 파일을 읽거나 저장하지 못했습니다. 파일 경로와 접근 권한을 확인해 주세요.", file=sys.stderr)
    except KeyboardInterrupt:
        print("연결을 취소했습니다.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
