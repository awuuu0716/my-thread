from unittest.mock import AsyncMock

import pytest
from textual.widgets import Static

from mythread.browser import BrowserSource, BrowserBatch, SNAPSHOT, SCROLL, classify, extract_posts
from mythread.browser_ui import BrowserApp, BridgeList
from mythread.browser_ui import BrowserReader as Article


def row(code="ABC", text="中文\nhello"):
    return {"permalink": f"https://www.threads.net/@alice/post/{code}?x=1", "text": text}


def test_normalize_and_dedupe():
    posts = extract_posts([row(), row(text="更新\x1b"),
                           {"permalink": "https://evil.test/@alice/post/ABC", "text": "bad"}])
    assert posts == [{"id": "ABC", "username": "alice", "text": "更新",
                      "permalink": "https://www.threads.com/@alice/post/ABC"}]


@pytest.mark.parametrize("snapshot,state", [({}, "error"), ({"login": True}, "login"),
    ({"loading": True}, "loading"), ({"empty": True}, "empty"),
    ({"empty": True, "candidates": 1}, "error"), ({"rows": [row()]}, "ready")])
def test_states(snapshot, state):
    assert classify(snapshot).state == state


@pytest.mark.parametrize('state', ['ready', 'login'])
async def test_startup_opens_browser_then_reads_automatically(state):
    calls = []
    source = AsyncMock()

    async def open_browser():
        calls.append('open')

    async def read(next_batch):
        calls.append(('read', next_batch))
        return BrowserBatch(state, extract_posts([row()]) if state == 'ready' else [], 'test status')

    source.open.side_effect = open_browser
    source.read.side_effect = read
    app = BrowserApp(source)
    async with app.run_test(size=(110, 35)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert calls == ['open', ('read', False)]
        assert len(app.posts_data) == (1 if state == 'ready' else 0)
        assert app.state == state
        expected_status = '已載入' if state == 'ready' else '需要登入'
        assert expected_status in str(app.query_one('#status', Static).render())


async def test_startup_waits_for_rendered_feed():
    source = AsyncMock()
    source.read.side_effect = [BrowserBatch('loading'), BrowserBatch('ready', extract_posts([row()]))]
    app = BrowserApp(source)
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        source.open.assert_awaited_once()
        assert source.read.await_count == 2
        assert len(app.posts_data) == 1


async def test_virtual_list_retention_and_duplicates():
    source = BrowserSource()
    source.page = AsyncMock()
    source.page.is_closed = lambda: False
    source.page.url = "https://www.threads.com/"
    source.page.evaluate.side_effect = [{"rows": [row()]}, {"rows": [row()]}, True, {"rows": [row("DEF")]}]
    assert len((await source.read()).posts) == 1
    batch = await source.read(True)
    assert [p["id"] for p in batch.posts] == ["ABC", "DEF"]
    assert any(call.args == (SCROLL,) for call in source.page.evaluate.await_args_list)
    source.page.evaluate.side_effect = RuntimeError("sensitive diagnostic")
    batch = await source.read()
    assert batch.state == "error" and "sensitive" not in batch.message
    assert len(source.posts) == 2


async def test_ui_read_next_and_readonly():
    source = AsyncMock()
    source.read.return_value = BrowserBatch("ready", extract_posts([row()]), "完成")
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.click("#open")
        await app.workers.wait_for_complete()
        source.switch_mode.assert_awaited_once_with(False)
        await pilot.press("ctrl+r")
        await app.workers.wait_for_complete()
        source.read.assert_awaited_with(refresh=True)
        assert len(app.posts_data) == 1
        await pilot.press("enter")
        assert isinstance(app.screen, Article)
        await pilot.press("escape", "ctrl+n")
        await app.workers.wait_for_complete()
        source.read.assert_awaited_with(True)
        await pilot.press("ctrl+w")
        assert len(app.screen_stack) == 1


async def test_next_scrolls_again_and_stops_at_limit(monkeypatch):
    monkeypatch.setattr('mythread.browser.asyncio.sleep', AsyncMock())
    source = BrowserSource()
    source.page = AsyncMock()
    source.page.is_closed = lambda: False
    source.page.url = 'https://www.threads.com/'
    scrolls = 0

    async def evaluate(script):
        nonlocal scrolls
        if script == SCROLL:
            scrolls += 1
            return True
        return {'rows': [row('DEF' if scrolls >= 3 else 'ABC')]}

    source.page.evaluate.side_effect = evaluate
    result = await source.read(True)
    assert scrolls == 3
    assert [p['id'] for p in result.posts] == ['ABC', 'DEF']
    result = await source.read(True)
    assert scrolls == 9  # Six attempts, no endless automatic scrolling.
    assert len(result.posts) == 2
    assert '新增 0' in result.message


async def test_terminal_scroll_loads_more_without_rebuilding_or_looping():
    first = extract_posts([row(str(i), '正文\n' * 8) for i in range(4)])
    source = AsyncMock()
    source.read.side_effect = [BrowserBatch('ready', first),
                              BrowserBatch('ready', first + extract_posts([row('NEW')]))]
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(100, 25)) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(BridgeList)
        original_item = view.children[0]
        app.next_auto_at = 0
        view.scroll_end(animate=False)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert source.read.await_count == 2
        source.read.assert_awaited_with(True)
        assert view.children[0] is original_item
        assert view.scroll_y > 0
        assert len(app.posts_data) == 5
        # Upward scrolling and layout changes do not request another browser batch.
        view.scroll_home(animate=False)
        await pilot.pause()
        assert source.read.await_count == 2


@pytest.mark.parametrize('busy', [False, True])
async def test_near_bottom_prefetch_survives_cooldown_without_another_scroll(busy):
    import time
    posts = extract_posts([row(str(i), '正文\n' * 10) for i in range(5)])
    source = AsyncMock()
    source.read.return_value = BrowserBatch('ready', posts)
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(100, 25)) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(BridgeList)
        app.next_auto_at = time.monotonic() + .2
        app.busy = busy
        view.scroll_to(y=view.max_scroll_y - 5, animate=False)
        await pilot.pause(.05)
        assert view.scroll_y < view.max_scroll_y
        assert source.read.await_count == 1
        app.busy = False
        await pilot.pause(.4)
        await app.workers.wait_for_complete()
        assert source.read.await_count == 2
        source.read.assert_awaited_with(True)
        # No new rows does not cause an automatic retry loop.
        await pilot.pause(.3)
        assert source.read.await_count == 2


def test_real_chromium_synthetic_dom():
    # Real browser engine, synthetic HTML only. This is NOT a Threads live test.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content('''<div id="feed" style="height:200px;overflow-y:auto">
                <a href="https://www.threads.com/@alice/post/A">post</a>
                <div style="height:2000px">feed</div></div>''')
            assert page.evaluate(SCROLL)
            assert page.locator('#feed').evaluate('(e) => e.scrollTop') > 0
            assert page.evaluate('window.scrollY') == 0
            page.set_content('''<main><p>navigation must not become a post</p>
              <article><a href="https://www.threads.com/@alice/post/ABC">1h</a>
              <a href="/@alice"><span dir="auto">alice</span></a>
              <div dir="auto">中文貼文</div><button><span dir="auto">Like</span></button></article>
              <article hidden><a href="https://www.threads.com/@bob/post/HIDDEN">2h</a>
              <div dir="auto">hidden</div></article></main>''')
            batch = classify(page.evaluate(SNAPSHOT))
            assert len(batch.posts) == 1
            assert batch.posts[0]["text"] == "中文貼文"
            page.set_content('<main><p>unknown layout</p></main>')
            assert classify(page.evaluate(SNAPSHOT)).state == "error"
            page.set_content('''<div><div><a href="/@alice">alice</a>
                <a href="https://www.threads.com/@alice/post/DEF">1h</a></div>
                <div dir="auto">fallback text</div></div>''')
            assert classify(page.evaluate(SNAPSHOT)).posts[0]["text"] == "fallback text"
            # Reported layout: timestamp is a sibling of the permalink, outside <time>.
            page.set_content('''<main><div role="button"><div>
                <a href="/@alice">alice</a><a href="https://www.threads.com/@alice/post/TIME">link</a>
                <span dir="auto">46分鐘</span></div>
                <div dir="auto">這才是文章正文<br>第二行</div></div>
                <div><a href="/@bob">bob</a><a href="https://www.threads.com/@bob/post/NEXT">link</a>
                <span dir="auto">8小時</span><div dir="auto">另一篇文章</div></div></main>''')
            posts = classify(page.evaluate(SNAPSHOT)).posts
            assert [p['text'] for p in posts] == ['這才是文章正文\n第二行', '另一篇文章']
            page.set_content('''<div><a href="/@alice">alice</a>
                <a href="https://www.threads.com/@alice/post/TIME">link</a>
                <span dir="auto">46分鐘</span><img alt="alice profile picture"></div>''')
            assert classify(page.evaluate(SNAPSHOT)).state == 'error'
            page.set_content('''<article><a href="https://www.threads.com/@alice/post/A">1h</a>
                <div dir="auto">outer</div><article><a href="https://www.threads.com/@bob/post/B">2h</a>
                <div dir="auto">quote</div></article></article>''')
            posts = classify(page.evaluate(SNAPSHOT)).posts
            assert len(posts) == 1 and posts[0]["username"] == "bob"
            page.set_content('<input type="password">')
            assert classify(page.evaluate(SNAPSHOT)).state == "login"
        finally:
            browser.close()
