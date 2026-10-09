"""Run once for a new Supabase project: uv run python scripts/setup_guest_storage.py."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.guest_work import BUCKET, MAX_BYTES, storage_client


def setup():
    with storage_client() as client:
        buckets = client.storage.list_buckets()
        if not any(bucket.id == BUCKET for bucket in buckets):
            client.storage.create_bucket(BUCKET, options={'public': False, 'file_size_limit': MAX_BYTES, 'allowed_mime_types': ['application/octet-stream']})
        bucket = client.storage.get_bucket(BUCKET)
        if bucket.public:
            raise RuntimeError('The guest draft bucket must be private.')
    print('Guest draft storage is ready (private).')


if __name__ == '__main__':
    setup()
