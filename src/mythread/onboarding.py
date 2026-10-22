"""First-run guidance and read-only connectivity checks."""

import time
from datetime import datetime, timezone

from .api import APIError, ThreadsClient, plain
from .storage import StorageError

SETUP_GUIDE = """myThread：第一次連接自己的 Threads 帳號

1. 開啟 Meta 開發者控制台：https://developers.facebook.com/apps/
   建立 App，選擇 Access the Threads API（Threads 使用案例）。
   若尚未有開發者帳號，先完成 Meta 要求的註冊流程。

2. 在 Threads 使用案例的設定中，加入自己的 Threads 測試帳號。
   到該 Threads 帳號的「網站權限／邀請」接受邀請。
   控制台選單可能調整，請以目前顯示的 Threads Tester 設定為準。

3. 設定需要的權限：
   threads_basic              讀取自己的帳號和文章
   threads_content_publish    發布文字
   threads_profile_discovery  讀取其他公開帳號（選用）
   threads_keyword_search     關鍵字搜尋（搜尋推薦需要）

4. 在 Threads 設定尋找 User Token Generator，為測試帳號產生
   Threads User Access Token。若控制台沒有提供，改參考官方授權流程。
   不要拿 App Access Token、App ID 或 App Secret 當成 User Token。

5. 回到本專案的 PowerShell，依序執行：
   .\\.venv\\Scripts\\mythread.exe login --token
   .\\.venv\\Scripts\\mythread.exe doctor
   .\\.venv\\Scripts\\mythread.exe

   Token 僅貼入 login 的隱藏輸入，存入系統憑證庫。
   此方式不需要先執行 configure 或架設 callback 網站。

要測試其他公開帳號：
   .\\.venv\\Scripts\\mythread.exe doctor --profile threads

doctor 只讀取帳號與文章，不發文。發文請在介面預覽後確認。
私人帳號或權限未開放時，公開帳號讀取可能無法使用。

官方入口：https://developers.facebook.com/docs/threads/get-started
Meta 官方範例：https://www.postman.com/meta/threads/collection/dht3nzz/threads-api
"""


async def diagnose(store, profile="", client_factory=ThreadsClient, keyword=""):
    """Return allowlisted summaries only: no credentials, article text or raw API data."""
    checks = []

    def add(name, status, message):
        checks.append({"check": name, "status": status, "message": plain(message)})

    def report():
        return {"ok": not any(c["status"] == "fail" for c in checks), "checks": checks}

    try:
        record = store.credential()
    except StorageError:
        add("credential_store", "fail", "無法讀取系統憑證庫，請確認 Windows 憑證管理員可用。")
        return report()
    add("credential_store", "pass", "系統憑證庫可讀取。")
    if not record.get("access_token"):
        add("token", "fail", "尚未登入。先執行 mythread setup，再執行 mythread login --token。")
        return report()
    add("token", "pass", "已儲存 Token（不顯示內容）。")
    expires_at = record.get("expires_at")
    if expires_at is None:
        add("expiry", "info", "匯入 Token 的到期時間未知，將以 API 連線確認。")
    elif expires_at <= time.time():
        add("expiry", "fail", "Token 已過期，請重新登入。")
        return report()
    else:
        expiry = datetime.fromtimestamp(expires_at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        add("expiry", "pass", f"本機記錄到期時間：{expiry}。")

    client = client_factory(record["access_token"])
    try:
        try:
            user = await client.me()
        except APIError as exc:
            add("account", "fail", str(exc))
            return report()
        add("account", "pass", f"目前連線帳號：@{user['username']}。")
        try:
            page = await client.posts()
        except APIError as exc:
            add("own_posts", "fail", str(exc))
        else:
            add("own_posts", "pass", f"成功讀取第一頁，共 {len(page.posts)} 篇；空列表也代表讀取成功。")
        if profile:
            try:
                page = await client.posts(profile)
            except APIError as exc:
                add("public_posts", "fail", str(exc))
            else:
                add("public_posts", "pass", f"成功讀取 @{profile.lstrip('@')}，第一頁共 {len(page.posts)} 篇。")
        else:
            add("public_posts", "skip", "未測試；可使用 doctor --profile threads 檢查公開帳號讀取。")
        if keyword:
            try:
                page = await client.search(keyword)
            except APIError as exc:
                add("keyword_search", "fail", str(exc))
            else:
                add("keyword_search", "pass", f"搜尋請求成功，取得 {len(page.posts)} 篇；不代表全站搜尋權限已獲核准。")
                if not page.posts or all(p.get("username") == user["username"] for p in page.posts):
                    add("search_scope", "info", "結果為空或僅有自己的文章；請確認 threads_keyword_search 的審查狀態與搜尋範圍。")
        add("publishing", "skip", "未驗證發文權限或實際發文；請在介面預覽並確認後測試。")
    finally:
        await client.close()
    return report()
