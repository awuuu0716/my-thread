import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

from .api import APIError, ThreadsClient

SCOPES = ["threads_basic", "threads_content_publish"]


def validate_redirect(redirect: str):
    value = urlsplit(redirect)
    if value.scheme != "https" or not value.hostname or value.query or value.fragment or value.username or value.password:
        raise APIError("Callback 必須是已在 Meta 登記的 HTTPS 網址，不含 query、fragment 或帳密。")


def authorization_url(app_id: str, redirect: str, discovery=False, search=False):
    validate_redirect(redirect)
    state = secrets.token_urlsafe(32)
    scopes = SCOPES + (["threads_profile_discovery"] if discovery else [])
    if search:
        scopes.append("threads_keyword_search")
    url = "https://threads.net/oauth/authorize?" + urlencode({
        "client_id": app_id, "redirect_uri": redirect, "scope": ",".join(scopes),
        "response_type": "code", "state": state,
    })
    return url, state


def callback_code(callback: str, redirect: str, state: str):
    expected, actual = urlsplit(redirect), urlsplit(callback.strip())
    if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path):
        raise APIError("Callback 網址與設定不一致，已取消登入。")
    query = parse_qs(actual.query)
    states = query.get("state", [])
    if len(states) != 1 or not secrets.compare_digest(states[0], state):
        raise APIError("OAuth state 驗證失敗，已取消登入。請重新執行 login。")
    if "error" in query:
        raise APIError("授權未完成或已被取消。")
    codes = query.get("code", [])
    if len(codes) != 1 or not codes[0]:
        raise APIError("Callback 缺少授權碼。")
    return codes[0]


async def exchange(app_id, secret, redirect, code):
    client = ThreadsClient()
    try:
        short = await client.request("POST", "/oauth/access_token", data={
            "client_id": app_id, "client_secret": secret, "redirect_uri": redirect,
            "code": code, "grant_type": "authorization_code",
        })
        result = await client.request("GET", "/access_token", params={
            "grant_type": "th_exchange_token", "client_secret": secret,
            "access_token": short["access_token"],
        })
        return result
    finally:
        await client.close()


async def refresh(token):
    client = ThreadsClient(token)
    try:
        return await client.request("GET", "/refresh_access_token", params={"grant_type": "th_refresh_token"})
    finally:
        await client.close()
