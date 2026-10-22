import json
import time
from pathlib import Path

import keyring
from keyring.errors import KeyringError
from platformdirs import user_config_path


class StorageError(Exception):
    pass


class Store:
    SERVICE = "mythread-terminal"

    def __init__(self, directory: Path | None = None):
        self.directory = directory or user_config_path("mythread", appauthor=False)

    def read(self, name: str) -> dict:
        path = self.directory / name
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError) as exc:
            raise StorageError(f"無法讀取設定：{path}") from exc

    def write(self, name: str, data: dict):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / name
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            raise StorageError("無法儲存本機設定。") from exc

    def credential(self) -> dict:
        try:
            value = keyring.get_password(self.SERVICE, "account")
            return json.loads(value) if value else {}
        except (KeyringError, ValueError) as exc:
            raise StorageError("無法使用系統憑證庫；不會改存明文 Token。") from exc

    def save_token(self, token: str, expires_in: int | None = None, long_lived=False):
        record = {"access_token": token, "saved_at": time.time(), "long_lived": long_lived}
        if expires_in is not None:
            record["expires_at"] = time.time() + int(expires_in)
        try:
            keyring.set_password(self.SERVICE, "account", json.dumps(record))
        except KeyringError as exc:
            raise StorageError("無法儲存到系統憑證庫。") from exc

    def logout(self):
        try:
            if keyring.get_password(self.SERVICE, "account"):
                keyring.delete_password(self.SERVICE, "account")
        except KeyringError as exc:
            raise StorageError("無法清除系統憑證庫。") from exc
        self.write("draft.json", {})
        self.write("feed-seen.json", {})
