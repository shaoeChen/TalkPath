# TalkPath 已保存課程入口改版（導覽列 + 獨立頁面）設計規格

| 項目 | 內容 |
| --- | --- |
| 狀態 | 已確認（2026-08-13，用戶以視覺伴侶確認版面後批准） |
| 關聯文件 | [第三期進度](../../PROGRESS.md)、[第三期實作計畫](./2026-08-13-enter-saved-lesson-implementation.md)、[第三期設計規格](./2026-08-13-enter-saved-lesson-design.md) |
| 使用情境 | 用戶想直接進入已保存課程練習；現行首頁下方區塊需要捲動才能看到，體驗不佳 |

## 1. 需求背景

第三期已在首頁 hero 下方新增「繼續我的課程」區塊（`#saved-lessons`）。用戶回饋：把課程列表塞在首頁下方會被往下擠、需要捲動，不好用。改為在右上導覽列（My progress、New lesson 旁）新增「My lessons」連結，點擊後進入一個獨立的課程列表頁面；首頁不再顯示課程區塊。

## 2. 現況與問題（已核對證據）

- 現行 `#saved-lessons` 區塊位於 `#home-screen` 內 hero 之後，需捲動才能看到（用戶明確表達不喜歡）。
- 頂部導覽列（`.topnav`）目前只有「My progress」「New lesson」兩個按鈕。
- 後端已具備所需能力（第三期完成）：`GET /api/lessons`（課程摘要列表）、`POST /api/sessions` 支援 `lesson_id`（直接建立可練習 session）、`GET /api/lessons/{lesson_id}`（完整課程）。本次不改後端。
- 前端已有 `screen-flow.js` 的 screen 機制與 `savedLessonOwner` 請求所有權 / navigation epoch 防呆慣例，沿用。

## 3. 設計決策

### 3.1 導覽列

- `.topnav` 新增「My lessons」連結（`data-action="lessons"`），與 My progress、New lesson 同列、同視覺。
- 點擊後進入新的 lessons screen（見 3.2）。

### 3.2 新頁面 lessons screen

- 新增 `<section id="lessons-screen" data-screen="lessons">`。
- 版面：單欄大卡片（用戶於視覺伴侶選擇 Option C）。每張卡片顯示：
  - 課程標題
  - scope 摘要（沿用 `lessonScopeSummary`，例如「國中 7 · English · Lesson 1」）
  - 內容數（`content_item_count`）
  - 明顯的「Continue →」按鈕
- 整張卡片可點擊（點卡片或 Continue 皆進入該課程）。

### 3.3 進入流程

點選卡片後（沿用現有 `enterSavedLesson` 流程與防呆）：

1. `POST /api/sessions`，body 帶 `{ operation_id, lesson_id }`。
2. `GET /api/lessons/{lesson_id}` 取回完整課程（供 preview / overview 使用）。
3. `state.lesson` 設為完整課程，`connectWebSocket(sessionId)`，`renderLessonContext`、`renderActivityCards`，`showScreen("overview")`。
4. 失敗時在 lessons screen 顯示錯誤訊息，不切換畫面。

### 3.4 空狀態

- 沒有已保存課程時：顯示說明文字與「Start a new lesson」按鈕（沿用現有空狀態樣式）。
- 載入失敗時：顯示錯誤訊息（「I could not load your saved lessons.」），不顯示空狀態。

### 3.5 首頁與載入時機

- 移除 `#home-screen` 內的 `#saved-lessons` 區塊，首頁回到乾淨 hero。
- `init()` 不再呼叫 `loadSavedLessons()`；改為點擊「My lessons」進入 lessons screen 時載入列表。
- 返回首頁（`data-action="home"`）不觸發列表載入。

### 3.6 樣式

- 沿用現有單字卡視覺語言（白卡、圓角、藍色主色、`--shadow`）。
- 桌面：單欄堆疊、卡片 max-width 約 720px 置中；手機：全寬單欄。
- 卡片 hover 與 reduced-motion 行為沿用現有按鈕/卡片慣例。

## 4. 測試與驗證

1. `tests/api/test_static_ui.py` 更新來源契約：
   - `.topnav` 含「My lessons」與 `data-action="lessons"`。
   - 存在 `id="lessons-screen"` / `data-screen="lessons"`。
   - 首頁不再包含 `id="saved-lessons"` 區塊。
   - `app.js`：`loadSavedLessons` / `renderSavedLessons` / `enterSavedLesson` 順序契約（含 `/api/lessons`、`/api/sessions`、`/api/lessons/${lesson_id}`、`showScreen("overview")`）、空狀態、`data-action="lessons"` 的 wiring。
   - 既有首頁 hero、wizard、preview、overview 契約維持不變（若需調整 `_source_between` 切片需同步更新）。
2. `node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs`。
3. 全量 `uv run pytest -q`（現基準 289 passed、9 skipped、1 warning，不允許 regression）。
4. `git diff --check` 乾淨。
5. 瀏覽器手動驗證仍受限（in-app Browser sandbox），以 static 契約與 node 測試為準，並在 PROGRESS.md 記錄。

## 5. 不變更範圍

- 後端 API 完全不動。
- overview / activity / preview（單字卡）流程不動。
- screen-flow.js 的 screen controller 不動（僅新增一個 screen）。
