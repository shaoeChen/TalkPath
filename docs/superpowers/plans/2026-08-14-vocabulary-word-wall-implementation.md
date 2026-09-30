# 詞彙練習：單字卡牆＋自選練習 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 Vocabulary practice 從「生成後逐題練習」變成「單字卡牆＋自選練習」：卡牆顯示該課全部單字（搜尋＋狀態＋喇叭），點卡進入該字練習（聽＋說＋STT 比對），Practice all 沿用整批隨機練習。

**Architecture:** 前端新增 words screen（`frontend/index.html`＋`app.js`＋`styles.css`），字卡資料讀 `state.lesson.content_items`（vocabulary），點卡進入 practice 頁的單字模式；單字作答走新後端端點 `POST /api/sessions/{id}/vocabulary/{content_id}/answer`（本機文字比對＋`record_attempt` 記錄，operation_id 冪等）。Practice all 沿用既有 `generateActivity(vocabulary_practice)`。

**Tech Stack:** Vanilla JS、FastAPI、pytest（含 static UI 來源契約）、uv、node。

---

## File Structure

- Modify: `frontend/index.html` — 新增 `#words-screen`（搜尋框、字卡格、Practice all）。
- Modify: `frontend/app.js` — activityDefinitions 的 vocabulary_practice 卡片改進入 words screen；字卡渲染／搜尋／喇叭／狀態標籤；單字模式練習（Listen＋Record＋自動送新端點）；`state.wordStatus` 與重置；Practice all 呼叫 generateActivity。
- Modify: `frontend/styles.css` — `.word-card` 牆樣式（沿用練習頁視覺語言）。
- Modify: `src/talkpath/api/routes.py` — 新端點 + Request/Response models。
- Modify: `src/talkpath/application/session_service.py` — `answer_vocabulary_word`（驗證 lesson/content、本機比對、記錄 attempt）。
- Modify: `tests/unit/...`、`tests/api/test_activity_flow.py`、`tests/api/test_static_ui.py` — TDD 新增。
- Add: `docs/superpowers/specs/2026-08-14-vocabulary-word-wall-design.md`（已建立）。
- Modify: `docs/PROGRESS.md` — 記錄設計與實作結果（AGENTS.md 要求）。

不改：其他七種活動、vocabulary_quiz、SQLite schema、LessonLens 格式、internal tools、`screen-flow.js`。

## 前置確認（執行者請先做）

- 讀 `docs/PROGRESS.md` 與 `docs/superpowers/specs/2026-08-14-vocabulary-word-wall-design.md`。
- 工作目錄必須是 `D:\python\TalkPath`。
- 基準測試數量：`uv run pytest -q` → 308 passed、9 skipped、1 warning。

### Task 1: 後端單字作答 API（TDD）

**Files:** `src/talkpath/application/session_service.py`、`src/talkpath/api/routes.py`、`tests/unit/test_session_service.py`、`tests/api/test_activity_flow.py`

- [ ] **Step 1: 寫失敗測試**
  - unit：`answer_vocabulary_word` 對（`passed=True`、attempt 寫入）／錯（`passed=False`、review item）、`operation_id` 冪等重送回同一結果、content 不存在與非 vocabulary 內容拒絕、activity_id 為 `{lesson_id}-word-{content_id}`。
  - API：POST 新端點 200、公開回應不含答案。
- [ ] **Step 2: 實作**
  - `SessionService.answer_vocabulary_word(session_id, content_id, answer, operation_id)`：取 lesson → 找 vocabulary content item → 取單字（english/word）→ `strip().casefold()` 比對 → `record_attempt(activity_id="{lesson_id}-word-{content_id}", ...)` → 回傳結果。
  - `routes.py`：`POST /api/sessions/{session_id}/vocabulary/{content_id}/answer`。
- [ ] **Step 3: 綠燈驗證**（相關 unit＋API 測試通過）

### Task 2: 前端單字卡牆 screen（TDD）

**Files:** `frontend/index.html`、`frontend/app.js`、`frontend/styles.css`、`tests/api/test_static_ui.py`

- [ ] **Step 1: 寫失敗測試（來源契約）**
  - HTML 含 `#words-screen`（搜尋框、`#word-grid`、Practice all）。
  - app.js：`vocabulary_practice` 卡片 action 改開 words screen；字卡由 `content_items` vocabulary 渲染（english/word 與 chinese/meaning 相容）；搜尋過濾；點喇叭呼叫 `/speech/synthesize`；`wordStatus` 標籤；`resetForNewCourse` 重置。
  - CSS 含字卡牆樣式 marker。
- [ ] **Step 2: 實作**
  - index.html 新增 words screen；app.js 新增 renderWordWall、過濾、喇叭播放（複用 `playPracticeWord`）、Practice all（`generateActivity`）；state 新增 `wordStatus`。
- [ ] **Step 3: 綠燈驗證**

### Task 3: 單字模式練習串接（TDD）

**Files:** `frontend/app.js`、`tests/api/test_static_ui.py`

- [ ] **Step 1: 寫失敗測試**
  - 點字卡進入 practice 頁單字模式：Listen＋Record；Record 後自動 POST `/api/sessions/{id}/vocabulary/{content_id}/answer`；答對標記 done、答錯標記 again；回卡牆。
- [ ] **Step 2: 實作**
  - 單字模式不生成活動：直接以字卡資料驅動 practice 頁（word、content_id），Record 轉錄後送新端點，依 `passed` 更新 `wordStatus` 與按鈕（Back to words）。
- [ ] **Step 3: 綠燈驗證**

### Task 4: 全量驗證與收尾

- [ ] 全量 `uv run pytest -q`（基準 308 passed、9 skipped、1 warning）；`compileall`；`node --check`；`node --test`；`git diff --check`。
- [ ] 更新 `docs/PROGRESS.md` 並 commit（spec＋plan＋程式＋測試）。
- [ ] 記錄已知限制（瀏覽器手動驗證、狀態僅 session 內、字卡來源欄位相容性）。
