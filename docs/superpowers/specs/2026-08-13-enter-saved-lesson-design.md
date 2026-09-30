# TalkPath 直接進入已保存課程 設計規格

| 項目 | 內容 |
| --- | --- |
| 狀態 | Draft（2026-08-13） |
| 關聯文件 | [第三期進度](../../PROGRESS.md) |
| 使用情境 | 用戶已匯入過課程後，再次開啟 TalkPath 可以直接進入該課程練習，不需重新上傳課本圖片 |

## 1. 需求背景

現行 TalkPath 流程是「上傳課本圖片 → 確認範圍 → Vision 萃取 → LessonLens 保存 → 生成活動 → 練習」，session 只存在記憶體，重新整理頁面後流程中斷，且 UI 沒有任何「進入已保存課程」的入口。用戶必須重新上傳同一張圖片才能回到已保存的課程。

目標：首頁提供「繼續我的課程」，列出 LessonLens 中已保存的課程，點選後直接建立可練習的 session。

## 2. 現況限制（已核對的證據）

- `GET /api/lessons/{lesson_id}` 已存在（`SessionService.get_lesson` → LessonLens）。
- `LessonLensMarkdownRepository.list_lessons()` 已存在，但沒有對應 API route，前端無法取得課程列表。
- `SessionService.create_session` 支援 `lesson_id` 參數，但 `CreateSessionRequest` 只有 `operation_id`，API 未開放；scope 依賴記憶體 `_scopes`。
- `generate_activity` 要求 session.state 為 `ASK_GENERATE_ACTIVITY` 且 `lesson_id` 存在；要達到該狀態目前只能走「上傳 → 確認範圍 → import」。

## 3. 設計決策

### 3.1 列出已保存課程

- `GET /api/lessons`：回傳 `LessonSummary` 列表（lesson_id、title、scope、source_images 數量、content_items 數量），不帶完整 passage/內容，避免大 payload；需要細節時再呼叫 `GET /api/lessons/{lesson_id}`。
- `SessionService` 新增 `list_lessons()`，轉呼叫 `lesson_repository.list_lessons()`。

### 3.2 以既有課程建立 session

- 方案（建議）：`POST /api/sessions` 的 request 增加可選 `lesson_id`。建立時：
  1. 從 LessonLens 讀回 `LessonDraft`，取 `scope` 寫入 `_scopes`。
  2. session 直接建立為 `ASK_GENERATE_ACTIVITY`（scope_confirmed=True、lesson_id 已帶），使 `generate_activity` 可直接執行。
  3. `operation_id` 冪等語意沿用既有 `create_session`。
- 需要處理 SessionStateMachine：新增 UPLOAD_IMAGE → ASK_GENERATE_ACTIVITY 的允許路徑（或新增獨立的初始狀態建構函式），並確保不與既有「上傳 → 萃取」流程衝突。
- 若課程不存在：回傳 404 / `LessonNotFound`，不建立 session。

### 3.3 前端

- 首頁新增「繼續我的課程」區塊：呼叫 `GET /api/lessons`，以卡片列表顯示（標題 + scope + 單字數），點選後呼叫建立 session 並直接 render overview。
- 空狀態：沒有已保存課程時顯示說明文字與「開始新課程」按鈕，不顯示列表。
- 進入後沿用既有 overview/activity/preview（單字卡）流程。

## 4. 驗收條件

1. `GET /api/lessons` 回傳 temporary LessonLens 中已保存的課程摘要；空 vault 回傳空列表。
2. 以 `lesson_id` 建立 session 後，session 可直接 `generate_activity`，不需上傳圖片或確認範圍。
3. 前端可列出課程並進入 practice；static UI 契約測試覆蓋入口與渲染。
4. 全量 `uv run pytest -q`、`node --check`、`node --test`、`git diff --check` 通過。
