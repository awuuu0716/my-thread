# 架構

0.2 只有一條讀取路徑：Terminal → Playwright → 專用 Chromium → 官方網頁 DOM。沒有 API client、OAuth callback、keyring 或發布流程。

| 模組 | 責任 |
| --- | --- |
| `cli.py` | 單一入口、可見／背景參數、版本、自我檢查、退出清理 |
| `browser.py` | 持久化 context、首頁／留言分頁、切換模式、DOM 擷取與去重 |
| `browser_ui.py` | Textual 列表、閱讀、預載、留言、登入按鈕、返回與關閉 |
| `text.py` | 純文字清理與文章格式，不依賴外部服務 |
| `runtime.py` | exe 以自身目錄定位隨附 Chromium，不依賴開發機快取 |
| `selftest.py` | 暫存 profile、合成 HTML、Textual headless 檢查 |

`BrowserBatch` 為 `state`、`posts`、`message`；文章欄位為 `id`、`username`、`text`、`permalink`。狀態包含 ready、login、loading、empty、unconfirmed、error、closed；未辨識不是空結果，新增 0 不是確認到底。

## 擷取與捲動

`SNAPSHOT` 只讀可見 DOM，以 `/post/` 連結定位容器及正文，排除時間／控制元件；歧義多連結容器略過，不使用整頁 body 文字。`extract_posts()` 驗證公開 host／path、去除 query、清理控制字元並去重。

留言以可見原文 permalink 定位，不要求原文正文解析成功。推薦標題只是啟發式邊界；虛擬列表可移除定位點，不能保證全站所有版面都正確。

`SCROLL` 找可捲動祖先，否則使用文件捲軸。捲動前擷取以免虛擬列表移除舊列，分段限次輪詢；各來源最多保留 2,000 篇。Ctrl+R 會重載並清除來源池，與追加下一批不同。

`BridgeList` 接近底部且往下移動時預載，保留一次忙碌／冷卻中的請求；向上移動取消待執行請求。列表成長不可觸發無限自動預載。

## 登入與生命週期

Playwright async API 與 UI 使用同一事件迴圈。首頁 lock／UI busy 控制讀取；只在首頁可切換可見／背景模式。切換必須先關閉原 context，再以相同 profile 啟動新 context；不匯出 Cookie 或同時開兩個 context。

留言使用獨立分頁以保留首頁。返回標記停止並關閉分頁；逾時關閉自有分頁，避免直接取消執行中的 protocol 呼叫。延遲 task 不可更新已卸載畫面，舊操作不可誤關新分頁。

CLI 以 `finally` 關閉來源；使用者手動關閉瀏覽器後可重新開啟。profile 路徑維持與 0.1 相同，程式不搬移登入資料。

遠端文字經 `plain()` 處理並以 Rich `Text` 顯示；錯誤不直接回顯完整底層 exception／DOM。診斷只含計數與判定。可攜版 `--self-test` 不使用真實 profile、不發出 Threads 請求。
