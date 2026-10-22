from urllib.parse import parse_qs, urlsplit

import pytest

from mythread.api import APIError
from mythread.auth import authorization_url, callback_code, validate_redirect


def test_oauth_minimal_scopes_and_discovery_opt_in():
    url, state = authorization_url("123", "https://localhost/callback")
    query = parse_qs(urlsplit(url).query)
    assert query["state"] == [state]
    assert query["scope"] == ["threads_basic,threads_content_publish"]
    url2, state2 = authorization_url("123", "https://localhost/callback", True)
    assert "threads_profile_discovery" in url2
    assert state != state2


def test_valid_callback():
    assert callback_code("https://localhost/callback?code=abc&state=xyz#_", "https://localhost/callback", "xyz") == "abc"


def test_search_scope_is_opt_in_and_independent_of_discovery():
    url, _ = authorization_url("123", "https://localhost/callback", search=True)
    scopes = parse_qs(urlsplit(url).query)["scope"][0].split(",")
    assert "threads_keyword_search" in scopes
    assert "threads_profile_discovery" not in scopes


@pytest.mark.parametrize("callback", [
    "https://localhost/callback?code=abc&state=wrong",
    "https://localhost/callback?code=abc",
    "https://evil.invalid/callback?code=abc&state=xyz",
    "https://localhost/other?code=abc&state=xyz",
    "https://localhost/callback?code=abc&state=xyz&state=xyz",
    "https://localhost/callback?error=access_denied&state=xyz",
])
def test_reject_invalid_callbacks(callback):
    with pytest.raises(APIError):
        callback_code(callback, "https://localhost/callback", "xyz")


@pytest.mark.parametrize("url", ["http://localhost/callback", "https://example.com/cb?x=1", "https://user:pass@example.com/cb"])
def test_redirect_validation(url):
    with pytest.raises(APIError):
        validate_redirect(url)
