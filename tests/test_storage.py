import pytest
from keyring.errors import NoKeyringError

from mythread.storage import Store, StorageError


def test_token_only_in_keyring_and_logout(tmp_path, monkeypatch):
    secrets = {}
    monkeypatch.setattr("keyring.set_password", lambda service, user, value: secrets.update({user: value}))
    monkeypatch.setattr("keyring.get_password", lambda service, user: secrets.get(user))
    monkeypatch.setattr("keyring.delete_password", lambda service, user: secrets.pop(user))
    store = Store(tmp_path)
    store.save_token("private-token", 3600)
    store.write("draft.json", {"text": "draft"})
    assert store.credential()["access_token"] == "private-token"
    assert all("private-token" not in p.read_text() for p in tmp_path.iterdir())
    store.logout()
    assert store.credential() == {}
    assert store.read("draft.json") == {}


def test_no_plaintext_fallback(tmp_path, monkeypatch):
    def fail(*args):
        raise NoKeyringError()
    monkeypatch.setattr("keyring.set_password", fail)
    with pytest.raises(StorageError):
        Store(tmp_path).save_token("secret")
    assert not list(tmp_path.iterdir())
