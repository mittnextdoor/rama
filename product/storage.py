"""Where source documents and generated packages are kept. The rest of the product talks to a DocumentStore, so the
local store used today can be replaced by encrypted cloud object storage without touching callers (docs/73 §4.1).

LocalStore keeps each file once, addressed by its SHA-256, under data/product/files/ (never committed). A cloud store is
not implemented yet; asking for one fails clearly instead of pretending to work."""
import hashlib
import os
import uuid

from . import config


class DocumentStore:
    def put(self, data: bytes) -> tuple[str, str]:          # -> (storage_key, sha256)
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError


class LocalStore(DocumentStore):
    def __init__(self, root=None):
        self.root = root or config.FILES_ROOT

    def _path(self, key):
        if not key.startswith("sha256/") or ".." in key:
            raise ValueError("not a storage key")
        return os.path.join(self.root, key)

    def put(self, data):
        digest = hashlib.sha256(data).hexdigest()
        key = f"sha256/{digest[:2]}/{digest}"
        path = self._path(key)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.part"   # its own temporary name: two uploads of the same file at once
            with open(tmp, "wb") as f:                                 # each write theirs (QA audit, QA-019)
                f.write(data)
            os.replace(tmp, path)                            # never a half-written file under the final name; the same bytes either way
        return key, digest

    def get(self, key):
        with open(self._path(key), "rb") as f:
            return f.read()

    def exists(self, key):
        return os.path.exists(self._path(key))


def store(kind=None) -> DocumentStore:
    kind = kind or config.env("NHB_PRODUCT_STORE", "local")
    if kind == "local":
        return LocalStore()
    raise NotImplementedError(f"document store {kind!r} isn't available yet (cloud storage is docs/74, B-13)")
