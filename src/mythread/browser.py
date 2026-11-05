"""Read-only DOM bridge. Never inspect network responses or browser credentials.

Data flow:  page --SNAPSHOT(js)--> snapshot dict --classify()--> BrowserBatch(posts via extract_posts)
Sources:    BrowserSource (home feed tab, owns Chromium)  ->  ReplySource (one comments tab)
Every public read returns a BrowserBatch and never raises (except CancelledError).
"""
import asyncio
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_dir

from .dom import SCROLL, SNAPSHOT
from .messages import Msg, browser_open_error, home_ready_text, reply_ready_text
from .model import (COUNT_PATTERN, HOME_URL, MAX_RETAINED_POSTS, THREADS_HOSTS,
                    BrowserBatch, Post, ProfileClearError, State)
from .runtime import configure_browser_runtime
from .text import plain

# SCROLL/SNAPSHOT/BrowserBatch/browser_open_error are re-exported for existing importers.
__all__ = ['BrowserBatch', 'BrowserSource', 'ReplySource', 'SCROLL', 'SNAPSHOT',
           'browser_open_error', 'classify', 'extract_posts']

# Timing knobs (seconds / counts). Tests patch asyncio.sleep, not these.
NAV_TIMEOUT_MS = 30000
HOME_RELOAD_TIMEOUT_MS = 10000
REPLY_RELOAD_TIMEOUT_MS = 8000
VIEWPORT = {'width': 1280, 'height': 900}
_PERMALINK_PATH = re.compile(r'/@([\w.]+)/post/([A-Za-z0-9_-]+)/?')
_COUNT = re.compile(COUNT_PATTERN, re.I)


def sandbox_enabled() -> bool:
    """Chromium's renderer sandbox; Playwright disables it unless asked.

    Opt-out exists only for Linux hosts that block unprivileged user namespaces.
    """
    return os.environ.get('MYTHREAD_DISABLE_SANDBOX') != '1'


def private_dir(path: Path) -> None:
    """Create the profile readable only by the current user (POSIX; Windows uses per-user AppData ACLs)."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'posix':
        os.chmod(path, 0o700)  # mkdir's mode is ignored for an existing directory


def _owned_profile(path: Path) -> bool:
    """Only a real (non-redirected) directory literally named `profile` may be removed."""
    return path.name == 'profile' and not path.is_symlink() and path.resolve() == path


def extract_posts(rows: list[dict]) -> list[Post]:
    """Validate public permalinks, discard query strings, normalize and deduplicate (last wins)."""
    result: dict[str, Post] = {}
    for row in rows:
        url = urlsplit(row.get('permalink', ''))
        if url.scheme != 'https' or url.hostname not in THREADS_HOSTS:
            continue
        match = _PERMALINK_PATH.fullmatch(url.path)
        if not match:
            continue
        author, post_id = match.groups()
        post: Post = {'id': post_id, 'username': author, 'text': plain(row.get('text', '')),
                      'permalink': f'https://www.threads.com/@{author}/post/{post_id}'}
        count = row.get('reply_count')
        if isinstance(count, (str, int)) and not isinstance(count, bool):
            count = str(count).strip()
            if _COUNT.fullmatch(count):
                post['reply_count'] = count
        result[post_id] = post
    return list(result.values())


def classify(snapshot: dict) -> BrowserBatch:
    """Turn one SNAPSHOT result into a batch. Order matters: login beats posts beats loading."""
    if snapshot.get('login'):
        return BrowserBatch(State.LOGIN, message=Msg.HOME_LOGIN)
    posts = extract_posts(snapshot.get('rows', []))
    if posts:
        return BrowserBatch(State.READY, posts)
    if snapshot.get('loading'):
        return BrowserBatch(State.LOADING, message=Msg.LOADING)
    if snapshot.get('empty') and not snapshot.get('candidates'):
        return BrowserBatch(State.EMPTY, message=Msg.EMPTY)
    return BrowserBatch(State.ERROR, message=Msg.UNRECOGNISED)


class _PageReader:
    """State shared by both sources: one page, a bounded ordered pool of posts, one lock."""
    def __init__(self):
        self.page = None
        self.posts: dict[str, Post] = {}
        self.lock = asyncio.Lock()

    def page_open(self) -> bool:
        return bool(self.page) and not self.page.is_closed()

    def remember(self, posts) -> None:
        for post in posts:
            self.posts[post['id']] = post
        # Bound retained text while keeping items a virtual list has already dropped.
        self.posts = dict(list(self.posts.items())[-MAX_RETAINED_POSTS:])


class BrowserSource(_PageReader):
    """Owns the Playwright runtime, the persistent profile and the home-feed page."""
    # Polling budgets: (attempts, seconds between attempts).
    REFRESH_SETTLE = (10, .5)    # after reload, wait while loading/error
    CLEAR_RETRIES = (4, .5)      # profile removal; Windows may hold locks briefly after close
    SCROLL_ROUNDS = 6            # scrolls per "next" request
    SCROLL_POLLS = (4, .25)      # snapshots after each scroll

    def __init__(self, *, headless=True):
        super().__init__()
        self.headless = headless
        self.profile = Path(user_data_dir('mythread-browser', appauthor=False)) / 'profile'
        self.runtime = self.context = None
        self.replies: ReplySource | None = None

    # ---- lifecycle -------------------------------------------------------
    async def open(self, *, start_url=HOME_URL):
        if self.page_open():
            if not self.headless:
                await self.page.bring_to_front()
            return
        await self.close()
        configure_browser_runtime()
        from playwright.async_api import async_playwright
        private_dir(self.profile)
        try:
            self.runtime = await async_playwright().start()
            self.context = await self.runtime.chromium.launch_persistent_context(
                self.profile, headless=self.headless, channel='chromium',
                chromium_sandbox=sandbox_enabled(), viewport=VIEWPORT, accept_downloads=False)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            await self.page.goto(start_url, wait_until='domcontentloaded', timeout=NAV_TIMEOUT_MS)
        except BaseException:
            await self.close()
            raise

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

    async def switch_mode(self, headless):
        """Restart only the owned context; leave authentication inside its profile."""
        async with self.lock:
            if self.headless == headless and self.page_open():
                await self.open()
                return
            await self.close()
            self.posts.clear()
            self.headless = headless
            await self.open()

    async def recover(self):
        """Recover a closed browser headlessly using its existing login profile."""
        async with self.lock:
            if not self.page_open():
                self.posts.clear()
                self.headless = True
            await self.open()

    async def relogin(self):
        """Discard only this app's dedicated profile after releasing Chromium."""
        async with self.lock:
            profile = self.profile.absolute()
            # Never follow a redirected profile directory when removing data.
            if not _owned_profile(profile):
                raise ProfileClearError('Unsafe browser profile path')
            await self.close()
            self.posts.clear()
            attempts, delay = self.CLEAR_RETRIES
            for _ in range(attempts):
                if not os.path.lexists(profile):
                    break
                # Re-check after every await: the path may have been swapped meanwhile.
                if not _owned_profile(profile):
                    raise ProfileClearError('Unsafe browser profile path')
                shutil.rmtree(profile, ignore_errors=True)
                if not os.path.lexists(profile):
                    break
                await asyncio.sleep(delay)
            else:
                # Partial removal can leave cookies behind; never report success.
                raise ProfileClearError('Profile still present')
            self.headless = False
            await self.open()

    # ---- replies tab -----------------------------------------------------
    async def open_replies(self, post) -> BrowserBatch:
        """Separate tab preserves the home feed's DOM and scroll position."""
        validated = extract_posts([post])
        if not validated or not self.context:
            return BrowserBatch(State.ERROR, message=Msg.REPLY_BAD_POST)
        await self.close_replies()
        replies = self.replies = ReplySource(validated[0]['id'])
        try:
            replies.page = await self.context.new_page()
            if replies.stopped:
                await replies.page.close()
                return BrowserBatch(State.CLOSED, message=Msg.REPLY_OPEN_STOPPED)
            await replies.page.goto(validated[0]['permalink'], wait_until='domcontentloaded',
                                    timeout=NAV_TIMEOUT_MS)
            return await replies.read()
        except asyncio.CancelledError:
            if self.replies is replies:
                await self.close_replies()
            raise
        except Exception:
            if self.replies is replies:
                await self.close_replies()
            return BrowserBatch(State.ERROR, message=Msg.REPLY_NAV_FAILED)

    async def close_replies(self):
        replies, self.replies = self.replies, None
        if replies:
            replies.stopped = True
            if replies.page and not replies.page.is_closed():
                await replies.page.close()

    # ---- reading ---------------------------------------------------------
    async def snapshot(self) -> BrowserBatch:
        return classify(await self.page.evaluate(SNAPSHOT))

    async def read(self, next_batch=False, *, refresh=False) -> BrowserBatch:
        """refresh: reload and replace the pool. next_batch: scroll until new posts appear."""
        async with self.lock:
            if not self.page_open():
                return BrowserBatch(State.CLOSED, message=Msg.HOME_CLOSED)
            try:
                return await self._read(next_batch, refresh)
            except Exception:
                return BrowserBatch(State.ERROR, message=Msg.HOME_READ_FAILED)

    async def _read(self, next_batch, refresh) -> BrowserBatch:
        if urlsplit(self.page.url).hostname not in THREADS_HOSTS:
            return BrowserBatch(State.LOGIN, message=Msg.HOME_OFF_SITE)
        if refresh:
            await self.page.reload(wait_until='domcontentloaded', timeout=HOME_RELOAD_TIMEOUT_MS)
            await self.page.evaluate(SCROLL, True)
            self.posts.clear()
        # Capture before scrolling so a virtual list cannot erase unseen rows.
        before = await self.snapshot()
        if refresh:
            attempts, delay = self.REFRESH_SETTLE
            for _ in range(attempts):
                if before.state not in {State.LOADING, State.ERROR}:
                    break
                await asyncio.sleep(delay)
                before = await self.snapshot()
        if before.state == State.LOGIN:
            self.posts.clear()
            return before
        collected = list(before.posts)
        batch = before
        if next_batch:
            batch = await self._scroll_for_new(before, collected)
            if batch.state == State.LOGIN:
                self.posts.clear()
                return batch
        new = sum(post['id'] not in self.posts for post in {p['id']: p for p in collected}.values())
        self.remember(collected)
        if batch.state != State.READY:
            return batch
        return BrowserBatch(State.READY, list(self.posts.values()), home_ready_text(new, len(self.posts)))

    async def _scroll_for_new(self, before, collected) -> BrowserBatch:
        """Scroll until a post outside the pool appears; appends every seen post to `collected`."""
        baseline = set(self.posts) | {p['id'] for p in before.posts}
        polls, delay = self.SCROLL_POLLS
        batch = before
        for _ in range(self.SCROLL_ROUNDS):
            await self.page.evaluate(SCROLL)
            found = False
            for _ in range(polls):
                await asyncio.sleep(delay)
                batch = await self.snapshot()
                collected.extend(batch.posts)
                if batch.state == State.LOGIN:
                    return batch
                found = any(p['id'] not in baseline for p in batch.posts)
                if found:
                    break
            if found or batch.state in {State.ERROR, State.EMPTY}:
                break
        return batch


class ReplySource(_PageReader):
    """Read public post cards in a thread; never infer reply counts or hierarchy."""
    POLL_DELAY = .5
    POLLS_FIRST, POLLS_MORE = 4, 7  # snapshot attempts per read (more = with scrolling)

    def __init__(self, parent_id):
        super().__init__()
        self.parent_id = parent_id
        self.anchored = False  # parent permalink seen at least once since last refresh
        self.stopped = False   # set by BrowserSource.close_replies; aborts polling

    async def read(self, next_batch=False, *, refresh=False) -> BrowserBatch:
        async with self.lock:
            if not self.page_open():
                return BrowserBatch(State.CLOSED, message=Msg.REPLY_CLOSED)
            try:
                return await self._read(next_batch, refresh)
            except Exception:
                return BrowserBatch(State.ERROR, message=Msg.REPLY_READ_FAILED)

    async def _read(self, next_batch, refresh) -> BrowserBatch:
        current = extract_posts([{'permalink': self.page.url}])
        if '/login' in urlsplit(self.page.url).path:
            self.posts.clear()
            return BrowserBatch(State.LOGIN, message=Msg.REPLY_LOGIN)
        if not current or current[0]['id'] != self.parent_id:
            return BrowserBatch(State.ERROR, message=Msg.REPLY_LEFT_POST)
        if refresh:
            await self.page.reload(wait_until='domcontentloaded', timeout=REPLY_RELOAD_TIMEOUT_MS)
            await self.page.evaluate(SCROLL, True)
            self.posts.clear()
            self.anchored = False
        baseline = set(self.posts)
        batch, snapshot = None, {}
        polls = self.POLLS_MORE if next_batch else self.POLLS_FIRST
        # Poll initial rendering; for more, capture before each incremental scroll.
        for step in range(polls):
            if self.stopped:
                return BrowserBatch(State.CLOSED, message=Msg.REPLY_STOPPED)
            snapshot = await self.page.evaluate(SNAPSHOT, {'replies': True, 'parent_id': self.parent_id})
            if self.stopped:
                return BrowserBatch(State.CLOSED, message=Msg.REPLY_STOPPED)
            batch = classify(snapshot)
            if batch.state == State.LOGIN:
                self.posts.clear()
                return batch
            self.remember(p for p in self._after_parent(snapshot, batch.posts) if p['id'] != self.parent_id)
            if set(self.posts) - baseline:
                break
            if next_batch and step < polls - 1:
                await self.page.evaluate(SCROLL)
            await asyncio.sleep(self.POLL_DELAY)
        if not self.anchored:
            diagnostic = snapshot.get('diagnostics', {})
            counts = ' · '.join(f'{key}={int(diagnostic.get(key, 0))}' for key in
                                ('visible_links', 'scoped_links', 'main', 'anchor', 'cards'))
            return BrowserBatch(State.ERROR, message=Msg.REPLY_NO_ANCHOR + Msg.DIAGNOSTICS + counts)
        if not self.posts:
            return BrowserBatch(State.LOADING if batch.state == State.LOADING else State.UNCONFIRMED,
                                message=Msg.REPLY_NONE_SEEN)
        return BrowserBatch(State.READY, list(self.posts.values()),
                            reply_ready_text(len(set(self.posts) - baseline), len(self.posts)))

    def _after_parent(self, snapshot, cards):
        """Only cards after the parent permalink are replies; before anchoring, none are."""
        ids = [p['id'] for p in cards]
        if snapshot.get('anchor_found'):
            self.anchored = True
        elif self.parent_id in ids:
            self.anchored = True
            return cards[ids.index(self.parent_id) + 1:]
        elif not self.anchored:
            return []
        return cards
