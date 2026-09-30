# TalkPath 直接進入已保存課程 實作計畫

- **Goal:** 讓用戶直接進入已保存的課程練習，不需重新上傳課本圖片。
- **Tech Stack:** Python 3.12、FastAPI、Pydantic v2、LessonLens Markdown、原生 HTML/CSS/JavaScript、pytest。
- **測試策略:** TDD；後端用 temporary LessonLens/fake provider；前端沿用 static UI source-shape contracts + node 測試。

## Task 1: 列出已保存課程 API

- Create: `SessionService.list_lessons()`（轉呼叫 `lesson_repository.list_lessons()`）。
- Create: `GET /api/lessons` route + `LessonSummary` response model（lesson_id、title、scope、source_images 數、content_items 數）。
- Create: `tests/api/test_lesson_list.py`；擴充 `tests/unit/test_session_service.py`。
- Expected: FAIL（尚未實作）→ PASS。
- Run: `uv run pytest tests/api/test_lesson_list.py tests/unit/test_session_service.py -q`

## Task 2: 以既有課程建立 session

- Update: `SessionService.create_session` 支援既有 lesson_id：從 LessonLens 讀回 scope、寫入 `_scopes`、建立為 `ASK_GENERATE_ACTIVITY`。
- Update: `CreateSessionRequest` 增加可選 `lesson_id`；`POST /api/sessions` 對應處理；課程不存在回 404。
- Update: SessionStateMachine 允許進入路徑（如 UPLOAD_IMAGE → ASK_GENERATE_ACTIVITY）。
- Create/Update: tests（session service + routes + state machine）。
- Run: `uv run pytest tests/unit/test_session_service.py tests/api/test_import_flow.py tests/api/test_activity_flow.py -q`

## Task 3: 前端課程列表與進入入口

- Update: `frontend/index.html` 首頁新增「繼續我的課程」入口與 lessons screen（或 home 內嵌列表）。
- Update: `frontend/app.js` 呼叫 `GET /api/lessons`、render 列表、點選後建立 session → overview；空狀態處理。
- Update: `frontend/styles.css` 列表卡片樣式（沿用單字卡視覺語言）。
- Update: `tests/api/test_static_ui.py` 新增來源契約；`node --check`、`node --test`。
- Run: `uv run pytest tests/api/test_static_ui.py -q`；`node --check frontend/app.js`；`node --test frontend/test/screen-flow.test.cjs`

## 驗證門檻

- 全量 `uv run pytest -q`（第二期結束基準：275 passed、9 skipped、1 warning）
- `uv run python -m compileall -q src tests`
- `node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs`
- `git diff --check`
- 若 in-app Browser 可用，補桌面/手機流程手動驗證；否則以 static 契約為準並在 PROGRESS.md 記錄限制。
