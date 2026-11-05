"""Screens pushed above the home feed: article reader and comments list.

To add a screen: subclass SubScreen (gets Esc/right-click back + quit button),
declare BUTTON_ACTIONS, and if it shows a post list also mix in FeedOwner.
"""
from rich.text import Text
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Static
from textual import work

from .browser import extract_posts
from .messages import UiMsg, browser_status
from .model import RENDERABLE_STATES
from .text import article_text, text_excerpt
from .widgets import BridgeList, BrowserTitle, ButtonActions, FeedOwner, call_with_deadline


class SubScreen(ButtonActions, Screen):
    """Any screen above home. App.on_event routes right-click to action_back."""

    def action_back(self):
        self.app.pop_screen()

    def action_quit_app(self):
        self.app.action_safe_quit()


class BrowserReader(SubScreen):
    """Full text of one post (also used for a single reply)."""
    BINDINGS = [('escape', 'back', '返回'), ('o', 'original', '查看原文')]
    BUTTON_ACTIONS = {'back': 'action_back', 'original': 'action_original', 'quit-app': 'action_quit_app'}
    SHOW_COMMENTS = False
    DEFAULT_CSS = '''
    BrowserReader #reader-actions { height: 3; }
    BrowserReader #reader-actions Button { min-width: 8; margin-right: 0; }
    BrowserReader #reader-actions #quit-app { dock: right; }
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
            if self.SHOW_COMMENTS:
                yield Button('讀取留言 [C]', id='comments')
            yield Button('原文 [O]', id='original')
            yield Button('關閉 APP', id='quit-app', variant='error')
        yield Footer()

    def action_original(self):
        # Open only the validated public permalink, following an explicit action.
        posts = extract_posts([self.post])
        if posts:
            self.app.open_url(posts[0]['permalink'])


class BrowserArticle(BrowserReader):
    """A home-feed post: reader plus a comments entry point."""
    BINDINGS = [('escape', 'back', '返回'), ('c', 'comments', '讀取留言')]
    BUTTON_ACTIONS = {**BrowserReader.BUTTON_ACTIONS, 'comments': 'action_comments'}
    SHOW_COMMENTS = True

    def action_comments(self):
        self.app.push_screen(CommentsScreen(self.post))


class CommentsScreen(FeedOwner, SubScreen):
    """Replies loaded in a separate browser tab (source.replies)."""
    READ_TIMEOUT = 12
    CLEANUP_TIMEOUT = 5
    PREVIEW_LINES = 3
    BINDINGS = [('escape', 'back', '返回文章'), ('ctrl+r', 'reload', '整理留言'),
                ('ctrl+n', 'more', '更多留言')]
    BUTTON_ACTIONS = {'comments-read': 'action_reload', 'comments-more': 'action_more',
                      'comments-back': 'action_back', 'quit-app': 'action_quit_app'}
    DEFAULT_CSS = '''
    CommentsScreen #comments-context { height: auto; max-height: 4; padding: 0 1; }
    CommentsScreen #comments-caveat { height: auto; color: $text-muted; }
    CommentsScreen #comments-actions { height: 3; }
    CommentsScreen #comments-actions Button { min-width: 8; margin-right: 0; }
    CommentsScreen #comments-actions #quit-app { dock: right; }
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
        yield Static(UiMsg.COMMENTS_CAVEAT, id='comments-caveat', markup=False)
        with Horizontal(id='comments-actions'):
            yield Button('重新整理', id='comments-read')
            yield Button('更多留言', id='comments-more', disabled=True)
            yield Button('返回文章 [右鍵]', id='comments-back')
            yield Button('關閉 APP', id='quit-app', variant='error')
        yield Static(UiMsg.COMMENTS_OPENING, id='comments-status', markup=False)
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
        if self.posts_data and not self.busy and not self.cooling_down():
            self.start_cooldown()
            self.load('next')

    def operation(self, action):
        """'open' opens the tab; 'read' reloads it; 'next' scrolls for more."""
        source = self.app.source
        if action == 'open' or source.replies is None:
            return source.open_replies(self.post)
        return source.replies.read(refresh=True) if action == 'read' else source.replies.read(action == 'next')

    @work
    async def load(self, action):
        if self.busy or self.leaving:
            return
        self.busy = True
        self.update_controls()
        status = self.query_one('#comments-status', Static)
        status.update(UiMsg.COMMENTS_LOADING)
        try:
            source = self.app.source
            try:
                batch = await call_with_deadline(self.operation(action), self.READ_TIMEOUT,
                                                 cleanup=source.close_replies,
                                                 cleanup_timeout=self.CLEANUP_TIMEOUT)
            except TimeoutError:
                if not self.leaving:
                    status.update(UiMsg.COMMENTS_TIMEOUT)
                return
            if self.leaving:
                return
            self.app.record_batch(batch)
            status.update(browser_status(source, batch))
            if batch.state in RENDERABLE_STATES:
                await self.query_one(BridgeList).show_posts(batch.posts, reset=action == 'read')
        except Exception:
            if not self.leaving:
                status.update(UiMsg.COMMENTS_FAILED)
        finally:
            self.busy = False
            self.start_cooldown()
            if self.is_mounted and not self.leaving:
                self.update_controls()
                self.query_one(BridgeList).refresh_previews()
            self.app.finish_pending_quit()

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
