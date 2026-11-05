# 安全政策

目前以開發分支最新版本為修復對象；尚未承諾歷史版本的安全更新或回覆時限。此工具是個人實驗用戶端，不提供託管服務。

## 回報漏洞

不要在公開 Issue／PR 張貼漏洞利用細節、Cookie、Token、App Secret、callback URL、瀏覽器 profile 或私人內容。

若託管倉庫已啟用 GitHub 私密漏洞回報，請從 **Security → Advisories → Report a vulnerability** 回報。若尚未提供此入口／私人聯絡方式，可先開不含技術細節的 Issue，要求維護者建立私人回報管道；在管道確認前勿公開敏感資訊。本倉庫尚未設定公開聯絡信箱，不提供虛構地址。

回報請包含受影響 commit／版本、平台、最小重現方式、影響及建議修復；使用測試資料代替真實憑證。

## 安全邊界

- 瀏覽器模式只讀 UI／DOM；不匯出 Cookie、不讀密碼或內部 token、不逆向私有 API、不繞過驗證。
- profile 包含登入狀態與瀏覽器快取，由 Chromium 管理；不能當成一般診斷附件。它等同已登入的 session：共用電腦使用後請「清除登入資料」，不要把 profile 所在資料夾納入雲端同步或備份。POSIX 平台會設為 `0700`；Linux／macOS 上 Playwright 不使用系統金鑰圈，Cookie 加密強度有限。
- 專用 Chromium 一律啟用沙箱；`MYTHREAD_DISABLE_SANDBOX=1` 僅供無法使用沙箱的 Linux 主機，會降低網頁漏洞的隔離。
- 「清除登入資料」只刪除未被重新導向的 `profile` 目錄；未完全刪除時會顯示失敗，不會假裝已登出。
- 0.2 已移除 API／Token／OAuth／發文功能，不讀取或清理舊版 keyring 與草稿；legacy 版本的資料須分開管理。
- 可攜版隨附 Python／Node／Chromium，需隨上游安全更新重新建置；目前沒有自動更新或程式碼簽章，不可宣稱已簽署。
- CI 僅使用 mock／合成 HTML／暫存 profile，不應加入真實 Threads 憑證或上傳原始瀏覽器 artifacts。
- `.gitignore` 是防誤提交措施，不是秘密掃描或權限控制。提交前仍需檢查 staged diff。

若憑證已外洩，先透過相應服務撤銷或更換，再清理倉庫歷史；只刪除檔案或新增 ignore 規則不能撤銷已曝光的憑證。
