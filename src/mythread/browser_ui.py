"""Browser-only Textual UI, with no API account or publishing actions."""
import time
from rich.text import Text
from textual import work
from textual.app import App
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static

from .tui import Article


class BridgeList(ListView):
    """Request more only on downward movement, never on layout growth."""
    def watch_scroll_y(self, old_value, new_value):
        super().watch_scroll_y(old_value, new_value)
        if new_value > old_value and new_value >= self.max_scroll_y - 1:
            self.app.request_more()

    def on_mouse_scroll_down(self, event):
        if not event.ctrl and not event.shift and self.scroll_y >= self.max_scroll_y - 1:
            self.app.request_more()


class BrowserApp(App):
    TITLE = "myThread · 瀏覽器唯讀實驗版"
    BINDINGS = [("ctrl+q", "safe_quit", "離開"), ("ctrl+r", "read", "重新讀取"),
                ("ctrl+n", "next", "下一批"), ("ctrl+b", "open", "開啟瀏覽器")]
    CSS = """
    Horizontal { height: 3; }
    #status { height: auto; min-height: 2; }
    ListView { height: 1fr; border: round $primary; }
    ListItem { padding: 1; }
    ListItem Label { width: 1fr; }
    #article { padding: 1 2; }
    """

    def __init__(self, source):
        super().__init__()
        self.source, self.busy, self.posts_data = source, False, []
        self.next_auto_at = 0.0

    def request_more(self):
        if (self.busy or not self.posts_data or len(self.screen_stack) != 1
                or time.monotonic() < self.next_auto_at):
            return
        self.next_auto_at = time.monotonic() + 2
        self.perform("next")

    def compose(self):
        yield Header()
        with Horizontal():
            yield Button("開啟瀏覽器", id="open")
            yield Button("重新讀取", id="read")
            yield Button("下一批", id="next")
        yield Static("請開啟專用瀏覽器並手動登入，再按重新讀取。", id="status", markup=False)
        yield BridgeList()
        yield Footer()

    def action_open(self):
        self.perform("open")

    def action_safe_quit(self):
        if self.busy:
            self.notify("請等目前瀏覽器操作完成後再離開。")
        else:
            self.exit()

    def action_read(self):
        self.perform("read")

    def action_next(self):
        self.perform("next")

    def on_button_pressed(self, event: Button.Pressed):
        self.perform(event.button.id)

    @work
    async def perform(self, action):
        if self.busy or len(self.screen_stack) != 1:
            return
        self.busy = True
        status = self.query_one("#status", Static)
        status.update("載入中……")
        try:
            if action == "open":
                await self.source.open()
                status.update("瀏覽器已開啟：請手動登入／完成驗證，再按重新讀取。")
                return
            batch = await self.source.read(action == "next")
            status.update(f"[{batch.state}] {batch.message}")
            if batch.state in {"ready", "empty", "login"}:
                view = self.query_one(ListView)
                old_index = view.index
                old_scroll = view.scroll_y
                previous_ids = [post['id'] for post in self.posts_data]
                new_ids = [post['id'] for post in batch.posts]
                append_only = bool(previous_ids) and new_ids[:len(previous_ids)] == previous_ids
                if not append_only:
                    await view.clear()
                self.posts_data = batch.posts
                for index, post in enumerate(batch.posts):
                    label = Text(f"@{post['username']}\n{post['text'] or '（無文字內容）'}\n{post['permalink']}")
                    if append_only and index < len(previous_ids):
                        view.children[index].query_one(Label).update(label)
                    else:
                        await view.append(ListItem(Label(label)))
                if batch.posts:
                    if not append_only:
                        view.index = min(old_index or 0, len(batch.posts) - 1)
                        view.focus()
                    else:
                        self.call_after_refresh(view.scroll_to, y=old_scroll, animate=False)
        except Exception:
            status.update("開啟失敗：請確認已安裝 Playwright Chromium，且沒有另一個實驗版使用同一設定檔。")
        finally:
            self.next_auto_at = time.monotonic() + 2
            self.busy = False

    def on_list_view_selected(self, event: ListView.Selected):
        index = event.list_view.index
        if not self.busy and index is not None and index < len(self.posts_data):
            self.push_screen(Article(self.posts_data[index]))
