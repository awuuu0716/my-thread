# myThread — agent guide

Read-only Threads terminal client: Textual UI → Playwright → dedicated Chromium profile → visible DOM.
No API, no posting, no cookies/network inspection. Human docs: `docs/architecture.md` (zh-TW).

## Commands
- Tests (Windows): `.venv\Scripts\python.exe -m pytest -q` — all must pass; ~45 s, some tests launch headless Chromium.
- Run: `.venv\Scripts\python.exe -m mythread [--headed]`; offline smoke: `--self-test`.
- Portable build: `python scripts/build_windows.py` (Windows x64 only).

## Module map (dependency order, no cycles)
| File | Owns | Edit here when… |
| --- | --- | --- |
| `model.py` | `State`, `Post`, `BrowserBatch`, `THREADS_HOSTS`, `COUNT_PATTERN`, limits | adding a field/state/constant used by >1 module |
| `dom/snapshot.js`, `dom/scroll.js` | every DOM/layout assumption | Threads changes its markup |
| `messages.py` | all status copy + `browser_status`/`browser_open_error` | changing wording or adding a message |
| `text.py` | `plain()` sanitising, previews, article format | changing how a post is rendered as text |
| `browser.py` | `extract_posts`, `classify`, `BrowserSource` (home), `ReplySource` (comments tab) | changing read/scroll/lifecycle logic |
| `widgets.py` | `BridgeList`, `FeedOwner`, `ButtonActions`, `call_with_deadline` | list behaviour, prefetch, anchors |
| `screens.py` | `SubScreen`, `BrowserReader`, `BrowserArticle`, `CommentsScreen` | screens above home |
| `browser_ui.py` | `BrowserApp`, `HomeAction`, `primary_button` | home buttons and the perform() pipeline |

## Invariants (tests enforce most of these)
- Never display raw exception text, URLs or DOM; status text comes from `messages.py`. Remote text goes through `text.plain()` and is rendered as `rich.Text` (no markup).
- Source reads return a `BrowserBatch`, never raise. Unknown layout ⇒ `error`/`unconfirmed`, never `empty`.
- Only open URLs that pass `extract_posts()` validation.
- All home browser calls go through `BrowserApp.browser_call` (timeout ⇒ close browser, then cancel). Comments use `call_with_deadline` with `close_replies`.
- "完成登入" (`HomeAction.BACKGROUND`) must not restart the browser — that can invalidate manual verification.
- `relogin` deletes only a directory literally named `profile` that is not a symlink.
- `COUNT_PATTERN` is duplicated inside `snapshot.js`; `tests/test_architecture.py` checks they match.
- Tests import names from `mythread.browser` and `mythread.browser_ui` (re-exports); keep those exports.

## Recipes
- **New home action**: add `HomeAction` member → button in `BrowserApp.compose` → `BUTTON_ACTIONS` entry + `action_*` method → browser steps in `first_batch()` → settle rules in `SETTLE_RETRY_STATES` if needed → `primary_button()` if it can be the main step.
- **New button on any screen**: give it an `id`, map it in that class's `BUTTON_ACTIONS` to a zero-arg method. No if/elif in `on_button_pressed`.
- **New screen with a post list**: `class X(FeedOwner, SubScreen)`; set `busy/leaving/posts_data/next_auto_at` in `__init__`, implement `request_more()`, render with `BridgeList.show_posts(posts, reset=...)`.
- **New post field**: extract in `snapshot.js` row → validate in `extract_posts` → declare in `model.Post` → render in `text.py`.
- **New state**: add to `model.State`, a title in `messages._STATE_TITLES`, and decide if it belongs in `RENDERABLE_STATES`.
- **Timing knobs** live as class attributes (`BrowserSource.REFRESH_SETTLE`, `ReplySource.POLLS_*`, `BrowserApp.SETTLE/HOME_*`, `*_TIMEOUT`) so tests can override them per instance.

## Testing patterns
- UI: `BrowserApp(AsyncMock_source, auto_start=False)` + `app.run_test()`; await `app.workers.wait_for_complete()` after triggering actions.
- Sources: assign `source.page = AsyncMock()` with `is_closed`/`url`, set `page.evaluate` return/side_effect to snapshot dicts; patch `mythread.browser.asyncio.sleep`.
- DOM: `tests/test_browser_headless.py` runs `SNAPSHOT` against synthetic HTML in real Chromium.
