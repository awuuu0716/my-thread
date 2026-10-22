import argparse
import asyncio
import getpass
import json
import os
import sys
import time
import webbrowser

from .api import APIError, DemoClient, ThreadsClient, plain
from .auth import authorization_url, callback_code, exchange, refresh, validate_redirect
from .storage import Store, StorageError


def parser():
    root = argparse.ArgumentParser(description="myThread：純文字 Threads Terminal 用戶端")
    root.add_argument("--demo", action="store_true", help="啟動離線示範，不需 Meta 帳號")
    commands = root.add_subparsers(dest="command")
    commands.add_parser("setup", help="顯示第一次建立 Meta Threads App 與取得 Token 的步驟")
    doctor = commands.add_parser("doctor", help="唯讀檢查憑證、帳號與文章讀取，不發文")
    doctor.add_argument("--profile", default="", help="額外測試指定公開帳號，例如 threads")
    doctor.add_argument("--keyword", default="", help="額外測試關鍵字搜尋，例如 貓")
    doctor.add_argument("--json", action="store_true", help="輸出不含 Token 或文章內容的 JSON 報告")
    commands.add_parser("configure", help="設定自己的 Threads App ID 與 HTTPS callback")
    login = commands.add_parser("login", help="瀏覽器 OAuth 授權或安全匯入 Token")
    login.add_argument("--discovery", action="store_true", help="額外請求公開帳號閱讀權限")
    login.add_argument("--search", action="store_true", help="額外請求關鍵字搜尋權限")
    login.add_argument("--token", action="store_true", help="以隱藏輸入匯入已有的 User Access Token")
    login.add_argument("--tunnel", action="store_true", help="建立臨時 HTTPS callback，自動接收 OAuth 授權")
    login.add_argument("--local-https", action="store_true", help="使用本機 HTTPS callback，不需要外部 Tunnel")
    commands.add_parser("logout", help="清除本機 Token 與草稿（不撤銷 Meta 端授權）")
    commands.add_parser("status", help="檢查登入狀態")
    commands.add_parser("refresh", help="手動更新長效 Token")
    commands.add_parser("browse", help="開啟互動式閱讀介面")
    return root


async def check_token(token):
    client = ThreadsClient(token)
    try:
        return await client.me()
    finally:
        await client.close()


async def credentials(store):
    record = store.credential()
    if not record.get("access_token"):
        raise APIError("尚未登入。請執行 mythread login；或 mythread --demo 試用介面。")
    now = time.time()
    expiry = record.get("expires_at")
    if expiry and expiry <= now:
        raise APIError("Token 已過期，請執行 mythread login。")
    if record.get("long_lived") and expiry and expiry - now < 7 * 86400 and now - record["saved_at"] > 86400:
        updated = await refresh(record["access_token"])
        store.save_token(updated["access_token"], updated.get("expires_in"), True)
        return updated["access_token"]
    return record["access_token"]


async def run(args, store):
    if args.demo:
        from .tui import ThreadsApp
        # Demo drafts must not overwrite the real account's drafts.
        await ThreadsApp(DemoClient(), Store(store.directory / "demo"), demo=True).run_async()
    elif args.command == "setup":
        from .onboarding import SETUP_GUIDE
        print(SETUP_GUIDE)
    elif args.command == "doctor":
        from .onboarding import diagnose
        report = await diagnose(store, args.profile, keyword=args.keyword)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            labels = {"pass": "通過", "fail": "失敗", "info": "資訊", "skip": "未測"}
            for check in report["checks"]:
                print(f"[{labels[check['status']]}] {check['message']}")
        if not report["ok"]:
            raise SystemExit(1)
    elif args.command == "configure":
        app_id = input("Threads App ID: ").strip()
        if not app_id.isdigit():
            raise APIError("App ID 應為數字。")
        redirect = input("已在 Meta 登記的 HTTPS callback URL: ").strip()
        validate_redirect(redirect)
        store.write("config.json", {"app_id": app_id, "redirect_uri": redirect})
        print("設定已儲存。App Secret 將在登入時以隱藏輸入詢問，不會儲存。")
    elif args.command == "login":
        if args.tunnel or args.local_https:
            if args.token or (args.tunnel and args.local_https):
                raise APIError("--tunnel、--local-https 與 --token 請擇一使用。")
            await tunnel_login(args, store)
            return
        if args.token:
            token = getpass.getpass("Threads User Access Token（隱藏輸入）: ").strip()
            if not token:
                raise APIError("Token 不可空白。")
            profile = await check_token(token)
            store.logout()
            store.save_token(token)
            print(f"已登入 @{plain(profile['username'])}。匯入 Token 的到期日未知；失效時請重新登入。")
            return
        config = store.read("config.json")
        if not config.get("app_id") or not config.get("redirect_uri"):
            raise APIError("請先執行 mythread configure，或用 mythread login --token 匯入 Token。")
        secret = os.environ.get("THREADS_APP_SECRET") or getpass.getpass("Threads App Secret（不儲存）: ")
        if not secret.strip():
            raise APIError("App Secret 不可空白。")
        url, state = authorization_url(config["app_id"], config["redirect_uri"], args.discovery, args.search)
        print("請在瀏覽器授權。若未自動開啟，請開啟此網址：\n" + url)
        webbrowser.open(url)
        print("授權後複製瀏覽器完整 callback 網址，貼到下方。請勿把此網址分享給他人。")
        callback = getpass.getpass("Callback URL（隱藏輸入）: ")
        code = callback_code(callback, config["redirect_uri"], state)
        result = await exchange(config["app_id"], secret, config["redirect_uri"], code)
        profile = await check_token(result["access_token"])
        store.logout()
        store.save_token(result["access_token"], result.get("expires_in"), True)
        print(f"已登入 @{plain(profile['username'])}。執行 mythread 開始瀏覽。")
    elif args.command == "logout":
        store.logout()
        print("已移除本機 Token 與草稿。若要撤銷 App 授權，請到 Threads 的網站權限設定操作。")
    elif args.command == "refresh":
        record = store.credential()
        if not record.get("long_lived"):
            raise APIError("目前沒有由 OAuth 建立的長效 Token；請執行 mythread login。")
        if time.time() - record["saved_at"] < 86400:
            raise APIError("Token 建立或更新未滿 24 小時，請稍後再更新。")
        if record.get("expires_at", 0) <= time.time():
            raise APIError("Token 已過期，請重新登入。")
        result = await refresh(record["access_token"])
        store.save_token(result["access_token"], result.get("expires_in"), True)
        print("長效 Token 已更新。")
    else:
        if args.command == "status":
            token = await credentials(store)
            profile = await check_token(token)
            print(f"已連線：@{plain(profile['username'])}")
        else:
            from .tui import ThreadsApp
            message = ""
            try:
                token = await credentials(store)
            except (APIError, StorageError) as exc:
                client = None
                message = str(exc)
            else:
                client = ThreadsClient(token)
            app = ThreadsApp(client, store, startup_message=message)
            try:
                await app.run_async()
            finally:
                if app.client:
                    await app.client.close()


async def tunnel_login(args, store):
    from .tunnel import quick_tunnel, local_https
    config = store.read("config.json")
    app_id = config.get("app_id") or input("Threads App ID（不是一般 Facebook App ID）: ").strip()
    if not app_id.isdigit():
        raise APIError("Threads App ID 應為數字。")
    print("正在建立 HTTPS callback……", flush=True)
    manager = local_https if args.local_https else quick_tunnel
    async with manager() as server:
        print("\n請把以下網址加入 Meta 的 Threads OAuth 重新導向網址，並儲存：", flush=True)
        print(server.redirect, flush=True)
        print("保留此 Terminal；不需執行 configure。" + ("本機網址固定，下次可沿用。" if args.local_https else "這個網址只在本次登入期間有效。"), flush=True)
        input("Meta 後台儲存完成後，按 Enter 繼續：")
        secret = os.environ.get("THREADS_APP_SECRET") or getpass.getpass("Threads App Secret（隱藏輸入，不儲存）: ")
        if not secret.strip():
            raise APIError("App Secret 不可空白。")
        url, state = authorization_url(app_id, server.redirect, args.discovery, args.search)
        server.state = state
        print("\n請在瀏覽器完成授權；回應會自動接收，不必複製 callback 網址。\n" + url, flush=True)
        webbrowser.open(url)
        code = await server.wait_code()
        result = await exchange(app_id, secret, server.redirect, code)
        profile = await check_token(result["access_token"])
        store.save_token(result["access_token"], result.get("expires_in"), True)
        store.write("draft.json", {})
        store.write("feed-seen.json", {})
        # Retain App ID, not an expiring tunnel URL as a permanent callback setting.
        store.write("config.json", {**config, "app_id": app_id})
        print(f"已登入 @{plain(profile['username'])}。臨時 HTTPS 連線即將關閉。", flush=True)


def main():
    args = parser().parse_args()
    try:
        asyncio.run(run(args, Store()))
    except (APIError, StorageError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。", file=sys.stderr)
        raise SystemExit(130)
