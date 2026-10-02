# 既有課程背景新增頁面驗證

日期：2026-10-02。正式專案：`D:\python\TalkPath`；隔離開發：`.worktrees/lesson-add-pages`。

## 結果與界線

程式與自動化驗證完成。資料庫、照片與課程檔案均使用臨時測試資料；模型、語音與 Pi 使用測試替身。沒有呼叫外部真實模型，也沒有操作正式課程資料。

真實瀏覽器人工驗收尚未執行：`cua.getState()` 回傳空的 apps／browsers，建立 iab 分頁回覆 `Browser is not available: iab`。Node 的 fake DOM 與初始化測試不能替代人工瀏覽器或實際手機操作。

## 需求覆蓋

| 驗收 | 已執行的證據 |
|---|---|
| AC01 唯讀身分、多頁、一頁新建 | API 拒絕額外 course identity 欄位與檔案／頁碼錯配；Node Add pages 保留原 ID、實際 FormData；static UI 檢查新建 input 無 multiple、新 input 有 multiple。 |
| AC02 textbook 舊 ID | worker fixture 使用已填 Book、無 textbook 後綴的原 ID，追加後僅一門課。 |
| AC03 接受後背景執行 | API 閘門暫停 vision，提交仍回 202；health、課程列表與另一 session 的活動生成可完成。另以受阻照片／SQLite 寫入測試事件迴圈可繼續。 |
| AC04 五頁一頁失敗 | `test_partial_failure_and_only_failed_page_retries`：12–16 中 13 首次失敗，其餘四頁成功，失敗原圖及頁碼保留。 |
| AC05 單頁 Retry | 上述測試僅 13 呼叫兩次；其餘頁一次，成功內容保留。direct／Pi 整合亦核對批次、段落、內容與來源圖片數量。 |
| AC06 前端斷線／重連 | 真 WebSocket disconnect 後 worker 繼續，重連取得 completed 快照；另驗證 SQLite 重開仍有結果。 |
| AC07 後端停止／重啟 | 真實 service.stop／新的 service.start：succeeded 保留，running／queued → interrupted，沒有自動模型呼叫，僅手動選定頁 Retry。 |
| AC08 存檔與狀態窗口 | 注入 Markdown 完成、SQL finish／reconcile 不可用，恢復後從 batch 校正 succeeded；模型一次、段落及批次不重複。停機期間已開始的發布 thread 先完成才恢復。 |
| AC09 冪等及處理中衝突 | SQLite 多連線 claim／Retry CAS、歷史 Retry 收據、相同 ID 不同 payload、active photo 衝突；提交／Retry 取消仍等待持久化與入隊。 |
| AC10 原圖及邊界 | 舊 session 引用過期、舊 upload 刪除後，retained photo 仍可 fresh session Retry；摘要竄改、路徑穿越、錯配 page、超限檔案拒絕。DB 接受失敗只清本次候選照片。 |
| AC11 通知與版本 | Node 驗證 revision 去舊、每輪完成一次、failed＋interrupted 計數、localStorage 失效回退；MESSAGE 的 View lesson 綁定實際 lesson_id。 |
| AC12 原功能與 Pi 相容 | 完整 Python、前端、Pi TypeScript 測試與 typecheck；worker direct／Pi double-save 與 Pi 已存檔後失敗均核對不重複。 |
| AC13 真實瀏覽器 | **待驗收**。fake DOM 已測初始化、多頁提交、頁碼 Cancel／Add anyway、遲到回應、通知與練習導航競態、Retry 重繪與同 ID 重送。 |

## 審查修正

- Retry 請求取消可能在 SQLite commit 後漏入隊：先觀察失敗測試，再加接受流程 shield，取消時等待接受完成。
- worker 準備照片及匯入狀態寫入阻塞 loop：先觀察失敗測試，再 offload 同步 I/O；狀態事件仍在原事件迴圈。
- 公開 RepositoryError 曾包含損壞課程的本機路徑：腐損教材測試先紅後綠，回應改為安全訊息，保留錯誤類型與狀態碼。
- 完成通知刷新詳情曾取消正在開始的練習請求：改背景 refresh，保持 navigation epoch／owner。
- Retry 列重繪曾恢復可按狀態並換 ID：以跨 render 的 Map 保留 pending／operation ID，模糊失敗重送沿用同 ID。

儲存子代理、前端子代理及獨立審查代理協作；主代理負責 worker／API／畫面整合與最後驗證。沒有變更模型提示詞、回應修復、課程 ID 或 Pi tool 契約。

## 驗證命令

- `uv run pytest -q -rs`：完整後端結果記於 HISTORY；略過包含 Windows symlink 權限及未開啟的 live tests。
- `node --test frontend/test/*.test.cjs`：32 passed。
- `npm run test`（pi-extension）：10 passed；`npm run typecheck` 通過。隔離工作樹先依現有 lock 執行 `npm ci`，未變更套件版本。
- `node --check frontend/app.js`、`node --check frontend/lesson-page-import.js`、`uv lock --check`、`git diff --check` 通過。

## 實作對計畫的調整

- 使用者授權選擇協作方式後，採主代理整合、獨立儲存與前端模組代理，而非原撰寫計畫時的單一代理安排。
- domain 測試實際為 `tests/unit/test_page_import.py`；fixture 留在相關測試檔，沒有增加全域 conftest fixture。計數／status 直接作為模型 property。
- Retry 收據只保存 operation_id／page_id；完成版本仍由 job 保存，不重複存 accepted_revision／created_at。重複 queue delivery 由 claim CAS 拒絕，不增加模型嘗試。
- 同步 SessionService upload helper 只在新建、未曝光且無 subscriber 的 worker session 中以 thread 執行；一般 session 事件不在 thread 操作 asyncio.Queue。
- 原分段提交建議改為一次功能提交；先前文件／診斷修改不混入功能提交。
- 後端重啟及保存窗口以真 service／repository 故障注入自動驗證；人工 fake server＋瀏覽器步驟仍待環境可用後執行。
