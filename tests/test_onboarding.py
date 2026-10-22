import json
import time

import pytest

from mythread.api import APIError, Page
from mythread.cli import parser, run
from mythread.onboarding import diagnose
from mythread.storage import StorageError


class Store:
    def __init__(self, record=None):
        self.record = record or {}

    def credential(self):
        return self.record


class Client:
    def __init__(self, token):
        self.calls = []
        self.closed = False

    async def me(self):
        self.calls.append("me")
        return {"id": "123", "username": "tester"}

    async def posts(self, username=""):
        self.calls.append(username or "own")
        return Page([])

    async def close(self):
        self.closed = True


async def test_missing_token_never_connects():
    def unexpected(token):
        pytest.fail("Missing token must not trigger API calls")
    report = await diagnose(Store(), client_factory=unexpected)
    assert not report["ok"]
    assert report["checks"][-1]["check"] == "token"


async def test_expired_token_never_connects():
    def unexpected(token):
        pytest.fail("Expired token must not trigger API calls")
    report = await diagnose(Store({"access_token": "secret", "expires_at": time.time() - 1}), client_factory=unexpected)
    assert not report["ok"]
    assert report["checks"][-1]["check"] == "expiry"


async def test_read_only_diagnosis_and_redaction():
    client = Client("secret")
    report = await diagnose(Store({"access_token": "secret"}), client_factory=lambda token: client)
    assert report["ok"]
    assert client.calls == ["me", "own"]
    assert client.closed
    assert "secret" not in json.dumps(report)
    assert report["checks"][-1]["status"] == "skip"


async def test_optional_public_profile_failure():
    class RestrictedClient(Client):
        async def posts(self, username=""):
            if username:
                raise APIError("權限不足")
            return Page([])
    client = RestrictedClient("secret")
    report = await diagnose(Store({"access_token": "secret"}), "threads", lambda token: client)
    assert not report["ok"]
    assert client.closed
    assert any(c["check"] == "own_posts" and c["status"] == "pass" for c in report["checks"])
    assert any(c["check"] == "public_posts" and c["status"] == "fail" for c in report["checks"])


async def test_auth_failure_stops_checks_and_closes():
    class ExpiredClient(Client):
        async def me(self):
            raise APIError("授權失效")
    client = ExpiredClient("secret")
    report = await diagnose(Store({"access_token": "secret"}), client_factory=lambda token: client)
    assert not report["ok"]
    assert client.calls == []
    assert client.closed


async def test_credential_store_failure_is_reported():
    class BrokenStore:
        def credential(self):
            raise StorageError("Unavailable")
    report = await diagnose(BrokenStore())
    assert not report["ok"]
    assert report["checks"][0]["check"] == "credential_store"


async def test_cli_json_failure_exit_code(capsys):
    with pytest.raises(SystemExit) as error:
        await run(parser().parse_args(["doctor", "--json"]), Store())
    assert error.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False


async def test_setup_does_not_need_credentials(capsys):
    await run(parser().parse_args(["setup"]), object())
    output = capsys.readouterr().out
    assert "login --token" in output
    assert "threads_basic" in output


async def test_empty_search_does_not_claim_public_access():
    class SearchClient(Client):
        async def search(self, keyword):
            return Page([])
    report = await diagnose(Store({"access_token": "secret"}), client_factory=SearchClient, keyword="貓")
    assert any(c["check"] == "search_scope" and c["status"] == "info" for c in report["checks"])
    assert "secret" not in json.dumps(report)
