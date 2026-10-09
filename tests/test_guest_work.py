import copy
import io
import json
from types import SimpleNamespace
from contextlib import contextmanager

import pytest
from src import guest_work as work
from src.errors import DocumentError
from src.models import sample_data


@pytest.fixture
def storage(monkeypatch):
    objects = {}
    bucket = SimpleNamespace(public=False)
    class Store:
        def download(self, path):
            return objects[path]
        def upload(self, path, value, options):
            if options['upsert'] == 'false':
                assert path not in objects
            objects[path] = value
    @contextmanager
    def client():
        yield SimpleNamespace(storage=SimpleNamespace(get_bucket=lambda name: bucket, from_=lambda name: Store()))
    monkeypatch.setattr(work, 'storage_client', client)
    return objects, bucket


def test_password_is_required_for_both_read_and_overwrite(storage):
    objects, _ = storage
    payload = {'data': sample_data(), 'messages': [], 'source_notes': '회사 자료'}
    first = work.save_work(payload)
    second = work.save_work(payload)
    assert first.number != second.number and first.password != second.password
    assert first.password not in repr(first)
    blob = objects[first.number + '.bin']
    assert '가온식품'.encode() not in blob and first.password.encode() not in blob
    loaded_access, loaded = work.load_work(first.number.lower(), first.password)
    assert loaded['data'] == payload['data']
    assert loaded_access == first
    with pytest.raises(DocumentError):
        work.load_work(first.number, second.password)
    with pytest.raises(DocumentError):
        work.save_work(payload, work.WorkAccess(first.number, second.password))
    assert objects[first.number + '.bin'] == blob
    payload['data']['company']['nameKo'] = '수정한 회사'
    work.save_work(payload, first)
    assert work.load_work(first.number, first.password)[1]['data']['company']['nameKo'] == '수정한 회사'
    assert work.load_work(second.number, second.password)[1]['data']['company']['nameKo'] != '수정한 회사'


def test_tampering_and_public_bucket_are_rejected(storage):
    objects, bucket = storage
    access = work.save_work({'data': sample_data()})
    objects[access.number + '.bin'] = objects[access.number + '.bin'][:-1] + b'!'
    with pytest.raises(DocumentError):
        work.load_work(access.number, access.password)
    bucket.public = True
    with pytest.raises(DocumentError, match='공개 설정'):
        work.save_work({'data': sample_data()})


@pytest.mark.parametrize('number', ['../../file', '', 'A'*25, 'g'*24])
def test_bad_work_number_never_reaches_storage(number, monkeypatch):
    monkeypatch.setattr(work, 'storage_client', lambda: pytest.fail('must not access storage'))
    with pytest.raises(DocumentError):
        work.load_work(number, 'long-password')
