# TalkPath 已保存課程入口改版（導覽列 + 獨立頁面）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「已保存課程」入口從首頁底部移到右上導覽列「My lessons」連結，並提供獨立的單欄大卡片課程列表頁。

**Architecture:** 純前端改動，後端 API 不動。沿用現有 `screen-flow.js` 的 screen 機制與 `data-action` 事件綁定：新增 `data-screen="lessons"` 頁面、`data-action="lessons"` 導覽連結，並把現有 `loadSavedLessons` / `renderSavedLessons` / `enterSavedLesson` 邏輯改接到新頁面。首頁移除課程區塊，進入 lessons 頁時才載入列表。

**Tech Stack:** 原生 HTML/CSS/JavaScript、FastAPI static 掛載、pytest（static UI 來源契約）、node --check / node --test。

**工作目錄：** `D:\python\TalkPath`（正式專案位置，分支 `codex/phase2-provider-speech`）。所有 shell 指令 workdir 皆為該目錄。

**測試策略：** 沿用專案慣例——前端行為以 `tests/api/test_static_ui.py` 的來源契約測試驗證（讀取 index.html / app.js / styles.css 的文字結構），搭配 `node --check` 與 `node --test`。每個 Task 先更新/新增契約測試（RED），再改前端檔案（GREEN）。

---

## 現況摘要（已核對）

- `frontend/index.html`：`#saved-lessons` 區塊位於 `#home-screen` 內 hero 之後；`.topnav` 目前只有 My progress、New lesson。
- `frontend/app.js`：`loadSavedLessons()` 在 home 按鈕 handler 與 `init()` 被呼叫；`renderSavedLessons` 產生的卡片是網格小卡；`enterSavedLesson` 已會 `GET /api/lessons/{lesson_id}` 取完整課程。
- `frontend/styles.css`：`.saved-lessons`、`.saved-lesson-card` 等樣式是為「首頁底部區塊」設計。
- `tests/api/test_static_ui.py`：`test_child_ui_home_lists_saved_lessons_and_opens_them_for_practice` 是目前唯一引用 saved-lessons 的契約測試（將被取代）。

## 命名對照（本計畫統一使用）

| 現行（待移除/改名） | 新版 |
| --- | --- |
| `<section id="saved-lessons">`（home 內） | `<section id="lessons-screen" class="screen content-screen" data-screen="lessons" hidden>` |
| `id="saved-lessons-title"` | `id="lessons-title"` |
| `id="saved-lesson-list"` | `id="lessons-list"`（class `lessons-list`） |
| `id="saved-lessons-empty"` | `id="lessons-empty"`（class `lessons-empty`） |
| `id="saved-lessons-error"` | `id="lessons-error"` |
| `.saved-lesson-card` / `-title` / `-scope` / `-count` | `.lesson-card` / `-title` / `-scope` / `-count`（新增 `.lesson-card-continue`） |

函數名稱 `loadSavedLessons` / `renderSavedLessons` / `enterSavedLesson` 與 `savedLessonOwner` 保留不變（行為仍為「載入/進入已保存課程」）。

---

### Task 1: HTML — 新增 My lessons 導覽連結與 lessons screen，移除首頁課程區塊

**Files:**
- Modify: `frontend/index.html`
- Test: `tests/api/test_static_ui.py`

- [ ] **Step 1: 以新契約測試取代舊測試（RED）**

把 `tests/api/test_static_ui.py` 最後一個測試 `test_child_ui_home_lists_saved_lessons_and_opens_them_for_practice` 整段替換為：

```python
def test_child_ui_adds_my_lessons_nav_link_and_lessons_screen() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    home = _source_between(
        html,
        '<section id="home-screen"',
        '<section id="lessons-screen"',
    )
    lessons_screen = _source_between(
        html,
        '<section id="lessons-screen"',
        '<section id="new-course-screen"',
    )

    assert (
        '<button class="nav-link" type="button" data-action="lessons">My lessons</button>'
        in html
    )
    assert (
        '<section id="lessons-screen" class="screen content-screen" '
        'data-screen="lessons" hidden>'
        in html
    )
    assert '<h2 id="lessons-title" data-screen-heading tabindex="-1">My lessons</h2>' in lessons_screen
    for marker in (
        'id="lessons-list"',
        'id="lessons-empty"',
        'id="lessons-error"',
        "Start a new lesson",
        'data-action="new-course"',
    ):
        assert marker in lessons_screen
    assert "saved" not in home
    assert 'id="saved-lessons"' not in html
    assert "saved-lesson" not in html
```

注意 `home` 切片上界改為 `<section id="lessons-screen"`，代表 lessons screen 必須插在 home 之後、new-course 之前；`assert "saved" not in home` 與 `"saved-lesson" not in html` 確保舊區塊完全移除。

- [ ] **Step 2: 執行測試確認失敗（RED）**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_adds_my_lessons_nav_link_and_lessons_screen -q`

Expected: FAIL（找不到 `data-action="lessons"`、`id="lessons-screen"`，且 html 仍含 `saved-lesson`）。

- [ ] **Step 3: 修改 `frontend/index.html`（GREEN）**

3a. 頂部導覽列加入「My lessons」連結（放在 New lesson 之後）：

```html
        <nav class="topnav" aria-label="Main navigation">
          <button class="nav-link" type="button" data-action="progress">My progress</button>
          <button class="nav-link" type="button" data-action="new-course">New lesson</button>
          <button class="nav-link" type="button" data-action="lessons">My lessons</button>
        </nav>
```

3b. 把 `#home-screen` 內的整個 `<section id="saved-lessons" ...>...</section>` 區塊刪除，改為在 `</section>`（home-screen 結尾）之後、`<section id="new-course-screen"` 之前插入：

```html
        <section id="lessons-screen" class="screen content-screen" data-screen="lessons" hidden>
          <div class="section-heading">
            <p class="eyebrow">Pick up where you left off</p>
            <h2 id="lessons-title" data-screen-heading tabindex="-1">My lessons</h2>
            <p>Open a saved lesson and keep practising without uploading its page again.</p>
          </div>
          <div id="lessons-list" class="lessons-list" aria-live="polite"></div>
          <p id="lessons-empty" class="lessons-empty" hidden>
            No saved lessons yet.
            <button class="secondary-button" type="button" data-action="new-course">Start a new lesson</button>
          </p>
          <p id="lessons-error" class="error-message" role="alert" aria-live="polite"></p>
        </section>
```

- [ ] **Step 4: 執行測試確認通過（GREEN）**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_adds_my_lessons_nav_link_and_lessons_screen -q`

Expected: PASS。

- [ ] **Step 5: 跑整份 static UI 契約，確認其他測試未被 HTML 移動破壞**

Run: `uv run pytest tests/api/test_static_ui.py -q`

Expected: 目前是 21 個測試；替換 1 個為 1 個，數量不變，全部 PASS。若 `test_child_ui_uses_focused_wizard_then_preview_and_practice_hub` 等切片測試失敗，表示 HTML 區塊順序與預期不同，回到 Step 3 修正位置。

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html tests/api/test_static_ui.py
git commit -m "feat: add My lessons nav link and lessons screen"
```

---

### Task 2: app.js — 接上導覽動作、改卡片為單欄 Continue 卡、只在 lessons 頁載入

**Files:**
- Modify: `frontend/app.js`
- Test: `tests/api/test_static_ui.py`

- [ ] **Step 1: 新增 app.js 契約測試（RED）**

在 `tests/api/test_static_ui.py` 的 Task 1 新測試之後新增：

```python
def test_child_ui_lessons_page_renders_cards_and_opens_lesson_for_practice() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    wire_actions = _source_between(
        script,
        "  function wireActions() {",
        "  function init()",
    )
    lessons_action = _source_between(
        wire_actions,
        "    $$('[data-action=\"lessons\"]')",
        "    $$('[data-action=\"upload-step\"]')",
    )
    saved = _source_between(
        script,
        "  async function loadSavedLessons() {",
        "  function wireActions()",
    )
    init_section = _source_between(
        script,
        "  function init() {",
        '  document.addEventListener("DOMContentLoaded", init);',
    )
    home_action = _source_between(
        wire_actions,
        "    $$('[data-action=\"home\"]')",
        "    $$('[data-action=\"new-course\"]')",
    )

    assert '$$(\'[data-action="lessons"]\').forEach' in wire_actions
    _assert_source_order(
        lessons_action,
        "invalidateNavigation()",
        'showScreen("lessons")',
        "loadSavedLessons()",
    )
    assert 'showScreen("lessons")' in script

    assert '"/api/lessons"' in saved
    assert "function renderSavedLessons(lessons)" in saved
    assert "lesson-card" in saved
    assert "lesson-card-continue" in saved
    assert "Continue" in saved
    assert "lessonScopeSummary(lesson.scope || {})" in saved
    assert "lesson.content_item_count" in saved
    assert "enterSavedLesson(lesson)" in saved
    _assert_source_order(
        saved,
        "async function loadSavedLessons()",
        '"/api/lessons"',
        "renderSavedLessons(lessons)",
        "function renderSavedLessons(lessons)",
        "enterSavedLesson(lesson)",
        "async function enterSavedLesson(summary)",
        '"/api/sessions"',
        "lesson_id: summary.lesson_id",
        "updateFromSession(session)",
        "`/api/lessons/${summary.lesson_id}`",
        "state.lesson = lesson",
        "renderLessonContext(state.lesson)",
        "renderActivityCards()",
        'showScreen("overview")',
    )
    assert "state.savedLessonOwner" in saved
    assert "connectWebSocket(sessionId)" in saved
    assert "loadSavedLessons()" not in home_action
    assert "loadSavedLessons()" not in init_section
    assert 'showError("#lessons-error"' in saved
```

- [ ] **Step 2: 執行測試確認失敗（RED）**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_lessons_page_renders_cards_and_opens_lesson_for_practice -q`

Expected: FAIL（`data-action="lessons"` wiring、`lesson-card`、`#lessons-error` 尚未存在，且 home/init 仍含 `loadSavedLessons()`）。

- [ ] **Step 3: 修改 `frontend/app.js`（GREEN）**

3a. `loadSavedLessons()`：把三個 selector 改名：

```js
  async function loadSavedLessons() {
    const list = $("#lessons-list");
    if (!list) return;
    showError("#lessons-error", "");
    try {
      const lessons = await api("/api/lessons");
      renderSavedLessons(lessons);
    } catch (_error) {
      list.replaceChildren();
      const empty = $("#lessons-empty");
      if (empty) empty.hidden = true;
      showError("#lessons-error", "I could not load your saved lessons.");
    }
  }
```

3b. `renderSavedLessons()`：卡片改為單欄大卡片 + Continue 按鈕樣式 span：

```js
  function renderSavedLessons(lessons) {
    const list = $("#lessons-list");
    if (!list) return;
    const empty = $("#lessons-empty");
    const saved = Array.isArray(lessons) ? lessons : [];
    list.replaceChildren();
    if (!saved.length) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    saved.forEach((lesson) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "lesson-card";
      const title = document.createElement("strong");
      title.className = "lesson-card-title";
      title.textContent = lesson.title || "Saved lesson";
      const scope = document.createElement("span");
      scope.className = "lesson-card-scope";
      scope.textContent = lessonScopeSummary(lesson.scope || {});
      const count = document.createElement("span");
      count.className = "lesson-card-count";
      const contentCount = Number(lesson.content_item_count) || 0;
      count.textContent = `${contentCount} content item${contentCount === 1 ? "" : "s"}`;
      const continueLabel = document.createElement("span");
      continueLabel.className = "lesson-card-continue";
      continueLabel.textContent = "Continue →";
      card.append(title, scope, count, continueLabel);
      card.addEventListener("click", () => enterSavedLesson(lesson));
      list.append(card);
    });
  }
```

3c. `enterSavedLesson()`：把 `showError("#saved-lessons-error", ...)` 兩處改為 `showError("#lessons-error", ...)`（函數其餘內容不變）。

3d. `wireActions()`：在 `[data-action="new-course"]` handler 之後新增：

```js
    $$('[data-action="lessons"]').forEach((button) => button.addEventListener("click", () => {
      invalidateNavigation();
      showScreen("lessons");
      loadSavedLessons();
    }));
```

3e. `wireActions()` 的 home handler 移除 `loadSavedLessons();`：

```js
    $$('[data-action="home"]').forEach((button) => button.addEventListener("click", () => {
      resetForNewCourse();
      showScreen("home");
    }));
```

3f. `init()` 移除最後的 `loadSavedLessons();`：

```js
    renderActivityCards();
    wireActions();
  }
```

- [ ] **Step 4: 執行測試確認通過（GREEN）**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_lessons_page_renders_cards_and_opens_lesson_for_practice -q`

Expected: PASS。

- [ ] **Step 5: 跑整份 static UI 契約 + node 檢查**

Run: `uv run pytest tests/api/test_static_ui.py -q` 與 `node --check frontend/app.js`

Expected: 全部 PASS；`node --check` 無輸出、exit 0。若既有切片測試失敗，檢查 lessons handler 是否插在 `[data-action="new-course"]` 之後、`[data-action="upload-step"]` 之前。

- [ ] **Step 6: Commit**

```bash
git add frontend/app.js tests/api/test_static_ui.py
git commit -m "feat: render saved lessons as continue cards and wire lessons navigation"
```

---

### Task 3: styles.css — lesson 卡片樣式

**Files:**
- Modify: `frontend/styles.css`
- Test: `tests/api/test_static_ui.py`

- [ ] **Step 1: 新增樣式契約測試（RED）**

在 Task 2 測試之後新增：

```python
def test_child_ui_lessons_page_uses_stacked_cards_with_continue_button() -> None:
    client = TestClient(create_app(testing=True))

    stylesheet = client.get("/styles.css").text
    for contract in (
        ".lessons-list {",
        ".lesson-card {",
        ".lesson-card:hover {",
        ".lesson-card-title {",
        ".lesson-card-scope {",
        ".lesson-card-count {",
        ".lesson-card-continue {",
        ".lessons-empty {",
    ):
        assert contract in stylesheet
    assert ".saved-lessons" not in stylesheet
    assert ".saved-lesson" not in stylesheet
```

- [ ] **Step 2: 執行測試確認失敗（RED）**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_lessons_page_uses_stacked_cards_with_continue_button -q`

Expected: FAIL（`.lessons-list` 等尚不存在，且 `.saved-lessons` 仍在）。

- [ ] **Step 3: 修改 `frontend/styles.css`（GREEN）**

3a. 把現有 `.saved-lessons ...` 到 `.saved-lessons-empty ...` 的整段規則替換為：

```css
.lessons-list { display: grid; gap: 14px; max-width: 720px; margin: 0 auto; }
.lesson-card { display: grid; gap: 8px; width: 100%; min-height: 140px; align-content: start; padding: 20px; text-align: left; color: var(--ink); background: #fff; border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 8px 18px rgba(46, 73, 110, 0.06); }
.lesson-card:hover { border-color: var(--blue); background: #f4f7ff; transform: translateY(-1px); }
.lesson-card-title { color: var(--blue-dark); font-size: 1.15rem; }.lesson-card-scope { color: var(--muted); font-size: 0.9rem; }.lesson-card-count { color: var(--muted); font-size: 0.82rem; }
.lesson-card-continue { justify-self: start; margin-top: 8px; padding: 9px 18px; color: #fff; background: var(--blue); border-radius: 999px; font-weight: 800; font-size: 0.9rem; }
.lessons-empty { max-width: 720px; margin: 0 auto; color: var(--muted); text-align: center; }.lessons-empty .secondary-button { margin-left: 8px; }
```

3b. 在 `@media (max-width: 600px)` 區塊內，把 `.saved-lesson-list { grid-template-columns: 1fr; }` 替換為：

```css
.lessons-list { gap: 10px; }
```

不要更動 `@media (prefers-reduced-motion: reduce)` 區塊（`tests/api/test_static_ui.py` 對它有逐字元比對）。

- [ ] **Step 4: 執行測試確認通過（GREEN）**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_lessons_page_uses_stacked_cards_with_continue_button -q`

Expected: PASS。

- [ ] **Step 5: 跑整份 static UI 契約**

Run: `uv run pytest tests/api/test_static_ui.py -q`

Expected: 全部 PASS（含 `test_child_ui_styles_focused_lesson_flow_and_preview_layout` 的 reduced-motion 逐字元比對）。

- [ ] **Step 6: Commit**

```bash
git add frontend/styles.css tests/api/test_static_ui.py
git commit -m "style: add stacked lesson card styles for lessons page"
```

---

### Task 4: 全量驗證、更新 PROGRESS.md、收尾 commit

**Files:**
- Modify: `docs/PROGRESS.md`

- [ ] **Step 1: 全量驗證**

Run:

```bash
uv run pytest -q
uv run python -m compileall -q src tests
node --check frontend/app.js frontend/screen-flow.js
node --test frontend/test/screen-flow.test.cjs
git diff --check
```

Expected: `291 passed、9 skipped、1 warning`（289 − 1 個被取代的舊契約測試 + 3 個新契約測試 = 291；若數目不同，以實際輸出為準並記錄於 PROGRESS.md）、compileall 通過、`node --check` 無輸出、`node --test` 3 passed、`git diff --check` 無輸出。

- [ ] **Step 2: 更新 `docs/PROGRESS.md`**

在「第三期後續：已保存課程入口改版（設計階段）」段落之後新增「（實作完成）」紀錄，內容包含：

```markdown
### 2026-08-13 已保存課程入口改版（實作完成）

- 實作：右上導覽列新增「My lessons」連結（`data-action="lessons"`）；新增 `#lessons-screen`（`data-screen="lessons"`）獨立頁面；單欄大卡片（`.lesson-card` + Continue 按鈕）；進入 lessons 頁時才呼叫 `GET /api/lessons`；點卡片 → 建立 session → 讀完整課程 → overview；空狀態含「Start a new lesson」；首頁移除 `#saved-lessons` 區塊。
- 驗證：`uv run pytest -q` → 291 passed、9 skipped、1 warning；`node --check`、`node --test` 3 passed；`git diff --check` 乾淨。
- 已知限制：瀏覽器手動驗證仍受限（in-app Browser sandbox），以 static UI 契約與 node 測試為準。
```

同時把「下一個開發起點」段落更新為：入口改版已完成並 commit（見 git log）；若需手動驗證，啟動 `uv run uvicorn talkpath.main:app` 點右上「My lessons」。

- [ ] **Step 3: Commit**

```bash
git add docs/PROGRESS.md
git commit -m "docs: record saved-lessons nav entry implementation"
```

- [ ] **Step 4: 回報完成**

回報內容：commit SHAs、全量驗證輸出摘要、剩餘限制（瀏覽器手動驗證未執行）。

---

## 驗證門檻（總結）

- 全量 `uv run pytest -q`：基準 289 passed、9 skipped、1 warning，不允許 regression。
- `uv run python -m compileall -q src tests`
- `node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs`（3 passed）
- `git diff --check` 乾淨
- 若 in-app Browser 可用，補「首頁 → My lessons → 點卡片 → overview」手動流程；否則以 static 契約為準並在 PROGRESS.md 記錄限制。
