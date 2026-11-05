"""Home screen app: browser-only Textual UI, with no API account or publishing actions.

Home actions (HomeAction) all run through perform(): one at a time, with timeouts.
To add one: add a HomeAction member, a button id in compose(), an entry in
BUTTON_ACTIONS and, if it needs browser steps before reading, a branch in first_batch().
"""
import asyncio
from enum import StrEnum

from textual import events, work
from textual.app import App
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, ListView, Static

from .dialogs import ClearLoginDialog
from .messages import (UiMsg, browser_open_error, browser_status, diagnostics_text,
                       home_busy_text, home_fill_text)
from .model import RENDERABLE_STATES, State
from .screens import BrowserArticle, BrowserReader, CommentsScreen, SubScreen
from .widgets import APP_TITLE, BridgeList, BrowserTitle, ButtonActions, FeedOwner, call_with_deadline

# Re-exported: tests and older imports use these names from browser_ui.
__all__ = ['BridgeList', 'BrowserApp', 'BrowserArticle', 'BrowserReader', 'BrowserTitle',
           'CommentsScreen', 'HomeAction', 'browser_status', 'primary_button']

INITIAL = 'initial'  # home state before any batch; otherwise BrowserApp.state is a State


class HomeAction(StrEnum):
    STARTUP = 'startup'        # auto on mount: open browser headless and read
    OPEN = 'open'              # restart browser visibly for manual login
    BACKGROUND = 'background'  # "完成登入": keep the verified page, retry reading
    READ = 'read'              # reload feed and jump to top
    NEXT = 'next'              # scroll for more posts
    RECOVER = 'recover'        # reopen a closed browser headless with same profile
    RELOGIN = 'relogin'        # wipe profile, then OPEN


# Initial-read retries (no scrolling, no login automation): DOMContentLoaded can
# precede the rendered feed. BACKGROUND also waits out a lingering login wall.
SETTLE_RETRY_STATES = {
    HomeAction.STARTUP: {State.LOADING, State.ERROR},
    HomeAction.RECOVER: {State.LOADING, State.ERROR},
    HomeAction.BACKGROUND: {State.LOADING, State.ERROR, State.LOGIN},
}


def awaiting_login(state, headless) -> bool:
    return headless is not True and state in {INITIAL, State.LOGIN}


def primary_button(state, headless) -> str:
    """Id of the home button highlighted as the next step."""
    if state == State.CLOSED:
        return 'recover'
    if awaiting_login(state, headless):
        return 'background'
    return 'read' if state == State.READY else 'open'


class BrowserApp(FeedOwner, ButtonActions, App):
    HOME_MIN_POSTS = 10   # auto-fill the feed up to this many posts...
    HOME_FILL_LIMIT = 10  # ...using at most this many extra reads
    SETTLE = (10, .5)     # (attempts, delay) for SETTLE_RETRY_STATES
    OPERATION_TIMEOUT = 40
    CLEANUP_TIMEOUT = 5
    TITLE = APP_TITLE
    BINDINGS = [('ctrl+q', 'safe_quit', '離開'), ('ctrl+r', 'read', '重新整理'),
                ('ctrl+n', 'next', '載入更多'), ('ctrl+b', 'open', '登入視窗')]
    BUTTON_ACTIONS = {
        'open': 'action_open', 'background': 'action_background', 'read': 'action_read',
        'next': 'action_next', 'recover': 'action_recover', 'relogin': 'action_relogin',
        'more-actions': 'action_toggle_extra', 'details': 'action_toggle_details',
        'quit-app': 'action_safe_quit',
    }
    CSS = """
    Horizontal { height: 3; }
    Button { min-width: 10; margin-right: 1; }
    #home-actions, #home-extra { height: auto; min-height: 3; }
    #home-actions Button { min-width: 8; padding: 0 1; }
    #home-spacer { width: 1fr; height: 1; }
    #more-actions { margin-right: 0; }
    #home-extra Horizontal { height: 3; align-horizontal: right; }
    #home-extra Button { min-width: 10; padding: 0 1; margin: 0 0 0 1; }
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
        self.source = source          # BrowserSource (or a test double)
        self.busy = False
        self.posts_data = []
        self.next_auto_at = 0.0
        self.auto_start = auto_start
        self.state = INITIAL
        self.extra_open = False       # "更多" panel expanded
        self.quit_pending = False
        self.quit_timer = None
        self.diagnostics = ''

    # ---- layout ----------------------------------------------------------
    def compose(self):
        yield BrowserTitle()
        with Horizontal(id='home-actions'):
            yield Button('登入視窗', id='open', variant='primary')
            yield Button('完成登入', id='background', disabled=self.source.headless is True)
            yield Button('重新整理', id='read')
            yield Static('', id='home-spacer')
            yield Button('更多', id='more-actions')
        with Vertical(id='home-extra'):
            with Horizontal():
                yield Button('載入更多', id='next', disabled=True)
                yield Button('恢復讀取', id='recover')
                yield Button('診斷資訊', id='details')
            with Horizontal():
                yield Button('清除登入資料', id='relogin', variant='warning')
                yield Button('關閉 APP', id='quit-app')
        yield Static(UiMsg.FIRST_RUN, id='status', markup=False)
        yield Static('', id='status-details', markup=False)
        yield Static(UiMsg.HOME_HINT, id='home-hint', markup=False)
        yield BridgeList()
        yield Footer()

    def on_mount(self):
        self.update_actions()
        if self.auto_start:
            self.perform(HomeAction.STARTUP)

    def update_actions(self):
        """Derive every home button's visibility/enabled/variant from current state."""
        if not self.is_mounted or not self.screen_stack or not self.screen_stack[0].query('#home-extra'):
            return
        root = self.screen_stack[0]
        locked = self.busy or self.quit_pending
        login_step = awaiting_login(self.state, self.source.headless)
        if not self.diagnostics:
            root.query_one('#status-details').display = False
        root.query_one('#home-extra').display = self.extra_open or self.state == State.CLOSED
        for button in root.query('#home-actions Button, #home-extra Button'):
            button.disabled = locked
            button.variant = 'warning' if button.id == 'relogin' else 'default'
        root.query_one('#quit-app', Button).disabled = False
        more = root.query_one('#more-actions', Button)
        more.disabled = False
        more.label = '收合' if self.extra_open else '更多'
        next_button = root.query_one('#next', Button)
        next_button.disabled = locked or not self.posts_data
        next_button.display = bool(self.posts_data)
        background = root.query_one('#background', Button)
        background.display = login_step
        background.disabled = locked or self.source.headless is True
        root.query_one('#open', Button).display = self.extra_open or self.state != State.READY
        root.query_one('#' + primary_button(self.state, self.source.headless), Button).variant = 'primary'
        self.refresh_bindings()

    # ---- input -----------------------------------------------------------
    async def on_event(self, event):
        # Intercept before dispatch to widgets: a right-click on a button or
        # list item must go back rather than activate that widget.
        if (isinstance(event, (events.MouseDown, events.MouseUp, events.Click))
                and not event.is_forwarded and event.button == 3):
            event.prevent_default()
            event.stop()
            if isinstance(event, events.MouseDown) and isinstance(self.screen, SubScreen):
                self.screen.action_back()
            return
        await super().on_event(event)

    def check_action(self, action, parameters):
        if action in {'open', 'read', 'next'}:
            if len(self.screen_stack) != 1 or self.busy or self.quit_pending:
                return False
            if action == 'next' and not self.posts_data:
                return False
        return True

    def on_list_view_selected(self, event: ListView.Selected):
        index = event.list_view.index
        if not self.busy and index is not None and index < len(self.posts_data):
            self.push_screen(BrowserArticle(self.posts_data[index]))

    # ---- actions ---------------------------------------------------------
    def action_open(self):
        self.perform(HomeAction.OPEN)

    def action_background(self):
        self.perform(HomeAction.BACKGROUND)

    def action_read(self):
        self.perform(HomeAction.READ)

    def action_next(self):
        if self.posts_data:
            self.perform(HomeAction.NEXT)

    def action_recover(self):
        self.perform(HomeAction.RECOVER)

    def action_relogin(self):
        self.push_screen(ClearLoginDialog(), self.confirm_relogin)

    def confirm_relogin(self, confirmed):
        if confirmed:
            self.perform(HomeAction.RELOGIN)

    def action_toggle_extra(self):
        self.extra_open = not self.extra_open
        self.update_actions()

    def action_toggle_details(self):
        details = self.query_one('#status-details', Static)
        details.update(self.diagnostics or UiMsg.NO_DIAGNOSTICS)
        details.display = not details.display

    def request_more(self):
        """FeedOwner hook: called by the home BridgeList near the end of the list."""
        if self.busy or not self.posts_data or len(self.screen_stack) != 1 or self.cooling_down():
            return
        self.start_cooldown()
        self.perform(HomeAction.NEXT)

    # ---- quitting --------------------------------------------------------
    def any_busy(self) -> bool:
        return self.busy or any(isinstance(s, FeedOwner) and s.busy for s in self.screen_stack)

    def action_safe_quit(self):
        if not self.any_busy():
            self.exit()
            return
        self.quit_pending = True
        self.update_actions()
        self.notify(UiMsg.QUIT_QUEUED)
        if self.quit_timer is None:
            self.quit_timer = self.set_interval(.2, self.finish_pending_quit)

    def finish_pending_quit(self):
        if self.quit_pending and not self.any_busy():
            self.exit()

    # ---- browser operations ------------------------------------------------
    def record_batch(self, batch):
        # Messages are authored locally by the source; never retain raw DOM/errors.
        self.diagnostics = diagnostics_text(batch)
        self.screen_stack[0].query_one('#status-details', Static).update(self.diagnostics)

    async def browser_call(self, operation):
        """Every source call goes through here: timeout closes the browser, then cancels."""
        return await call_with_deadline(operation, self.OPERATION_TIMEOUT,
                                        cleanup=self.source.close, cleanup_timeout=self.CLEANUP_TIMEOUT)

    @work
    async def perform(self, action):
        if self.busy or len(self.screen_stack) != 1:
            return
        self.busy = True
        self.update_actions()
        status = self.query_one('#status', Static)
        status.update(home_busy_text(action))
        try:
            if action in {HomeAction.OPEN, HomeAction.RELOGIN}:
                await self.open_login_window(action, status)
                return
            batch = await self.first_batch(action, status)
            await self.show_and_fill(action, batch, status)
        except TimeoutError:
            self.state = State.CLOSED
            status.update(UiMsg.HOME_TIMEOUT)
        except Exception as exc:
            self.state = State.ERROR
            status.update(browser_open_error(exc))
        finally:
            self.start_cooldown()
            self.busy = False
            self.update_actions()
            self.query_one(BridgeList).refresh_previews()
            self.finish_pending_quit()

    async def open_login_window(self, action, status):
        self.posts_data = []
        await self.query_one(ListView).clear()
        status.update(UiMsg.SWITCHING)
        if action == HomeAction.RELOGIN:
            status.update(UiMsg.RELOGIN)
            await self.browser_call(self.source.relogin())
        else:
            await self.browser_call(self.source.switch_mode(False))
        self.state = State.LOGIN
        status.update(UiMsg.LOGIN_WAIT)

    async def first_batch(self, action, status):
        """Prepare the browser for `action`, read once, then settle initial renders.

        BACKGROUND deliberately keeps the verified context/page: a headed-to-headless
        restart can invalidate manual verification.
        """
        if action == HomeAction.RECOVER:
            status.update(UiMsg.RECOVERING)
            await self.browser_call(self.source.recover())
        elif action == HomeAction.STARTUP:
            status.update(UiMsg.STARTING)
            await self.browser_call(self.source.open())
            status.update(UiMsg.STARTED)
        if action == HomeAction.READ:
            batch = await self.browser_call(self.source.read(refresh=True))
        else:
            batch = await self.browser_call(self.source.read(action == HomeAction.NEXT))
        retry_states = SETTLE_RETRY_STATES.get(action, set())
        attempts, delay = self.SETTLE
        for _ in range(attempts):
            if batch.state not in retry_states:
                break
            await asyncio.sleep(delay)
            batch = await self.browser_call(self.source.read(False))
        return batch

    async def show_and_fill(self, action, batch, status):
        """Render each batch, then keep reading until HOME_MIN_POSTS or no progress.

        Rendering before each extra read keeps the UI responsive and preserves
        already loaded posts if a later read fails.
        """
        seen = set()
        for attempt in range(self.HOME_FILL_LIMIT + 1):
            self.state = batch.state
            self.record_batch(batch)
            status.update(browser_status(self.source, batch))
            if batch.state in RENDERABLE_STATES:
                reset = action == HomeAction.READ and attempt == 0
                await self.query_one(BridgeList).show_posts(batch.posts, reset=reset)
            ids = {post['id'] for post in batch.posts}
            if (batch.state != State.READY or not ids or len(ids) >= self.HOME_MIN_POSTS
                    or (attempt and not ids - seen)
                    or attempt == self.HOME_FILL_LIMIT or self.quit_pending):
                return
            seen = ids
            status.update(home_fill_text(len(ids), self.HOME_MIN_POSTS))
            batch = await self.browser_call(self.source.read(True))
