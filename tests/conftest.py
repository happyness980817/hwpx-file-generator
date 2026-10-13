from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from storage3.exceptions import StorageApiError

from src import password_documents as documents


@pytest.fixture
def document_store(monkeypatch):
    objects = {}
    bucket = SimpleNamespace(public=False)

    class Store:
        def download(self, path):
            if path not in objects:
                raise StorageApiError('Not found', 'not_found', 404)
            return objects[path]

        def upload(self, path, content, options):
            if path in objects and options['upsert'] == 'false':
                raise StorageApiError('Already exists', 'Duplicate', 409)
            objects[path] = content

    @contextmanager
    def client():
        yield SimpleNamespace(storage=SimpleNamespace(get_bucket=lambda name: bucket, from_=lambda name: Store()))

    documents._attempts.clear()
    monkeypatch.setattr(documents, 'storage_client', client)
    yield objects, bucket
    documents._attempts.clear()
