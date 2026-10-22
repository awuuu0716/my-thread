# 安全政策

目前以開發分支最新版本為修復對象；尚未承諾歷史版本的安全更新或回覆時限。此工具是個人實驗用戶端，不提供託管服務。

## 回報漏洞

不要在公開 Issue／PR 張貼漏洞利用細節、Cookie、Token、App Secret、callback URL、瀏覽器 profile 或私人內容。

若託管倉庫已啟用 GitHub 私密漏洞回報，請從 **Security → Advisories → Report a vulnerability** 回報。若尚未提供此入口／私人聯絡方式，可先開不含技術細節的 Issue，要求維護者建立私人回報管道；在管道確認前勿公開敏感資訊。本倉庫尚未設定公開聯絡信箱，不提供虛構地址。

回報請包含受影響 commit／版本、平台、最小重現方式、影響及建議修復；使用測試資料代替真實憑證。

## 安全邊界

- 瀏覽器模式只讀 UI／DOM；不匯出 Cookie、不讀密碼或內部 token、不逆向私有 API、不繞過驗證。
- profile 包含登入狀態與瀏覽器快取，由 Chromium 管理；不能當成一般診斷附件。
- API Token 存在系統 keyring，草稿是本機明文。API 發文須確認，網路結果不明時不自動重送。
- CI 僅使用 mock／合成 HTML／暫存 profile，不應加入真實 Threads 憑證或上傳原始瀏覽器 artifacts。
- `.gitignore` 是防誤提交措施，不是秘密掃描或權限控制。提交前仍需檢查 staged diff。

若憑證已外洩，先透過相應服務撤銷或更換，再清理倉庫歷史；只刪除檔案或新增 ignore 規則不能撤銷已曝光的憑證。
