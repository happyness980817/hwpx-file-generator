import copy

import pytest

from src import password_documents as documents
from src.errors import DocumentError
from src.guest_work import WorkAccess
from src.models import sample_data


def test_password_only_reopens_and_updates_across_sessions(document_store):
    objects, _ = document_store
    payload = {'data': sample_data(), 'source_names': ['https://example.com/product']}
    first = documents.create_document('Test-password-123', payload)
    second = documents.create_document('Another-password-456', payload)
    blob = objects[documents.document_path(first)]
    assert first.password not in repr(first)
    assert first.password.encode() not in blob and '가온식품'.encode() not in blob
    loaded, restored = documents.load_document('Test-password-123', 'browser-2')
    assert loaded == first and restored['data'] == payload['data']
    assert restored['source_names'] == payload['source_names']
    restored['data']['company']['nameKo'] = '수정한 기업'
    documents.save_document(restored, loaded)
    assert documents.load_document(first.password, 'browser-3')[1]['data']['company']['nameKo'] == '수정한 기업'
    assert documents.load_document(second.password, 'browser-4')[1]['data'] == payload['data']


def test_duplicate_password_never_opens_or_overwrites_other_document(document_store):
    objects, _ = document_store
    original = documents.create_document('Test-password-123', {'data': sample_data()})
    blob = copy.deepcopy(objects)
    with pytest.raises(DocumentError, match='다른 비밀번호'):
        documents.create_document(original.password, {'data': sample_data()})
    with pytest.raises(DocumentError, match='비밀번호'):
        documents.load_document('Wrong-password-123', 'wrong-browser')
    with pytest.raises(DocumentError, match='비밀번호'):
        documents.save_document({'data': sample_data()}, WorkAccess(original.number, 'Wrong-password-123'))
    assert objects == blob


@pytest.mark.parametrize('password', ['', 'abc123', '123456789012', 'onlyletterspassword', 'password1234'])
def test_invalid_password_fails_before_storage(password, monkeypatch):
    monkeypatch.setattr(documents, 'storage_client', lambda: pytest.fail('No network'))
    with pytest.raises(DocumentError, match='10자'):
        documents.create_document(password, {'data': sample_data()})


def test_wrong_password_attempts_are_limited_and_expire(document_store, monkeypatch):
    now = [1000]
    monkeypatch.setattr(documents.time, 'monotonic', lambda: now[0])
    for _ in range(8):
        with pytest.raises(DocumentError, match='비밀번호'):
            documents.load_document('Wrong-password-123', 'same-browser')
    with pytest.raises(DocumentError, match='1분'):
        documents.load_document('Wrong-password-123', 'same-browser')
    now[0] += 61
    with pytest.raises(DocumentError, match='비밀번호'):
        documents.load_document('Wrong-password-123', 'same-browser')


def test_tampering_and_public_storage_are_not_accepted(document_store):
    objects, bucket = document_store
    access = documents.create_document('Test-password-123', {'data': sample_data()})
    path = documents.document_path(access)
    objects[path] = objects[path][:-1] + bytes([objects[path][-1] ^ 1])
    with pytest.raises(DocumentError, match='비밀번호'):
        documents.load_document(access.password, 'browser')
    bucket.public = True
    with pytest.raises(DocumentError, match='보관함'):
        documents.create_document('Another-password-456', {'data': sample_data()})
