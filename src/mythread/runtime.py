"""Locate the bundled browser without using the user's browser installation."""
import os
from pathlib import Path
import sys


def configure_browser_runtime():
    if getattr(sys, 'frozen', False):
        browsers = Path(sys.executable).resolve().parent / 'browsers'
        if not browsers.is_dir():
            raise RuntimeError('缺少隨附的 browsers 資料夾；請完整解壓縮可攜版，不要只複製 exe。')
        # A portable distribution must use its matching browser, not an unrelated
        # cache or a developer's PLAYWRIGHT_BROWSERS_PATH environment setting.
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(browsers)
