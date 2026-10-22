from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static, TextArea

from .api import APIError
from .storage import StorageError


class FeedSettings(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, feed):
        super().__init__()
        self.feed = feed

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="feed-settings-box"):
            yield Label("本機推薦設定")
            yield Static("只填關鍵字也能搜尋，不需先知道帳號。\n搜尋範圍取決於 Meta 權限；本頁非官方推薦。", markup=False)
            yield Label("搜尋關鍵字：例如 比特幣, 貓（最多 20 個，以逗號或換行分隔）")
            yield TextArea(", ".join(self.feed.keywords), id="feed-keywords")
            yield Label("公開帳號（選填，最多 10 個，以逗號或換行分隔）")
            yield TextArea("\n".join(self.feed.sources), id="feed-sources")
            yield Static("", id="feed-settings-error", markup=False)
            with Horizontal():
                yield Button("取消", id="feed-cancel")
                yield Button("儲存並搜尋", id="feed-save", variant="primary")

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == "feed-cancel":
            self.dismiss(False)
        elif event.button.id == "feed-save":
            try:
                self.feed.configure(self.query_one("#feed-sources", TextArea).text,
                                    self.query_one("#feed-keywords", TextArea).text)
            except (APIError, StorageError) as exc:
                self.query_one("#feed-settings-error", Static).update(str(exc))
            else:
                self.dismiss(True)
