# 貢獻指南

感謝協助改善 myThread。請先閱讀 [README](README.md)、[架構](docs/architecture.md)與 [安全政策](SECURITY.md)。討論請描述可重現的行為，尊重不同使用者，避免人身攻擊或貼出他人的私人內容。

## 建立環境

在自己的 clone／worktree 建立獨立 `.venv`，不要共用其他 worktree 的環境。Python 最低版本為 3.11；瀏覽器測試需要 Playwright 與完整 Chromium（不能只安裝 headless shell）。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,browser]'
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest -q
```

Linux／macOS 將 `.venv\Scripts\python.exe` 換成 `.venv/bin/python`；Linux CI 使用 `playwright install --with-deps chromium`。只體驗 API／demo 可不安裝 browser extra，但完整測試需安裝。

## 提交變更

1. 先查現有 Issue；大型功能先描述使用情境、範圍與驗證方式。
2. 使用獨立分支，將修復與無關重構分開。不要順手改動日常瀏覽器設定或作業系統設定。
3. 遵循現有 Python 風格：4 空格、UTF-8、清楚命名；遠端內容透過 `plain()` 清理並以 Rich `Text` 顯示，不當作 markup。
4. 功能／錯誤修復補對應回歸測試，先跑相關檔案再跑全套；純文字修改不需新增鏡像測試。
5. 修改行為時同步更新 README／指南與 CHANGELOG；`git diff --check` 應通過。
6. PR 說明問題、修改後行為、測試命令與限制。區分 mock、合成 DOM 與真實 Threads 驗證。

目前沒有強制 formatter／linter；不要為了小修復重排整個程式庫。新增依賴必須說明用途並更新 `pyproject.toml`，不可依賴個人電腦已安裝的套件。

## 測試策略

| 範圍 | 方法 |
| --- | --- |
| API／OAuth／儲存 | HTTP mock、假的 keyring、暫存目錄 |
| 瀏覽器擷取 | Chromium `set_content()` 加匿名合成 HTML |
| 互動流程 | Textual `run_test()`／pilot，滑鼠與快捷鍵都要驗證 |
| 持久化 profile | pytest `tmp_path`，不得使用真正登入的 profile |
| 實站檢查 | 使用者手動登入，另記錄環境與限制，不放在 CI |

瀏覽器 regression 重點：時間／工具列不是正文、虛擬列表、去重、捲動容器、失效選擇器、忙碌時返回、逾時、headless／headed、頁面關閉。非同步測試不要留下未結束的 worker、task 或瀏覽器程序。

`HeaderTitle` 與按鈕事件曾發生生命週期錯誤：Textual 的 `event.stop()` 只阻止冒泡；覆寫父類別事件時可能還需 `prevent_default()`。請以實際點擊測試確認，不能只測快捷鍵。

## 回報擷取問題

提供 commit、Python／Playwright／作業系統版本、模式、操作步驟、預期／實際結果，以及畫面顯示的 DOM 診斷數字。不需提供 Token、Cookie、真實帳號或完整 DOM。

製作 fixture 時，以虛構作者與文字重建最小 DOM，保留導致錯誤的結構（例如沒有 `<main>`、原文為引用、時間位於連結外）。不要保存網路回應、登入頁、整頁 HTML、真實 profile 或私人留言。

一般功能使用 Issue／PR 模板；安全問題走 [私密回報流程](SECURITY.md)。提交貢獻表示你有權提供內容，並同意以本專案 MIT 授權散布該貢獻。
