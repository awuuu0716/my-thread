from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static, TextArea

from .api import APIError, PublishUncertain, ThreadsClient, plain
from .account_ui import AccountScreen
from .storage import StorageError
from .feed import RecommendationFeed
from .feed_ui import FeedSettings


def article_text(post: dict) -> str:
    media = post.get("media_type", "")
    attachment = {"IMAGE": "[圖片]", "VIDEO": "[影片]", "CAROUSEL_ALBUM": "[多媒體附件]"}.get(media, "")
    return plain(f"@{post.get('username', '')}  {post.get('timestamp', '')}\n\n"
                 f"{post.get('text') or '（無文字內容）'}\n\n{attachment}\n{post.get('permalink', '')}"
                 + (f"\n\n本機推薦理由：{post['_recommendation']}" if post.get('_recommendation') else ""))


class Article(Screen):
    BINDINGS = [("escape", "app.pop_screen", "返回")]

    def __init__(self, post):
        super().__init__()
        self.post = post

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static(Text(article_text(self.post)), id="article")
        yield Button("返回 [Esc]", id="back")
        yield Footer()

    def on_button_pressed(self):
        self.app.pop_screen()


class Confirm(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="confirm-box"):
            yield Label("發布預覽：確認後會送到你的 Threads 帳號")
            yield Static(Text(plain(self.text)))
            with Horizontal():
                yield Button("取消", id="cancel")
                yield Button("確認發布", variant="warning", id="confirm")

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "confirm")


class Composer(Screen):
    BINDINGS = [("escape", "back", "保留草稿並返回")]

    def __init__(self, store, client):
        super().__init__()
        self.store = store
        self.client = client
        self.sending = False
        self.uncertain = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("撰寫文字 · 草稿自動儲存於本機 · Tab 切換按鈕")
        yield TextArea(self.store.read("draft.json").get("text", ""), id="editor")
        yield Static("", id="compose-status", markup=False)
        with Horizontal():
            yield Button("預覽並發布", variant="primary", id="preview")
            yield Button("保留草稿並返回", id="back")
        yield Footer()

    def on_text_area_changed(self, event: TextArea.Changed):
        try:
            self.store.write("draft.json", {"text": event.text_area.text})
        except StorageError as exc:
            self.query_one("#compose-status", Static).update(str(exc))

    def action_back(self):
        if not self.sending:
            self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "back":
            self.action_back()
        elif event.button.id == "preview" and not self.sending and not self.uncertain:
            text = self.query_one(TextArea).text
            if not text.strip():
                self.query_one("#compose-status", Static).update("請先輸入文字。")
                return
            self.app.push_screen(Confirm(text), lambda confirmed: self.send(text) if confirmed else None)

    @work
    async def send(self, text):
        if self.sending:
            return
        self.sending = True
        self.query_one("#preview", Button).disabled = True
        self.query_one("#back", Button).disabled = True
        self.query_one(TextArea).disabled = True
        status = self.query_one("#compose-status", Static)
        status.update("正在發布，請勿關閉程式……")
        try:
            post_id = await self.client.publish(text)
        except PublishUncertain as exc:
            self.uncertain = True
            status.update(str(exc) + " 草稿已保留；返回檢查後再開啟編輯器。")
        except APIError as exc:
            status.update(str(exc))
        else:
            self.query_one(TextArea).load_text("")
            status.update(f"發布成功，文章 ID：{plain(post_id)}。返回「我的文章」並更新即可查看。")
        finally:
            self.sending = False
            self.query_one("#preview", Button).disabled = self.uncertain
            self.query_one("#back", Button).disabled = False
            self.query_one(TextArea).disabled = False


class ThreadsApp(App):
    TITLE = "myThread"
    BINDINGS = [("ctrl+q", "safe_quit", "離開"), ("ctrl+r", "reload_posts", "更新"),
                ("ctrl+n", "next_page", "下一頁"), ("ctrl+w", "compose_post", "發文"),
                ("ctrl+f", "recommendations", "推薦"), ("ctrl+l", "account", "帳號")]
    CSS = """
    Screen { background: $surface; }
    #toolbar { height: 3; }
    #toolbar-bottom { height: 3; }
    #toolbar Input { width: 1fr; }
    Button { min-width: 10; margin-right: 1; }
    #status { height: auto; min-height: 2; padding: 0 1; color: $text-muted; }
    ListView { height: 1fr; margin: 0 1; border: round $primary; }
    ListItem { padding: 1; }
    ListItem Label { width: 1fr; }
    #article { padding: 1 2; }
    #editor { height: 1fr; margin: 1; }
    #compose-status { height: auto; min-height: 2; padding: 1; }
    Composer Horizontal { height: 3; }
    Confirm { align: center middle; background: $background 70%; }
    #confirm-box { width: 85%; max-height: 85%; border: thick $primary; padding: 1 2; background: $surface; }
    #confirm-box Static { margin: 1 0; }
    #confirm-box Horizontal { height: 3; }
    FeedSettings { align: center middle; background: $background 70%; }
    #feed-settings-box { width: 90%; max-height: 95%; border: thick $primary; padding: 1; background: $surface; }
    #feed-sources { height: 5; }
    #feed-keywords { height: 3; }
    #feed-settings-box Horizontal { height: 3; }
    AccountScreen { align: center middle; background: $background 70%; }
    #account-box { width: 90%; max-height: 90%; border: thick $primary; padding: 1; background: $surface; }
    #account-box Horizontal { height: 3; }
    #account-error { min-height: 2; height: auto; }
    #account-current { margin: 1 0; }
    """

    def __init__(self, client, store, demo=False, client_factory=ThreadsClient, startup_message=""):
        super().__init__()
        self.client = client
        self.store = store
        self.demo = demo
        self.client_factory = client_factory
        self.startup_message = startup_message
        self.auth_busy = False
        self.account_label = "離線示範" if demo else ("已連線" if client else "尚未登入")
        self.posts_data = []
        self.username = ""
        self.cursor = None
        self.busy = False
        self.feed_mode = False
        self.feed_more = False
        self.feed = RecommendationFeed(client, store, demo)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="toolbar"):
            yield Button("我的文章", id="mine")
            yield Input(placeholder="公開帳號，例如 threads", id="username")
            yield Button("讀取帳號", id="profile")
            yield Button("發文", id="compose")
        yield Static("載入中……", id="status", markup=False)
        yield ListView(id="posts")
        with Horizontal(id="toolbar-bottom"):
            yield Button("本機推薦", id="recommend")
            yield Button("推薦設定", id="feed-settings")
            yield Button("更新", id="reload")
            yield Button("下一頁", id="next", disabled=True)
            yield Button("帳號", id="account", disabled=self.demo)
        yield Footer()

    def on_mount(self):
        self.sub_title = "離線示範 · 不會發布" if self.demo else "Threads API"
        if self.client is None:
            self.query_one("#status", Static).update("尚未登入，請點「帳號」貼上 Token。")
            self.call_after_refresh(self.action_account)
        else:
            self.load_posts("")

    def action_account(self):
        if self.demo:
            self.notify("示範模式不使用真實 Token；請退出後以 mythread 開啟正式模式。")
        elif len(self.screen_stack) == 1 and not self.auth_busy:
            if self.busy:
                self.notify("正在讀取文章，請完成後再開啟帳號。")
                return
            self.push_screen(AccountScreen(self.startup_message))
            self.startup_message = ""

    async def clear_account_view(self):
        self.posts_data, self.username, self.cursor = [], "", None
        self.feed_mode, self.feed_more = False, False
        await self.query_one(ListView).clear()
        self.query_one("#next", Button).disabled = True
        self.query_one("#username", Input).value = ""
        self.feed = RecommendationFeed(self.client, self.store, self.demo)

    async def replace_account(self, token):
        candidate = self.client_factory(token)
        try:
            profile = await candidate.me()
            self.store.save_token(token)
        except BaseException:
            await candidate.close()
            raise
        old_client, self.client = self.client, candidate
        # The new credential is committed. Clear account-specific local state before browsing.
        try:
            self.store.write("draft.json", {})
            self.store.write("feed-seen.json", {})
        except StorageError:
            # Do not expose another account's drafts if local cleanup fails.
            await candidate.close()
            self.client = None
            if old_client:
                await old_client.close()
            await self.clear_account_view()
            self.account_label = "登入資料已保存，但本機資料清除失敗；請修復後重新登入"
            raise
        if old_client:
            await old_client.close()
        await self.clear_account_view()
        self.account_label = f"已登入 @{plain(profile['username'])}"
        self.sub_title = self.account_label

    async def logout_account(self):
        self.store.logout()
        if self.client:
            await self.client.close()
        self.client = None
        await self.clear_account_view()
        self.account_label = "尚未登入"
        self.sub_title = self.account_label
        self.query_one("#status", Static).update("已登出。點「帳號」可重新登入。")

    @work
    async def load_posts(self, username, after=None):
        if self.busy or self.client is None:
            return
        self.busy = True
        status = self.query_one("#status", Static)
        status.update("讀取中……")
        try:
            if not self.demo and self.account_label == "已連線":
                profile = await self.client.me()
                self.account_label = f"已登入 @{plain(profile['username'])}"
                self.sub_title = self.account_label
            page = await self.client.posts(username, after)
        except APIError as exc:
            status.update(str(exc) + "（保留上一個列表）")
        else:
            view = self.query_one(ListView)
            await view.clear()
            self.posts_data = page.posts
            self.feed_mode = False
            self.username, self.cursor = username, page.after
            for post in page.posts:
                snippet = plain(post.get("text") or "（無文字內容）").replace("\n", " ")[:160]
                label = Text(f"@{plain(post.get('username', ''))}  {plain(post.get('timestamp', ''))}\n{snippet}")
                await view.append(ListItem(Label(label)))
            if page.posts:
                view.index = 0
            self.query_one("#next", Button).disabled = not bool(self.cursor)
            status.update(f"{'@' + username if username else '我的文章'} · {len(page.posts)} 篇 · Enter 閱讀全文"
                          if page.posts else "目前沒有文章。")
            view.focus()
        finally:
            self.busy = False

    def on_list_view_selected(self, event: ListView.Selected):
        index = event.list_view.index
        if not self.busy and index is not None and index < len(self.posts_data):
            if self.feed_mode:
                try:
                    self.feed.mark_seen(self.posts_data[index].get("id"))
                except StorageError as exc:
                    self.notify(str(exc), severity="error")
            self.push_screen(Article(self.posts_data[index]))

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "username":
            return
        username = event.value.strip().lstrip("@")
        if username:
            self.load_posts(username)

    def on_button_pressed(self, event: Button.Pressed):
        action = event.button.id
        if action == "mine":
            self.load_posts("")
        elif action == "profile":
            username = self.query_one("#username", Input).value.strip().lstrip("@")
            if username:
                self.load_posts(username)
        elif action == "reload":
            self.action_reload_posts()
        elif action == "next":
            self.action_next_page()
        elif action == "compose":
            self.action_compose_post()
        elif action == "recommend":
            self.action_recommendations()
        elif action == "feed-settings":
            self.open_feed_settings()
        elif action == "account":
            self.action_account()

    def action_reload_posts(self):
        if len(self.screen_stack) == 1:
            if self.feed_mode:
                self.load_feed(reset=True)
            else:
                self.load_posts(self.username)

    def action_next_page(self):
        if len(self.screen_stack) == 1:
            if self.feed_mode and self.feed_more:
                self.load_feed()
            elif not self.feed_mode and self.cursor:
                self.load_posts(self.username, self.cursor)

    def action_recommendations(self):
        if len(self.screen_stack) != 1 or self.busy:
            return
        if self.feed.sources or self.feed.keywords:
            self.load_feed(reset=True)
        else:
            self.open_feed_settings()

    def open_feed_settings(self):
        if len(self.screen_stack) == 1 and not self.busy:
            self.push_screen(FeedSettings(self.feed), lambda saved: self.load_feed(reset=True) if saved else None)

    @work
    async def load_feed(self, reset=False):
        if self.busy or self.client is None:
            return
        self.busy = True
        status = self.query_one("#status", Static)
        status.update("正在混合推薦來源……")
        try:
            page = await self.feed.page(reset)
        except (APIError, StorageError) as exc:
            status.update(str(exc) + "（保留上一個列表）")
        else:
            view = self.query_one(ListView)
            await view.clear()
            self.posts_data = page.posts
            self.feed_mode, self.feed_more = True, page.has_more
            for post in page.posts:
                snippet = plain(post.get("text") or "（無文字內容）").replace("\n", " ")[:160]
                heading = f"@{plain(post.get('username', ''))} · {plain(post.get('_recommendation', ''))}"
                await view.append(ListItem(Label(Text(f"{heading}\n{snippet}"))))
            if page.posts:
                view.index = 0
            self.query_one("#next", Button).disabled = not page.has_more
            status.update(f"本機推薦 · {len(page.posts)} 篇 · {len(self.feed.keywords)} 個關鍵字／{len(self.feed.sources)} 個帳號"
                          + (f" · {len(page.errors)} 個來源失敗，請查看通知" if page.errors else "")
                          + (" · 無結果；可能無符合文章或搜尋權限受限" if not page.posts else ""))
            for error in page.errors:
                self.notify(plain(error), severity="warning", timeout=10)
            view.focus()
        finally:
            self.busy = False

    def action_compose_post(self):
        if len(self.screen_stack) == 1:
            if self.client is None:
                self.action_account()
            else:
                self.push_screen(Composer(self.store, self.client))

    def action_safe_quit(self):
        if self.auth_busy:
            self.notify("正在處理登入／登出，請稍候。")
            return
        if any(isinstance(screen, Composer) and screen.sending for screen in self.screen_stack):
            self.notify("正在發布，請等候結果。")
            return
        self.exit()
