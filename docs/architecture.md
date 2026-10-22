# 架構與資料流

[返回 README](../README.md)

## 模組責任

| 模組 | 責任 |
| --- | --- |
| `cli.py` | argparse、模式選擇、API 登入指令；瀏覽器來源在 `finally` 關閉 |
| `browser.py` | Playwright 專用持久化 context、DOM 擷取、狀態分類、去重、留言分頁 |
| `browser_ui.py` | 瀏覽器專用 Textual 畫面、預載、重新整理、留言與返回 |
| `api.py` | 官方 HTTP API、錯誤型別、demo 資料、共用純文字清理 |
| `tui.py` | API 主介面、文章閱讀、草稿、預覽與發布確認 |
| `auth.py`／`tunnel.py` | OAuth state／callback、Token 交換、本機 callback／可選 tunnel |
| `storage.py` | keyring 與設定／草稿 JSON |
| `feed.py`／`feed_ui.py` | API 結果的本機推薦排序、來源設定、已讀紀錄 |
| `account_ui.py`／`onboarding.py` | API 帳號操作與診斷 |

瀏覽器來源不建立 `ThreadsClient`、不讀 keyring。介面仍共用 `Article`／`article_text()` 與 `plain()`；這是顯示工具共用，不是讓瀏覽器來源取得 API 發文能力。兩者刻意分開，不以龐大旗標分支混在同一個 App。

## 瀏覽器流程

```text
CLI browser → BrowserApp → BrowserSource → 專用 Chromium context
                               ├─ 首頁 page → SNAPSHOT → classify → BrowserBatch
                               └─ 留言 page → ReplySource → BrowserBatch
```

`BrowserBatch` 包含 `state`、`posts`、`message`。文章使用 `id`、`username`、`text`、`permalink`；公開 permalink 正規化為 Threads 網址，query 不保留。

| 狀態 | 意義 |
| --- | --- |
| `ready` | 有可顯示結果；新增 0 不代表到底 |
| `login` | 偵測到登入／驗證需求或登入導向 |
| `loading` | 頁面仍在載入 |
| `empty` | DOM 有可辨識空結果訊號 |
| `unconfirmed` | 沒擷取到留言，不能宣稱沒有留言 |
| `error` | 導覽、擷取、頁面位置或其他問題 |
| `closed` | 分頁已關閉／操作已停止 |

`SNAPSHOT` 僅檢查可見 DOM，從 `/post/` 連結尋找文章容器與文字節點。拒絕含多個不同 permalink 的歧義容器，排除時間及控制元件；不把整頁 body 文字當文章。`extract_posts()` 再檢查公開 host／path、清理控制字元並去重。改選擇器時必須以合成 DOM 覆蓋新結構及拒絕案例。

留言頁以目標 permalink 定位，排除它之前的項目；即使原文正文不能解析，仍可用可見連結作為位置基準。推薦標題只是啟發式邊界，不是網站提供的「這一定是留言」保證。定位與推薦邊界在虛擬列表中可能消失，這是未解限制之一。

## 捲動與快取

捲動前先擷取，避免虛擬列表移除尚未保存的項目。`SCROLL` 尋找可捲動祖先，否則使用文件捲軸；每次約八成容器高度，限次輪詢，找到新 ID 即停止。首頁與留言各自保留最多 2,000 篇，無持久化文章資料庫。

`BridgeList` 在靠近底部且向下移動時要求預載，忙碌／冷卻時保留一次請求。列表成長不應自行發起無限預載，向上移動取消待處理請求。UI 儘量更新／追加既有列，以免失去閱讀位置。

Ctrl+R 是真正 `page.reload()`：回頂端、清除來源池、重建列表。它與捲動追加的語意必須分開，亦不可讓舊資料混入新的重新整理結果。

## 生命週期與錯誤處理

Playwright async API 留在同一事件迴圈，讀取由 lock 與 UI busy 狀態控制，不在不同執行緒共用物件。Windows 使用 Python 預設支援子程序的事件迴圈。

留言分頁由 `BrowserSource` 擁有，返回時標記停止並關閉分頁；正在進行的讀取不應在畫面卸載後更新 UI。留言畫面有逾時，利用關閉自有分頁結束操作，避免直接取消正在進行的 Playwright protocol 呼叫。未完成的新分頁與延遲 task 都要處理清理／例外，不能讓上一個讀取誤關新的分頁。

可見模式與 headless 使用同一個 profile，一次僅一個 context。只在可見模式呼叫 bring-to-front；不從 Cookie／儲存狀態推測登入，登入狀態由頁面訊號判斷。

錯誤文字不要直接回顯瀏覽器底層 exception／整頁 DOM。診斷僅輸出計數與判定結果。所有外部文字視為不可信，使用純文字渲染。
