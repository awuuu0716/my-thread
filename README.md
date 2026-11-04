# myThread Terminal

透過專用瀏覽器，在 Terminal 閱讀 Threads 動態、文章與留言。Python 3.11+、Textual、Playwright；網站預設在背景執行，Terminal 保留純文字閱讀介面。這是非官方唯讀專案，未獲 Meta 背書。

**0.2 瀏覽器獨立版**不再包含 API、OAuth、Token、搜尋 API 或發文功能。程式入口為 `mythread`，不需 `browser` 子指令。網站版面與驗證流程可能改變，目前仍屬實驗階段。

## Windows：直接執行可攜版

取得此版本的 Windows x64 ZIP 後完整解壓縮，進入 `mythread` 資料夾，雙擊 **`mythread.exe`**。包含 Python 執行環境與 Chromium，不需另外安裝 Python／瀏覽器；不可只複製 exe，請保留 `_internal` 與 `browsers`。

目前可在本機用[建置指令](docs/maintaining.md)產出 ZIP，尚未宣稱已發布下載頁。詳見 [可攜版操作與驗收](docs/portable.md)。可攜版保留 Terminal 視窗，只有網站瀏覽器在背景執行。

## 登入與閱讀

1. 啟動後自動在背景開啟專用 Chromium，嘗試沿用登入狀態並讀取文章。
2. 首次使用或需要驗證時，點首頁「**登入視窗**」，在可見 Chromium 手動登入。程式不代填密碼、不繞過驗證碼。
3. 回 Terminal 點「**完成登入**」：沿用已驗證的瀏覽器與目前頁面讀取文章，不重啟瀏覽器。請保留網站視窗開啟，可自行最小化；關閉 APP 時會一併關閉。
4. 文章列表直接顯示完整內文，Enter 開啟文章詳情；C 開啟留言；O 在預設瀏覽器查看原文；Esc 返回。首頁讀取到文章但不足 10 篇時，會自動接續載入，直到至少 10 篇；沒有新增文章、需要登入或讀取失敗時停止，每次最多自動追加 10 批。接近列表底部也會自動預載下一批。

不需要 Meta App、App Secret、API Token、hosts 或 HTTPS callback。背景模式不會自動彈出網站視窗；只有使用者點「登入視窗」或指定 `--headed` 才顯示。

## 從原始碼啟動

在倉庫根目錄使用 Python 3.11+ 建立獨立環境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\mythread.exe
```

可選參數：

```powershell
.\.venv\Scripts\mythread.exe --headed
.\.venv\Scripts\mythread.exe --version
.\.venv\Scripts\mythread.exe --self-test
```

`--headless` 明確指定背景模式（也是預設）。`--self-test` 使用暫存 profile／合成 HTML 測試 Chromium、擷取與 Textual，不連線 Threads，不讀真實登入資料。

Linux／macOS 使用 `python3` 建立 venv，將執行檔路徑換成 `.venv/bin/python`／`.venv/bin/mythread`。Linux 必要時執行 `.venv/bin/python -m playwright install --with-deps chromium` 安裝系統函式庫；`--headed` 需要桌面環境。主要人工試用平台是 Windows；macOS 尚未全面驗證。

## 操作

| 操作 | 按鈕／快捷鍵 | 行為 |
| --- | --- | --- |
| 登入視窗 | Ctrl+B | 重新啟動為可見瀏覽器，手動登入／驗證 |
| 完成登入 | 首頁按鈕 | 沿用已驗證的視窗與頁面讀取文章 |
| 更多 | 首頁按鈕 | 展開登入管理、恢復讀取與關閉 APP；主要操作依目前狀態顯示 |
| 診斷資訊 | 首頁「更多」 | 展開目前來源狀態與安全診斷訊息，供回報問題；不顯示原始例外或完整 DOM |
| 恢復讀取 | 首頁「更多」；瀏覽器關閉時自動顯示 | 誤關瀏覽器後，沿用登入資料以 headless 模式重開、讀取首頁；需驗證時提示開啟登入視窗 |
| 清除登入資料 | 首頁「更多」 | 顯示確認視窗，預設取消；確認後關閉專用瀏覽器、清除其登入與快取資料，再開啟登入視窗 |
| 重新整理 | Ctrl+R | 真正重載網頁、回頂端、清除並重建列表 |
| 載入更多／更多留言 | Ctrl+N | 分段捲動瀏覽器、合併與去重；尚無文章或載入中時不可使用 |
| 閱讀文章／單則留言 | Enter | 顯示已擷取文字與原文連結 |
| 留言數 | 文章列表作者旁 | 顯示網站留言／回覆控制項上的數量；無法辨識時顯示「-」，不代表 0，也不保證能載入全部留言 |
| 分篇編號 | 作者旁 | 文章末尾獨立的 `1/2` 等編號移到此處顯示為「分篇 1/2」；句子內的分數維持原文 |
| 返回上一層 | Esc／滑鼠右鍵 | 文章返回列表、留言詳情返回留言列表、留言列表返回文章；右鍵需終端機將滑鼠事件傳給 APP |
| 讀取留言 | 文章畫面 C | 另開討論分頁，保留首頁位置 |
| 查看原文 | 文章／留言詳情 O 或原文按鈕 | 依明確操作在預設瀏覽器開啟該則公開原文連結 |
| 返回 | Esc | 回上一畫面；離開留言時停止讀取並關閉該分頁 |
| 關閉 APP | Ctrl+Q／關閉按鈕 | 清理專用瀏覽器；操作中先排定關閉，待目前操作結束後離開 |

建議 Terminal 110×35，亦針對 80×24、60×20 檢查操作入口。文章列表顯示已擷取的完整內文，依視窗寬度換行；留言列表保留三行摘要，Enter 可開啟詳情。距列表底部約一個畫面時開始預載；忙碌／冷卻時保留一次請求，向上捲取消尚未執行的預載。這是接續載入，不是兩側捲軸等比例同步。每個列表最多保留 2,000 篇；追加或移除較舊項目時，盡可能保留仍存在的閱讀位置。新增 0 不代表已到底。

## 資料與隱私

- 登入與瀏覽器快取保留於專用 profile：Windows 通常為 `%LOCALAPPDATA%\mythread-browser\profile`，其他平台由 `platformdirs.user_data_dir("mythread-browser")` 決定。升級 0.1 瀏覽器版可沿用此路徑。
- 不操作日常 Chrome profile；同一專用 profile 一次只能啟動一份 APP。
- 列表保留在記憶體，不另存文章全文檔；Chromium 仍會正常載入媒體並可能自行快取。
- 不讀取／輸出 Cookie、密碼或內部 token，不攔截網路回應、不使用私有 API。
- 不自動按讚、追蹤、回覆或發文。

登出可點「登入視窗」後在 Threads 網站操作（正常閱讀時可先展開「更多」）。需要清除既有登入或更換帳號時，點「更多」→「清除登入資料」，閱讀確認說明後再確認；程式會先關閉專用瀏覽器，再清除專用 profile（含登入與快取），不影響日常 Chrome。取消或 Esc 不會清除資料。手動移除 profile 前請先關閉 APP。不要分享 profile、完整 DOM、憑證或含私人內容的截圖，見 [安全政策](SECURITY.md)。

## 已知限制與排錯

| 現象 | 處理方式 |
| --- | --- |
| 需要登入／驗證 | 首頁點「登入視窗」，手動完成後點「完成登入」 |
| 誤關網站視窗／瀏覽器已關閉 | 回首頁點「恢復讀取」，不必重開 APP；若網站要求驗證，再手動完成登入 |
| 清除登入／更換帳號 | 首頁「更多」→「清除登入資料」並確認，在新視窗登入後點「完成登入」 |
| 可攜版缺少瀏覽器 | 完整解壓縮 ZIP，保留 `browsers` 與 `_internal` |
| 原始碼啟動失敗 | 用同一 venv 安裝 Chromium；確認沒有另一份 APP 佔用 profile |
| 讀取失敗／無法辨識原文 | 用登入視窗查看頁面，回報版本、重現步驟及「更多」→「診斷資訊」中的診斷數字 |
| 載入中／尚未確認內容 | 仍在載入或未確認，不能當作沒有文章／留言 |
| 重新整理後舊文章消失 | 預期行為：重載會清除舊合併列表 |
| 混入標籤／輪播頁碼 | 已知 DOM 限制，歡迎提供匿名合成 HTML 案例 |

留言只列出網頁已載入的討論項目，不保證完整留言數、回覆層級或推薦區完全排除。引用／多連結容器可能略過。網站顯示「部分回覆無法顯示」時，程式不能補出未載入內容。

Ctrl+R 會重載並可能重設手動展開狀態；保留展開狀態的獨立擷取操作、推薦／追蹤切換、網頁搜尋仍屬後續項目。

## 開發與驗證

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest -q
```

測試包括 Textual pilot、合成 DOM、來源 mock 與暫存 profile，不使用真實帳號。Windows 可見模式文章／留言有人工成功回報；網站版面、headless 及可攜版乾淨機器驗收需分開記錄，不能用離線測試代替。

- [貢獻指南](CONTRIBUTING.md)
- [架構](docs/architecture.md)
- [UX 驗收清單](docs/ux-validation.md)
- [維護、打包與發行](docs/maintaining.md)
- [0.2 遷移與歷史分支](docs/migration-0.2.md)
- [變更紀錄](CHANGELOG.md)

## 授權

採用 [MIT License](LICENSE)。第三方套件與隨附 Chromium／Python／Node 各有授權，可攜版保留其 license／notice 檔案及版本清單；本專案授權不涵蓋 Threads 品牌或使用者內容。
