# 架構

0.2 只有一條讀取路徑：Terminal → Playwright → 專用 Chromium → 官方網頁 DOM。沒有 API client、OAuth callback、keyring 或發布流程。

| 模組 | 責任 |
| --- | --- |
| `cli.py` | 單一入口、可見／背景參數、版本、自我檢查、退出清理 |
| `model.py` | 共用資料契約：`State`、`Post`、`BrowserBatch`、Threads host、留言數格式、保留上限 |
| `dom/*.js` | 在頁面內執行的 `SNAPSHOT`／`SCROLL`；所有 DOM 版面假設集中於此 |
| `browser.py` | 持久化 context、首頁／留言分頁、切換模式、`classify()` 與 `extract_posts()` 去重 |
| `messages.py` | 所有狀態訊息文字與挑選訊息的純函式（`browser_status`、`browser_open_error`） |
| `widgets.py` | `BridgeList`（錨點保留、預載）、`FeedOwner` 契約、`ButtonActions`、逾時清理 `call_with_deadline` |
| `screens.py` | 文章閱讀、留言列表（皆繼承 `SubScreen`：Esc／右鍵返回） |
| `browser_ui.py` | 首頁 `BrowserApp`：`HomeAction`、主操作選擇、讀取與自動補足流程 |
| `dialogs.py` | 清除登入資料前的確認視窗，預設取消 |
| `text.py` | 純文字清理與文章格式，不依賴外部服務 |
| `runtime.py` | exe 以自身目錄定位隨附 Chromium，不依賴開發機快取 |
| `selftest.py` | 暫存 profile、合成 HTML、Textual headless 檢查 |

`BrowserBatch` 為 `state`、`posts`、`message`；文章欄位為 `id`、`username`、`text`、`permalink`、選用 `reply_count`（定義於 `model.py`）。狀態包含 ready、login、loading、empty、unconfirmed、error、closed；未辨識不是空結果，新增 0 不是確認到底。

## 擷取與捲動

`SNAPSHOT` 只讀可見 DOM，以 `/post/` 連結定位容器及正文，排除時間／控制元件；歧義多連結容器略過，不使用整頁 body 文字。`extract_posts()` 驗證公開 host／path、去除 query、清理控制字元並去重。

留言以可見原文 permalink 定位，不要求原文正文解析成功。推薦標題只是啟發式邊界；虛擬列表可移除定位點，不能保證全站所有版面都正確。

`SCROLL` 找可捲動祖先，否則使用文件捲軸。捲動前擷取以免虛擬列表移除舊列，分段限次輪詢；各來源最多保留 2,000 篇。Ctrl+R 會重載並清除來源池，與追加下一批不同。

`BridgeList` 接近底部且往下移動時預載，保留一次忙碌／冷卻中的請求；向上移動取消待執行請求。列表成長不可觸發無限自動預載。

列表使用依終端機欄寬換行的三行正文摘要，詳情保留全文。更新列表時以文章 ID 與可見列偏移保留閱讀位置；視窗縮放會重算摘要。原文連結由使用者明確操作開啟，先沿用公開 host／path 驗證。

## 登入與生命週期

Playwright async API 與 UI 使用同一事件迴圈。首頁 lock／UI busy 控制讀取；只在首頁可開啟登入視窗。從背景切至可見模式時先關閉原 context，再以相同 profile 啟動新 context；「完成登入」保留已驗證的 context 與頁面，僅重試 DOM 讀取，避免重啟造成驗證狀態失效。不匯出 Cookie 或同時開兩個 context。

留言使用獨立分頁以保留首頁。返回標記停止並關閉分頁；逾時關閉自有分頁，避免直接取消執行中的 protocol 呼叫。延遲 task 不可更新已卸載畫面，舊操作不可誤關新分頁。

CLI 以 `finally` 關閉來源；使用者手動關閉瀏覽器後可重新開啟。profile 路徑維持與 0.1 相同，程式不搬移登入資料。

首頁按狀態選擇主操作，次要操作收於「更多」。清除登入需確認；忙碌時停用衝突操作，離開請求會排定在目前操作結束後執行。操作設有逾時，停止讀取後提示恢復。詳情頁不提供只能在首頁執行的快捷鍵。

遠端文字經 `plain()` 處理並以 Rich `Text` 顯示；錯誤不直接回顯完整底層 exception／DOM。診斷只含計數與判定。可攜版 `--self-test` 不使用真實 profile、不發出 Threads 請求。
