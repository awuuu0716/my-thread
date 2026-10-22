# myThread Terminal

以 Meta Threads 官方 API 製作的個人純文字 Terminal 用戶端。Python 3.11+，目前以 Windows 為主要開發環境。

## 快速試用（不用 Meta 帳號）

在本專案資料夾執行 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\mythread.exe --demo
```

若已建立虛擬環境並安裝，直接執行最後一行即可。示範資料不連線、不發文，示範草稿與正式草稿分開保存。

## 已實作功能

- 我的文章、指定公開帳號文章、游標分頁、全文閱讀。
- 關鍵字搜尋，以及搜尋結果與公開帳號文章的混合推薦。
- 純文字顯示，不下載圖片或影片；保留附件類型提示和原文網址。
- 多行文字編輯、本機草稿、發布前預覽與確認。
- OAuth 登入、匯入既有 User Access Token、狀態檢查、長效 Token 更新、登出。
- Terminal 內的帳號畫面：遮罩 Token 輸入、更新登入、登出後重新登入。
- Token 存在系統憑證庫；Windows 使用 Credential Manager。憑證庫不可用時拒絕保存，不退回明文。
- 網路錯誤不自動重送發文；結果不明時保留草稿並停用當次編輯器的發布按鈕。

不提供官方「為你推薦／追蹤中」動態、按讚、私訊、通知或回覆管理。提供由搜尋結果和選填公開帳號組成的本機推薦，資料範圍受 Meta 的權限與帳號可用性限制。

## 在操作介面登入／登出

直接執行 `.\.venv\Scripts\mythread.exe`。沒有 Token 或本機記錄已過期時，程式仍可開啟，並顯示登入畫面。

- 貼上 **Threads User Access Token**，按 Enter 或「登入／更新」。輸入會遮罩；透過 `/me` 驗證後存入系統憑證庫並讀取文章。
- 已登入時，點主畫面下方「帳號」或按 **Ctrl+L**，即可貼入含新權限的 Token 或切換帳號。更新成功會清除舊草稿與已讀紀錄，保留推薦來源與關鍵字。
- 無效 Token 或憑證庫保存失敗時，保留原本連線，畫面顯示錯誤，Token 輸入欄會清空。
- 點「登出」，再點「確認登出」。會清除本機 Token、草稿、已讀紀錄、文章列表與記憶體快取，不撤銷 Meta 端 App 授權。可留在同一畫面重新登入。
- 讀取文章期間請稍候再開啟帳號；發文編輯畫面需先返回主畫面。示範模式停用真實帳號登入，請退出後以正式模式啟動。

匯入 Token 不會自動增加權限；仍需先在 Meta 後台取得所需權限。此登入方式不需 App Secret，也不需設定 OAuth callback。

## 本機推薦動態

啟動 `mythread`，點下方「本機推薦」（或 Ctrl+F）。第一次會開啟設定：

1. 填入搜尋關鍵字，例如 `比特幣, 貓`，最多 20 個，以逗號或換行分隔。每個詞獨立搜尋，再合併結果，不是要求文章同時包含所有詞。
2. 公開帳號可以留白；若有固定作者也可加入，最多 10 個，填 username 而非網址。
3. 點「儲存並搜尋」，開始混合閱讀。隨時可按「推薦設定」調整。

這是 **本機排序的 API 搜尋與帳號文章，不是 Threads 官方推薦首頁**。沒有自動取得追蹤名單，也不會發出追蹤操作。關鍵字會送往 Meta 的 `GET /keyword_search`（`q`、`search_type=TOP`、`fields`、`limit=20`），需要 `threads_keyword_search`。只有加入公開帳號時才需要 `threads_profile_discovery`。搜尋成功或空結果不代表全站搜尋權限已核准；結果範圍以 Meta 的權限、審查狀態與實際回應為準。

請到 Meta 的 Threads「權限與功能」加入 `threads_keyword_search`，依控制台提示處理測試或審查要求，再產生並匯入含該權限的新 Token：

```powershell
.\.venv\Scripts\mythread.exe login --token
.\.venv\Scripts\mythread.exe doctor --keyword "貓"
```

OAuth 使用者可執行 `login --search`；需要兩種來源時執行 `login --search --discovery`。舊版保存的興趣關鍵字現在也會作為搜尋來源，公開帳號可清空。

排序依未讀優先、時間新鮮度、關鍵字命中加分，並降低同一作者連續佔據前列的機會。文章旁與全文底部顯示本機推薦理由。開啟全文才記錄已讀；下次更新重新排序，已讀文章仍可出現。

每頁最多 20 篇；Ctrl+N 讀取後續候選，Ctrl+R 回到第一頁並重排。公開帳號使用 API 分頁游標；關鍵字每次取最多 20 筆，搜尋 API 的游標支援未確認，因此搜尋只對已取得的合併結果做本機分頁，不保證涵蓋全部相關文章。合併時按文章 ID 去重，重複命中保留搜尋來源。最多同時讀取 3 個來源；請求結果在記憶體快取 60 秒，因此短時間更新不保證取得剛發出的文章。單一來源失敗時顯示通知並保留其他來源；全部失敗時保留原列表，可稍後更新重試。

來源與關鍵字存入本機 `feed.json`；最近 2,000 個已讀文章 ID 與閱讀時間存入 `feed-seen.json`。不把文章全文快取到磁碟、不傳送閱讀紀錄到 Meta。登出或重新登入時清除已讀紀錄；來源與關鍵字保留為此電腦的偏好設定。示範模式使用獨立設定目錄並預設三個虛構來源，適合無權限時體驗。

## 最快連接真實帳號：匯入 Token

尚未建立 Meta App 時，可在 Terminal 查看逐步指引：

```powershell
.\.venv\Scripts\mythread.exe setup
```

先在 Meta 開發者控制台建立含 Threads use case 的 App，設定自己的測試帳號，依控制台流程取得 **Threads User Access Token**。

- 基本閱讀：`threads_basic`
- 發文：另需 `threads_content_publish`
- 公開帳號閱讀：另需 `threads_profile_discovery`
- 關鍵字搜尋：另需 `threads_keyword_search`

```powershell
.\.venv\Scripts\mythread.exe login --token
.\.venv\Scripts\mythread.exe doctor
.\.venv\Scripts\mythread.exe
```

Token 以隱藏輸入貼上，不放命令列參數、shell history、原始碼或 `.env`。匯入的 Token 到期時間與種類未知，因此不自動更新；失效後重新匯入或使用 OAuth 登入。

`doctor` 讀取本機憑證狀態、目前帳號與自己的文章第一頁。它不更新 Token、不發文，也不把文章內容或 Token 放進報告；沒有文章的空列表仍算讀取成功。預設不測公開帳號，需指定 `--profile`。

```powershell
.\.venv\Scripts\mythread.exe doctor --profile threads
.\.venv\Scripts\mythread.exe doctor --keyword "貓"
.\.venv\Scripts\mythread.exe doctor --json
```

診斷失敗時 exit code 為 1；通過為 0。通過只代表已執行的讀取檢查成功，**不代表發文權限或未測的公開帳號權限已通過**。JSON 報告含帳號名稱，分享前請確認是否需要移除。

## OAuth 登入

### 不依賴外網 Tunnel：本機 HTTPS（Meta 官方範例方式）

Meta 的[官方範例](https://github.com/fbsamples/threads_api/blob/main/README.md)使用 hosts 名稱對應與本機 HTTPS，並指出 Threads callback 不支援直接填 `localhost`。這個專案提供固定網址 `https://threads-sample.meta:8765/callback`；不需購買此網域，它只在本機 hosts 指向 `127.0.0.1`。

先安裝本機憑證產生套件（目前工作環境已安裝）：

```powershell
.\.venv\Scripts\python.exe -m pip install "cryptography>=43"
```

接著以**同一個 Windows 帳號開啟管理員 PowerShell**，切換到本專案資料夾，執行一次：

```powershell
.\scripts\setup_local_https.ps1
```

這個腳本會變更兩項系統設定：在 Windows hosts 加入 `127.0.0.1 threads-sample.meta`，並將僅適用此主機名稱、效期 30 天的自簽伺服器憑證加入目前使用者的信任憑證庫。它不是可簽發其他憑證的 CA；私鑰位於已忽略的 `.tools/callback-key.pem`，ACL 限制目前使用者存取。**開發代理不會自動執行此管理員腳本。**若 PowerShell 執行原則禁止腳本，請依你的電腦管理政策處理，不需永久修改執行原則。

回到一般 PowerShell：

```powershell
.\.venv\Scripts\mythread.exe login --local-https --search --discovery
```

輸入 Threads App ID，把程式顯示的 callback 網址加入 Meta 的 Threads Redirect Callback URLs 並儲存，再按 Enter、隱藏輸入 App Secret、完成瀏覽器授權。程序會自動接收回應並保存 Token。此網址固定可重用，但登入期間必須保持程序執行；請在同一台電腦的瀏覽器完成授權。憑證過期後需重新執行設定腳本；停止使用可移除 hosts 中標有 `myThread local OAuth` 的項目，及目前使用者信任根憑證庫中對應的 `threads-sample.meta` 憑證。

目前環境測試 Cloudflare 時發生未知簽發者的 TLS 錯誤，所以建議使用這個本機模式；不關閉 TLS 驗證。

### 沒有 HTTPS 網址：臨時 Tunnel 登入

Windows 可使用專案內的 Cloudflare Quick Tunnel，不需自己的網域或 Cloudflare 帳號。第一次安裝輔助程式（從 Cloudflare 官方 GitHub release 下載，並核對 release 提供的 SHA-256）：

```powershell
.\.venv\Scripts\python.exe scripts/install_cloudflared.py
.\.venv\Scripts\mythread.exe login --tunnel --search --discovery
```

工具存在 `.tools/cloudflared.exe`，不修改系統 PATH、不安裝 Windows 服務。程式也支援已安裝在 PATH 中的 `cloudflared`。

1. 在 Terminal 輸入 **Threads App ID**。
2. 等待產生 `https://…trycloudflare.com/callback`。
3. 到 Meta 的 Threads 使用案例設定，將完整網址加入 **OAuth 重新導向網址／Redirect Callback URLs**，儲存後回 Terminal 按 Enter。
4. 隱藏輸入 **Threads App Secret**。瀏覽器會開啟，明確要求搜尋與公開帳號權限。
5. 完成授權後自動驗證 `state`、接收授權碼、交換長效 Token，存入系統憑證庫；不需要複製 callback URL。回到 Terminal 查看結果，再執行 `doctor --keyword "貓"`。

本機僅開啟 `127.0.0.1` 的專用 callback 接收器，對外只有固定 callback 與健康檢查頁，不提供本機檔案。Cloudflare 會代理 HTTPS 授權回應；接收器不記錄 callback query、不在頁面回顯授權碼，App Secret 與 Token 交換直接連線 Meta。

每次執行會取得新網址，需重新加入 Meta 白名單。登入結束、失敗或 Ctrl+C 時會關閉 tunnel；舊網址失效，可從 Meta 後台移除。Quick Tunnel 僅供開發測試，Meta 是否接受該網址仍需實際在後台確認。[Cloudflare 官方說明](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

### 已有自己的 HTTPS callback

這是自用 App 的 OAuth 流程，不是可安全內嵌共用 App Secret 的公開 CLI 發行架構。

1. 在 Meta App 設定 Threads OAuth redirect URI。使用自己控制的 HTTPS callback，不能填第三方網站；此程式要求不含 query 或 fragment。以控制台接受的設定為準，不假設 HTTP localhost 可用。
2. callback 頁面需保留網址中的 `code`、`state`，不要自動跳轉清除。使用簡單的 HTTPS 頁面即可，不需由頁面交換 Token；請停用記錄 query string 的存取日誌及第三方分析腳本。
3. 執行 `configure` 輸入 Threads App ID 和完全相同的 callback URL。
4. 執行 `login`，以隱藏輸入提供 **Threads App Secret**。Secret 只留在本次程序記憶體，也可用 `THREADS_APP_SECRET` 環境變數提供。
5. 瀏覽器完成授權後，複製完整 callback 網址並貼回 Terminal 的隱藏輸入。程式檢查網址與隨機 `state`，再交換長效 Token。

```powershell
.\.venv\Scripts\mythread.exe configure
.\.venv\Scripts\mythread.exe login
# 要讀其他公開帳號，確認 App 有相應權限後改用：
.\.venv\Scripts\mythread.exe login --discovery
```

此手動模式需貼回 callback 網址；使用 `--tunnel` 則自動接收。一般使用者可用性、App Review、正式模式需求須依 Meta 控制台與最新政策完成；OAuth 仍待使用者完成真實 App 授權驗證。

OAuth Token 依 `expires_in` 保存到期時間。在啟動或查詢狀態時，若長效 Token 距離到期小於七日、且建立或上次更新已超過 24 小時，嘗試更新。這不是背景排程；長期不啟動導致過期須重新登入。長時間開著 TUI 遇到授權失效時也需退出重新登入。

```powershell
.\.venv\Scripts\mythread.exe refresh
.\.venv\Scripts\mythread.exe logout
```

登出清除本機 Token 與草稿，不撤銷 Meta 端 App 授權；需在 Threads 的網站權限設定撤銷。重新登入也會清除舊草稿，避免跨帳號誤發。

## 鍵盤操作

| 操作 | 按鍵 |
| --- | --- |
| 選擇文章 | ↑ / ↓ |
| 閱讀全文 | Enter |
| 切換欄位、按鈕 | Tab / Shift+Tab |
| 返回／取消預覽 | Esc |
| 更新目前來源 | Ctrl+R |
| 下一頁 | Ctrl+N |
| 撰寫文章 | Ctrl+W |
| 本機推薦 | Ctrl+F |
| 登入／更新 Token／登出 | Ctrl+L |
| 離開 | Ctrl+Q |

在公開帳號欄輸入完整 username（例如 `threads`），按 Enter 或「讀取帳號」。目前頁面顯示 20 筆；更新回到該來源第一頁。支援一般 80×24 以上終端，建議 Windows Terminal 110×35。

草稿以明文存於使用者設定目錄（Windows 通常為 `%LOCALAPPDATA%\mythread`），包含你輸入的文章內容；Token 不在此目錄。輸出當作純文字，不解析遠端內容的 Rich markup，並移除終端控制字元。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

測試使用 HTTP mock 與 Textual headless pilot，覆蓋 OAuth state/callback 驗證、權限錯誤、分頁、發布結果不明不重試、憑證儲存、全文閱讀、草稿與發布確認，以及推薦去重、排序、來源設定、已讀保存、快取和部分來源失敗。測試不使用真實 Token，不會發文。

實機讀取驗證：目前帳號與自己的文章可讀取；搜尋功能開發時，`doctor --keyword "貓"` 回傳需要 `threads_keyword_search` 的權限錯誤。推薦與搜尋已通過模擬及鍵盤操作測試，真實搜尋結果仍待權限解決後驗證。

## 程式結構

```text
src/mythread/
  cli.py       命令列與登入流程
  auth.py      OAuth state、callback 與 Token 交換
  api.py       Threads HTTP client、錯誤處理與離線資料
  storage.py   系統憑證庫與本機設定／草稿
  tui.py       Textual 互動介面
  feed.py      公開帳號聚合、去重分頁與本機推薦排序
  feed_ui.py   推薦來源與興趣設定
  account_ui.py Token 登入與登出畫面
tests/         API、OAuth、儲存與互動流程測試
```

## 官方參考與驗證範圍

查閱日期：2026-10-22。

- [Meta 官方 Threads API Postman collection](https://www.postman.com/meta/threads/collection/dht3nzz/threads-api)
- [官方 API 請求、授權與 Token 交換範例](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)
- [官方純文字發布範例](https://www.postman.com/meta/threads/request/jkuogpa/1-1-create-text-container)
- [官方關鍵字搜尋範例](https://www.postman.com/meta/threads/request/34203612-b3b2c12a-7ce6-4d86-a3c6-6d31e3b66ea1)
- [Meta 開發者文件入口](https://developers.facebook.com/docs/threads/)
- [Textual widgets](https://textual.textualize.io/guide/widgets/) / [測試指南](https://textual.textualize.io/guide/testing/)

實作依 Meta 維護的 Postman 範例使用 `graph.threads.net`：`GET /me`、`GET /me/threads`、`GET /profile_posts`，以及 `POST /me/threads` 搭配 `media_type=TEXT`、`auto_publish_text=true`。API 主機集中在 `api.py`，沒有自動追隨分頁 URL 或 HTTP redirects。Meta 文件主站查閱時回傳 429；最新額度、文字限制與權限審核以 Meta 實際回應及最新文件為準。

已以匯入 Token 驗證自己的帳號與文章。待真實帳號驗證：OAuth 網址與 callback 設定、Token 交換與更新、公開帳號閱讀權限及推薦資料、實際發文與中文長度限制。程式不自動拆文或截斷文字；超出 API 限制時保留草稿並顯示錯誤。
