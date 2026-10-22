"""Offline portable-build smoke test. Never uses the real account profile."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .browser import BrowserSource, SNAPSHOT, classify
from .browser_ui import BrowserApp, BridgeList


async def self_test():
    with TemporaryDirectory(prefix='mythread-smoke-') as directory:
        source = BrowserSource()
        source.profile = Path(directory) / 'profile'
        try:
            await source.open(start_url='about:blank')
            await source.page.set_content('''<main><article>
              <a href="https://www.threads.com/@example/post/SMOKE">post</a>
              <div dir="auto">Offline smoke test</div></article></main>''')
            batch = classify(await source.page.evaluate(SNAPSHOT))
            if len(batch.posts) != 1 or batch.posts[0]['text'] != 'Offline smoke test':
                raise RuntimeError('DOM smoke test failed')
            app = BrowserApp(source, auto_start=False)
            async with app.run_test(size=(110, 35)) as pilot:
                await pilot.pause()
                app.query_one(BridgeList)
            print(json.dumps({'browser': 'ok', 'dom': 'ok', 'terminal': 'ok',
                              'network': 'not used', 'profile': 'temporary'}))
        finally:
            await source.close()
