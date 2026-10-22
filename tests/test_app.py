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


async def test_click_login_then_return_to_background():
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
        await pilot.click('#background')
        await app.workers.wait_for_complete()
        source.switch_mode.assert_awaited_with(True)
        source.read.assert_awaited_once_with(False)


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
