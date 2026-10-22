"""Read-only DOM bridge. Never inspect network responses or browser credentials."""
import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_dir

from .api import plain


SCROLL = r"""() => {
 const links = [...document.querySelectorAll('a[href*="/post/"]')];
 const link = links.find(e => { const r = e.getBoundingClientRect();
   return r.width && r.height && r.bottom > 0 && r.top < innerHeight; }) || links[0];
 let target = document.scrollingElement;
 for (let p = link?.parentElement; p && p !== document.body; p = p.parentElement) {
   if (/(auto|scroll)/.test(getComputedStyle(p).overflowY) && p.scrollHeight > p.clientHeight + 2) {
     target = p; break;
   }
 }
 if (!target) return false;
 const before = target.scrollTop;
 target.scrollBy({top: Math.max(200, target.clientHeight * .8), behavior: 'instant'});
 return target.scrollTop > before;
}"""


# Keep DOM assumptions in one place; unknown layouts fail closed, not as empty feeds.
SNAPSHOT = r"""() => {
 const visible = e => !!(e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
 const links = [...document.querySelectorAll('a[href*="/post/"]')].filter(visible);
 const rows = [];
 const metadata = text => /^(?:\d+\s*(?:秒|分鐘|分鐘前|分|小時|天|週|周|個月|年|seconds?|minutes?|hours?|days?|weeks?|months?|years?|[smhdwy])(?:前| ago)?|剛剛|just now)$/i.test(text);
 const blocksIn = root => [...root.querySelectorAll('[dir="auto"]')].filter(e => {
   const text = e.innerText.trim();
   if (!visible(e) || !text || metadata(text) || e.querySelector('[dir="auto"]')) return false;
   // Only exclude controls inside the candidate, not an enclosing clickable card.
   for (let p = e; p && p !== root; p = p.parentElement) {
     if (p.matches('button, [role="button"], a, [role="link"], time')) return false;
   }
   const article = e.closest('article, [role="article"]');
   return !article || article === root;
 });
 for (const link of links) {
   let root = link.closest('article, [role="article"]');
   if (!root) {
     // Use the smallest ancestor containing both a permalink and text blocks.
     for (let p = link.parentElement; p && p !== document.body; p = p.parentElement) {
       const paths = new Set([...p.querySelectorAll('a[href*="/post/"]')].map(a => new URL(a.href).pathname));
       if (paths.size > 1) break;
       if (blocksIn(p).length && p.querySelector('a[href*="/@"]')) { root = p; break; }
     }
   }
   if (!root) continue;
   // Ambiguous quotes/threads require a dedicated adapter; do not merge authors.
   if (new Set([...root.querySelectorAll('a[href*="/post/"]')].map(a => new URL(a.href).pathname)).size > 1) continue;
   const blocks = blocksIn(root);
   const text = blocks.map(e => e.innerText.trim()).filter(Boolean).join('\n');
   // Avatars in a header are not evidence of a media-only post.
   if (text || root.querySelector('video, img[alt]:not([alt=""]):not([alt*="profile"]):not([alt*="大頭"])')) rows.push({permalink: link.href, text});
 }
 const signals = [...document.querySelectorAll('[role="status"], main h1, main h2')].filter(visible).map(e => e.innerText.trim());
 return {rows, candidates: links.length,
   login: !![...document.querySelectorAll('input[type="password"], a[href*="/login"]')].find(visible),
   loading: !![...document.querySelectorAll('[role="progressbar"], [aria-busy="true"]')].find(visible),
   empty: signals.some(s => /^(No posts yet|No results found|尚無貼文|沒有貼文|找不到結果)[。.!！]?$/.test(s))};
}"""


@dataclass
class BrowserBatch:
    state: str
    posts: list[dict] = field(default_factory=list)
    message: str = ""


def extract_posts(rows):
    """Validate public permalinks, discard query strings, normalize and deduplicate."""
    result = {}
    for row in rows:
        url = urlsplit(row.get("permalink", ""))
        if url.scheme != "https" or url.hostname not in {"www.threads.com", "threads.com", "www.threads.net", "threads.net"}:
            continue
        match = re.fullmatch(r"/@([\w.]+)/post/([A-Za-z0-9_-]+)/?", url.path)
        if not match:
            continue
        author, post_id = match.groups()
        result[post_id] = {"id": post_id, "username": author,
                           "text": plain(row.get("text", "")),
                           "permalink": f"https://www.threads.com/@{author}/post/{post_id}"}
    return list(result.values())


def classify(snapshot):
    if snapshot.get("login"):
        return BrowserBatch("login", message="尚未登入或需要驗證：請在專用瀏覽器手動完成，再按重新讀取。")
    posts = extract_posts(snapshot.get("rows", []))
    if posts:
        return BrowserBatch("ready", posts)
    if snapshot.get("loading"):
        return BrowserBatch("loading", message="網頁仍在載入，稍後按重新讀取。")
    if snapshot.get("empty") and not snapshot.get("candidates"):
        return BrowserBatch("empty", message="網頁顯示空結果。")
    return BrowserBatch("error", message="無法辨識文章：可能是驗證畫面或網站版面變更，請查看瀏覽器。")


class BrowserSource:
    def __init__(self):
        self.profile = Path(user_data_dir("mythread-browser", appauthor=False)) / "profile"
        self.runtime = self.context = self.page = None
        self.posts = {}
        self.lock = asyncio.Lock()

    async def open(self):
        if self.page and not self.page.is_closed():
            await self.page.bring_to_front()
            return
        await self.close()
        from playwright.async_api import async_playwright
        self.profile.mkdir(parents=True, exist_ok=True)
        self.runtime = await async_playwright().start()
        self.context = await self.runtime.chromium.launch_persistent_context(
            self.profile, headless=False, accept_downloads=False)
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto("https://www.threads.com/", wait_until="domcontentloaded", timeout=30000)

    async def read(self, next_batch=False):
        async with self.lock:
            if not self.page or self.page.is_closed():
                return BrowserBatch("closed", message="請先開啟瀏覽器。")
            try:
                if urlsplit(self.page.url).hostname not in {"www.threads.com", "threads.com", "www.threads.net", "threads.net"}:
                    return BrowserBatch("login", message="請在瀏覽器完成登入／驗證並返回 Threads。")
                # Capture before scrolling so a virtual list cannot erase unseen rows.
                before = classify(await self.page.evaluate(SNAPSHOT))
                if before.state == "login":
                    self.posts.clear()
                    return before
                collected = list(before.posts)
                if next_batch:
                    baseline = set(self.posts) | {p['id'] for p in before.posts}
                    for _ in range(6):
                        await self.page.evaluate(SCROLL)
                        found = False
                        for _ in range(4):
                            await asyncio.sleep(.25)
                            batch = classify(await self.page.evaluate(SNAPSHOT))
                            collected.extend(batch.posts)
                            if batch.state == "login":
                                self.posts.clear()
                                return batch
                            found = any(p['id'] not in baseline for p in batch.posts)
                            if found:
                                break
                        if found or batch.state in {"error", "empty"}:
                            break
                else:
                    batch = before
                new = sum(p["id"] not in self.posts for p in {p['id']: p for p in collected}.values())
                for post in collected:
                    self.posts[post["id"]] = post
                # Bound retained article text while keeping virtualized items across reads.
                self.posts = dict(list(self.posts.items())[-2000:])
                if batch.state != "ready":
                    return batch
                return BrowserBatch("ready", list(self.posts.values()), f"新增 {new} 篇 · 保留 {len(self.posts)} 篇" + (" · 尚無新文章，可稍後再試" if not new else ""))
            except Exception:
                return BrowserBatch("error", message="讀取失敗：請檢查瀏覽器與網路，再重試。")

    async def close(self):
        try:
            if self.context:
                await self.context.close()
        finally:
            self.context = self.page = None
            if self.runtime:
                await self.runtime.stop()
                self.runtime = None
