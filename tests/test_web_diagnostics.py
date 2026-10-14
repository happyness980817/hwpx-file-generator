import io
import json

from src.web_diagnostics import log_http_failure


class ErrorResponse(io.BytesIO):
    status = 403

    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


def test_http_error_logs_evidence_but_not_url_parameters_or_credentials(caplog):
    response = ErrorResponse(b'''<h1>403 ERROR</h1><p>The Amazon CloudFront distribution is configured to block access from your country.</p>
        <script>password=script-secret</script><form><input value="hidden-secret"></form>
        <p>token=query-secret admin@example.com 192.0.2.42 https://example.com/?token=url-secret</p>''',
        {'Server': 'CloudFront', 'Content-Type': 'text/html', 'X-Cache': 'Error from cloudfront',
         'Set-Cookie': 'session=cookie-secret', 'Authorization': 'Bearer authorization-secret'})
    log_http_failure('https://example.com/product?token=request-secret', response)
    record = json.loads(caplog.records[-1].getMessage())
    assert record['status'] == 403 and record['host'] == 'example.com'
    assert record['headers']['Server'] == 'CloudFront'
    assert 'block access from your country' in record['body_excerpt']
    for secret in ('script-secret', 'hidden-secret', 'query-secret', 'url-secret', 'cookie-secret',
                   'authorization-secret', 'request-secret', 'admin@example.com', '192.0.2.42'):
        assert secret not in caplog.text


def test_error_body_is_bounded_and_read_failure_does_not_mask_status(caplog):
    response = ErrorResponse(b'x' * 9000)
    log_http_failure('https://example.com', response)
    record = json.loads(caplog.records[-1].getMessage())
    assert response.tell() == 4096 and len(record['body_excerpt']) <= 1200
    assert record['body_may_be_truncated']
    response.read1 = lambda *args: (_ for _ in ()).throw(TimeoutError('secret-in-exception'))
    log_http_failure('https://example.com', response)
    record = json.loads(caplog.records[-1].getMessage())
    assert record['status'] == 403 and record['body_excerpt'] == '[Error body unavailable]'
    assert 'secret-in-exception' not in caplog.text


def test_compressed_or_binary_error_is_not_read(caplog):
    response = ErrorResponse(b'not-logged', {'Content-Encoding': 'gzip'})
    log_http_failure('https://example.com', response)
    assert response.tell() == 0 and 'not-logged' not in caplog.text
