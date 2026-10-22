# 維護與發行

[返回 README](../README.md)

## 支援範圍與驗收

最低 Python 3.11，主要人工試用為 Windows。CI 規劃 Windows／Ubuntu、Python 3.11／3.13；配置檔存在不表示遠端已執行，macOS 與其他 Python 版本也不可據此宣稱支援完成。

每個 PR 應通過相關 regression、完整 pytest 及 `git diff --check`。套件 metadata／依賴變更還要通過 build 與 twine check。CI 不使用 Threads 帳號，不執行真實登入或發文。

DOM 變更至少驗證：作者與正文對應、原文與留言去重、時間不是正文、歧義容器、缺少 main、引用、推薦邊界、虛擬列表移除舊文章。UI 變更同時測滑鼠與快捷鍵、載入中返回、畫面卸載及不重複預載。

## 人工實站檢查

使用專用測試帳號／profile；這份清單是待執行流程，不是完成證明。

1. 可見模式手動登入後重新整理，核對數篇作者、正文與 permalink。
2. 捲動預載、向上閱讀、重新整理後清除舊列表。
3. 開留言、核對原文排除及數則留言，檢查返回後首頁位置。
4. 讀取中返回、關閉留言分頁、網路中斷、登入失效，確認可以恢復。
5. 關閉後用 headless 啟動，確認 session 沿用且沒有彈窗。
6. 記錄 commit、OS、Python／Playwright 版本、網站語言、日期及限制；不保存憑證或原始 DOM。

目前開發紀錄有 Windows 可見模式文章／留言成功回報，也有輪播頁碼、標籤、引用與底部載入問題。不要把這些個案提升成全站或 headless 實站保證。

## 依賴與 CI

`pyproject.toml` 為依賴範圍與版本唯一來源；目前未採用完整 lockfile，新的安裝可能解析不同相依版本。CI 記錄環境版本；若發生漂移，先附版本與最小重現，再決定是否縮小範圍，不盲目升級全部套件。

Dependabot 每月提出 Python／GitHub Actions 更新 PR。升級 Playwright 後需重新安裝相應 Chromium；升級 Textual 時特別檢查事件繼承與 worker／畫面生命週期。工作流程只需 `contents: read`，不在 `pull_request_target` 執行外部 PR 程式碼，不上傳登入 profile 或網站 trace。

CI 參考 [Playwright 官方 CI 指南](https://playwright.dev/python/docs/ci)。

## 發行流程

目前沒有自動發布 PyPI 或部署工作流程；`CHANGELOG.md` 的 Unreleased 不代表已發行。

1. 確認目標分支與工作樹，完成測試及適用的人工檢查。
2. 更新 `pyproject.toml` 版本，將 CHANGELOG 中已完成項目移至實際版本與日期；0.x 破壞性操作變更需明確說明。
3. 建置並檢查：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install build twine
   .\.venv\Scripts\python.exe -m build
   .\.venv\Scripts\python.exe -m twine check dist/*
   ```

4. 在獨立暫存 venv 安裝產出的 wheel，驗證 `mythread --help`／`mythread browser --help`；確認 wheel 包含 MIT 授權與 README metadata，不包含 profile／秘密。
5. 維護者決定是否建立 tag／GitHub release／PyPI 發布。未取得發行授權前，不把 merge／本機 build 視為發布指示。

## 公開倉庫前的設定

這些是託管平台設定，不能僅靠本機文件完成：

- 設定正式 remote，補上 `pyproject.toml` 的專案／Issue URL；目前不填占位網址。
- 在預設分支啟用 CI、分支保護與必要 status checks；實際跑過 Windows／Linux matrix 再標示徽章。
- 啟用 GitHub 私密漏洞回報，或提供維護者確認的私人聯絡管道，更新 SECURITY.md。
- 確認貢獻內容的授權來源與 MIT copyright 歸屬；依賴授權仍各自適用。
- 若開始接受多人協作，指定實際維護者與 review 責任，再建立 CODEOWNERS；不要填虛構帳號。

## 後續優先項目

1. 擷取品質：作者標籤／輪播計數、引用、推薦區與留言層級。
2. 獨立「擷取目前 DOM」操作，避免重載後失去手動展開的內容。
3. 擴充實站 smoke 記錄與不同語言／版面的匿名 fixtures。
4. 需要時再抽離共用純文字與文章閱讀元件，降低瀏覽器 UI 對 API UI 的耦合。
5. 官方網頁推薦／追蹤切換、搜尋；維持唯讀與手動驗證邊界。
