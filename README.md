# myThread Terminal

在 Terminal 閱讀 Threads 的個人用戶端，使用 Python 3.11+ 與 Textual。提供操作官方網頁的**瀏覽器唯讀實驗版**，以及使用官方 API 的帳號、搜尋與發文介面。這是非官方社群專案，未獲 Meta 背書。

目前為 0.1.x 實驗階段，主要開發／人工試用環境為 Windows。網站 DOM 變更可能讓擷取失效，自動測試通過不代表 Threads 全功能保證。

## 選擇模式

| | 瀏覽器模式 | API 模式 | 離線示範 |
| --- | --- | --- | --- |
| 指令 | `mythread browser` | `mythread` | `mythread --demo` |
| 資料來源 | 已登入的官方網頁 DOM | 官方 API | 內建虛構資料 |
| 登入 | 專用 Chromium 手動登入 | User Access Token／OAuth | 不需要 |
| 閱讀 | 目前動態、文章、已載入留言 | 自己／公開帳號文章、權限允許的搜尋 | 示範文章 |
| 發文 | 不提供 | 預覽並確認後發布 | 模擬操作 |

瀏覽器模式不需要 Meta App、App Secret、API Token、hosts 或 HTTPS callback。它不會賦予額外 API 權限，也不會自動按讚、追蹤、回覆或發文。

## 快速開始

取得本倉庫後，在倉庫根目錄執行。需要 Python 3.11+、網路連線及可手動登入 Threads 的帳號；建議終端大小至少 110×35。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[browser]'
.\.venv\Scripts\python.exe -m playwright install chromium
# 首次使用：可見瀏覽器中手動登入
.\.venv\Scripts\mythread.exe browser --headed
```

登入／驗證完成後按「重新整理」。關閉 APP，再開始背景閱讀，沿用登入狀態：

```powershell
.\.venv\Scripts\mythread.exe browser
```

啟動會自動開啟背景瀏覽器並讀取文章。`--headless` 也可明確指定背景模式；`--headed` 顯示視窗。兩者共用專用設定檔，**不要同時執行**。遇到登入失效或驗證時，先關閉 APP，再以 `--headed` 啟動；程式不會自行繞過驗證或彈出視窗。

### Linux／macOS

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser]'
.venv/bin/python -m playwright install chromium
.venv/bin/mythread browser --headed
# 登入後關閉，再啟動背景模式
.venv/bin/mythread browser
```

Linux 若缺少系統函式庫，可依 [Playwright 安裝說明](https://playwright.dev/python/docs/browsers)執行 `.venv/bin/python -m playwright install --with-deps chromium`；安裝系統套件可能需要管理權限。`--headed` 需要桌面顯示環境。Linux 自動測試已配置於 CI；Linux／macOS 人工登入尚未全面驗證。

## 操作

| 操作 | 按鈕／快捷鍵 | 行為 |
| --- | --- | --- |
| 重新整理 | Ctrl+R | 真正重新載入目前網頁、回頂端、重建列表 |
| 下一批／更多留言 | Ctrl+N | 分段捲動瀏覽器，合併與去重 |
| 閱讀文章／單則留言 | Enter | 顯示已擷取文字與原文連結 |
| 讀取留言 | 文章畫面 C | 另開討論分頁，保留首頁位置 |
| 返回 | Esc | 回上一畫面；離開留言時停止讀取並關閉留言分頁 |
| 開啟瀏覽器 | Ctrl+B | 可見模式叫出視窗；背景模式保持背景執行 |
| 關閉 APP | Ctrl+Q／紅色按鈕 | 清理專用瀏覽器；操作中可能提示稍候 |

向下捲至距底部約一個畫面時預載下一批。忙碌／冷卻中的請求保留一次，向上捲會取消待執行的預載。這是接續載入，**不是兩邊捲軸百分比同步**。每個列表最多保留 2,000 篇；沒有新增不代表已到底。

留言只包含已載入、可辨識公開連結的討論項目；不推定完整留言數或巢狀層級。單次留言讀取設有時間上限，載入中可按返回。網站顯示「部分回覆無法顯示」時，程式無法補出未載入內容。

## 資料與隱私

| 資料 | 儲存位置／行為 |
| --- | --- |
| 瀏覽器登入與快取 | `platformdirs.user_data_dir("mythread-browser")/profile`；Windows 通常為 `%LOCALAPPDATA%\mythread-browser\profile` |
| 瀏覽器文章／留言列表 | 程式記憶體；不另存全文檔案，Chromium 仍可能自行快取網頁與媒體 |
| API Token | 系統 keyring；不可用時拒絕保存，不退回明文 |
| API 草稿、偏好、已讀 ID | `platformdirs.user_config_path("mythread")`；草稿為明文 |

程式不讀取／輸出 Cookie、密碼或網站內部 token，不攔截網路回應、不使用私有 API。瀏覽器仍會正常載入媒體；Terminal 純文字顯示不代表瀏覽器不下載圖片。

專用 profile 不是日常 Chrome 設定檔。登出請用 `--headed` 在 Threads 網頁操作；重設前先關閉 APP，再移除專用 profile（會失去該 profile 登入狀態）。不要把 profile、完整 DOM、憑證、實際草稿或未去識別的截圖提交至 Git／Issue。見 [安全政策](SECURITY.md)。

## 已知限制與排錯

| 現象 | 處理方式 |
| --- | --- |
| 找不到 Chromium／啟動失敗 | 用同一 `.venv` 安裝 Chromium；確認沒有另一個 APP 佔用 profile |
| 背景無資料、要求登入／驗證 | 關閉後用 `browser --headed`，手動完成再重啟 |
| `error`／無法辨識原文 | 用可見模式確認頁面；回報 DOM 診斷數字、版本與步驟 |
| `loading`／`unconfirmed` | 稍候重試；代表載入中或未確認，不等於沒有文章／留言 |
| 重新整理後舊文章消失 | 預期行為：重新整理會清除先前合併列表 |
| 下一批沒有新增 | 可能在尾端、仍載入或選擇器失效；不會無限自動重試 |
| 混入作者標籤／輪播頁碼 | 已知 DOM 限制，歡迎提供匿名合成 HTML 案例 |

引用／多連結容器可能略過；缺少推薦區標題時，留言列表可能混入其他文章。推薦／追蹤切換、網頁搜尋、回覆層級解析尚未提供專用操作。

折疊文字可在 `--headed` 手動展開；注意 Ctrl+R 會重載，可能重設展開狀態，並非單純重抓目前 DOM。保留展開狀態的獨立擷取操作列為後續改善項目。

## API 模式與離線示範

```powershell
# 示範不需 Chromium 或帳號
.\.venv\Scripts\mythread.exe --demo
# API：隱藏輸入 Token，再開啟介面
.\.venv\Scripts\mythread.exe login --token
.\.venv\Scripts\mythread.exe
```

API 模式保留 OAuth、公開帳號、搜尋、本機排序及確認後發文。搜尋成功不代表全站搜尋權限已核准；結果受 Meta 審查與權限限制。本機推薦不是官方首頁動態。完整操作見 [API 指南](docs/api.md)，其 HTTPS／OAuth 設定與瀏覽器模式無關。

## 開發與驗證

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev,browser]'
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest -q
```

自動測試使用 HTTP mock、Textual pilot 與真實 Chromium 上的合成 HTML，不使用真實 Threads 帳號、不發文。人工操作回報已確認部分 Windows 可見模式文章與留言可讀；headless 實站及各種網站版面仍需另行驗證。

CI 配置在 Windows／Linux、Python 3.11／3.13 執行測試與套件建置檢查；**配置不等於已在遠端通過**。測試數量以 pytest／CI 輸出為準。

- [貢獻指南](CONTRIBUTING.md)：環境、PR、測試與匿名 fixture
- [架構與資料流](docs/architecture.md)：來源分離、擷取與生命週期
- [維護與發行](docs/maintaining.md)：驗收、版本與倉庫設定
- [變更紀錄](CHANGELOG.md)

## 授權

採用 [MIT License](LICENSE)。第三方套件各自保留其授權；本授權不涵蓋 Threads 品牌或使用者內容。
