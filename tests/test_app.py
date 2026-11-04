from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest

from mythread.browser import BrowserBatch, BrowserSource
from mythread.browser_ui import BrowserApp
from mythread.cli import parser, run
from mythread.runtime import configure_browser_runtime
from mythread.text import article_text, plain


def test_single_entry_and_removed_api_commands():
    assert parser().parse_args([]).headless is True
    assert parser().parse_args(['--headed']).headless is False
    for args in (['browser'], ['login'], ['logout'], ['doctor'], ['--demo']):
        with pytest.raises(SystemExit):
            parser().parse_args(args)


def test_safe_text_and_article_format():
    assert plain('a\x1b\x00\x85\nb') == 'a\nb'
    text = article_text({'username': 'alice', 'text': '[red]literal[/red]', 'permalink': 'https://example.test'})
    assert '[red]literal[/red]' in text
    assert '@alice' in text


async def test_switch_closes_old_context_before_reopening_same_profile():
    source = BrowserSource()
    profile = source.profile
    events = []

    async def close():
        events.append('close')

    async def open():
        events.append(('open', source.headless, source.profile))

    source.close, source.open = AsyncMock(side_effect=close), AsyncMock(side_effect=open)
    source.posts['old'] = {}
    await source.switch_mode(False)
    assert events == ['close', ('open', False, profile)]
    assert source.posts == {}
    await source.switch_mode(True)
    assert events[-2:] == ['close', ('open', True, profile)]


async def test_click_login_then_read_without_restarting_browser():
    source = AsyncMock()
    source.headless = True
    source.read.return_value = BrowserBatch('ready', [])

    async def switch(headless):
        source.headless = headless

    source.switch_mode.side_effect = switch
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.click('#open')
        await app.workers.wait_for_complete()
        source.switch_mode.assert_awaited_with(False)
        await pilot.pause(.1)
        await pilot.click('#background')
        await app.workers.wait_for_complete()
        source.switch_mode.assert_awaited_once_with(False)
        assert source.headless is False
        source.read.assert_awaited_once_with(False)


@pytest.mark.parametrize('final_state', ['ready', 'login'])
async def test_complete_login_preserves_verified_page(monkeypatch, final_state):
    from unittest.mock import Mock
    from textual.widgets import Static

    monkeypatch.setattr('mythread.browser_ui.asyncio.sleep', AsyncMock())
    source = BrowserSource(headless=False)
    source.context = AsyncMock()
    source.page = AsyncMock()
    source.page.is_closed = Mock(return_value=False)
    source.page.url = 'https://www.threads.com/'
    post = {'permalink': 'https://www.threads.com/@alice/post/VERIFIED',
            'text': 'verified session'}
    final = {'rows': [post]} if final_state == 'ready' else {'login': True}
    source.page.evaluate.side_effect = [{'login': True}] + [final] * 10
    page, context = source.page, source.context
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.click('#background')
        await app.workers.wait_for_complete()
        assert source.page is page and source.context is context
        context.close.assert_not_awaited()
        page.goto.assert_not_awaited()
        page.reload.assert_not_awaited()
        assert source.headless is False
        assert ('已載入' if final_state == 'ready' else '需要登入') in str(app.query_one('#status', Static).render())
        assert len(app.posts_data) == (1 if final_state == 'ready' else 0)


@pytest.mark.parametrize('logged_in', [True, False])
async def test_recover_closed_browser_keeps_profile_and_reads(tmp_path, logged_in):
    from unittest.mock import Mock
    from textual.widgets import Button, Static

    source = BrowserSource(headless=False)
    source.profile = tmp_path / 'profile'
    source.profile.mkdir()
    marker = source.profile / 'session-marker'
    marker.write_text('preserve')
    source.page = Mock()
    source.page.is_closed.return_value = True
    source.posts['stale'] = {}
    page = AsyncMock()
    page.is_closed = Mock(return_value=False)
    page.url = 'https://www.threads.com/'
    page.evaluate.return_value = {'rows': [
        {'permalink': 'https://www.threads.com/@alice/post/RECOVERED', 'text': 'new feed'}]}
    if not logged_in:
        page.evaluate.return_value = {'login': True}

    async def reopen():
        assert marker.read_text() == 'preserve'
        assert source.headless is True
        source.page = page

    source.open = AsyncMock(side_effect=reopen)
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.click('#more-actions')
        await pilot.pause(.1)
        await pilot.click('#recover')
        await app.workers.wait_for_complete()
        source.open.assert_awaited_once()
        assert [p['id'] for p in app.posts_data] == (['RECOVERED'] if logged_in else [])
        assert app.query_one('#background', Button).disabled
        if not logged_in:
            status = str(app.query_one('#status', Static).render())
            assert '需要登入' in status and '登入視窗' in status
        assert 'stale' not in source.posts
        assert marker.exists()


async def test_relogin_removes_only_owned_profile_after_close(tmp_path):
    source = BrowserSource()
    source.profile = tmp_path / 'profile'
    source.profile.mkdir()
    (source.profile / 'Cookies').write_text('synthetic session')
    sibling = tmp_path / 'unrelated'
    sibling.write_text('keep')
    source.posts['old'] = {}
    events = []

    async def close():
        assert (source.profile / 'Cookies').exists()
        events.append('close')

    async def reopen():
        assert not source.profile.exists()
        assert source.headless is False
        events.append('open')

    source.close = AsyncMock(side_effect=close)
    source.open = AsyncMock(side_effect=reopen)
    app = BrowserApp(source, auto_start=False)
    async with app.run_test(size=(110, 35)) as pilot:
        await pilot.click('#more-actions')
        await pilot.pause(.1)
        await pilot.click('#relogin')
        await pilot.pause(.1)
        await pilot.click('#confirm-clear')
        await app.workers.wait_for_complete()
        assert events == ['close', 'open']
        assert not source.posts and not app.posts_data
        assert sibling.read_text() == 'keep'


async def test_relogin_does_not_delete_profile_if_close_fails(tmp_path):
    source = BrowserSource()
    source.profile = tmp_path / 'profile'
    source.profile.mkdir()
    marker = source.profile / 'Cookies'
    marker.write_text('synthetic session')
    source.close = AsyncMock(side_effect=RuntimeError('still running'))
    source.open = AsyncMock()
    with pytest.raises(RuntimeError, match='still running'):
        await source.relogin()
    assert marker.exists()
    source.open.assert_not_awaited()


def test_portable_browser_path_is_relative_to_exe(monkeypatch, tmp_path):
    folder = tmp_path / 'portable with spaces'
    (folder / 'browsers').mkdir(parents=True)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(folder / 'mythread.exe'))
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', 'wrong-user-cache')
    configure_browser_runtime()
    import os
    assert Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']) == folder / 'browsers'


def test_incomplete_portable_distribution_has_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'mythread.exe'))
    with pytest.raises(RuntimeError, match='完整解壓縮'):
        configure_browser_runtime()


async def test_cli_closes_source_when_ui_fails(monkeypatch):
    source = AsyncMock()
    monkeypatch.setattr('mythread.browser.BrowserSource', lambda **kwargs: source)
    app = AsyncMock()
    app.run_async.side_effect = RuntimeError('UI failure')
    monkeypatch.setattr('mythread.browser_ui.BrowserApp', lambda _: app)
    with pytest.raises(RuntimeError, match='UI failure'):
        await run(parser().parse_args([]))
    source.close.assert_awaited_once()


def test_browser_startup_errors_do_not_expose_raw_diagnostics():
    from mythread.browser import browser_open_error
    assert '設定檔使用中' in browser_open_error(Exception('ProcessSingleton secret-value'))
    assert 'install chromium' in browser_open_error(Exception("Executable doesn't exist secret-value"))
    assert '網路' in browser_open_error(Exception('net::ERR_CONNECTION_RESET secret-value'))
    for message in ('ProcessSingleton', "Executable doesn't exist", 'Timeout', 'unknown'):
        assert 'secret-value' not in browser_open_error(Exception(message + ' secret-value'))


async def test_failed_launch_stops_playwright(monkeypatch, tmp_path):
    from unittest.mock import Mock
    runtime = AsyncMock()
    runtime.chromium.launch_persistent_context.side_effect = RuntimeError('ProcessSingleton')
    manager = Mock()
    manager.start = AsyncMock(return_value=runtime)
    monkeypatch.setattr('playwright.async_api.async_playwright', lambda: manager)
    source = BrowserSource()
    source.profile = tmp_path / 'profile'
    with pytest.raises(RuntimeError, match='ProcessSingleton'):
        await source.open(start_url='about:blank')
    runtime.stop.assert_awaited_once()
    assert source.runtime is None
    assert source.context is None
