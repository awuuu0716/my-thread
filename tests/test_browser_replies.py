from unittest.mock import AsyncMock
import asyncio
import pytest

from mythread.browser import BrowserBatch, BrowserSource, ReplySource, SNAPSHOT, extract_posts
from mythread.browser import SCROLL
from mythread.browser_ui import BrowserApp, BrowserArticle, CommentsScreen
from mythread.tui import Article


def row(code):
    return {'permalink': f'https://www.threads.com/@alice/post/{code}', 'text': code}


@pytest.mark.parametrize('replies', [False, True])
async def test_refresh_reloads_and_replaces_previous_collection(replies):
    source = ReplySource('ROOT') if replies else BrowserSource()
    source.page = AsyncMock()
    source.page.is_closed = lambda: False
    source.page.url = row('ROOT')['permalink']
    source.posts = {'OLD': extract_posts([row('OLD')])[0]}

    async def evaluate(script, *args):
        if script == SCROLL:
            assert args == (True,)
            return False
        return {'anchor_found': True, 'rows': [row('NEW')]}

    source.page.evaluate.side_effect = evaluate
    result = await source.read(refresh=True)
    source.page.reload.assert_awaited_once()
    assert result.state == 'ready'
    assert [p['id'] for p in result.posts] == ['NEW']
    assert 'OLD' not in source.posts


async def test_reply_anchor_dedup_virtualization_and_wrong_page(monkeypatch):
    monkeypatch.setattr('mythread.browser.asyncio.sleep', AsyncMock())
    source = ReplySource('ROOT')
    source.page = AsyncMock()
    source.page.is_closed = lambda: False
    source.page.url = row('ROOT')['permalink']
    source.page.evaluate.return_value = {'rows': [row('ANCESTOR'), row('ROOT'), row('REPLY'), row('REPLY')]}
    assert [p['id'] for p in (await source.read()).posts] == ['REPLY']
    source.page.evaluate.return_value = {'rows': [row('REPLY'), row('NEXT')]}
    assert [p['id'] for p in (await source.read()).posts] == ['REPLY', 'NEXT']
    source.page.url = row('OTHER')['permalink']
    assert (await source.read()).state == 'error'


async def test_reply_unknown_is_not_no_comments(monkeypatch):
    monkeypatch.setattr('mythread.browser.asyncio.sleep', AsyncMock())
    source = ReplySource('ROOT')
    source.page = AsyncMock()
    source.page.is_closed = lambda: False
    source.page.url = row('ROOT')['permalink']
    source.page.evaluate.return_value = {'rows': [row('UNRELATED')]}
    assert (await source.read()).state == 'error'
    assert source.posts == {}
    source.page.evaluate.return_value = {'rows': [row('ROOT')]}
    assert (await source.read()).state == 'unconfirmed'
    source.page.evaluate.return_value = {'login': True}
    assert (await source.read()).state == 'login'


async def test_reply_permalink_anchor_does_not_require_parent_body():
    source = ReplySource('ROOT')
    source.page = AsyncMock()
    source.page.is_closed = lambda: False
    source.page.url = row('ROOT')['permalink']
    source.page.evaluate.return_value = {'anchor_found': True, 'rows': [row('REPLY')]}
    result = await source.read()
    assert result.state == 'ready'
    assert [p['id'] for p in result.posts] == ['REPLY']


async def test_open_replies_separate_tab_and_cleanup(monkeypatch):
    monkeypatch.setattr('mythread.browser.asyncio.sleep', AsyncMock())
    source = BrowserSource()
    source.context = AsyncMock()
    home = source.page = AsyncMock()
    tab = source.context.new_page.return_value
    tab.is_closed = lambda: False
    tab.url = row('ROOT')['permalink']
    tab.evaluate.return_value = {'rows': [row('ROOT'), row('REPLY')]}
    result = await source.open_replies(row('ROOT'))
    assert result.posts[0]['id'] == 'REPLY'
    assert source.page is home
    home.goto.assert_not_awaited()
    await source.close_replies()
    tab.close.assert_awaited_once()
    assert source.replies is None
    result = await source.open_replies({'permalink': 'https://evil.test/'})
    assert result.state == 'error'
    assert source.context.new_page.await_count == 1


@pytest.mark.parametrize('use_mouse', [True, False])
async def test_comments_screen_read_more_detail_and_back(use_mouse):
    source = AsyncMock()
    parent = extract_posts([row('ROOT')])
    replies = extract_posts([row('REPLY')])
    source.read.return_value = BrowserBatch('ready', parent)
    source.open_replies.return_value = BrowserBatch('ready', replies)
    source.replies.read.return_value = BrowserBatch('ready', replies + extract_posts([row('NEXT')]))
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(110, 35)) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press('enter')
        assert isinstance(app.screen, BrowserArticle)
        if use_mouse:
            await pilot.click('#comments')
        else:
            await pilot.press('c')
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, CommentsScreen)
        assert len(app.screen.posts_data) == 1
        await pilot.press('ctrl+n')
        await app.workers.wait_for_complete()
        assert len(app.screen.posts_data) == 2
        source.replies.read.assert_awaited_with(True)
        await pilot.press('enter')
        assert isinstance(app.screen, Article)
        await pilot.press('escape', 'escape')
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, BrowserArticle)
        source.close_replies.assert_awaited_once()
        assert app.posts_data == parent
        await pilot.click('#back')
        await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.parametrize('cancelled', [True, False])
async def test_failed_or_cancelled_navigation_closes_unfinished_tab(cancelled):
    source = BrowserSource()
    source.context = AsyncMock()
    tab = source.context.new_page.return_value
    tab.is_closed = lambda: False
    tab.goto.side_effect = asyncio.CancelledError() if cancelled else RuntimeError('navigation failed')
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await source.open_replies(row('ROOT'))
    else:
        result = await source.open_replies(row('ROOT'))
        assert result.state == 'error'
    tab.close.assert_awaited_once()
    assert source.replies is None


def test_reply_dom_ignores_navigation_and_recommendations():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        try:
            page = browser.new_page()
            def card(code):
                return f'<article><a href="{row(code)["permalink"]}">link</a><div dir="auto">{code}</div></article>'
            page.set_content(card('NAV') + '<main>' + card('ROOT') + card('REPLY') +
                             '<h2>Recommended posts</h2>' + card('OTHER') + '</main>')
            snapshot = page.evaluate(SNAPSHOT, {'replies': True})
            assert [p['id'] for p in extract_posts(snapshot['rows'])] == ['ROOT', 'REPLY']
            # No semantic main; root has no supported text block. Its permalink
            # must anchor the discussion without requiring successful body parsing.
            page.set_content('<nav>' + card('NAV') + '</nav><div>' + card('ANCESTOR') +
                f'<div><a href="{row("ROOT")["permalink"]}">original post</a></div>' +
                card('REPLY') + '<h2>推薦貼文</h2>' + card('OTHER') + '</div>')
            snapshot = page.evaluate(SNAPSHOT, {'replies': True, 'parent_id': 'ROOT'})
            assert snapshot['anchor_found']
            assert snapshot['diagnostics']['main'] is False
            assert [p['id'] for p in extract_posts(snapshot['rows'])] == ['REPLY']
        finally:
            browser.close()


async def test_browser_titles_survive_repeated_screen_mount_and_unmount():
    from textual.widgets import Header
    from mythread.browser_ui import BrowserReader, BrowserTitle

    source = AsyncMock()
    post = extract_posts([row('ROOT')])[0]
    source.open_replies.return_value = BrowserBatch('ready', [])
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(100, 30)) as pilot:
        assert len(app.screen.query(BrowserTitle)) == 1
        assert not app.screen.query(Header)
        for _ in range(4):
            for screen in (BrowserArticle(post), CommentsScreen(post), BrowserReader(post)):
                await app.push_screen(screen)
                await app.workers.wait_for_complete()
                assert len(screen.query(BrowserTitle)) == 1
                assert not screen.query(Header)
                app.title = 'title changed while switching'
                app.sub_title = 'subtitle changed while switching'
                await app.pop_screen()
                app.title = 'after removal'
                await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.parametrize('timeout', [False, True])
async def test_busy_comments_can_return_or_time_out(timeout):
    started, released = asyncio.Event(), asyncio.Event()
    source = AsyncMock()

    async def pending_open(post):
        started.set()
        await released.wait()
        return BrowserBatch('closed')

    async def close():
        released.set()

    source.open_replies.side_effect = pending_open
    source.close_replies.side_effect = close
    app = BrowserApp(source, auto_start=False)
    screen = CommentsScreen(extract_posts([row('ROOT')])[0])
    if timeout:
        screen.READ_TIMEOUT = .05
    async with app.run_test(size=(110, 35)) as pilot:
        await app.push_screen(screen)
        await started.wait()
        if timeout:
            await app.workers.wait_for_complete()
            from textual.widgets import Static
            assert '逾時' in str(screen.query_one('#comments-status', Static).render())
            assert not screen.busy
        else:
            await pilot.press('escape')
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app.screen_stack) == 1
        source.close_replies.assert_awaited_once()
