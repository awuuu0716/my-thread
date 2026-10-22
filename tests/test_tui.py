from textual.widgets import ListView, TextArea, Button

from mythread.api import DemoClient, PublishUncertain
from mythread.storage import Store
from mythread.tui import ThreadsApp, Article, Composer, Confirm
from mythread.feed_ui import FeedSettings


async def test_keyboard_read_pagination_and_draft(tmp_path):
    store = Store(tmp_path)
    app = ThreadsApp(DemoClient(), store, demo=True)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.pause()
        assert len(app.posts_data) == 3
        app.query_one(ListView).focus()
        await pilot.press("enter")
        assert isinstance(app.screen, Article)
        await pilot.press("escape")
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert len(app.posts_data) == 1
        assert app.cursor is None
        await pilot.press("ctrl+w")
        assert isinstance(app.screen, Composer)
        app.screen.query_one(TextArea).load_text("中文草稿\n🧵")
        await pilot.pause()
        assert store.read("draft.json")["text"] == "中文草稿\n🧵"
        await pilot.click("#preview")
        await pilot.pause()
        assert isinstance(app.screen, Confirm)
        await pilot.press("escape")
        assert isinstance(app.screen, Composer)
        await pilot.press("escape")
        await pilot.press("ctrl+w")
        assert app.screen.query_one(TextArea).text == "中文草稿\n🧵"


async def test_uncertain_publish_disables_retry_and_keeps_draft(tmp_path):
    class Client(DemoClient):
        calls = 0
        async def publish(self, text):
            self.calls += 1
            raise PublishUncertain("請先確認是否已發布")
    client = Client()
    store = Store(tmp_path)
    app = ThreadsApp(client, store)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+w")
        app.screen.query_one(TextArea).load_text("保留我")
        await pilot.pause()
        await pilot.click("#preview")
        await pilot.pause()
        assert client.calls == 0
        await pilot.click("#confirm")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert client.calls == 1
        assert app.screen.query_one("#preview", Button).disabled
        assert store.read("draft.json")["text"] == "保留我"


async def test_success_clears_draft(tmp_path):
    class Client(DemoClient):
        async def publish(self, text):
            return "published-id"
    store = Store(tmp_path)
    app = ThreadsApp(Client(), store)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+w")
        app.screen.query_one(TextArea).load_text("test")
        await pilot.pause()
        await pilot.click("#preview")
        await pilot.pause()
        await pilot.click("#confirm")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert store.read("draft.json").get("text", "") == ""
        assert app.screen.query_one(TextArea).text == ""


async def test_small_terminal_layout(tmp_path):
    app = ThreadsApp(DemoClient(), Store(tmp_path), demo=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        for selector in ("#mine", "#profile", "#compose", "#reload", "#next", "#recommend", "#feed-settings", "#account"):
            region = app.query_one(selector).region
            assert region.right <= 80
            assert region.bottom <= 24
        assert app.query_one(ListView).region.height >= 8


async def test_recommendation_setup_read_and_return_to_own_posts(tmp_path):
    store = Store(tmp_path)
    app = ThreadsApp(DemoClient(), store)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.click("#recommend")
        assert isinstance(app.screen, FeedSettings)
        app.screen.query_one("#feed-sources", TextArea).load_text("alice,bob")
        app.screen.query_one("#feed-keywords", TextArea).load_text("文字")
        await pilot.pause()
        await pilot.click("#feed-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.feed_mode
        assert len(app.posts_data) == 18
        selected_id = app.posts_data[0]["id"]
        await pilot.press("enter")
        assert isinstance(app.screen, Article)
        assert selected_id in store.read("feed-seen.json")["seen"]
        await pilot.press("escape")
        await pilot.press("ctrl+n")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.posts_data) == 2
        assert not app.feed_more
        await pilot.click("#mine")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not app.feed_mode
        assert len(app.posts_data) == 3


async def test_recommendation_settings_cancel_preserves_feed(tmp_path):
    app = ThreadsApp(DemoClient(), Store(tmp_path), demo=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+f")
        await app.workers.wait_for_complete()
        await pilot.pause()
        previous_ids = [p["id"] for p in app.posts_data]
        await pilot.click("#feed-settings")
        await pilot.pause(0.1)
        app.screen.query_one("#feed-sources", TextArea).load_text("changed")
        await pilot.press("escape")
        assert [p["id"] for p in app.posts_data] == previous_ids
        assert app.feed.sources == ["demo", "design", "coding"]


async def test_keyword_only_recommendation_in_small_terminal(tmp_path):
    store = Store(tmp_path)
    app = ThreadsApp(DemoClient(), store)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.click("#recommend")
        await pilot.pause()
        app.screen.query_one("#feed-keywords", TextArea).load_text("比特幣, 貓")
        assert app.screen.query_one("#feed-sources", TextArea).text == ""
        await pilot.pause()
        assert await pilot.click("#feed-save")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.feed_mode
        assert len(app.posts_data) == 20
        assert all(p.get("_search_terms") for p in app.posts_data)
        await pilot.press("ctrl+n")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.posts_data) == 4
        assert not app.feed_more
