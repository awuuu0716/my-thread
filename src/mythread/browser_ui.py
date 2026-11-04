"""Browser-only Textual UI, with no API account or publishing actions."""
import time
import asyncio
from rich.text import Text
from textual import events, work
from textual.app import App
from textual.screen import Screen
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Label, ListItem, ListView, Static

from .text import article_text, post_preview, text_excerpt
from .browser import browser_open_error
from .dialogs import ClearLoginDialog


def browser_status(source, batch):
    if batch.state == 'login':
        return '需要登入或驗證：請返回首頁點「登入視窗」，在瀏覽器完成後點「完成登入」。'
    titles = {'ready': '已載入', 'loading': '仍在載入', 'empty': '頁面顯示空結果',
              'unconfirmed': '尚未確認內容', 'error': '讀取失敗', 'closed': '瀏覽器已關閉'}
    message = batch.message.split('DOM 診斷：', 1)[0].strip()
    message = message.replace('保留 ', '已載入 ').replace('稍後按重新整理', '稍後重試')
    result = f"{titles.get(batch.state, '讀取狀態')} · {message}" if message else titles.get(batch.state, '讀取狀態')
    if getattr(source, 'headless', False) and batch.state in {'error', 'unconfirmed'}:
        result += ' · 如需查看網站，請返回首頁點「登入視窗」。'
    return result


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
        self.restoring_anchor = False
        self.anchor_generation = 0
        self.pending_anchor = None
        self.preview_width = None
        self.setting_anchor_index = False

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

    def near_end(self):
        return self.max_scroll_y - self.scroll_y <= max(3, self.size.height)

    def capture_anchor(self, posts):
        """Remember the focused article and the visible row independently."""
        selected = posts[self.index]['id'] if self.index is not None and self.index < len(posts) else None
        for index, child in enumerate(self.children):
            if child.virtual_region.bottom > self.scroll_y and index < len(posts):
                return selected, posts[index]['id'], child.virtual_region.y - self.scroll_y
        return selected, None, 0

    def restore_anchor(self, anchor, posts):
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

    def on_resize(self):
        if self.is_mounted:
            self.call_after_refresh(self.refresh_previews)

    def refresh_previews(self):
        owner = self.screen if isinstance(self.screen, CommentsScreen) else self.app
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
            child.query_one(Label).update(Text(post_preview(post, width=width)))
        self.restore_anchor(anchor, posts)

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


class BrowserReader(Screen):
    BINDINGS = [('escape', 'app.pop_screen', '返回'), ('o', 'original', '查看原文')]
    DEFAULT_CSS = '''
    BrowserReader #reader-actions { height: 3; }
    BrowserReader #reader-actions Button { min-width: 8; margin-right: 0; }
    '''

    def __init__(self, post):
        super().__init__()
        self.post = post

    def compose(self):
        yield BrowserTitle()
        with VerticalScroll():
            yield Static(Text(article_text(self.post)), id='article')
        with Horizontal(id='reader-actions'):
            yield Button('返回 [Esc／右鍵]', id='back')
            if isinstance(self, BrowserArticle):
                yield Button('讀取留言 [C]', id='comments')
            yield Button('原文 [O]', id='original')
            yield Button('關閉 APP', id='quit-app', variant='error')
        yield Footer()

    def action_original(self):
        # Open only the validated public permalink, following an explicit action.
        from .browser import extract_posts
        posts = extract_posts([self.post])
        if posts:
            self.app.open_url(posts[0]['permalink'])

    def on_button_pressed(self, event):
        event.prevent_default()
        event.stop()
        if event.button.id == 'quit-app':
            self.app.action_safe_quit()
        elif event.button.id == 'original':
            self.action_original()
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
        elif event.button.id == 'original':
            self.action_original()
        elif event.button.id == 'quit-app':
            self.app.action_safe_quit()
        else:
            self.app.pop_screen()


class CommentsScreen(Screen):
    READ_TIMEOUT = 12
    BINDINGS = [('escape', 'back', '返回文章'), ('ctrl+r', 'reload', '整理留言'),
                ('ctrl+n', 'more', '更多留言')]
    DEFAULT_CSS = '''
    CommentsScreen #comments-context { height: auto; max-height: 4; padding: 0 1; }
    CommentsScreen #comments-caveat { height: auto; color: $text-muted; }
    CommentsScreen #comments-actions { height: 3; }
    CommentsScreen #comments-actions Button { min-width: 8; margin-right: 0; }
    '''

    def __init__(self, post):
        super().__init__()
        self.post = post
        self.busy = False
        self.posts_data = []
        self.next_auto_at = 0.0
        self.leaving = False

    def compose(self):
        yield BrowserTitle()
        yield Static(Text(f"@{self.post['username']} 的文章留言\n"
                          f"{text_excerpt(self.post.get('text', ''), width=48, lines=2)}"), id='comments-context')
        yield Static('僅顯示網頁已載入的留言；不代表完整數量或回覆層級。', id='comments-caveat', markup=False)
        with Horizontal(id='comments-actions'):
            yield Button('重新整理', id='comments-read')
            yield Button('更多留言', id='comments-more', disabled=True)
            yield Button('返回文章 [右鍵]', id='comments-back')
            yield Button('關閉 APP', id='quit-app', variant='error')
        yield Static('正在開啟留言頁……', id='comments-status', markup=False)
        yield BridgeList()
        yield Footer()

    def on_mount(self):
        self.update_controls()
        self.load('open')

    def update_controls(self):
        self.query_one('#comments-read', Button).disabled = self.busy or self.leaving
        self.query_one('#comments-more', Button).disabled = self.busy or self.leaving or not self.posts_data
        self.refresh_bindings()

    def check_action(self, action, parameters):
        if action in {'reload', 'more'} and (self.busy or self.leaving):
            return None
        if action == 'more' and not self.posts_data:
            return None
        return True

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
        self.update_controls()
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
            record_batch = getattr(self.app, 'record_batch', None)
            if record_batch:
                record_batch(batch)
            status.update(browser_status(source, batch))
            if batch.state in {'ready', 'empty', 'login'}:
                view = self.query_one(BridgeList)
                anchor = view.capture_anchor(self.posts_data)
                old_ids = [p['id'] for p in self.posts_data]
                append = action != 'read' and bool(old_ids) and [p['id'] for p in batch.posts[:len(old_ids)]] == old_ids
                if not append:
                    await view.clear()
                    if action == 'read' or not old_ids:
                        view.scroll_home(animate=False)
                self.posts_data = batch.posts
                for index, post in enumerate(batch.posts):
                    text = Text(post_preview(post, width=max(12, view.size.width - 6)))
                    if append and index < len(old_ids):
                        view.children[index].query_one(Label).update(text)
                    else:
                        await view.append(ListItem(Label(text)))
                if batch.posts:
                    if action != 'read' and old_ids:
                        await view.restore_anchor(anchor, batch.posts)
                    else:
                        view.index = 0
                        view.focus()
        except Exception:
            if not self.leaving:
                status.update('留言讀取失敗，請重試。')
        finally:
            self.busy = False
            self.next_auto_at = time.monotonic() + 2
            if self.is_mounted and not self.leaving:
                self.update_controls()
                self.query_one(BridgeList).refresh_previews()
            finish_quit = getattr(self.app, 'finish_pending_quit', None)
            if finish_quit:
                finish_quit()

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
    HOME_MIN_POSTS = 10
    HOME_FILL_LIMIT = 10
    OPERATION_TIMEOUT = 40
    CLEANUP_TIMEOUT = 5
    TITLE = "myThread · 唯讀瀏覽器版"
    BINDINGS = [("ctrl+q", "safe_quit", "離開"), ("ctrl+r", "read", "重新整理"),
                ("ctrl+n", "next", "載入更多"), ("ctrl+b", "open", "登入視窗")]
    CSS = """
    Horizontal { height: 3; }
    Button { min-width: 10; margin-right: 1; }
    #home-actions, #home-extra { height: auto; min-height: 3; }
    #home-actions Button { min-width: 8; padding: 0 1; }
    #home-extra Button { min-width: 10; padding: 0 1; }
    #home-hint { height: auto; color: $text-muted; }
    #status-details { height: auto; color: $text-muted; }
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
        self.state = "initial"
        self.extra_open = False
        self.quit_pending = False
        self.quit_timer = None
        self.diagnostics = ''

    def on_mount(self):
        self.update_actions()
        if self.auto_start:
            self.perform('startup')

    async def on_event(self, event):
        # Intercept before dispatch to widgets: a right-click on a button or
        # list item must return rather than activate that widget.
        if (isinstance(event, (events.MouseDown, events.MouseUp, events.Click))
                and not event.is_forwarded and event.button == 3):
            event.prevent_default()
            event.stop()
            if isinstance(event, events.MouseDown):
                if isinstance(self.screen, CommentsScreen):
                    self.screen.action_back()
                elif isinstance(self.screen, BrowserReader):
                    self.pop_screen()
            return
        await super().on_event(event)

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
        with Horizontal(id='home-actions'):
            yield Button("登入視窗", id="open", variant='primary')
            yield Button("完成登入", id="background", disabled=self.source.headless is True)
            yield Button("重新整理", id="read")
            yield Button("載入更多", id="next", disabled=True)
            yield Button("更多", id="more-actions")
        with Horizontal(id='home-extra'):
            yield Button("恢復讀取", id="recover")
            yield Button("清除登入資料", id="relogin", variant='warning')
            yield Button('關閉 APP', id='quit-app')
            yield Button('診斷資訊', id='details')
        yield Static("首次使用請點「登入視窗」，完成後點「完成登入」開始閱讀。", id="status", markup=False)
        yield Static('', id='status-details', markup=False)
        yield Static('↑↓ 選擇 · Enter 閱讀 · 接近底部自動載入 · Ctrl+R 重載並回頂端', id='home-hint', markup=False)
        yield BridgeList()
        yield Footer()

    def check_action(self, action, parameters):
        if action in {'open', 'read', 'next'}:
            if len(self.screen_stack) != 1:
                return False
            if self.busy or self.quit_pending:
                return False
            if action == 'next' and not self.posts_data:
                return False
        return True

    def update_actions(self):
        if not self.is_mounted or not self.screen_stack or not self.screen_stack[0].query('#home-extra'):
            return
        root = self.screen_stack[0]
        if not self.diagnostics:
            root.query_one('#status-details').display = False
        root.query_one('#home-extra').display = self.extra_open or self.state == 'closed'
        for button in root.query('#home-actions Button, #home-extra Button'):
            button.disabled = self.busy or self.quit_pending
            button.variant = 'warning' if button.id == 'relogin' else 'default'
        root.query_one('#quit-app', Button).disabled = False
        root.query_one('#more-actions', Button).disabled = False
        root.query_one('#more-actions', Button).label = '收合' if self.extra_open else '更多'
        root.query_one('#next', Button).disabled = self.busy or self.quit_pending or not self.posts_data
        root.query_one('#next', Button).display = bool(self.posts_data)
        root.query_one('#background', Button).display = self.source.headless is not True and self.state in {'initial', 'login'}
        root.query_one('#background', Button).disabled = self.busy or self.quit_pending or self.source.headless is True
        root.query_one('#open', Button).display = self.extra_open or self.state != 'ready'
        main_id = 'recover' if self.state == 'closed' else 'background' if self.source.headless is not True and self.state in {'initial', 'login'} else 'read' if self.state == 'ready' else 'open'
        root.query_one('#' + main_id, Button).variant = 'primary'
        self.refresh_bindings()

    def action_open(self):
        self.perform("open")

    def action_safe_quit(self):
        if self.busy or any(isinstance(s, CommentsScreen) and s.busy for s in self.screen_stack):
            self.quit_pending = True
            self.update_actions()
            self.notify("已排定關閉，會在目前操作結束後離開。")
            if self.quit_timer is None:
                self.quit_timer = self.set_interval(.2, self.finish_pending_quit)
        else:
            self.exit()

    def finish_pending_quit(self):
        if self.quit_pending and not self.busy and not any(isinstance(s, CommentsScreen) and s.busy for s in self.screen_stack):
            self.exit()

    def action_read(self):
        self.perform("read")

    def action_next(self):
        if self.posts_data:
            self.perform("next")

    def confirm_relogin(self, confirmed):
        if confirmed:
            self.perform('relogin')

    def record_batch(self, batch):
        # These messages are authored locally by the source; never retain raw DOM/errors.
        self.diagnostics = f'狀態：{batch.state} · {batch.message}'
        details = self.screen_stack[0].query_one('#status-details', Static)
        details.update(self.diagnostics)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == 'quit-app':
            self.action_safe_quit()
        elif event.button.id == 'more-actions':
            self.extra_open = not self.extra_open
            self.update_actions()
        elif event.button.id == 'relogin':
            self.push_screen(ClearLoginDialog(), self.confirm_relogin)
        elif event.button.id == 'details':
            details = self.query_one('#status-details', Static)
            details.update(self.diagnostics or '目前沒有診斷資訊。')
            details.display = not details.display
        else:
            self.perform(event.button.id)

    async def browser_call(self, operation):
        task = asyncio.create_task(operation)
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        try:
            return await asyncio.wait_for(asyncio.shield(task), self.OPERATION_TIMEOUT)
        except TimeoutError:
            # Release the owned browser before cancelling an outstanding protocol call.
            try:
                await asyncio.wait_for(self.source.close(), self.CLEANUP_TIMEOUT)
            except Exception:
                # A failed shutdown must not leave the shielded operation running
                # while the UI offers another read or recovery action.
                pass
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    @work
    async def perform(self, action):
        if self.busy or len(self.screen_stack) != 1:
            return
        self.busy = True
        self.update_actions()
        status = self.query_one("#status", Static)
        status.update("正在載入更多文章……" if action == "next" else "正在重載動態並回到頂端……" if action == "read" else "正在讀取文章……")
        try:
            if action in {'open', 'relogin'}:
                self.posts_data = []
                await self.query_one(ListView).clear()
                status.update('正在切換專用瀏覽器……')
                if action == 'relogin':
                    status.update('正在清除專用瀏覽器登入資料並開啟登入視窗……')
                    await self.browser_call(self.source.relogin())
                else:
                    await self.browser_call(self.source.switch_mode(False))
                self.state = 'login'
                status.update('請在專用瀏覽器手動登入／完成驗證並返回 Threads，然後點「完成登入」。請保留瀏覽器開啟，可自行最小化。')
                return
            elif action == 'recover':
                status.update('正在恢復瀏覽器與文章讀取……')
                await self.browser_call(self.source.recover())
            elif action == 'startup':
                status.update('正在開啟專用瀏覽器……')
                await self.browser_call(self.source.open())
                status.update('瀏覽器已開啟，正在讀取文章……')
            batch = (await self.browser_call(self.source.read(refresh=True)) if action == 'read'
                     else await self.browser_call(self.source.read(action == "next")))
            if action in {'startup', 'background', 'recover'}:
                # DOMContentLoaded may precede the rendered feed. Bounded retry,
                # with no scrolling or automatic login/verification interaction.
                # Completing login keeps the verified context/page alive; a
                # headed-to-headless restart can invalidate manual verification.
                retry_states = {'loading', 'error'}
                if action == 'background':
                    retry_states.add('login')
                for _ in range(10):
                    if batch.state not in retry_states:
                        break
                    await asyncio.sleep(.5)
                    batch = await self.browser_call(self.source.read(False))
            fill_ids = set()
            for attempt in range(self.HOME_FILL_LIMIT + 1):
                reset_feed = action == 'read' and attempt == 0
                self.state = batch.state
                self.record_batch(batch)
                status.update(browser_status(self.source, batch))
                if batch.state in {"ready", "empty", "login"}:
                    view = self.query_one(BridgeList)
                    anchor = view.capture_anchor(self.posts_data)
                    previous_ids = [post['id'] for post in self.posts_data]
                    new_ids = [post['id'] for post in batch.posts]
                    append_only = not reset_feed and bool(previous_ids) and new_ids[:len(previous_ids)] == previous_ids
                    if not append_only:
                        await view.clear()
                        if reset_feed or not previous_ids:
                            view.scroll_home(animate=False)
                    self.posts_data = batch.posts
                    for index, post in enumerate(batch.posts):
                        label = Text(post_preview(post, width=max(12, view.size.width - 6)))
                        if append_only and index < len(previous_ids):
                            view.children[index].query_one(Label).update(label)
                        else:
                            await view.append(ListItem(Label(label)))
                    if batch.posts:
                        if not reset_feed and previous_ids:
                            await view.restore_anchor(anchor, batch.posts)
                        elif not append_only:
                            view.index = 0
                            view.focus()
                # Render each batch before fetching more, keeping the UI responsive
                # and preserving already loaded articles if a later read fails.
                ids = {post['id'] for post in batch.posts}
                if (batch.state != 'ready' or not ids or len(ids) >= self.HOME_MIN_POSTS
                        or (attempt and not ids - fill_ids)
                        or attempt == self.HOME_FILL_LIMIT or self.quit_pending):
                    break
                fill_ids = ids
                status.update(f'已載入 {len(ids)} 篇，正在自動補足 {self.HOME_MIN_POSTS} 篇……')
                batch = await self.browser_call(self.source.read(True))
        except TimeoutError:
            self.state = "closed"
            status.update("讀取逾時，已停止本次操作。請點「恢復讀取」重新開啟瀏覽器。")
        except Exception as exc:
            self.state = "error"
            status.update(browser_open_error(exc))
        finally:
            self.next_auto_at = time.monotonic() + 2
            self.busy = False
            self.update_actions()
            self.query_one(BridgeList).refresh_previews()
            self.finish_pending_quit()

    def on_list_view_selected(self, event: ListView.Selected):
        index = event.list_view.index
        if not self.busy and index is not None and index < len(self.posts_data):
            self.push_screen(BrowserArticle(self.posts_data[index]))
