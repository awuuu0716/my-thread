import re
from dataclasses import dataclass

import httpx

BASE_URL = "https://graph.threads.net"
FIELDS = "id,username,text,media_type,timestamp,permalink"


class APIError(Exception):
    pass


class PublishUncertain(APIError):
    pass


def plain(value: str) -> str:
    # Do not let remote text inject terminal control sequences.
    return "".join(c for c in str(value) if c in "\n\t" or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


@dataclass
class Page:
    posts: list[dict]
    after: str | None = None


class ThreadsClient:
    def __init__(self, token: str = "", transport=None):
        self.http = httpx.AsyncClient(base_url=BASE_URL, timeout=25, transport=transport,
                                     headers={"Authorization": f"Bearer {token}"} if token else {})

    async def close(self):
        await self.http.aclose()

    async def request(self, method: str, path: str, params=None, data=None, publishing=False):
        try:
            response = await self.http.request(method, path, params=params, data=data)
        except httpx.RequestError as exc:
            if publishing:
                raise PublishUncertain("發布結果不明：請先更新「我的文章」或檢查 Threads，再決定是否重送。") from exc
            raise APIError("無法連線至 Threads，請檢查網路後重試。") from exc
        if publishing and response.status_code >= 500:
            raise PublishUncertain("Meta 伺服器錯誤，發布結果不明；請先確認文章是否已發布。")
        try:
            result = response.json()
        except ValueError as exc:
            error = PublishUncertain if publishing else APIError
            raise error("API 回傳無法解析；若正在發布，請先檢查文章是否已出現。") from exc
        if not isinstance(result, dict):
            error = PublishUncertain if publishing else APIError
            raise error("API 回傳格式不正確；若正在發布，請先檢查文章是否已出現。")
        if response.is_error or "error" in result:
            detail = result.get("error", {})
            code = detail.get("code") if isinstance(detail, dict) else None
            code = code if isinstance(code, int) else None
            if response.status_code == 401 or code == 190:
                raise APIError("授權已失效，請點「帳號」更新 Token，或執行 mythread login。")
            if response.status_code == 429 or code in (4, 17, 32, 613):
                raise APIError("已達 API 使用額度，請稍後再試。")
            if response.status_code == 403 or code in (10, 200):
                permission = {"/keyword_search": "threads_keyword_search", "/profile_posts": "threads_profile_discovery",
                              "/me/threads": "threads_content_publish" if publishing else "threads_basic"}.get(path, "threads_basic")
                raise APIError(f"權限不足；此功能需要 {permission}，請確認 App 權限／審查狀態並重新授權。")
            # Avoid logging remote messages, URLs or bodies that might contain credentials.
            raise APIError(f"Threads 拒絕請求（HTTP {response.status_code}，code={code}）。請檢查權限與輸入。")
        return result

    async def me(self):
        result = await self.request("GET", "/me", params={"fields": "id,username"})
        if not all(isinstance(result.get(key), str) and result[key] for key in ("id", "username")):
            raise APIError("帳號回應缺少 id 或 username；請確認使用 Threads User Access Token。")
        return result

    async def posts(self, username="", after=None):
        params = {"fields": FIELDS, "limit": "20"}
        if username:
            username = username.lstrip("@").strip()
            if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
                raise APIError("請輸入完整帳號名稱，例如 threads，不要貼網址。")
            params["username"] = username
        if after:
            params["after"] = after
        result = await self.request("GET", "/profile_posts" if username else "/me/threads", params=params)
        return self.parse_page(result)

    async def search(self, keyword):
        keyword = keyword.strip()
        if not keyword or len(keyword) > 50:
            raise APIError("搜尋關鍵字需為 1 至 50 字。")
        result = await self.request("GET", "/keyword_search", params={
            "q": keyword, "search_type": "TOP", "fields": FIELDS, "limit": "20",
        })
        page = self.parse_page(result)
        # Search cursor support is not confirmed; paginate only the local result pool.
        return Page(page.posts)

    @staticmethod
    def parse_page(result):
        posts = result.get("data")
        paging = result.get("paging") or {}
        if not isinstance(posts, list) or not all(isinstance(post, dict) for post in posts):
            raise APIError("文章列表回應格式不正確。")
        if not isinstance(paging, dict) or not isinstance(paging.get("cursors", {}), dict):
            raise APIError("文章分頁回應格式不正確。")
        # A cursor alone does not guarantee another page. Never follow server-provided URLs.
        cursor = paging.get("cursors", {}).get("after") if paging.get("next") else None
        if cursor is not None and not isinstance(cursor, str):
            raise APIError("文章分頁游標格式不正確。")
        return Page(posts, cursor)

    async def publish(self, text):
        if not text.strip():
            raise APIError("文章不能是空白。")
        result = await self.request("POST", "/me/threads", data={
            "media_type": "TEXT", "text": text, "auto_publish_text": "true"
        }, publishing=True)
        if not result.get("id"):
            raise PublishUncertain("未收到文章 ID；請先檢查文章是否已發布。")
        return result["id"]


class DemoClient:
    async def close(self):
        pass

    async def me(self):
        return {"id": "demo", "username": "demo"}

    async def posts(self, username="", after=None):
        offset = 3 if after else 0
        samples = ["歡迎使用 myThread！\n這是離線示範，不會連線或發布到 Meta。",
                   "用方向鍵選文章、Enter 開啟全文。\nTab 可切換按鈕與欄位。",
                   "附圖貼文也只呈現文字。", "這是下一頁。\n中文、emoji 🧵 與多行文字都可閱讀。"]
        return Page([{"id": f"demo-{username or 'demo'}-{i}", "username": username or "demo", "text": text,
                      "timestamp": "2026-10-22T08:00:00+0000", "media_type": "IMAGE" if i == 2 else "TEXT_POST",
                      "permalink": ""} for i, text in enumerate(samples[offset:offset+3], offset)],
                    None if after else "demo-next")

    async def publish(self, text):
        raise APIError("離線示範模式不發布文章。")

    async def search(self, keyword):
        return Page([{"id": f"search-{keyword}-{i}", "username": f"demo_author_{i}",
                      "text": f"關於「{keyword}」的離線搜尋示範 {i + 1}。\n這不是實際 Threads 文章。",
                      "timestamp": "2026-10-22T08:00:00+0000", "media_type": "TEXT_POST", "permalink": ""}
                     for i in range(12)])
