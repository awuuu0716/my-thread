import httpx
import pytest

from mythread.api import APIError, PublishUncertain, ThreadsClient, plain


async def test_own_posts_cursor_and_no_media_download():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer fake-token"
        assert request.url.path == "/me/threads"
        assert request.url.params["after"] == "page-two"
        return httpx.Response(200, json={"data": [{"id": "1", "media_type": "IMAGE", "text": "hello"}],
                                        "paging": {"next": "https://evil.invalid/?access_token=secret",
                                                   "cursors": {"after": "page-three"}}})
    client = ThreadsClient("fake-token", httpx.MockTransport(handler))
    try:
        page = await client.posts(after="page-two")
        assert page.after == "page-three"
        assert len(requests) == 1
        assert "media_url" not in requests[0].url.params["fields"]
    finally:
        await client.close()


async def test_public_profile_and_last_page():
    def handler(request):
        assert request.url.path == "/profile_posts"
        assert request.url.params["username"] == "threads"
        return httpx.Response(200, json={"data": [], "paging": {"cursors": {"after": "last"}}})
    client = ThreadsClient("test", httpx.MockTransport(handler))
    try:
        assert (await client.posts("@threads")).after is None
        with pytest.raises(APIError):
            await client.posts("https://threads.com/@someone")
    finally:
        await client.close()


@pytest.mark.parametrize("status,code,message", [(401,190,"授權"),(403,10,"權限"),(429,4,"額度")])
async def test_safe_api_errors(status, code, message):
    client = ThreadsClient("secret", httpx.MockTransport(lambda r: httpx.Response(
        status, json={"error": {"code": code, "message": "secret"}})))
    try:
        with pytest.raises(APIError) as error:
            await client.posts()
        assert message in str(error.value)
        assert "secret" not in str(error.value)
    finally:
        await client.close()


async def test_publish_timeout_never_retries():
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("contains-secret", request=request)
    client = ThreadsClient("secret", httpx.MockTransport(handler))
    try:
        with pytest.raises(PublishUncertain):
            await client.publish("hello")
        assert len(requests) == 1
    finally:
        await client.close()


async def test_publish_chinese_and_newline():
    from urllib.parse import parse_qs
    def handler(request):
        assert request.method == "POST"
        body = parse_qs(request.content.decode())
        assert body["text"] == ["你好\n🧵"]
        assert body["auto_publish_text"] == ["true"]
        return httpx.Response(200, json={"id": "published"})
    client = ThreadsClient("test", httpx.MockTransport(handler))
    try:
        assert await client.publish("你好\n🧵") == "published"
        with pytest.raises(APIError):
            await client.publish("  ")
    finally:
        await client.close()


def test_terminal_control_characters_removed():
    assert "\x1b" not in plain("hello\x1b[31m")
    assert plain("中文\n🧵\t") == "中文\n🧵\t"


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": ["bad"]},
                                      {"data": [], "paging": {"cursors": None}}])
async def test_bad_post_response_becomes_actionable_error(payload):
    client = ThreadsClient("secret", httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(APIError):
            await client.posts()
    finally:
        await client.close()


async def test_wrong_token_profile_shape():
    client = ThreadsClient("secret", httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "123"})))
    try:
        with pytest.raises(APIError, match="User Access Token"):
            await client.me()
    finally:
        await client.close()


async def test_keyword_search_request_and_local_only_pagination():
    def handler(request):
        assert request.url.path == "/keyword_search"
        assert request.url.params["q"] == "比特幣 貓"
        assert request.url.params["search_type"] == "TOP"
        assert "username" not in request.url.params
        assert "after" not in request.url.params
        return httpx.Response(200, json={"data": [{"id": "1", "text": "中文"}],
                                        "paging": {"next": "https://example.com", "cursors": {"after": "x"}}})
    client = ThreadsClient("test", httpx.MockTransport(handler))
    try:
        result = await client.search("比特幣 貓")
        assert len(result.posts) == 1
        assert result.after is None
        with pytest.raises(APIError):
            await client.search(" ")
    finally:
        await client.close()


async def test_keyword_permission_error_names_correct_scope():
    client = ThreadsClient("secret", httpx.MockTransport(lambda r: httpx.Response(403, json={"error": {"code": 10}})))
    try:
        with pytest.raises(APIError, match="threads_keyword_search") as error:
            await client.search("貓")
        assert "threads_profile_discovery" not in str(error.value)
    finally:
        await client.close()
