import httpx
import pytest

from mythread.api import APIError
from mythread.cli import parser
from mythread.tunnel import CallbackServer, READY, tunnel_url_from_line


@pytest.fixture
def server():
    callback = CallbackServer()
    callback.redirect = "https://example.trycloudflare.com/callback"
    callback.state = "expected-state"
    callback.start()
    yield callback
    callback.close()


async def test_callback_checks_state_without_echoing_secrets(server, capsys):
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.http.server_port}", trust_env=False) as client:
        response = await client.get("/callback?state=wrong&code=secret-code")
        assert response.status_code == 400
        assert server.result.empty()
        response = await client.get("/callback?state=expected-state&code=secret-code")
        assert response.status_code == 200
        assert "secret-code" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert await server.wait_code(timeout=1) == "secret-code"
        duplicate = await client.get("/callback?state=expected-state&code=another-code")
        assert duplicate.status_code == 409
        assert "secret-code" not in capsys.readouterr().err


async def test_no_file_serving_and_health(server):
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.http.server_port}", trust_env=False) as client:
        assert (await client.get("/health")).content == READY
        assert (await client.get("/callback")).status_code == 200
        for path in ("/", "/.env", "/config.json", "/src/mythread/storage.py"):
            assert (await client.get(path)).status_code == 404


async def test_timeout_and_denied_authorization(server):
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.http.server_port}", trust_env=False) as client:
        assert (await client.get("/callback?state=expected-state&error=access_denied")).status_code == 400
    with pytest.raises(APIError, match="等待授權"):
        await server.wait_code(timeout=0.01)


def test_tunnel_login_can_request_both_permissions():
    args = parser().parse_args(["login", "--tunnel", "--search", "--discovery"])
    assert args.tunnel and args.search and args.discovery


def test_tunnel_parser_rejects_api_url_in_failure_logs():
    assert tunnel_url_from_line(b'Post "https://api.trycloudflare.com/tunnel": certificate error') is None
    assert tunnel_url_from_line(b'| https://a-test-host.trycloudflare.com |') == 'https://a-test-host.trycloudflare.com'
