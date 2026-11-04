from unittest.mock import AsyncMock, Mock, call

import pytest
from rich.cells import cell_len
from textual import events
from textual.widgets import Button, Label, ListItem

from mythread.browser import BrowserBatch, extract_posts
from mythread.browser_ui import BrowserApp, BrowserArticle, BrowserReader, BridgeList, CommentsScreen
from mythread.text import EMPTY_TEXT, article_text, post_preview, text_excerpt


def posts(count=1):
    return extract_posts([{'permalink': f'https://www.threads.com/@alice/post/P{i}',
                           'text': '測試內容 [red]literal[/red] ' * 100} for i in range(count)])


async def right_click(app, pilot, widget):
    # Pilot.click bypasses App.on_event; send raw terminal events to exercise
    # interception before Textual dispatches clicks to buttons / list items.
    x, y = widget.region.x + 1, widget.region.y
    for event_type in (events.MouseDown, events.MouseUp):
        app.post_message(event_type(widget, x, y, 0, 0, 3, False, False, False))
        await pilot.pause()


@pytest.mark.parametrize('target', ['#article', '#original', '#quit-app'])
async def test_right_click_article_returns_once_and_preserves_home_position(target):
    source = AsyncMock()
    source.headless = True
    source.read.return_value = BrowserBatch('ready', posts(12))
    app = BrowserApp(source, auto_start=False)
    app.open_url = Mock()
    app.exit = Mock()
    async with app.run_test(size=(80, 24)) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        view = app.query_one(BridgeList)
        view.index = 4
        await pilot.pause()
        anchor = view.capture_anchor(app.posts_data)
        await pilot.press('enter')
        assert isinstance(app.screen, BrowserArticle)
        await right_click(app, pilot, app.screen.query_one(target))
        assert len(app.screen_stack) == 1
        assert view.capture_anchor(app.posts_data) == anchor
        app.open_url.assert_not_called()
        app.exit.assert_not_called()
        source.read.assert_awaited_once()


async def test_right_click_returns_from_reply_then_closes_comments_tab():
    source = AsyncMock()
    source.headless = True
    source.open_replies.return_value = BrowserBatch('ready', posts(12))
    app = BrowserApp(source, auto_start=False)
    async with app.run_test() as pilot:
        article = BrowserArticle(posts()[0])
        await app.push_screen(article)
        article.action_comments()
        await app.workers.wait_for_complete()
        comments = app.screen
        await app.push_screen(BrowserReader(posts()[0]))
        await right_click(app, pilot, app.screen.query_one('#article'))
        assert app.screen is comments
        source.close_replies.assert_not_awaited()
        await right_click(app, pilot, comments.query_one(BridgeList).children[0])
        await app.workers.wait_for_complete()
        assert app.screen is article
        source.close_replies.assert_awaited_once()


async def test_right_click_home_does_not_open_article():
    source = AsyncMock()
    source.headless = True
    source.read.return_value = BrowserBatch('ready', posts(12))
    app = BrowserApp(source, auto_start=False)
    async with app.run_test() as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        await right_click(app, pilot, app.query_one(BridgeList).children[0])
        assert len(app.screen_stack) == 1


@pytest.mark.parametrize('action', ['startup', 'background', 'recover', 'read', 'next'])
async def test_home_fills_short_feed_without_scrolling(action):
    source = AsyncMock()
    source.headless = True
    source.read.side_effect = [BrowserBatch('ready', posts(n)) for n in (3, 6, 10)]
    app = BrowserApp(source, auto_start=False)
    async with app.run_test() as pilot:
        app.perform(action)
        await app.workers.wait_for_complete()
        assert len(app.posts_data) == 10
        assert len(app.query_one(BridgeList).children) == 10
        assert app.query_one(BridgeList).index == 0
        assert source.read.await_args_list[1:] == [call(True), call(True)]
        assert not app.busy


@pytest.mark.parametrize('state', ['ready', 'empty', 'login', 'error', 'closed'])
async def test_home_stops_filling_when_no_progress_or_read_unavailable(state):
    source = AsyncMock()
    source.headless = True
    source.read.side_effect = [BrowserBatch('ready', posts(3)),
                               BrowserBatch(state, posts(3) if state == 'ready' else [])]
    app = BrowserApp(source, auto_start=False)
    async with app.run_test():
        app.action_read()
        await app.workers.wait_for_complete()
        assert source.read.await_count == 2
        assert app.state == state
        assert not app.busy
        if state in {'error', 'closed', 'ready'}:
            assert len(app.posts_data) == 3


@pytest.mark.parametrize('count', [0, 10, 12])
async def test_home_does_not_fill_empty_or_sufficient_feed(count):
    source = AsyncMock()
    source.headless = True
    source.read.return_value = BrowserBatch('ready' if count else 'empty', posts(count))
    app = BrowserApp(source, auto_start=False)
    async with app.run_test():
        app.action_read()
        await app.workers.wait_for_complete()
        source.read.assert_awaited_once_with(refresh=True)


async def test_home_filling_has_attempt_limit_even_if_ids_keep_changing():
    source = AsyncMock()
    source.headless = True
    source.read.side_effect = [BrowserBatch('ready', [post]) for post in posts(12)]
    app = BrowserApp(source, auto_start=False)
    async with app.run_test():
        app.action_read()
        await app.workers.wait_for_complete()
        assert source.read.await_count == app.HOME_FILL_LIMIT + 1
        assert not app.busy


def test_preview_is_bounded_safe_and_full_article_remains_available():
    post = posts()[0]
    post['text'] += '\x1b\x00'
    preview = post_preview(post, width=24)
    body = preview.splitlines()[1:]
    assert len(body) == 3
    assert all(cell_len(line) <= 24 for line in body)
    assert body[-1].endswith('…')
    assert '\x1b' not in preview and '\x00' not in preview
    assert len(article_text(post)) > len(preview)
    assert '[red]literal[/red]' in article_text(post)
    assert text_excerpt('') == EMPTY_TEXT


async def test_home_displays_complete_text_and_rewraps_without_truncation():
    source = AsyncMock()
    source.headless = True
    feed = posts(10)
    body = '完整內文[red]literal[/red]' * 30 + '\n文章尾端確認'
    feed[0]['text'] = body + '\x1b\x00'
    feed[0]['reply_count'] = '12'
    source.read.return_value = BrowserBatch('ready', feed)
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(110, 35)) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(BridgeList)
        for width in (110, 60):
            if width == 60:
                await pilot.resize_terminal(width, 20)
                await pilot.pause()
            rendered = str(view.children[0].query_one(Label).render())
            assert '留言 12' in rendered.splitlines()[0]
            assert ''.join(rendered.splitlines()[1:]) == body.replace('\n', '')
            assert all(cell_len(line) <= width - 6 for line in rendered.splitlines())
            assert view.children[0].region.height > 7
            assert view.index == 0
        source.read.assert_awaited_once_with(refresh=True)


@pytest.mark.parametrize('count, expected', [(None, '-'), ('0', '0'), ('2.5萬', '2.5萬')])
def test_home_list_reply_count_distinguishes_unknown_from_zero(count, expected):
    post = posts()[0]
    if count is not None:
        post['reply_count'] = count
    assert f'留言 {expected}' in post_preview(post, lines=None).splitlines()[0]


@pytest.mark.parametrize('reader_type', [BrowserReader, BrowserArticle])
async def test_original_button_and_shortcut_are_explicit_and_preserve_screen(reader_type):
    source = AsyncMock()
    source.headless = True
    app = BrowserApp(source, auto_start=False)
    app.open_url = Mock()
    post = posts()[0]
    async with app.run_test(size=(60, 20)) as pilot:
        reader = reader_type(post)
        await app.push_screen(reader)
        await pilot.pause()
        app.open_url.assert_not_called()
        for button in reader.query(Button):
            assert button.region.right <= 60
        await pilot.click('#original')
        await pilot.press('o')
        assert app.screen is reader
        assert app.open_url.call_count == 2
        app.open_url.assert_called_with(post['permalink'])


async def test_original_rejects_untrusted_url():
    app = BrowserApp(AsyncMock(), auto_start=False)
    app.open_url = Mock()
    async with app.run_test() as pilot:
        await app.push_screen(BrowserReader({'username': 'alice', 'text': '',
                                            'permalink': 'https://evil.test/'}))
        await pilot.press('o')
        app.open_url.assert_not_called()


async def test_comments_preview_context_busy_controls_and_eviction_anchor():
    source = AsyncMock()
    source.headless = True
    replies = posts(12)
    source.open_replies.return_value = BrowserBatch('ready', replies)
    source.replies.read.return_value = BrowserBatch('ready', replies[2:] + posts(15)[12:])
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(60, 20)) as pilot:
        screen = CommentsScreen(posts()[0])
        await app.push_screen(screen)
        await app.workers.wait_for_complete()
        await pilot.pause()
        for button in screen.query(Button):
            assert button.region.right <= 60
        assert '僅顯示' in str(screen.query_one('#comments-caveat').render())
        view = screen.query_one(BridgeList)
        assert view.children[0].region.height <= 7
        assert 'https://' not in str(view.children[0].query_one(Label).render())
        view.index = 6
        await pilot.pause()
        anchor = view.capture_anchor(screen.posts_data)
        screen.action_more()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert screen.posts_data[view.index]['id'] == anchor[0]
        assert view.capture_anchor(screen.posts_data)[1:] == anchor[1:]
        assert not screen.query_one('#comments-more', Button).disabled


@pytest.mark.parametrize('back_method', ['escape', 'right_click'])
async def test_comments_buttons_disable_while_reading_but_back_remains_available(back_method):
    import asyncio

    started, released = asyncio.Event(), asyncio.Event()
    source = AsyncMock()
    source.headless = True

    async def opening(post):
        started.set()
        await released.wait()
        return BrowserBatch('ready', [])

    async def close():
        released.set()

    source.open_replies.side_effect = opening
    source.close_replies.side_effect = close
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(60, 20)) as pilot:
        screen = CommentsScreen(posts()[0])
        await app.push_screen(screen)
        await started.wait()
        assert screen.query_one('#comments-read', Button).disabled
        assert screen.query_one('#comments-more', Button).disabled
        assert not screen.query_one('#comments-back', Button).disabled
        if back_method == 'right_click':
            await right_click(app, pilot, screen.query_one('#comments-context'))
        else:
            await pilot.press('escape')
        await app.workers.wait_for_complete()
        assert len(app.screen_stack) == 1


async def test_resize_rewraps_previews_without_requesting_more():
    source = AsyncMock()
    source.headless = True
    source.open_replies.return_value = BrowserBatch('ready', posts(8))
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(110, 35)) as pilot:
        screen = CommentsScreen(posts()[0])
        await app.push_screen(screen)
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = screen.query_one(BridgeList)
        view.index = 3
        await pilot.pause()
        selected = screen.posts_data[view.index]['id']
        await pilot.resize_terminal(60, 20)
        await pilot.pause()
        assert all(child.region.height <= 7 for child in view.children)
        assert screen.posts_data[view.index]['id'] == selected
        source.replies.read.assert_not_awaited()


async def test_cancelled_anchor_completion_does_not_break_ui_callbacks():
    import asyncio

    source = AsyncMock()
    source.headless = True
    source.open_replies.return_value = BrowserBatch('ready', posts(8))
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(60, 20)) as pilot:
        screen = CommentsScreen(posts()[0])
        await app.push_screen(screen)
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = screen.query_one(BridgeList)
        settled = view.restore_anchor(view.capture_anchor(screen.posts_data), screen.posts_data)
        settled.cancel()
        refreshed = asyncio.Event()
        app.call_after_refresh(refreshed.set)
        await asyncio.wait_for(refreshed.wait(), timeout=5)
        assert settled.cancelled()
        assert not view.restoring_anchor
