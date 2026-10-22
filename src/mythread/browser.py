"""Read-only DOM bridge. Never inspect network responses or browser credentials."""
import asyncio
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_dir

from .text import plain
from .runtime import configure_browser_runtime


def browser_open_error(exc):
    """Map diagnostics to safe guidance without displaying browser logs or URLs."""
    detail = str(exc).lower()
    if any(term in detail for term in ('processsingleton', 'singletonlock', 'profile appears to be in use', 'user data directory is already in use')):
        return '瀏覽器設定檔使用中：請先關閉另一個 myThread APP（包含背景執行的版本），再點「登入視窗」重試。'
    if 'executable doesn' in detail or 'executable not found' in detail:
        return '找不到 Chromium：原始碼版請執行 .\\.venv\\Scripts\\python.exe -m playwright install chromium；可攜版請完整解壓縮 ZIP。'
    if 'timeout' in detail or 'net::' in detail:
        return '瀏覽器開啟網站失敗或逾時：請檢查網路，再點「登入視窗」重試。'
    return '瀏覽器啟動失敗：請先關閉其他 myThread APP 再重試；原始碼版請確認已安裝對應的 Chromium，可攜版請完整解壓縮。'


SCROLL = r"""(reset = false) => {
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
 target.scrollBy({top: reset ? -target.scrollHeight : Math.max(200, target.clientHeight * .8), behavior: 'instant'});
 return target.scrollTop > before;
}"""


# Keep DOM assumptions in one place; unknown layouts fail closed, not as empty feeds.
SNAPSHOT = r"""(options = {}) => {
 options = options || {};
 const visible = e => !!(e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
 const boundary = options.replies ? [...document.querySelectorAll('h1,h2,h3,[role="heading"]')].find(e =>
   visible(e) && /推薦|相關貼文|更多貼文|suggested|recommended|related posts|more posts/i.test(e.innerText)) : null;
 const main = [...document.querySelectorAll('main, [role="main"]')].find(visible);
 const allLinks = [...document.querySelectorAll('a[href*="/post/"]')].filter(visible);
 const links = allLinks.filter(e =>
   (!options.replies || (main ? main.contains(e) : !e.closest('nav, aside, [role="navigation"]'))) &&
   (!boundary || !(boundary.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)));
 const postId = e => new URL(e.href).pathname.match(/\/post\/([A-Za-z0-9_-]+)\/?$/)?.[1];
 // The original post can have an unsupported body (e.g. a quote), but its
 // visible permalink still establishes ordering without inventing its text.
 const anchor = options.parent_id ? links.find(e => postId(e) === options.parent_id) : null;
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
   if (anchor && (postId(link) === options.parent_id ||
       !(anchor.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING))) continue;
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
 return {rows, candidates: links.length, anchor_found: !!anchor,
   diagnostics: {visible_links: allLinks.length, scoped_links: links.length,
     main: !!main, anchor: !!anchor, cards: rows.length},
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
        return BrowserBatch("login", message="尚未登入或需要驗證：請在專用瀏覽器手動完成，再按重新整理。")
    posts = extract_posts(snapshot.get("rows", []))
    if posts:
        return BrowserBatch("ready", posts)
    if snapshot.get("loading"):
        return BrowserBatch("loading", message="網頁仍在載入，稍後按重新整理。")
    if snapshot.get("empty") and not snapshot.get("candidates"):
        return BrowserBatch("empty", message="網頁顯示空結果。")
    return BrowserBatch("error", message="無法辨識文章：可能是驗證畫面或網站版面變更，請查看瀏覽器。")


class BrowserSource:
    def __init__(self, *, headless=True):
        self.headless = headless
        self.profile = Path(user_data_dir("mythread-browser", appauthor=False)) / "profile"
        self.runtime = self.context = self.page = None
        self.posts = {}
        self.lock = asyncio.Lock()
        self.replies = None

    async def open_replies(self, post):
        """Separate tab preserves the home feed's DOM and scroll position."""
        validated = extract_posts([post])
        if not validated or not self.context:
            return BrowserBatch('error', message='無法開啟留言：請先開啟瀏覽器並確認文章連結。')
        await self.close_replies()
        replies = self.replies = ReplySource(validated[0]['id'])
        try:
            replies.page = await self.context.new_page()
            if replies.stopped:
                await replies.page.close()
                return BrowserBatch('closed', message='已停止開啟留言。')
            await replies.page.goto(validated[0]['permalink'], wait_until='domcontentloaded', timeout=30000)
            return await replies.read()
        except asyncio.CancelledError:
            if self.replies is replies:
                await self.close_replies()
            raise
        except Exception:
            if self.replies is replies:
                await self.close_replies()
            return BrowserBatch('error', message='留言頁導覽失敗或逾時；已關閉未完成分頁，請按重新整理重試。')

    async def close_replies(self):
        replies, self.replies = self.replies, None
        if replies:
            replies.stopped = True
            if replies.page and not replies.page.is_closed():
                await replies.page.close()

    async def switch_mode(self, headless):
        """Restart only the owned context; leave authentication inside its profile."""
        async with self.lock:
            if self.headless == headless and self.page and not self.page.is_closed():
                await self.open()
                return
            await self.close()
            self.posts.clear()
            self.headless = headless
            await self.open()

    async def recover(self):
        """Recover a closed browser headlessly using its existing login profile."""
        async with self.lock:
            if not self.page or self.page.is_closed():
                self.posts.clear()
                self.headless = True
            await self.open()

    async def relogin(self):
        """Discard only this app's dedicated profile after releasing Chromium."""
        async with self.lock:
            profile = self.profile.absolute()
            # Never follow a redirected profile directory when removing data.
            if profile.name != 'profile' or profile.resolve() != profile:
                raise RuntimeError('Unsafe browser profile path')
            await self.close()
            self.posts.clear()
            if profile.exists():
                shutil.rmtree(profile)
            self.headless = False
            await self.open()

    async def open(self, *, start_url='https://www.threads.com/'):
        if self.page and not self.page.is_closed():
            if not self.headless:
                await self.page.bring_to_front()
            return
        await self.close()
        configure_browser_runtime()
        from playwright.async_api import async_playwright
        self.profile.mkdir(parents=True, exist_ok=True)
        try:
            self.runtime = await async_playwright().start()
            self.context = await self.runtime.chromium.launch_persistent_context(
                self.profile, headless=self.headless, channel='chromium',
                viewport={'width': 1280, 'height': 900}, accept_downloads=False)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            await self.page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
        except BaseException:
            await self.close()
            raise

    async def read(self, next_batch=False, *, refresh=False):
        async with self.lock:
            if not self.page or self.page.is_closed():
                return BrowserBatch("closed", message="瀏覽器已關閉，請點「恢復讀取」重新開啟並讀取文章。")
            try:
                if urlsplit(self.page.url).hostname not in {"www.threads.com", "threads.com", "www.threads.net", "threads.net"}:
                    return BrowserBatch("login", message="請在瀏覽器完成登入／驗證並返回 Threads。")
                if refresh:
                    await self.page.reload(wait_until='domcontentloaded', timeout=10000)
                    await self.page.evaluate(SCROLL, True)
                    self.posts.clear()
                # Capture before scrolling so a virtual list cannot erase unseen rows.
                before = classify(await self.page.evaluate(SNAPSHOT))
                if refresh:
                    for _ in range(10):
                        if before.state not in {'loading', 'error'}:
                            break
                        await asyncio.sleep(.5)
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
            await self.close_replies()
            if self.context:
                await self.context.close()
        finally:
            self.context = self.page = None
            if self.runtime:
                await self.runtime.stop()
                self.runtime = None


class ReplySource:
    """Read public post cards in a thread; never infer reply counts or hierarchy."""
    def __init__(self, parent_id):
        self.parent_id = parent_id
        self.page = None
        self.posts = {}
        self.anchored = False
        self.stopped = False
        self.lock = asyncio.Lock()

    async def read(self, next_batch=False, *, refresh=False):
        async with self.lock:
            if not self.page or self.page.is_closed():
                return BrowserBatch('closed', message='留言分頁已關閉，請返回文章重新開啟。')
            try:
                current = extract_posts([{'permalink': self.page.url}])
                if '/login' in urlsplit(self.page.url).path:
                    self.posts.clear()
                    return BrowserBatch('login', message='請在專用瀏覽器完成登入，再返回文章重新開啟留言。')
                if not current or current[0]['id'] != self.parent_id:
                    return BrowserBatch('error', message='留言分頁已離開原文章；請返回後重新開啟留言。')
                if refresh:
                    await self.page.reload(wait_until='domcontentloaded', timeout=8000)
                    await self.page.evaluate(SCROLL, True)
                    self.posts.clear()
                    self.anchored = False
                baseline = set(self.posts)
                batch = None
                # Poll initial rendering; for more, capture before each incremental scroll.
                for step in range(7 if next_batch else 4):
                    if self.stopped:
                        return BrowserBatch('closed', message='已停止留言讀取。')
                    snapshot = await self.page.evaluate(SNAPSHOT, {'replies': True, 'parent_id': self.parent_id})
                    if self.stopped:
                        return BrowserBatch('closed', message='已停止留言讀取。')
                    batch = classify(snapshot)
                    if batch.state == 'login':
                        self.posts.clear()
                        return batch
                    cards = batch.posts
                    ids = [p['id'] for p in cards]
                    if snapshot.get('anchor_found'):
                        self.anchored = True
                    elif self.parent_id in ids:
                        self.anchored = True
                        cards = cards[ids.index(self.parent_id) + 1:]
                    elif not self.anchored:
                        cards = []
                    for card in cards:
                        if card['id'] != self.parent_id:
                            self.posts[card['id']] = card
                    self.posts = dict(list(self.posts.items())[-2000:])
                    if set(self.posts) - baseline:
                        break
                    if next_batch and step < 6:
                        await self.page.evaluate(SCROLL)
                    await asyncio.sleep(.5)
                if not self.anchored:
                    diagnostic = snapshot.get('diagnostics', {})
                    counts = ' · '.join(f'{key}={int(diagnostic.get(key, 0))}' for key in
                        ('visible_links', 'scoped_links', 'main', 'anchor', 'cards'))
                    return BrowserBatch('error', message='尚未辨識原文章，請確認瀏覽器已顯示文章並重試。DOM 診斷：' + counts)
                if not self.posts:
                    return BrowserBatch('loading' if batch.state == 'loading' else 'unconfirmed',
                        message='目前未擷取到留言；可能尚未載入、被折疊或版面無法辨識，不代表沒有留言。')
                return BrowserBatch('ready', list(self.posts.values()),
                    f'新增 {len(set(self.posts) - baseline)} 則 · 保留 {len(self.posts)} 則 · 僅列出頁面已載入的討論，不推定回覆層級')
            except Exception:
                return BrowserBatch('error', message='留言讀取失敗，請檢查瀏覽器後重試。')
