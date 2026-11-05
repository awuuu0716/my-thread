"""Reusable UI building blocks shared by the home app and sub-screens.

Extension points:
- FeedOwner: implement on any App/Screen that hosts a BridgeList.
- ButtonActions: declare BUTTON_ACTIONS = {'button-id': 'method_name'} instead of if/elif chains.
- call_with_deadline: run a browser coroutine with a timeout that cleans up before cancelling.
"""
import asyncio
import time
from typing import Awaitable, Callable, ClassVar

from rich.text import Text
from textual.widgets import Label, ListItem, ListView, Static

from .text import post_preview

APP_TITLE = 'myThread · 唯讀瀏覽器版'


class FeedOwner:
    """Contract between a BridgeList and the App/Screen that hosts it.

    Subclasses set these in __init__ and implement request_more(). BridgeList
    finds its owner via BridgeList.owner (the screen if it is a FeedOwner, else the app).
    """
    PREVIEW_LINES: ClassVar[int | None] = None  # None = full text in list rows
    AUTO_MORE_COOLDOWN: ClassVar[float] = 2.0   # seconds between automatic "load more"
    posts_data: list
    busy: bool = False      # an operation is running; list must not be rebuilt
    leaving: bool = False   # owner is being dismissed; ignore late results
    next_auto_at: float = 0.0

    def request_more(self) -> None:
        raise NotImplementedError

    def start_cooldown(self) -> None:
        self.next_auto_at = time.monotonic() + self.AUTO_MORE_COOLDOWN

    def cooling_down(self) -> bool:
        return time.monotonic() < self.next_auto_at


class ButtonActions:
    """Map Button ids to zero-argument methods on self; unknown ids are ignored."""
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {}

    def on_button_pressed(self, event) -> None:
        # prevent_default stops Textual from also running base-class handlers.
        event.prevent_default()
        event.stop()
        name = self.BUTTON_ACTIONS.get(event.button.id)
        if name:
            getattr(self, name)()


def _consume_exception(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


async def call_with_deadline(operation: Awaitable, timeout: float, *,
                             cleanup: Callable[[], Awaitable], cleanup_timeout: float):
    """Await `operation`; on timeout run `cleanup` (e.g. close the owned browser/tab)
    first, then cancel. Closing interrupts Playwright cleanly, whereas cancelling a
    protocol call halfway leaves it in an unknown state. Re-raises TimeoutError."""
    task = asyncio.ensure_future(operation)
    task.add_done_callback(_consume_exception)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except TimeoutError:
        try:
            await asyncio.wait_for(cleanup(), cleanup_timeout)
        except Exception:
            pass  # a failed shutdown must not leave the operation running
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        raise


class BrowserTitle(Static):
    """Single-node title: no delayed HeaderTitle queries during screen teardown."""
    DEFAULT_CSS = '''
    BrowserTitle { dock: top; height: 1; width: 1fr;
        background: $primary-background; text-align: center; text-style: bold; }
    '''

    def __init__(self):
        super().__init__(APP_TITLE, markup=False)


class BridgeList(ListView):
    """Post list with anchor-preserving updates and near-end prefetch.

    Prefetch keeps at most one pending user request across busy/cooldown;
    scrolling up cancels it. List growth must never trigger endless auto-loading.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending_more = False
        self.more_timer = None
        self.restoring_anchor = False   # suppress scroll side effects while restoring
        self.anchor_generation = 0      # bumps on each restore/user move; stale restores no-op
        self.pending_anchor = None
        self.preview_width = None
        self.setting_anchor_index = False

    @property
    def owner(self) -> FeedOwner:
        return self.screen if isinstance(self.screen, FeedOwner) else self.app

    def preview(self, post) -> Text:
        return Text(post_preview(post, width=max(12, self.size.width - 6), lines=self.owner.PREVIEW_LINES))

    # ---- rendering -------------------------------------------------------
    async def show_posts(self, posts, *, reset: bool) -> None:
        """Replace owner.posts_data with `posts` and update rows.

        reset=True: rebuild and jump to the top. Otherwise, when `posts` extends the
        current list, rows are updated in place and the reading position is kept.
        """
        owner = self.owner
        anchor = self.capture_anchor(owner.posts_data)
        old_ids = [post['id'] for post in owner.posts_data]
        append = not reset and bool(old_ids) and [p['id'] for p in posts[:len(old_ids)]] == old_ids
        if not append:
            await self.clear()
            if reset or not old_ids:
                self.scroll_home(animate=False)
        owner.posts_data = posts
        for index, post in enumerate(posts):
            if append and index < len(old_ids):
                self.children[index].query_one(Label).update(self.preview(post))
            else:
                await self.append(ListItem(Label(self.preview(post))))
        if posts:
            if not reset and old_ids:
                await self.restore_anchor(anchor, posts)
            else:
                self.index = 0
                self.focus()

    def on_resize(self):
        if self.is_mounted:
            self.call_after_refresh(self.refresh_previews)

    def refresh_previews(self):
        """Re-wrap rows after a width change, keeping the reading anchor."""
        owner = self.owner
        posts = owner.posts_data
        width = max(12, self.size.width - 6)
        if owner.busy:
            self.preview_width = None
            return
        if not posts or len(self.children) != len(posts) or width == self.preview_width:
            return
        self.preview_width = width
        anchor = self.pending_anchor or self.capture_anchor(posts)
        for child, post in zip(self.children, posts):
            child.query_one(Label).update(self.preview(post))
        self.restore_anchor(anchor, posts)

    # ---- reading anchor --------------------------------------------------
    def watch_index(self, old_index, new_index):
        # A new user selection supersedes any restore queued by an older layout.
        if not self.setting_anchor_index:
            self.anchor_generation += 1
            self.restoring_anchor = False
            self.pending_anchor = None
        super().watch_index(old_index, new_index)

    def scroll_to_widget(self, widget, **kwargs):
        if self.restoring_anchor:
            return False
        kwargs['immediate'] = True
        return super().scroll_to_widget(widget, **kwargs)

    def capture_anchor(self, posts):
        """(selected id, first visible id, its offset from the viewport top)."""
        selected = posts[self.index]['id'] if self.index is not None and self.index < len(posts) else None
        for index, child in enumerate(self.children):
            if child.virtual_region.bottom > self.scroll_y and index < len(posts):
                return selected, posts[index]['id'], child.virtual_region.y - self.scroll_y
        return selected, None, 0

    def restore_anchor(self, anchor, posts) -> asyncio.Future:
        """Restore after layout; callers may await the returned completion future."""
        settled = asyncio.get_running_loop().create_future()

        def complete():
            if not settled.done():
                settled.set_result(None)

        selected, visible, offset = anchor
        ids = [post['id'] for post in posts]
        self.pending_more = False
        if not ids:
            complete()
            return settled
        self.anchor_generation += 1
        generation = self.anchor_generation
        self.pending_anchor = anchor
        self.restoring_anchor = True
        self.setting_anchor_index = True
        try:
            self.index = ids.index(selected) if selected in ids else 0
        finally:
            self.setting_anchor_index = False

        def restore_scroll():
            if not self.is_mounted or generation != self.anchor_generation:
                complete()
                return
            index = ids.index(visible) if visible in ids else self.index
            if index is not None and index < len(self.children):
                self.scroll_to(y=max(0, self.children[index].virtual_region.y - offset),
                               animate=False, immediate=True)
            self.finish_restoring_anchor(generation)
            complete()

        self.app.call_after_refresh(restore_scroll)
        return settled

    def finish_restoring_anchor(self, generation):
        if generation == self.anchor_generation:
            self.restoring_anchor = False
            self.pending_anchor = None

    # ---- prefetch --------------------------------------------------------
    def near_end(self):
        return self.max_scroll_y - self.scroll_y <= max(3, self.size.height)

    def queue_more(self):
        if self.near_end():
            self.pending_more = True
            self.flush_more()

    def flush_more(self):
        if not self.pending_more or not self.is_mounted:
            return
        if self.screen is not self.app.screen or not self.near_end():
            self.pending_more = False
            return
        owner = self.owner
        if not owner.posts_data or owner.leaving:
            self.pending_more = False
            return
        delay = owner.next_auto_at - time.monotonic()
        if owner.busy or delay > 0:
            if self.more_timer is None:
                self.more_timer = self.set_timer(max(.1, delay) if not owner.busy else .2, self.retry_more)
            return
        self.pending_more = False
        owner.request_more()

    def retry_more(self):
        self.more_timer = None
        self.flush_more()

    def watch_scroll_y(self, old_value, new_value):
        super().watch_scroll_y(old_value, new_value)
        if self.restoring_anchor:
            return
        if new_value > old_value:
            self.queue_more()
        elif new_value < old_value:
            self.pending_more = False

    def on_mouse_scroll_down(self, event):
        if not event.ctrl and not event.shift:
            self.queue_more()

    def on_mouse_scroll_up(self, event):
        self.pending_more = False
