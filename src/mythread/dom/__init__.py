"""Page scripts evaluated inside Chromium. Edit the .js files, not Python strings.

Packaging: setuptools package-data and the PyInstaller --add-data in
scripts/build_windows.py must both include mythread/dom/*.js.
"""
from importlib.resources import files


def _load(name: str) -> str:
    return files(__name__).joinpath(name).read_text(encoding='utf-8')


SNAPSHOT = _load('snapshot.js')  # page.evaluate(SNAPSHOT, {replies?, parent_id?}) -> dict
SCROLL = _load('scroll.js')      # page.evaluate(SCROLL, reset: bool) -> bool
