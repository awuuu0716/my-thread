from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from .api import APIError
from .storage import StorageError


class AccountScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "返回")]

    def __init__(self, message=""):
        super().__init__()
        self.message = message
        self.pending = False
        self.confirm_logout = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="account-box"):
            yield Label("帳號登入／登出")
            yield Static("", id="account-current", markup=False)
            yield Static("貼上 Threads User Access Token；輸入會遮罩，驗證後存入系統憑證庫。\n更新 Token 或切換帳號會清除舊草稿與已讀紀錄，保留推薦設定。", markup=False)
            yield Input(placeholder="貼上 Token，按 Enter 登入", password=True, id="account-token")
            yield Static(self.message, id="account-error", markup=False)
            with Horizontal():
                yield Button("登入／更新", id="account-login", variant="primary")
                yield Button("登出", id="account-logout", variant="warning")
                yield Button("返回", id="account-cancel")

    def on_mount(self):
        self.query_one("#account-current", Static).update(self.app.account_label)
        self.query_one("#account-logout", Button).disabled = self.app.client is None
        self.query_one(Input).focus()

    def action_cancel(self):
        if not self.pending:
            self.query_one(Input).value = ""
            self.dismiss()

    def on_input_submitted(self, event: Input.Submitted):
        event.stop()  # Never bubble the Token into the public-profile input handler.
        if not self.pending:
            self.login()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if self.pending:
            return
        if event.button.id == "account-cancel":
            self.action_cancel()
        elif event.button.id == "account-login":
            self.login()
        elif event.button.id == "account-logout":
            if self.confirm_logout:
                self.logout()
            else:
                self.confirm_logout = True
                event.button.label = "確認登出"
                self.query_one("#account-error", Static).update("登出將清除本機 Token、草稿和已讀紀錄；不撤銷 Meta 端授權。再按一次確認。")

    def set_pending(self, pending):
        self.pending = pending
        self.app.auth_busy = pending
        for button in self.query(Button):
            button.disabled = pending or (button.id == "account-logout" and self.app.client is None)
        self.query_one(Input).disabled = pending

    @work
    async def login(self):
        if self.pending:
            return
        field = self.query_one(Input)
        token = field.value.strip()
        field.value = ""
        if not token:
            self.query_one("#account-error", Static).update("請先貼上 Token。")
            return
        self.set_pending(True)
        self.query_one("#account-error", Static).update("正在驗證帳號……")
        try:
            await self.app.replace_account(token)
        except (APIError, StorageError) as exc:
            self.query_one("#account-error", Static).update(str(exc))
        else:
            self.dismiss()
            self.app.load_posts("")
        finally:
            token = ""
            self.set_pending(False)

    @work
    async def logout(self):
        if self.pending:
            return
        self.set_pending(True)
        try:
            await self.app.logout_account()
        except StorageError as exc:
            self.query_one("#account-error", Static).update(str(exc))
        else:
            self.query_one(Input).value = ""
            self.query_one("#account-current", Static).update(self.app.account_label)
            self.query_one("#account-error", Static).update("已登出。可貼上 Token 重新登入。")
            self.confirm_logout = False
            self.query_one("#account-logout", Button).label = "登出"
        finally:
            self.set_pending(False)
