"""All user-facing status copy (zh-TW) and the pure functions that choose it.

Rules: messages are authored here, never built from raw exceptions, URLs or DOM
text. Widget labels stay next to their widgets in the UI modules.
"""
from .model import BrowserBatch, State


class Msg:
    """Source (browser.py) messages carried in BrowserBatch.message."""
    HOME_LOGIN = '尚未登入或需要驗證：請在專用瀏覽器手動完成，再按重新整理。'
    HOME_OFF_SITE = '請在瀏覽器完成登入／驗證並返回 Threads。'
    LOADING = '網頁仍在載入，稍後按重新整理。'
    EMPTY = '網頁顯示空結果。'
    UNRECOGNISED = '無法辨識文章：可能是驗證畫面或網站版面變更，請查看瀏覽器。'
    HOME_CLOSED = '瀏覽器已關閉，請點「恢復讀取」重新開啟並讀取文章。'
    HOME_READ_FAILED = '讀取失敗：請檢查瀏覽器與網路，再重試。'

    REPLY_BAD_POST = '無法開啟留言：請先開啟瀏覽器並確認文章連結。'
    REPLY_OPEN_STOPPED = '已停止開啟留言。'
    REPLY_NAV_FAILED = '留言頁導覽失敗或逾時；已關閉未完成分頁，請按重新整理重試。'
    REPLY_CLOSED = '留言分頁已關閉，請返回文章重新開啟。'
    REPLY_LOGIN = '請在專用瀏覽器完成登入，再返回文章重新開啟留言。'
    REPLY_LEFT_POST = '留言分頁已離開原文章；請返回後重新開啟留言。'
    REPLY_STOPPED = '已停止留言讀取。'
    REPLY_NO_ANCHOR = '尚未辨識原文章，請確認瀏覽器已顯示文章並重試。'
    REPLY_NONE_SEEN = '目前未擷取到留言；可能尚未載入、被折疊或版面無法辨識，不代表沒有留言。'
    REPLY_READ_FAILED = '留言讀取失敗，請檢查瀏覽器後重試。'

    # Marker separating user text from diagnostics; browser_status() hides the tail.
    DIAGNOSTICS = 'DOM 診斷：'


class UiMsg:
    """Status lines written by the UI (browser_ui.py / screens.py)."""
    FIRST_RUN = '首次使用請點「登入視窗」，完成後點「完成登入」開始閱讀。'
    HOME_HINT = '↑↓ 選擇 · Enter 閱讀 · 接近底部自動載入 · Ctrl+R 重載並回頂端'
    SWITCHING = '正在切換專用瀏覽器……'
    RELOGIN = '正在清除專用瀏覽器登入資料並開啟登入視窗……'
    LOGIN_WAIT = '請在專用瀏覽器手動登入／完成驗證並返回 Threads，然後點「完成登入」。請保留瀏覽器開啟，可自行最小化。'
    RECOVERING = '正在恢復瀏覽器與文章讀取……'
    STARTING = '正在開啟專用瀏覽器……'
    STARTED = '瀏覽器已開啟，正在讀取文章……'
    HOME_TIMEOUT = '讀取逾時，已停止本次操作。請點「恢復讀取」重新開啟瀏覽器。'
    QUIT_QUEUED = '已排定關閉，會在目前操作結束後離開。'
    NO_DIAGNOSTICS = '目前沒有診斷資訊。'

    COMMENTS_OPENING = '正在開啟留言頁……'
    COMMENTS_LOADING = '留言載入中……'
    COMMENTS_TIMEOUT = '留言讀取逾時，已停止本次讀取；可返回文章或重新整理。'
    COMMENTS_FAILED = '留言讀取失敗，請重試。'
    COMMENTS_CAVEAT = '僅顯示網頁已載入的留言；不代表完整數量或回覆層級。'


def home_busy_text(action: str) -> str:
    """First status line shown when a home action starts."""
    return {'next': '正在載入更多文章……', 'read': '正在重載動態並回到頂端……'}.get(action, '正在讀取文章……')


def home_fill_text(loaded: int, target: int) -> str:
    return f'已載入 {loaded} 篇，正在自動補足 {target} 篇……'


def home_ready_text(new: int, kept: int) -> str:
    return f'新增 {new} 篇 · 保留 {kept} 篇' + (' · 尚無新文章，可稍後再試' if not new else '')


def reply_ready_text(new: int, kept: int) -> str:
    return f'新增 {new} 則 · 保留 {kept} 則 · 僅列出頁面已載入的討論，不推定回覆層級'


def diagnostics_text(batch: BrowserBatch) -> str:
    return f'狀態：{batch.state} · {batch.message}'


_STATE_TITLES = {
    State.READY: '已載入', State.LOADING: '仍在載入', State.EMPTY: '頁面顯示空結果',
    State.UNCONFIRMED: '尚未確認內容', State.ERROR: '讀取失敗', State.CLOSED: '瀏覽器已關閉',
}


def browser_status(source, batch: BrowserBatch) -> str:
    """One-line status for a batch; hides diagnostics and adapts source wording to the UI."""
    if batch.state == State.LOGIN:
        return '需要登入或驗證：請返回首頁點「登入視窗」，在瀏覽器完成後點「完成登入」。'
    title = _STATE_TITLES.get(batch.state, '讀取狀態')
    message = batch.message.split(Msg.DIAGNOSTICS, 1)[0].strip()
    message = message.replace('保留 ', '已載入 ').replace('稍後按重新整理', '稍後重試')
    result = f'{title} · {message}' if message else title
    if getattr(source, 'headless', False) and batch.state in {State.ERROR, State.UNCONFIRMED}:
        result += ' · 如需查看網站，請返回首頁點「登入視窗」。'
    return result


def browser_open_error(exc: BaseException) -> str:
    """Map a launch/navigation exception to safe guidance; never echo its text."""
    detail = str(exc).lower()
    if any(term in detail for term in ('processsingleton', 'singletonlock', 'profile appears to be in use',
                                       'user data directory is already in use')):
        return '瀏覽器設定檔使用中：請先關閉另一個 myThread APP（包含背景執行的版本），再點「登入視窗」重試。'
    if 'executable doesn' in detail or 'executable not found' in detail:
        return '找不到 Chromium：原始碼版請執行 .\\.venv\\Scripts\\python.exe -m playwright install chromium；可攜版請完整解壓縮 ZIP。'
    if 'timeout' in detail or 'net::' in detail:
        return '瀏覽器開啟網站失敗或逾時：請檢查網路，再點「登入視窗」重試。'
    return '瀏覽器啟動失敗：請先關閉其他 myThread APP 再重試；原始碼版請確認已安裝對應的 Chromium，可攜版請完整解壓縮。'
