from textual.widgets import Button, Input, ListView, Static

from mythread.account_ui import AccountScreen
from mythread.api import APIError, DemoClient
from mythread.storage import Store, StorageError
from mythread.tui import ThreadsApp


class MemoryStore(Store):
    def __init__(self, directory):
        super().__init__(directory)
        self.token = "old-token"
        self.fail_save = False

    def save_token(self, token, *args):
        if self.fail_save:
            raise StorageError("憑證庫無法寫入")
        self.token = token

    def logout(self):
        self.token = None
        self.write("draft.json", {})
        self.write("feed-seen.json", {})


class Client(DemoClient):
    def __init__(self, token):
        self.token = token
        self.closed = False
        self.post_queries = []

    async def me(self):
        if self.token == "bad-token":
            raise APIError("授權已失效")
        return {"id": "1", "username": "new_account"}

    async def posts(self, username="", after=None):
        self.post_queries.append(username)
        return await super().posts(username, after)

    async def close(self):
        self.closed = True


async def enter_token(app, pilot, token):
    await pilot.pause(0.1)
    field = app.screen.query_one("#account-token", Input)
    assert field.password
    field.value = token
    field.focus()
    await pilot.press("enter")
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)


async def test_signed_out_launch_login_and_no_token_in_profile_requests(tmp_path):
    store = MemoryStore(tmp_path)
    app = ThreadsApp(None, store, client_factory=Client)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.screen, AccountScreen)
        await enter_token(app, pilot, "new-token")
        assert not isinstance(app.screen, AccountScreen)
        assert store.token == "new-token"
        assert app.client.post_queries == [""]
        assert app.posts_data
        assert "new_account" in app.account_label
        assert "new-token" not in "".join(p.read_text() for p in tmp_path.iterdir())


async def test_bad_token_keeps_current_connection_and_clears_input(tmp_path):
    store = MemoryStore(tmp_path)
    old = Client("old-token")
    app = ThreadsApp(old, store, client_factory=Client)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        previous = list(app.posts_data)
        await pilot.click("#account")
        await enter_token(app, pilot, "bad-token")
        assert isinstance(app.screen, AccountScreen)
        assert app.screen.query_one(Input).value == ""
        assert app.client is old and not old.closed
        assert store.token == "old-token"
        assert app.posts_data == previous


async def test_switch_clears_old_state_and_closes_old_client(tmp_path):
    store = MemoryStore(tmp_path)
    store.write("draft.json", {"text": "old draft"})
    store.write("feed-seen.json", {"seen": {"old-post": 1}})
    old = Client("old-token")
    app = ThreadsApp(old, store, client_factory=Client)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.click("#account")
        await enter_token(app, pilot, "new-token")
        assert old.closed
        assert app.client is not old
        assert store.read("draft.json") == {}
        assert app.feed.seen == {}


async def test_logout_confirmation_and_relogin(tmp_path):
    store = MemoryStore(tmp_path)
    old = Client("old-token")
    app = ThreadsApp(old, store, client_factory=Client)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.click("#account")
        await pilot.pause(0.1)
        await pilot.click("#account-logout")
        assert app.client is old
        await pilot.pause(0.4)
        app.screen.query_one("#account-logout", Button).focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert store.token is None
        assert app.client is None and old.closed
        assert not app.posts_data
        assert len(app.query_one(ListView).children) == 0
        assert app.screen.query_one("#account-logout", Button).disabled
        await enter_token(app, pilot, "second-token")
        assert app.client is not None
        assert store.token == "second-token"


async def test_failed_credential_save_keeps_session(tmp_path):
    store = MemoryStore(tmp_path)
    store.fail_save = True
    old = Client("old-token")
    app = ThreadsApp(old, store, client_factory=Client)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.click("#account")
        await enter_token(app, pilot, "new-token")
        assert app.client is old
        assert not old.closed
        assert store.token == "old-token"
        assert isinstance(app.screen, AccountScreen)


async def test_cancel_login_and_empty_token_no_api_call(tmp_path):
    def forbidden(token):
        raise AssertionError("Empty token must not connect")
    app = ThreadsApp(None, MemoryStore(tmp_path), client_factory=forbidden)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        await enter_token(app, pilot, " ")
        assert isinstance(app.screen, AccountScreen)
        await pilot.press("escape")
        assert len(app.screen_stack) == 1
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert isinstance(app.screen, AccountScreen)
