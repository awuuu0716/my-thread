from unittest.mock import AsyncMock, Mock

import pytest
from rich.cells import cell_len
from textual.widgets import Button, Label, ListItem

from mythread.browser import BrowserBatch, extract_posts
from mythread.browser_ui import BrowserApp, BrowserArticle, BrowserReader, BridgeList, CommentsScreen
from mythread.text import EMPTY_TEXT, article_text, post_preview, text_excerpt


def posts(count=1):
    return extract_posts([{'permalink': f'https://www.threads.com/@alice/post/P{i}',
                           'text': '測試內容 [red]literal[/red] ' * 100} for i in range(count)])


def test_preview_is_bounded_safe_and_full_article_remains_available():
    post = posts()[0]
    post['text'] += '\x1b\x00'
    preview = post_preview(post, width=24)
    body = preview.splitlines()[1:-1]
    assert len(body) == 3
    assert all(cell_len(line) <= 24 for line in body)
    assert body[-1].endswith('…')
    assert '\x1b' not in preview and '\x00' not in preview
    assert len(article_text(post)) > len(preview)
    assert '[red]literal[/red]' in article_text(post)
    assert text_excerpt('') == EMPTY_TEXT


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


async def test_comments_buttons_disable_while_reading_but_back_remains_available():
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
