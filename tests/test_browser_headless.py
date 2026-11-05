import sys
from unittest.mock import AsyncMock, Mock

import pytest

from mythread.browser import BrowserSource, BrowserBatch, SNAPSHOT, classify
from mythread.browser_ui import browser_status
from mythread.cli import parser


def test_browser_visibility_flags():
    assert parser().parse_args([]).headless is True
    assert parser().parse_args(['--headless']).headless is True
    assert parser().parse_args(['--headed']).headless is False
    with pytest.raises(SystemExit):
        parser().parse_args(['--headless', '--headed'])


@pytest.mark.parametrize('headless', [True, False])
async def test_browser_launch_visibility_and_profile(monkeypatch, tmp_path, headless):
    runtime = AsyncMock()
    page = AsyncMock()
    page.is_closed = lambda: False
    context = runtime.chromium.launch_persistent_context.return_value
    context.pages = [page]
    manager = Mock()
    manager.start = AsyncMock(return_value=runtime)
    monkeypatch.setattr('playwright.async_api.async_playwright', lambda: manager)
    source = BrowserSource(headless=headless)
    source.profile = tmp_path / 'isolated-profile'
    await source.open()
    options = runtime.chromium.launch_persistent_context.call_args
    assert options.args == (source.profile,)
    assert options.kwargs['headless'] is headless
    assert options.kwargs['channel'] == 'chromium'
    assert options.kwargs['chromium_sandbox'] is True  # Playwright defaults to --no-sandbox
    await source.open()
    assert page.bring_to_front.await_count == (0 if headless else 1)
    await source.close()
    context.close.assert_awaited_once()
    runtime.stop.assert_awaited_once()


def test_sandbox_opt_out_is_explicit(monkeypatch):
    from mythread.browser import sandbox_enabled
    monkeypatch.delenv('MYTHREAD_DISABLE_SANDBOX', raising=False)
    assert sandbox_enabled() is True
    monkeypatch.setenv('MYTHREAD_DISABLE_SANDBOX', 'true')
    assert sandbox_enabled() is True
    monkeypatch.setenv('MYTHREAD_DISABLE_SANDBOX', '1')
    assert sandbox_enabled() is False


def test_headless_login_message_has_manual_recovery():
    text = browser_status(BrowserSource(), BrowserBatch('login', message='尚未登入'))
    assert '登入視窗' in text and '完成登入' in text


def test_real_chromium_headless_persistent_profile(tmp_path):
    # Synthetic DOM in an isolated temporary profile, not Threads verification.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        context = runtime.chromium.launch_persistent_context(
            tmp_path / 'profile', headless=True, channel='chromium',
            chromium_sandbox=sys.platform != 'linux', viewport={'width': 1280, 'height': 900}, accept_downloads=False)
        try:
            page = context.pages[0]
            page.set_content('''<main><article>
                <a href="https://www.threads.com/@alice/post/HEADLESS">post</a>
                <div dir="auto">background reading</div></article></main>''')
            batch = classify(page.evaluate(SNAPSHOT))
            assert batch.state == 'ready'
            assert batch.posts[0]['text'] == 'background reading'
        finally:
            context.close()
