# TalkPath 實作計畫交接進度

> 本文件是本次 TalkPath 實作計畫的進度交接文件。
> 實作計畫是否完成，以本文件的 Task 狀態與驗證結果為準。

更新日期：2026-08-11  
對應計畫：[2026-08-10-talkpath-implementation.md](superpowers/plans/2026-08-10-talkpath-implementation.md)

## 1. 總體狀態

原始實作計畫 Task 1～Task 10 已完成（以 fake provider、測試替身與本機 TestClient 驗證）；2026-08-11 的 LessonLens activity persistence bounded follow-up 也已完成。

目前完成情況：

- Task 1～Task 8：已完成
- Task 9：已完成（fake-provider 範圍）
- Task 10：已完成（fake-provider 範圍）

因此目前不能宣稱實際模型、真實 Pi agent、瀏覽器與音訊設備整合完成；目前狀態是「fake-provider 後端、兒童 UI 垂直流程與 LessonLens activity persistence 完成，完整回歸與交付檢查已通過」。

## 2. 實作計畫執行狀態

| Task | 內容 | 狀態 | 實際成果與證據 |
| --- | --- | --- | --- |
| Task 1 | Python 專案骨架、設定與 FastAPI 入口 | 已完成 | `pyproject.toml`、`src/talkpath/config.py`、FastAPI app、health check 與測試入口已建立 |
| Task 2 | 領域模型、Session 狀態機與服務接口 | 已完成 | `domain/models.py`、`domain/errors.py`、`ports/` 與相關單元測試已建立 |
| Task 3 | LessonLens Markdown repository | 已完成 | Obsidian 相容的 Markdown／YAML frontmatter 儲存、讀取、重試與安全檢查已建立 |
| Task 4 | SQLite 學習進度 repository | 已完成 | Session、作答紀錄、錯題回顧與 idempotency 已建立並通過測試 |
| Task 5 | 視覺、文字、STT、TTS provider adapters | 已完成 | Fake provider、HTTP provider、provider registry 與錯誤轉換已建立 |
| Task 6 | Pi RPC client 與 TypeScript extension | 已完成 | Python Pi JSONL RPC、request correlation、生命週期處理、白名單工具與 TypeScript 測試已建立 |
| Task 7 | Session service、課本匯入 API 與內部工具 API | 已完成 | Session service、課程範圍確認 gate、圖片上傳、匯入、活動生成入口、WebSocket 與 loopback internal tools 已建立 |
| Task 8 | 兒童 Web UI 垂直流程 | 已完成 | `frontend/` 三個檔案、cwd-independent FastAPI 靜態掛載、圖片上傳、scope gate、WebSocket 狀態、單一 ActivityPanel、音訊 fallback 與回歸測試已完成；答案已在公開 API 邊界遮罩 |
| Task 9 | 活動、作答回饋與語音互動 | 已完成（fake-provider 範圍） | `ActivityService`、公開作答評估、SQLite attempt/review、公開 STT/TTS API、answer redaction 與文字 fallback 已完成；實際音訊 provider 尚未接入 |
| Task 10 | 端到端驗證與交付文件 | 已完成（fake-provider 範圍） | `tests/integration/test_textbook_to_activity.py` 與 `tests/integration/test_failure_recovery.py` 已建立並通過；README、產品進度與設計規格已同步更新；完整 pytest、TypeScript 與 JavaScript 驗證均通過 |

## 2.1 LessonLens activity persistence bounded follow-up

| Task | 狀態 | 實際成果與證據 |
| --- | --- | --- |
| Follow-up Task 1 | 已完成 | tests/unit/test_lessonlens_activities.py 已涵蓋 round-trip、idempotency、identity conflict、unsafe ID 與內部答案保存 |
| Follow-up Task 2 | 已完成 | LessonLensMarkdownRepository 已提供 activity path、atomic write、operation-id 冪等、activity／lesson／nested-item identity validation 與跨 instance reload |
| Follow-up Task 3 | 已完成 | 聚焦回歸 uv run pytest tests/unit/test_lessonlens_activities.py tests/unit/test_lessonlens_markdown.py tests/unit/test_activity_service.py -q -> 33 passed、4 skipped；文件與 diff 檢查完成 |
## 3. 已完成的核心能力

目前系統已具備以下能力：

1. 建立兒童學習 Session。
2. 接收課本圖片並建立受控的圖片參照。
3. 在課本內容萃取前要求確認課程範圍，例如「國中一年級、英文、第一課」。
4. 以 `CourseScope`、`LessonDraft`、`ContentItem`、`Activity` 等模型保存結構化資料。
5. 將課程內容保存到 LessonLens Obsidian Markdown 結構。
6. 以 SQLite 保存學習 Session、作答結果與錯題回顧項目。
7. 預留視覺模型、文字模型、語音轉文字與文字轉語音的 provider 介面。
8. 透過 Pi RPC 與 TalkPath TypeScript extension 連接 Pi agent。
9. 提供公開 Session API、課本匯入 API、活動生成入口與 Agent WebSocket 事件。
10. 提供兒童 Web UI 的課本上傳、課程範圍確認、匯入狀態、課程預覽、活動總覽與結果／進度佔位畫面。

## 4. 驗證結果

最後一次已執行的驗證結果：

- 完整 Python：`uv run pytest -q -rs` -> `175 passed, 4 skipped`
- Task 10 integration：`7 passed`
- Pi TypeScript：`npm test --prefix pi-extension` -> `9 passed`
- TypeScript：`npm run typecheck --prefix pi-extension` -> 通過
- JavaScript：`node --check frontend/app.js` -> 通過

- LessonLens activity persistence 聚焦回歸：uv run pytest tests/unit/test_lessonlens_activities.py tests/unit/test_lessonlens_markdown.py tests/unit/test_activity_service.py -q -> 33 passed, 4 skipped
- Pi extension：npm install --prefix pi-extension 完成；npm test --prefix pi-extension -> 9 passed；npm run typecheck --prefix pi-extension -> 通過；node --check frontend/app.js -> 通過
- Node 依賴安裝時 npm audit 回報 3 個 vulnerabilities（1 moderate、2 high）；本次只切齊進度文件，尚未進行依賴升級或安全修補

Python 測試曾受到使用者層級 `uv` cache 權限影響，改用專案內 `.uv-cache` 後完成測試。4 個 skip 都是 Windows 測試環境沒有建立 symlink 的特殊權限，分別是 LessonLens 對 symlink lesson/content/source 與 vault escape 的防護測試；不是功能失敗，也沒有因此跳過一般流程測試。

目前驗證以 fake provider、HTTP contract、Pi RPC fixture 與 FastAPI TestClient 為主；尚未使用實際視覺模型、實際文字模型、實際 STT/TTS 服務與真實 Pi agent 完成完整流程。

## 5. 實作計畫完成後的後續事項

### 5.1 Task 8：Web UI 後續改善（不阻塞本次完成）

- 補充真實瀏覽器環境的 WebSocket、重連與音訊 fallback 整合測試。
- 後續可補上 CSP/security headers 與更細緻的 WebSocket 診斷錯誤處理。

### 5.2 實際 provider 與設備整合（不屬於本次 Task 1～10）

- 接入實際視覺模型、文字模型、STT、TTS 與真實 Pi agent。
- 以真實瀏覽器與實體麥克風/喇叭補做 WebSocket、重連與音訊整合測試。
- 實際設備音訊不可用時，保留目前的文字 fallback。

### 5.3 正式工作區交付

- 本輪已確認目前工作區為使用者指定的正式路徑：D:/python/TalkPath。
- Python 全量測試、LessonLens activity persistence 聚焦測試、Pi TypeScript 測試、TypeScript typecheck 與 JavaScript syntax check 均在此工作區完成。
- C:/Users/<user>/Documents/Codex/2026-08-10/d-python 為歷史副本；後續以 D:/python/TalkPath 為唯一交接與開發起點，避免兩份工作區分叉。
## 6. 交接時的路徑注意事項

使用者原始要求與目前實際工作區都是：

D:/python/TalkPath

本輪已直接從該工作區讀取並驗證程式、測試與進度文件。歷史副本 C:/Users/<user>/Documents/Codex/2026-08-10/d-python 仍存在，但不再作為本次交接的活動工作區；後續執行者應以 D:/python/TalkPath 為準。
## 7. Task 10 本次執行狀態（2026-08-11）

### 已完成

- integration tests 使用 temporary LessonLens root、temporary SQLite、FakeVision/FakeText/FakeSTT/FakeTTS/FakePi。
- 完整流程驗證 scope confirmation、LessonLens `lesson.md`、`vocabulary/`、`grammar/`、`vocabulary_quiz`、錯誤作答、SQLite attempt/review item、public lesson/activity/progress，以及 repository restart 後 activity 可讀與 answer redaction。
- failure recovery 驗證錯誤 response code、retryable、`FAILED` 或可重試狀態，以及失敗不留下半寫入 lesson/activity/attempt。

### 路徑限制與已知限制

本次驗收直接使用：

D:/python/TalkPath

驗收使用 fake provider、FastAPI TestClient、temporary LessonLens root 與 temporary SQLite files；實際模型、真實 Pi agent、瀏覽器自動化、實體音訊設備與 production endpoint 尚未接入。Node 依賴目前有 npm audit 回報的 3 個 vulnerabilities，尚未在本次文件同步中處理。
### 下一個開發起點

下一個開發起點是依需求接入實際模型、真實 Pi agent、瀏覽器與實體音訊設備，並補做真實瀏覽器 WebSocket／重連／音訊 fallback 與安全標頭檢查；本次不把這些未接入項目宣稱為完成。

## 8. 歷史交接摘要

本文件早期曾記錄 Task 9 尚待完整回歸；該狀態已由 2026-08-11 的完整 Python、Pi TypeScript、TypeScript typecheck、JavaScript syntax 與 LessonLens activity persistence 聚焦驗證取代。後續執行者以本文件前述 Task 1～Task 10、bounded follow-up、真實整合限制與 D:/python/TalkPath 工作區狀態為準。