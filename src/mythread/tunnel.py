"""Ephemeral HTTPS OAuth callback via Cloudflare Quick Tunnel.

Only fixed callback pages are exposed, never local files or credentials.
"""
import asyncio
import contextlib
import queue
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .api import APIError
from .auth import callback_code

READY = b"mythread-oauth-callback-ready"


def tunnel_url_from_line(line):
    match = re.search(rb"https://([a-z0-9-]+)\.trycloudflare\.com", line)
    if match and match[1] not in (b"api", b"www"):
        return match.group().decode()
    return None


class CallbackServer:
    def __init__(self, port=0):
        self.redirect = ""
        self.state = ""
        self.result = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.received = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Do not log query strings containing OAuth codes.

            def reply(self, status, body, content_type="text/html; charset=utf-8"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path == "/health" and not parsed.query:
                    self.reply(200, READY, "text/plain")
                    return
                if parsed.path != "/callback":
                    self.reply(404, b"Not found")
                    return
                if not parsed.query:
                    self.reply(200, "<meta charset='utf-8'><h1>myThread 登入接收頁</h1><p>請回到 Terminal 繼續登入。</p>".encode())
                    return
                if not owner.state:
                    self.reply(409, b"No login in progress. Return to the terminal.")
                    return
                try:
                    code = callback_code(owner.redirect + "?" + parsed.query, owner.redirect, owner.state)
                except APIError:
                    # Invalid callbacks cannot consume the active login attempt.
                    self.reply(400, "<meta charset='utf-8'><h1>授權未完成或驗證失敗</h1><p>請回 Terminal 取消後重新登入。</p>".encode())
                    return
                with owner.lock:
                    if owner.received:
                        self.reply(409, b"Callback already received.")
                        return
                    owner.result.put_nowait(code)
                    owner.received = True
                self.reply(200, "<meta charset='utf-8'><h1>已收到授權回應</h1><p>請回 Terminal 查看登入結果。現在可關閉此頁。</p>".encode())

        self.http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.http.daemon_threads = True
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)

    async def wait_code(self, timeout=300):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            try:
                return self.result.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
        raise APIError("等待授權超過 5 分鐘，請重新執行登入。")


def find_cloudflared():
    installed = shutil.which("cloudflared")
    local = Path(__file__).resolve().parents[2] / ".tools" / "cloudflared.exe"
    if installed:
        return installed
    if local.is_file():
        return str(local)
    raise APIError("找不到 cloudflared；請執行 .\\.venv\\Scripts\\python.exe scripts/install_cloudflared.py。")


@contextlib.asynccontextmanager
async def quick_tunnel():
    executable = find_cloudflared()
    server = CallbackServer()
    server.start()
    process = None
    drain = None
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        process = await asyncio.create_subprocess_exec(
            executable, "tunnel", "--no-autoupdate", "--url",
            f"http://127.0.0.1:{server.http.server_port}", "--protocol", "http2",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, creationflags=flags,
        )

        async def find_url():
            while line := await process.stdout.readline():
                if b"certificate signed by unknown authority" in line:
                    raise APIError("Cloudflare HTTPS 憑證驗證失敗；可改用 login --local-https。")
                url = tunnel_url_from_line(line)
                if url:
                    return url
            raise APIError("臨時 HTTPS 連線未能啟動；請檢查網路或 cloudflared 設定。")

        try:
            base = await asyncio.wait_for(find_url(), timeout=60)
        except asyncio.TimeoutError as exc:
            raise APIError("建立 HTTPS 網址逾時，請稍後重試。") from exc

        async def discard_logs():
            while await process.stdout.readline():
                pass
        drain = asyncio.create_task(discard_logs())
        server.redirect = base + "/callback"
        yield server
    finally:
        if process and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if drain:
            drain.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drain
        server.close()


@contextlib.asynccontextmanager
async def local_https():
    import ssl
    directory = Path(__file__).resolve().parents[2] / ".tools"
    cert, key = directory / "callback-cert.pem", directory / "callback-key.pem"
    if not cert.is_file() or not key.is_file():
        raise APIError("請先以系統管理員 PowerShell 執行 scripts/setup_local_https.ps1。")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(str(cert), str(key))
        server = CallbackServer(port=8765)
    except (OSError, ssl.SSLError) as exc:
        raise APIError("無法啟動本機 HTTPS；請確認憑證已建立且 8765 連接埠未被占用。") from exc
    server.http.socket = context.wrap_socket(server.http.socket, server_side=True)
    server.redirect = "https://threads-sample.meta:8765/callback"
    server.start()
    try:
        yield server
    finally:
        server.close()
