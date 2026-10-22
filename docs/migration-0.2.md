# 0.2 瀏覽器獨立版遷移

0.2 將瀏覽器路徑視為主產品，API 實作保留於 Git 歷史，不再包含在目前程式或發行包。

| 項目 | 舊版 | 0.2 |
| --- | --- | --- |
| 背景啟動 | `mythread browser` | `mythread` |
| 可見啟動 | `mythread browser --headed` | `mythread --headed` 或「登入視窗」按鈕 |
| 完成登入回背景 | 關閉再重啟 | 「完成登入」按鈕 |
| 原始碼依賴 | `.[browser]` | `.`（Playwright 為必要依賴） |
| 開發依賴 | `.[dev,browser]` | `.[dev]` |
| API、Token、OAuth、發文、demo | 另有指令 | 已移除，不提供相容別名 |
| Windows 發行 | 需要 Python | 可建置完整資料夾式 exe ZIP |

保留的本機 Git refs：

- `legacy/api` → `c105b34`：純 API 基線。
- `experiment/browser-bridge` → `609b309`：拆分前、API 與瀏覽器並存的版本。
- `browser/main`：瀏覽器獨立版開發線。

原先 `main` 與原 worktree 保持原狀，沒有重設或合併。尚未設定遠端預設分支；發布前由維護者決定是否將 `browser/main` 推送並設為預設分支。

專用瀏覽器 profile 路徑不變，可沿用登入。舊 API 的系統 keyring、草稿與偏好不會被讀取、遷移或刪除；若要管理它們，請使用 legacy 版本。不要將個人 profile 複製進可攜版或倉庫。

想執行 API 舊版時，另外建立 worktree 與獨立 venv：

```powershell
git worktree add --detach ..\myThread-api-legacy legacy/api
```

請勿在瀏覽器主線重新加入 API 依賴來恢復舊功能；需要新功能時優先討論唯讀網頁操作範圍。
