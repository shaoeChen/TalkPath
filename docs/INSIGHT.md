# TalkPath 關鍵洞察

> 記錄討論過程中的關鍵洞察（為何這樣決定、發現了什麼），供日後回顧。每則附日期。

## 2026-09-30

- 文件流轉採「單向、不重複」原則：`IDEAS` → `PLANS` → （實作計畫書）→ `PROGRESS` → `HISTORY`，每個項目同一時間只存在於一處，避免多份文件狀態不一致。
- 語音錄音的 `getUserMedia` 需要 secure context，純 HTTP 區網無法使用麥克風（詳見 `PLANS.md` 區網連線項目）。
- 錄音轉不出字的根因曾是麥克風全靜音（環境問題，非程式問題）；遇到 STT 異常應先排除環境（詳見 `HISTORY.md` 2026-08-15）。
- 上一輪「同課程分次匯入」失敗的主因是範圍過大（約 4,000 行、35 個檔案），並動到抽取、提示詞與 Pi internal tools，污染了已穩定的生成邏輯。重做時的原則是：抽取流程不動，合併只放在儲存前唯一的插入點（`SessionService._save_lesson_draft`）。
- 附加匯入的隱藏地雷：Pi 路徑的 `save_lesson_draft`、`generate_activity_for_lesson` 會比對 `lesson.scope == session scope`，附加後 pages 變成聯集就會對不上。合併後必須同步 session scope。
- 加入 TEXTBOOK 識別時，textbook 為空則 `lesson_id` 維持原格式，既有課程與 SQLite 進度的 key 都不需要 migration。
- 前端的來源契約測試只驗證程式碼字串，抓不到真實行為：`.scope-notice { display: grid }` 蓋過 `hidden` 屬性，警告框取消後不會消失，是用真實瀏覽器（Chrome＋暫存資料夾＋fake provider）走流程才發現。前端功能完成前，除了契約測試，也要實際操作一次。
- 專案 `.env` 設定了真實的 vision／text provider；做瀏覽器驗證時不能用 `create_app()` 讀設定啟動，必須手動組裝 fake 服務，避免測試圖片被送到外部模型。
- 課程 ID 新增識別欄位（如 textbook）時，必須讓「舊 ID 仍能通過驗證」，否則已存檔課程會讀取失敗，連帶 `list_lessons` 整個失敗。
- 後端改版後必須重啟伺服器（未加 `--reload` 時舊程序會一直跑舊路由），而前端靜態檔每次從硬碟讀取、會立即是新版；兩者版本不一致時，新畫面呼叫新 API 會得到 FastAPI 預設的 `{"detail":"Not Found"}`。排查 404 先看 `/openapi.json` 的路由清單。
