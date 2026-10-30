"""Verify archive delivery without regenerating, leaking, or altering bytes."""
import base64
import io
import zipfile
from unittest.mock import Mock

import pytest

from src import download_ui


def archive_bytes():
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as archive:
        archive.writestr('신청서.hwpx', b'example document bytes')
        archive.writestr('상품리스트.xlsx', b'example sheet bytes')
    return result.getvalue()


def test_delivers_exact_bytes_and_korean_filename_as_data(monkeypatch):
    mount = Mock()
    monkeypatch.setattr(download_ui, '_download', mount)
    content = archive_bytes()
    download_ui.render_file_download(content, 'K-브랜드_필작성_5종.zip', request_id='request-1')
    params = mount.call_args.kwargs
    assert base64.b64decode(params['data']['content']) == content
    assert params['data']['filename'] == 'K-브랜드_필작성_5종.zip'
    assert params['data']['requestId'] == 'request-1'
    assert params['data']['showRetry'] is True
    assert params['key'] == 'application_file_download'


def test_repeated_explicit_downloads_have_distinct_ids(monkeypatch):
    mount = Mock()
    monkeypatch.setattr(download_ui, '_download', mount)
    content = archive_bytes()
    for request_id in ['click_1', 'click_2']:
        download_ui.render_file_download(content, '문서.zip', request_id=request_id)
    payloads = [call.kwargs['data'] for call in mount.call_args_list]
    assert payloads[0]['content'] == payloads[1]['content']
    assert payloads[0]['requestId'] != payloads[1]['requestId']


def test_untrusted_filename_is_data_not_code_and_path_is_removed(monkeypatch):
    mount = Mock()
    monkeypatch.setattr(download_ui, '_download', mount)
    filename = '../<script>alert("x")</script>\\문서\n.zip'
    download_ui.render_file_download(b'bytes', filename, request_id='click-1')
    sent = mount.call_args.kwargs['data']['filename']
    assert '/' not in sent and '\\' not in sent and '\n' not in sent
    assert 'alert("x")' in sent  # Passed as a download property, never HTML.
    assert filename not in download_ui.DOWNLOAD_JS


@pytest.mark.parametrize('content,request_id', [(b'', 'id'), ('text', 'id'), (b'bytes', ''),
    (b'bytes', '../unsafe'), (b'bytes', 'x' * 129)])
def test_invalid_delivery_rejected_before_mount(content, request_id, monkeypatch):
    mount = Mock()
    monkeypatch.setattr(download_ui, '_download', mount)
    with pytest.raises(ValueError):
        download_ui.render_file_download(content, '문서.zip', request_id=request_id)
    mount.assert_not_called()


def test_hidden_mount_is_available_without_additional_visible_controls(monkeypatch):
    mount = Mock()
    monkeypatch.setattr(download_ui, '_download', mount)
    download_ui.render_file_download(b'bytes', '문서.zip', request_id='click-1', show_retry=False)
    assert mount.call_args.kwargs['height'] == 0
    assert mount.call_args.kwargs['data']['showRetry'] is False
