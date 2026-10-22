"""Single browser-only entry point for source installs and portable executables."""
import argparse
import asyncio
from importlib.metadata import version
import sys


def parser():
    root = argparse.ArgumentParser(description='myThread：唯讀 Threads Terminal 用戶端')
    visibility = root.add_mutually_exclusive_group()
    visibility.add_argument('--headed', dest='headless', action='store_false',
                            help='顯示專用瀏覽器，供手動登入／驗證或檢查頁面')
    visibility.add_argument('--headless', dest='headless', action='store_true',
                            help='背景執行，不顯示網站視窗（預設）')
    root.set_defaults(headless=True)
    root.add_argument('--version', action='version', version=f'myThread {version("mythread-terminal")}')
    root.add_argument('--self-test', action='store_true', help='離線檢查隨附瀏覽器與 Terminal 元件，不連線 Threads')
    return root


async def run(args):
    from .browser import BrowserSource
    from .browser_ui import BrowserApp
    source = BrowserSource(headless=args.headless)
    try:
        await BrowserApp(source).run_async()
    finally:
        await source.close()


def main():
    args = parser().parse_args()
    try:
        from .runtime import configure_browser_runtime
        configure_browser_runtime()
        if args.self_test:
            from .selftest import self_test
            asyncio.run(self_test())
        else:
            asyncio.run(run(args))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        # Runtime setup errors are deliberately human-authored; do not dump
        # arbitrary Playwright exceptions that may contain page data.
        if isinstance(exc, RuntimeError) and str(exc).startswith('缺少隨附'):
            print(str(exc), file=sys.stderr)
        else:
            print('啟動或自我檢查失敗。請確認完整解壓縮；原始碼安裝請執行 python -m playwright install chromium。', file=sys.stderr)
        raise SystemExit(1)
