import json
import tomllib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from scripts import authorize_google_sheets as oauth


def client_payload():
    return {"web": {
        "client_id": "123-example.apps.googleusercontent.com",
        "client_secret": "private-client-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": oauth.TOKEN_URL,
        "redirect_uris": [oauth.REDIRECT_URI],
    }}


def test_pkce_matches_rfc7636_and_consent_requests_only_sheets_scope():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert oauth.pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    url = oauth.authorization_url("public-client-id", "random-state", verifier, "managergoal@example.com")
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.scheme == "https" and parts.netloc == "accounts.google.com"
    assert query["scope"] == [oauth.SCOPE]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [oauth.REDIRECT_URI]
    assert query["state"] == ["random-state"]
    assert verifier not in url and "client_secret" not in query


@pytest.mark.parametrize("target", [
    "/favicon.ico?state=expected&code=private-code",
    "https://attacker.example/oauth/callback?state=expected&code=private-code",
    "/oauth/callback?state=wrong&code=private-code",
    "/oauth/callback?code=private-code",
    "/oauth/callback?state=expected&state=expected&code=private-code",
    "/oauth/callback?state=expected&code=one&code=private-code",
    "/oauth/callback?state=expected&code=",
    "/oauth/callback?state=expected&code=private-code#fragment",
])
def test_callback_rejects_wrong_path_state_or_ambiguous_values_without_echoing(target):
    with pytest.raises(oauth.InvalidCallback) as error:
        oauth.parse_callback(target, "expected")
    assert "private-code" not in str(error.value)


def test_valid_callback_accepts_code_and_denial_does_not_expose_error_description():
    assert oauth.parse_callback("/oauth/callback?state=expected&code=accepted-code&scope=scope", "expected") == "accepted-code"
    with pytest.raises(oauth.AuthorizationError) as error:
        oauth.parse_callback("/oauth/callback?state=expected&error=access_denied&error_description=private-error", "expected")
    assert not isinstance(error.value, oauth.InvalidCallback)
    assert "private-error" not in str(error.value)
    with pytest.raises(oauth.InvalidCallback):
        oauth.parse_callback("/oauth/callback?state=wrong&error=access_denied", "expected")


def test_web_client_config_requires_registered_redirect_and_google_endpoints(tmp_path):
    path = tmp_path / "client.json"
    payload = client_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert oauth.read_client_config(path)["client_secret"] == "private-client-secret"
    for change in ({"token_uri": "https://attacker.example/token"}, {"redirect_uris": []}):
        altered = client_payload()
        altered["web"].update(change)
        path.write_text(json.dumps(altered), encoding="utf-8")
        with pytest.raises(oauth.AuthorizationError) as error:
            oauth.read_client_config(path)
        assert "private-client-secret" not in str(error.value)


def install_mock_client(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(oauth.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs
    ))


def test_exchange_uses_fixed_endpoint_and_verifier_then_returns_only_refresh_token(monkeypatch):
    def handler(request):
        assert str(request.url) == oauth.TOKEN_URL
        form = parse_qs(request.content.decode())
        assert form["code_verifier"] == ["private-verifier"]
        assert form["redirect_uri"] == [oauth.REDIRECT_URI]
        assert form["client_secret"] == ["private-client-secret"]
        return httpx.Response(200, json={"refresh_token": "private-refresh", "access_token": "private-access", "scope": oauth.SCOPE})
    install_mock_client(monkeypatch, handler)
    assert oauth.exchange_code({
        "client_id": "public-client-id", "client_secret": "private-client-secret"
    }, "private-code", "private-verifier") == "private-refresh"


@pytest.mark.parametrize("status,payload", [
    (400, {"error": "invalid_grant", "error_description": "private-server-detail"}),
    (200, {"access_token": "private-access"}),
    (200, {"refresh_token": "private-refresh", "scope": "unrelated-scope"}),
])
def test_token_failure_never_leaks_response_secrets(monkeypatch, status, payload):
    install_mock_client(monkeypatch, lambda request: httpx.Response(status, json=payload))
    with pytest.raises(oauth.AuthorizationError) as error:
        oauth.exchange_code({"client_id": "public-id", "client_secret": "private-client-secret"}, "private-code", "private-verifier")
    assert "private-" not in str(error.value)


def test_toml_roundtrips_quotes_controls_and_unicode_without_extra_sections():
    value = 'quote " slash \\ newline\n tab\t null\x00 delete\x7f 한글 😀'
    text = oauth.secrets_toml({"client_id": value, "client_secret": value}, value, "sheet-id", '신청 기업 "목록"')
    parsed = tomllib.loads(text)
    assert list(parsed) == ["google_sheets"]
    assert parsed["google_sheets"]["refresh_token"] == value
    assert parsed["google_sheets"]["sheet_name"] == '신청 기업 "목록"'
    assert set(parsed["google_sheets"]) == {"client_id", "client_secret", "refresh_token", "spreadsheet_id", "sheet_name"}


def test_output_must_be_ignored_data_toml_and_must_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "PROJECT_ROOT", tmp_path)
    output = oauth.validate_output_path(tmp_path / "data" / "google_oauth" / "new.toml")
    oauth.write_secrets(output, "private-value")
    assert output.read_text(encoding="utf-8") == "private-value"
    with pytest.raises(oauth.AuthorizationError):
        oauth.validate_output_path(output)
    with pytest.raises(FileExistsError):
        oauth.write_secrets(output, "replacement")
    assert output.read_text(encoding="utf-8") == "private-value"
    for path in (tmp_path / "tracked.toml", tmp_path / "data" / "credentials.json", tmp_path / "data" / ".." / "tracked.toml"):
        with pytest.raises(oauth.AuthorizationError):
            oauth.validate_output_path(path)


def test_cli_failure_never_prints_token_response_body(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(oauth, "PROJECT_ROOT", tmp_path)
    path = tmp_path / "client.json"
    path.write_text(json.dumps(client_payload()), encoding="utf-8")
    monkeypatch.setattr(oauth, "receive_code", lambda *args: "private-code")
    install_mock_client(monkeypatch, lambda request: httpx.Response(400, json={"error_description": "private-server-detail"}))
    assert oauth.main(["--client-json", str(path), "--output", str(tmp_path / "data" / "secrets.toml")]) == 1
    output = capsys.readouterr()
    assert "private-" not in output.out + output.err
    assert not (tmp_path / "data" / "secrets.toml").exists()
