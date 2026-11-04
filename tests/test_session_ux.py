import asyncio
from unittest.mock import AsyncMock

import pytest
from textual.widgets import Button, Static

from mythread.browser import BrowserBatch, extract_posts
from mythread.browser_ui import BrowserApp, BrowserArticle, BridgeList, browser_status
from mythread.dialogs import ClearLoginDialog


def source():
    result = AsyncMock()
    result.headless = True
    result.read.return_value = BrowserBatch('ready', [])
    return result


@pytest.mark.parametrize('size', [(60, 20), (80, 24), (110, 35)])
async def test_home_actions_fit_and_clear_login_requires_confirmation(size):
    backend = source()
    app = BrowserApp(backend, auto_start=False)
    async with app.run_test(size=size) as pilot:
        assert app.query_one('#next', Button).disabled
        await pilot.click('#more-actions')
        await pilot.pause(.1)
        for button in app.query(Button):
            if button.display:
                assert button.region.right <= size[0]
                assert button.region.bottom <= size[1]
        await pilot.click('#relogin')
        await pilot.pause(.1)
        assert isinstance(app.screen, ClearLoginDialog)
        assert app.focused.id == 'cancel-clear'
        await pilot.press('escape')
        await pilot.pause(.3)
        backend.relogin.assert_not_awaited()
        backend.close.assert_not_awaited()
        await pilot.click('#relogin')
        await pilot.pause(.1)
        await pilot.click('#confirm-clear')
        await app.workers.wait_for_complete()
        backend.relogin.assert_awaited_once()


@pytest.mark.parametrize('size', [(60, 20), (80, 24), (110, 35)])
async def test_load_more_is_in_right_aligned_menu_and_shortcut_still_works(size):
    backend = source()
    posts = extract_posts([{'permalink': f'https://www.threads.com/@alice/post/P{i}',
                            'text': 'Article text'} for i in range(10)])
    backend.read.return_value = BrowserBatch('ready', posts)
    app = BrowserApp(backend, auto_start=False)
    async with app.run_test(size=size) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.query_one('#more-actions', Button).region.right == size[0]
        assert not app.query_one('#home-extra').display
        assert app.query_one('#next', Button).parent.parent.id == 'home-extra'

        await pilot.press('ctrl+n')
        await app.workers.wait_for_complete()
        backend.read.assert_awaited_with(True)
        assert not app.query_one('#home-extra').display

        await pilot.click('#more-actions')
        await pilot.pause()
        for button in app.query('#home-extra Button'):
            assert button.region.width > 0
            assert 0 <= button.region.x < button.region.right <= size[0]
            assert button.region.bottom < size[1]
        backend.read.reset_mock()
        await pilot.click('#next')
        await app.workers.wait_for_complete()
        backend.read.assert_awaited_once_with(True)
        await pilot.click('#more-actions')
        await pilot.pause()
        assert not app.query_one('#home-extra').display
        assert app.query_one('#more-actions', Button).region.right == size[0]


async def test_busy_feedback_disables_conflicting_actions_and_quit_is_queued():
    backend = source()
    started, release = asyncio.Event(), asyncio.Event()

    async def pending(*args, **kwargs):
        started.set()
        await release.wait()
        return BrowserBatch('ready', [])

    backend.read.side_effect = pending
    app = BrowserApp(backend, auto_start=False)
    async with app.run_test(size=(80, 24)) as pilot:
        app.action_read()
        await started.wait()
        assert app.busy
        assert app.query_one('#read', Button).disabled
        assert app.query_one('#open', Button).disabled
        assert '頂端' in str(app.query_one('#status', Static).render())
        await pilot.press('ctrl+r')
        assert backend.read.await_count == 1
        app.action_safe_quit()
        assert app.quit_pending
        release.set()
        await app.workers.wait_for_complete()
        assert not app.busy


async def test_timed_out_read_closes_owned_browser_and_offers_recovery():
    backend = source()
    release = asyncio.Event()

    async def pending(*args, **kwargs):
        await release.wait()
        return BrowserBatch('closed')

    backend.read.side_effect = pending
    backend.close.side_effect = release.set
    app = BrowserApp(backend, auto_start=False)
    app.OPERATION_TIMEOUT = .05
    async with app.run_test(size=(80, 24)) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        await pilot.pause()
        backend.close.assert_awaited_once()
        assert not app.busy
        assert app.state == 'closed'
        assert app.query_one('#recover', Button).region.width > 0
        assert '逾時' in str(app.query_one('#status', Static).render())


async def test_article_hides_inactive_global_shortcuts():
    backend = source()
    app = BrowserApp(backend, auto_start=False)
    post = extract_posts([{'permalink': 'https://www.threads.com/@alice/post/ONE', 'text': 'body'}])[0]
    async with app.run_test() as pilot:
        await app.push_screen(BrowserArticle(post))
        await pilot.pause()
        for key in ('ctrl+r', 'ctrl+n', 'ctrl+b'):
            binding = app.screen.active_bindings.get(key)
            assert binding is None or not binding.enabled
        await pilot.press('ctrl+r', 'ctrl+n', 'ctrl+b')
        backend.read.assert_not_awaited()
        backend.switch_mode.assert_not_awaited()


@pytest.mark.parametrize('close_failure', ['exception', 'timeout'])
async def test_read_timeout_releases_operation_even_when_browser_cleanup_fails(close_failure):
    backend = source()
    cancelled = asyncio.Event()

    async def pending_read(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def failed_close():
        if close_failure == 'exception':
            raise RuntimeError('synthetic shutdown failure')
        await asyncio.Event().wait()

    backend.read.side_effect = pending_read
    backend.close.side_effect = failed_close
    app = BrowserApp(backend, auto_start=False)
    app.OPERATION_TIMEOUT = .02
    app.CLEANUP_TIMEOUT = .02
    async with app.run_test(size=(80, 24)) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        assert cancelled.is_set()
        assert not app.busy
        assert app.state == 'closed'
        assert '逾時' in str(app.query_one('#status', Static).render())


def test_chinese_status_uses_consistent_login_action_and_hides_diagnostics():
    backend = source()
    login = browser_status(backend, BrowserBatch('login', message='請按重新整理'))
    assert '完成登入' in login and '重新整理' not in login
    status = browser_status(backend, BrowserBatch('error', message='請重試。DOM 診斷：cards=0'))
    assert 'DOM' not in status and '[error]' not in status


async def test_home_eviction_preserves_focused_and_visible_article():
    backend = source()
    posts = extract_posts([{'permalink': f'https://www.threads.com/@alice/post/P{i}',
                            'text': 'body ' * 100} for i in range(12)])
    backend.read.return_value = BrowserBatch('ready', posts)
    app = BrowserApp(backend, auto_start=False)
    async with app.run_test(size=(80, 24)) as pilot:
        app.action_read()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(BridgeList)
        view.index = 4
        view.scroll_to(y=view.children[4].virtual_region.y, animate=False)
        await pilot.pause()
        anchor = view.capture_anchor(posts)
        backend.read.return_value = BrowserBatch('ready', posts[2:])
        app.action_next()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.posts_data[view.index]['id'] == 'P4'
        assert view.capture_anchor(app.posts_data)[1:] == anchor[1:]
