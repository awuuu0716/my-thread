# 維護、打包與發行

## 驗收與支援

Python 最低 3.11，主要人工試用為 Windows；來源 CI 配置 Windows／Ubuntu、Python 3.11／3.13。可攜 exe 目前僅 Windows x64，必須在 Windows x64 建置。配置不代表遠端已通過；macOS 未全面驗證。

PR 應執行相關 regression、完整 pytest、`git diff --check`。套件修改另跑 build／twine check。測試不使用 Threads 帳號，滑鼠與快捷鍵都要驗證，不能只測其中一種。

依賴與版本來自 `pyproject.toml`。目前未採全量 lockfile，發行時保存實際版本；升級 Playwright 必須一起換相應 Chromium，升級 Textual 要檢查事件繼承／畫面卸載。Dependabot 每月提出更新 PR。

## 建置 Windows 可攜版

使用乾淨的專用建置環境，避免混入 legacy API 或其他開發套件：

```powershell
python -m venv .tools\bundle-env
.\.tools\bundle-env\Scripts\python.exe -m pip install -e '.[bundle]'
.\.tools\bundle-env\Scripts\python.exe scripts/build_windows.py
```

腳本下載對應的完整 Chromium 到已忽略的 `.tools/playwright-bundle-cache`，使用 PyInstaller `onedir`／console 打包 Python、Playwright driver、Textual，將 Chromium 放在發行包 `browsers`。保留各元件授權與版本清單，不複製個人 profile。

每次建立新的 `dist/mythread-版本-windows-x64-時間/`，不覆蓋既有版本。內含 `mythread/mythread.exe`、`_internal`、`browsers`、使用說明與 notices。腳本從不同工作目錄、帶錯誤的使用者瀏覽器快取設定執行 exe `--self-test`，通過後才產出 ZIP 與 `.sha256`。

ZIP 很大是因為包含 Chromium 與 Python／Node 執行環境；不要為了縮小體積刪除必要 DLL 或授權檔。完整建置需網路下載套件／瀏覽器，使用者執行不需 Python；讀取 Threads 仍需要網路。

參考 [Playwright 打包說明](https://playwright.dev/python/docs/library#pyinstaller)與 [PyInstaller 使用說明](https://pyinstaller.org/en/stable/usage.html)。

## 乾淨 Windows 驗收（尚需人工完成）

不要把開發機的離線 smoke 視為此清單完成：

1. 在沒有 Python、Playwright 或瀏覽器快取的 Windows x64 VM／電腦，完整解壓縮。
2. 雙擊 exe，確認 Terminal 正常顯示，首次使用可以點登入按鈕。
3. 手動登入，點完成登入，確認網站視窗關閉但文章可讀。
4. 讀留言、更多、捲動預載、重整、返回、關閉，再啟動確認登入延續。
5. 測試失去網路、頁面關閉、登入驗證、不同路徑與非 ASCII 使用者目錄。
6. 記錄 commit、ZIP SHA-256、Windows 版本、測試結果與限制，不保存個人 profile 或原始 DOM。

發行包目前未簽署，尚無自動更新機制；來源／簽章／下載管道與乾淨機驗收完成前，不宣稱正式穩定版本。

## 原始碼套件

```powershell
.\.venv\Scripts\python.exe -m pip install build twine
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m twine check dist/mythread_terminal-0.2.0.tar.gz dist/mythread_terminal-0.2.0-py3-none-any.whl
```

升版時更新命令中的版本。清潔 venv 安裝 wheel 並驗證 `mythread --help`、`--version`；wheel 使用者仍需 `python -m playwright install chromium`，只有可攜 ZIP 隨附瀏覽器。

## 發行與倉庫設定

CI 自動測試與 build；Windows 可攜版 workflow 為手動觸發，只上傳建置 artifact，不建立 release 或發布 PyPI。維護者確認後才能建立 tag／正式 release。

目前 API 歷史在 `legacy/api`，拆分前在 `experiment/browser-bridge`，瀏覽器主線在 `browser/main`。原 `main` 不自動改寫；設定 remote 與預設分支、分支保護、私密漏洞回報、CODEOWNERS 需由維護者依實際倉庫設定，不填占位帳號。

後續優先項目：引用／標籤／輪播計數／推薦區擷取品質、保留手動展開的 DOM 擷取操作、不同語言 fixture、推薦／追蹤切換與網頁搜尋。持續維持唯讀與手動驗證邊界。
