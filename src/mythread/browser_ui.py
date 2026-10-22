"""Browser-only Textual UI, with no API account or publishing actions."""
import time
import asyncio
from rich.text import Text
from textual import work
from textual.app import App
from textual.screen import Screen
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Label, ListItem, ListView, Static

from .text import article_text
from .browser import browser_open_error


def browser_status(source, batch):
    message = f'[{batch.state}] {batch.message}'
    if getattr(source, 'headless', False) and batch.state in {'login', 'error', 'unconfirmed'}:
        message += ' · 背景模式：請返回首頁點「登入視窗」，手動完成登入／驗證後點「完成登入」。'
    return message


class BrowserTitle(Static):
    """Single-node title: no delayed HeaderTitle queries during screen teardown."""
    DEFAULT_CSS = '''
    BrowserTitle { dock: top; height: 1; width: 1fr;
        background: $primary-background; text-align: center; text-style: bold; }
    '''

    def __init__(self):
        super().__init__('myThread · 唯讀瀏覽器版', markup=False)


class BridgeList(ListView):
    """Prefetch near the end; retain one user request across busy/cooldown."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending_more = False
        self.more_timer = None

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
        owner = self.screen if isinstance(self.screen, CommentsScreen) else self.app
        if not owner.posts_data or getattr(owner, 'leaving', False):
            self.pending_more = False
            return
        delay = owner.next_auto_at - time.monotonic()
        if owner.busy or delay > 0:
            if self.more_timer is None:
                self.more_timer = self.set_timer(max(.1, delay) if not owner.busy else .2, self.retry_more)
            return
        self.pending_more = False
        self.app.request_more()

    def retry_more(self):
        self.more_timer = None
        self.flush_more()

    def watch_scroll_y(self, old_value, new_value):
        super().watch_scroll_y(old_value, new_value)
        if new_value > old_value:
            self.queue_more()
        elif new_value < old_value:
            self.pending_more = False

    def on_mouse_scroll_down(self, event):
        if not event.ctrl and not event.shift:
            self.queue_more()

    def on_mouse_scroll_up(self, event):
        self.pending_more = False


class BrowserReader(Screen):
    BINDINGS = [('escape', 'app.pop_screen', '返回')]

    def __init__(self, post):
        super().__init__()
        self.post = post

    def compose(self):
        yield BrowserTitle()
        with VerticalScroll():
            yield Static(Text(article_text(self.post)), id='article')
        with Horizontal():
            yield Button('返回 [Esc]', id='back')
            if isinstance(self, BrowserArticle):
                yield Button('讀取留言 [C]', id='comments')
            yield Button('關閉 APP', id='quit-app', variant='error')
        yield Footer()

    def on_button_pressed(self, event):
        event.prevent_default()
        event.stop()
        if event.button.id == 'quit-app':
            self.app.action_safe_quit()
        else:
            self.app.pop_screen()


class BrowserArticle(BrowserReader):
    BINDINGS = [('escape', 'app.pop_screen', '返回'), ('c', 'comments', '讀取留言')]

    def action_comments(self):
        self.app.push_screen(CommentsScreen(self.post))

    def on_button_pressed(self, event):
        # stop() only stops bubbling; Textual also dispatches base-class handlers.
        # BrowserReader's default handler would pop the new comments screen.
        event.prevent_default()
        event.stop()
        if event.button.id == 'comments':
            self.action_comments()
        elif event.button.id == 'quit-app':
            self.app.action_safe_quit()
        else:
            self.app.pop_screen()


class CommentsScreen(Screen):
    READ_TIMEOUT = 12
    BINDINGS = [('escape', 'back', '返回文章'), ('ctrl+r', 'reload', '整理留言'),
                ('ctrl+n', 'more', '更多留言')]

    def __init__(self, post):
        super().__init__()
        self.post = post
        self.busy = False
        self.posts_data = []
        self.next_auto_at = 0.0
        self.leaving = False

    def compose(self):
        yield BrowserTitle()
        yield Static(Text(f"@{self.post['username']} 的文章留言"))
        with Horizontal():
            yield Button('重新整理', id='comments-read')
            yield Button('更多留言', id='comments-more')
            yield Button('返回文章', id='comments-back')
            yield Button('關閉 APP', id='quit-app', variant='error')
        yield Static('正在開啟留言頁……', id='comments-status', markup=False)
        yield BridgeList()
        yield Footer()

    def on_mount(self):
        self.load('open')

    def action_reload(self):
        self.load('read')

    def action_more(self):
        self.load('next')

    def request_more(self):
        if self.posts_data and not self.busy and time.monotonic() >= self.next_auto_at:
            self.next_auto_at = time.monotonic() + 2
            self.load('next')

    def on_button_pressed(self, event):
        event.stop()
        if event.button.id == 'quit-app':
            self.app.action_safe_quit()
        elif event.button.id == 'comments-back':
            self.action_back()
        else:
            self.load('next' if event.button.id == 'comments-more' else 'read')

    @work
    async def load(self, action):
        if self.busy or self.leaving:
            return
        self.busy = True
        status = self.query_one('#comments-status', Static)
        status.update('留言載入中……')
        try:
            source = self.app.source
            if action == 'open' or source.replies is None:
                operation = source.open_replies(self.post)
            else:
                operation = (source.replies.read(refresh=True) if action == 'read'
                             else source.replies.read(action == 'next'))
            task = asyncio.create_task(operation)
            # Close the owned tab to interrupt Playwright, rather than cancelling
            # a protocol call halfway through and leaving it in an unknown state.
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
            try:
                batch = await asyncio.wait_for(asyncio.shield(task), timeout=self.READ_TIMEOUT)
            except TimeoutError:
                await source.close_replies()
                if not self.leaving:
                    status.update('留言讀取逾時，已停止本次讀取；可返回文章或重新整理。')
                return
            if self.leaving:
                return
            status.update(browser_status(source, batch))
            if batch.state in {'ready', 'empty', 'login'}:
                view = self.query_one(BridgeList)
                old_ids = [p['id'] for p in self.posts_data]
                append = action != 'read' and bool(old_ids) and [p['id'] for p in batch.posts[:len(old_ids)]] == old_ids
                if not append:
                    await view.clear()
                    view.scroll_home(animate=False)
                self.posts_data = batch.posts
                for index, post in enumerate(batch.posts):
                    text = Text(f"@{post['username']}\n{post['text'] or '（無文字內容）'}\n{post['permalink']}")
                    if append and index < len(old_ids):
                        view.children[index].query_one(Label).update(text)
                    else:
                        await view.append(ListItem(Label(text)))
                if batch.posts and not append:
                    view.index = 0
                    view.focus()
        except Exception:
            if not self.leaving:
                status.update('留言讀取失敗，請重試。')
        finally:
            self.busy = False
            self.next_auto_at = time.monotonic() + 2

    @work
    async def action_back(self):
        if self.leaving:
            return
        self.leaving = True
        try:
            await self.app.source.close_replies()
        finally:
            self.busy = False
            self.app.pop_screen()

    def on_list_view_selected(self, event):
        event.stop()
        index = event.list_view.index
        if not self.busy and index is not None and index < len(self.posts_data):
            self.app.push_screen(BrowserReader(self.posts_data[index]))


class BrowserApp(App):
    TITLE = "myThread · 唯讀瀏覽器版"
    BINDINGS = [("ctrl+q", "safe_quit", "離開"), ("ctrl+r", "read", "重新整理"),
                ("ctrl+n", "next", "下一批"), ("ctrl+b", "open", "登入視窗")]
    CSS = """
    Horizontal { height: 3; }
    Button { min-width: 10; margin-right: 1; }
    #status { height: auto; min-height: 2; }
    #comments-status { height: auto; min-height: 2; }
    ListView { height: 1fr; border: round $primary; }
    ListItem { padding: 1; }
    ListItem Label { width: 1fr; }
    #article { padding: 1 2; }
    """

    def __init__(self, source, *, auto_start=True):
        super().__init__()
        self.source, self.busy, self.posts_data = source, False, []
        self.next_auto_at = 0.0
        self.auto_start = auto_start

    def on_mount(self):
        if self.auto_start:
            self.perform('startup')

    def request_more(self):
        if isinstance(self.screen, CommentsScreen):
            self.screen.request_more()
            return
        if (self.busy or not self.posts_data or len(self.screen_stack) != 1
                or time.monotonic() < self.next_auto_at):
            return
        self.next_auto_at = time.monotonic() + 2
        self.perform("next")

    def compose(self):
        yield BrowserTitle()
        with Horizontal():
            yield Button("登入視窗", id="open")
            yield Button("完成登入", id="background", disabled=self.source.headless is True)
            yield Button("重新整理", id="read")
            yield Button("下一批", id="next")
            yield Button('關閉 APP', id='quit-app', variant='error')
        yield Static("首次使用請點「登入視窗」，完成後點「完成登入」回到背景閱讀。", id="status", markup=False)
        yield BridgeList()
        yield Footer()

    def action_open(self):
        self.perform("open")

    def action_safe_quit(self):
        if self.busy or any(isinstance(s, CommentsScreen) and s.busy for s in self.screen_stack):
            self.notify("請等目前瀏覽器操作完成後再離開。")
        else:
            self.exit()

    def action_read(self):
        self.perform("read")

    def action_next(self):
        self.perform("next")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == 'quit-app':
            event.stop()
            self.action_safe_quit()
        else:
            self.perform(event.button.id)

    @work
    async def perform(self, action):
        if self.busy or len(self.screen_stack) != 1:
            return
        self.busy = True
        status = self.query_one("#status", Static)
        status.update("載入中……")
        try:
            if action in {'open', 'background'}:
                self.posts_data = []
                await self.query_one(ListView).clear()
                status.update('正在切換專用瀏覽器……')
                await self.source.switch_mode(action == 'background')
                self.query_one('#background', Button).disabled = self.source.headless is True
                if action == 'open':
                    status.update('請在專用瀏覽器手動登入／完成驗證，然後點「完成登入」回到背景閱讀。')
                    return
            elif action == 'startup':
                status.update('正在開啟專用瀏覽器……')
                await self.source.open()
                status.update('瀏覽器已開啟，正在讀取文章……')
            batch = (await self.source.read(refresh=True) if action == 'read'
                     else await self.source.read(action == "next"))
            if action in {'startup', 'background'}:
                # DOMContentLoaded may precede the rendered feed. Bounded retry,
                # with no scrolling or automatic login/verification interaction.
                for _ in range(10):
                    if batch.state not in {'loading', 'error'}:
                        break
                    await asyncio.sleep(.5)
                    batch = await self.source.read(False)
            status.update(browser_status(self.source, batch))
            if batch.state in {"ready", "empty", "login"}:
                view = self.query_one(ListView)
                old_index = view.index
                old_scroll = view.scroll_y
                previous_ids = [post['id'] for post in self.posts_data]
                new_ids = [post['id'] for post in batch.posts]
                append_only = action != 'read' and bool(previous_ids) and new_ids[:len(previous_ids)] == previous_ids
                if not append_only:
                    await view.clear()
                    view.scroll_home(animate=False)
                self.posts_data = batch.posts
                for index, post in enumerate(batch.posts):
                    label = Text(f"@{post['username']}\n{post['text'] or '（無文字內容）'}\n{post['permalink']}")
                    if append_only and index < len(previous_ids):
                        view.children[index].query_one(Label).update(label)
                    else:
                        await view.append(ListItem(Label(label)))
                if batch.posts:
                    if not append_only:
                        view.index = 0 if action == 'read' else min(old_index or 0, len(batch.posts) - 1)
                        view.focus()
                    else:
                        self.call_after_refresh(view.scroll_to, y=old_scroll, animate=False)
        except Exception as exc:
            status.update(browser_open_error(exc))
        finally:
            self.next_auto_at = time.monotonic() + 2
            self.busy = False

    def on_list_view_selected(self, event: ListView.Selected):
        index = event.list_view.index
        if not self.busy and index is not None and index < len(self.posts_data):
            self.push_screen(BrowserArticle(self.posts_data[index]))
