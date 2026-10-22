import time

import pytest

from mythread.api import APIError
from mythread.cli import credentials


class MemoryStore:
    def __init__(self, record):
        self.record = record
        self.saved = None

    def credential(self):
        return self.record

    def save_token(self, *args):
        self.saved = args


async def test_near_expiry_refreshes(monkeypatch):
    async def fake_refresh(token):
        assert token == "old"
        return {"access_token": "new", "expires_in": 5184000}
    monkeypatch.setattr("mythread.cli.refresh", fake_refresh)
    store = MemoryStore({"access_token": "old", "long_lived": True,
                         "saved_at": time.time() - 2 * 86400, "expires_at": time.time() + 86400})
    assert await credentials(store) == "new"
    assert store.saved == ("new", 5184000, True)


async def test_expired_requires_relogin():
    store = MemoryStore({"access_token": "old", "expires_at": time.time() - 1})
    with pytest.raises(APIError, match="過期"):
        await credentials(store)


async def test_imported_token_not_automatically_refreshed():
    store = MemoryStore({"access_token": "imported"})
    assert await credentials(store) == "imported"
    assert store.saved is None
