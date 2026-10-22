# Windows 可攜版

完整解壓縮 ZIP，進入 `mythread` 資料夾，雙擊 `mythread.exe`。不需安裝 Python，也不需另外安裝 Chromium。不要只複製 exe；`_internal` 與 `browsers` 資料夾都必須保留。

1. 程式開啟 Terminal；網站瀏覽器預設在背景執行。
2. 首次使用點「登入視窗」，在專用 Chromium 手動登入或處理驗證。
3. 回到 Terminal 點「完成登入」，程式會沿用已驗證的瀏覽器與目前頁面讀取文章。請保留網站視窗開啟，可自行最小化。

誤關網站視窗時，回首頁點「恢復讀取」會沿用登入資料，以 headless 模式重開並繼續讀取，不必重開 APP。若登入失效或需要驗證，依提示點「登入視窗」手動完成。若要清除既有登入或更換帳號，點「重新登入」；專用瀏覽器的登入與快取資料會清除，再開啟登入視窗。
4. Ctrl+R 重新整理、Ctrl+N 下一批、Enter 閱讀、C 看留言、Esc 返回。
5. 用「關閉 APP」或 Ctrl+Q 結束。不要在瀏覽器仍執行時移動發行資料夾。

設定檔仍在 `%LOCALAPPDATA%\mythread-browser\profile`，不在解壓縮目錄。這是「程式免安裝」，不是把登入憑證帶著走的可攜 profile。升級時解壓縮新版本到新資料夾即可沿用登入；不要同時執行兩份 APP。

開啟網頁需要網路。背景模式不會繞過驗證；重新登入請使用按鈕。原始 API Token、keyring 與 OAuth 功能不包含在此版本，也不會讀取或移除舊版憑證。

本發行包尚未簽署程式碼。Windows 可能顯示來源驗證提示；請核對下載來源及 SHA-256，不要停用系統防護。這不是安裝程式，也不會修改 PATH、hosts 或憑證庫。

排錯可在 PowerShell 執行：

```powershell
.\mythread.exe --version
.\mythread.exe --headed
.\mythread.exe --self-test
```

`--self-test` 只使用暫存 profile 與合成 HTML 檢查 Chromium、DOM 和 Textual，不連線 Threads，也不是實站驗證。切勿分享 `profile`、Cookie 或私人文章資料。

建置於開發機的驗證不等於「全新 Windows 已驗收」。正式發布前仍需在沒有 Python／Playwright／瀏覽器快取的乾淨 Windows x64 環境，驗證雙擊啟動、手動登入、背景閱讀、留言與退出。
