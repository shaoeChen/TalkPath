# TalkPath 練習頁改版（獨立頁面 + 一次一題）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把活動練習從 overview 同頁面板改成獨立 practice 頁，一次只顯示一題，並提供點狀進度、答對/答錯溫和回饋、Try again / Next（跳過）與最後一題 Finish 進 results，完全不改後端。

**Architecture:** 前端單頁應用（原生 HTML/CSS/JS + screen controller）。新增 `#practice-screen` 取代 overview 內的 `#activity-panel`；`state` 增加 `currentQuestionIndex` 等練習狀態；`renderActivity` 改為渲染單題並搭配 `renderPracticeProgress` / `renderPracticeQuestion` / `renderPracticeResultActions` 等輔助函式；作答後不直接進 results，而是依 passed 渲染 Next / Try again + Skip / Finish 按鈕，只有 Finish 才呼叫既有 `showAnswerResult`。

**Tech Stack:** 原生 HTML/CSS/JavaScript、FastAPI TestClient（static UI 來源契約）、Node 內建測試（screen-flow controller）、pytest、uv。

---

## 檔案結構

| 檔案 | 職責 |
| --- | --- |
| `frontend/index.html` | 新增 `#practice-screen`（單卡、點狀進度、Question label、Back to practice list）；overview 移除 `#activity-panel` / `#activity-error` / `#close-activity` |
| `frontend/styles.css` | practice 單卡、點狀進度、操作按鈕樣式；移除無用的 `.activity-panel` / `.activity-panel-header` / `.icon-button` / `.question-card` 樣式 |
| `frontend/app.js` | 練習狀態欄位、`generateActivity` 進 practice 頁、單題渲染、作答流程（Check / Next / Try again / Finish）、audio fallback 改指向 practice 元素、移除 close-activity 監聽、`resetForNewCourse` 清練習狀態 |
| `tests/api/test_static_ui.py` | 更新既有契約 + 新增 practice 流程契約 |
| `docs/PROGRESS.md` | 每個 Task 完成後立即記錄 |

## 名詞與字串約定（所有 Task 共用）

- 英文 UI 的「第 X 題」實作為 `Question ${current + 1}`（刻意不顯示總數，避免考卷框架）。
- 回饋 class 用 `is-passed` / `is-try-again`，**不得**出現 `is-correct`（避免破壞既有「不洩漏正確答案」契約測試中的 `"correct" not in script`）。
- 按鈕文字固定為：`Check my answer`、`Next question`、`Try again`、`Finish`。
- 頂部返回按鈕：`← Back to practice list`，沿用 `data-action="overview"`（overview 即練習清單）。
- 所有新 DOM 一律用 `createElement` + `textContent`，不得使用 `innerHTML`。

---

## Task 1：HTML — 新增獨立 practice 頁，overview 移除活動面板

**Files:**
- Modify: `frontend/index.html`（overview 區塊結尾與 results 之間）
- Test: `tests/api/test_static_ui.py`
- Docs: `docs/PROGRESS.md`

- [ ] **Step 1：寫失敗測試（更新 4 個既有契約 + 改名 1 個）**

在 `tests/api/test_static_ui.py` 中，把 `test_child_ui_homepage_serves_core_flow_sections` 的 marker tuple 改為加入 `'id="practice-screen"'`，並把 `assert html.count("data-screen-heading") >= 8` 改為 `>= 9`：

```python
    for marker in (
        'id="home-screen"',
        'id="new-course-screen"',
        'id="scope-screen"',
        'id="processing-screen"',
        'id="preview-screen"',
        'id="overview-screen"',
        'id="practice-screen"',
        'id="results-screen"',
        'id="progress-screen"',
    ):
        assert marker in html
    assert html.count("data-screen-heading") >= 9
```

把 `test_child_ui_uses_focused_wizard_then_preview_and_practice_hub` 中這一行：

```python
    practice = _source_between(html, '<section id="overview-screen"', '<section id="results-screen"')
```

改為：

```python
    overview = _source_between(html, '<section id="overview-screen"', '<section id="practice-screen"')
    practice = _source_between(html, '<section id="practice-screen"', '<section id="results-screen"')
```

並把該測試中這一段：

```python
    for marker in ("Pick a practice", 'data-action="preview"'):
        assert marker in practice
    assert '<h2 id="overview-title" data-screen-heading tabindex="-1">Pick a practice</h2>' in practice
    overview_actions = _source_between(practice, '<div class="overview-actions">', "</div>")
```

改為（overview 改從新 slice 取名，practice 改驗證新頁面）：

```python
    for marker in ("Pick a practice", 'data-action="preview"'):
        assert marker in overview
    assert '<h2 id="overview-title" data-screen-heading tabindex="-1">Pick a practice</h2>' in overview
    overview_actions = _source_between(overview, '<div class="overview-actions">', "</div>")

    for marker in ("One question at a time", "← Back to practice list", 'data-action="overview"'):
        assert marker in practice
    assert '<h2 id="practice-title" data-screen-heading tabindex="-1">Let\'s practise</h2>' in practice
    for marker in ('id="practice-dots"', 'id="practice-question-label"', 'id="practice-card"'):
        assert marker in practice
```

把整個 `test_child_ui_uses_one_activity_panel_for_the_complete_activity_path` 替換為：

```python
def test_child_ui_practice_is_a_separate_screen_without_inline_activity_panel() -> None:
    client = TestClient(create_app(testing=True))

    html = client.get("/").text
    script = client.get("/app.js").text

    assert html.count('id="activity-panel"') == 0
    assert 'id="activity-error"' not in html
    assert html.count('id="practice-card"') == 1
    for label in (
        "Vocabulary practice",
        "Vocabulary quiz",
        "Grammar explanation & practice",
        "Grammar quiz",
        "Listening practice",
        "Listening quiz",
        "Reading / read aloud",
        "Speaking practice",
    ):
        assert label in script
```

把 `test_child_ui_renders_safe_read_only_lesson_context_in_preview_and_practice` 中這一行：

```python
    overview = _source_between(html, '<section id="overview-screen"', '<section id="results-screen"')
```

改為：

```python
    overview = _source_between(html, '<section id="overview-screen"', '<section id="practice-screen"')
```

- [ ] **Step 2：確認紅燈**

Run: `uv run pytest tests/api/test_static_ui.py -q`
Expected: FAIL — `id="practice-screen"` 不存在、`html.count('id="activity-panel"') == 0` 失敗。

- [ ] **Step 3：實作 `frontend/index.html`**

把 overview 結尾的這段（`#activity-list` 之後到 `</section>`）：

```html
          <div id="activity-list" class="activity-grid" aria-live="polite"></div>
          <section id="activity-panel" class="card activity-panel" aria-labelledby="activity-panel-title" hidden>
            <div class="activity-panel-header">
              <div>
                <p class="eyebrow">One activity at a time</p>
                <h3 id="activity-panel-title">Let's practise</h3>
              </div>
              <button id="close-activity" class="icon-button" type="button" aria-label="Close activity">×</button>
            </div>
            <div id="activity-panel-body"></div>
          </section>
          <p id="activity-error" class="error-message" role="alert" aria-live="polite"></p>
        </section>
```

替換為（overview 只留活動卡片，並在 results 之前新增 practice screen）：

```html
          <div id="activity-list" class="activity-grid" aria-live="polite"></div>
        </section>

        <section id="practice-screen" class="screen content-screen" data-screen="practice" hidden>
          <div class="section-heading practice-heading">
            <div>
              <p class="eyebrow">One question at a time</p>
              <h2 id="practice-title" data-screen-heading tabindex="-1">Let's practise</h2>
              <p class="practice-progress" aria-live="polite">
                <span id="practice-dots" class="practice-dots" aria-hidden="true"></span>
                <span id="practice-question-label">Question 1</span>
              </p>
            </div>
            <button class="text-button" type="button" data-action="overview">← Back to practice list</button>
          </div>
          <article id="practice-card" class="card practice-card">
            <div id="practice-body"></div>
          </article>
          <p id="practice-error" class="error-message" role="alert" aria-live="polite"></p>
        </section>
```

- [ ] **Step 4：確認綠燈**

Run: `uv run pytest tests/api/test_static_ui.py -q`
Expected: PASS — 21 passed。

- [ ] **Step 5：更新 `docs/PROGRESS.md`**

在「第三期後續 2」區塊之後追加：

```markdown
### 2026-08-13 Task 1：新增獨立 practice 頁、overview 移除活動面板（完成）

- 實作：`frontend/index.html` 新增 `<section id="practice-screen" data-screen="practice">`（單卡、點狀進度 +「Question X」、Back to practice list）；overview 移除 `#activity-panel` / `#activity-error` / `#close-activity`。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 21 passed（含新增/更新的 HTML 契約）。
- 已知問題：無。
- 下一步：Task 2（practice 樣式）。
```

- [ ] **Step 6：Commit**

```bash
git add frontend/index.html tests/api/test_static_ui.py docs/PROGRESS.md
git commit -m "feat: add separate practice screen and remove inline activity panel"
```

---

## Task 2：CSS — practice 單卡、點狀進度與操作按鈕樣式

**Files:**
- Modify: `frontend/styles.css`
- Test: `tests/api/test_static_ui.py`
- Docs: `docs/PROGRESS.md`

- [ ] **Step 1：寫失敗測試**

在 `tests/api/test_static_ui.py` 新增（放在 `test_child_ui_lessons_page_uses_stacked_cards_with_continue_button` 之後）：

```python
def test_child_ui_practice_styles_use_single_card_and_dot_progress() -> None:
    client = TestClient(create_app(testing=True))

    stylesheet = client.get("/styles.css").text

    for contract in (
        ".practice-heading {",
        ".practice-progress {",
        ".practice-dots {",
        ".practice-dot {",
        ".practice-dot.is-done {",
        ".practice-dot.is-current {",
        ".practice-card { max-width: 720px;",
        ".practice-question {",
        ".practice-actions {",
        ".answer-feedback.is-passed {",
        ".answer-feedback.is-try-again {",
    ):
        assert contract in stylesheet
    assert ".activity-panel" not in stylesheet
    assert ".icon-button" not in stylesheet
```

- [ ] **Step 2：確認紅燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_practice_styles_use_single_card_and_dot_progress -q`
Expected: FAIL — `.practice-card {` 不存在。

- [ ] **Step 3：實作 `frontend/styles.css`**

把這一行（`.activity-panel` 開頭的單行規則）：

```css
.activity-panel { margin-top: 24px; padding: clamp(22px, 4vw, 34px); }.activity-panel-header { display: flex; justify-content: space-between; gap: 20px; }.icon-button { width: 36px; height: 36px; color: var(--muted); background: #f5f7fa; border: 0; border-radius: 10px; font-size: 1.5rem; line-height: 1; }.activity-instructions { color: var(--muted); line-height: 1.6; }.question-card { margin-top: 16px; padding: 18px; background: #f8fbff; border: 1px solid #e2eaf5; border-radius: 14px; }.choice-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }.choice-button { padding: 11px; color: var(--ink); background: #fff; border: 1px solid var(--line); border-radius: 10px; text-align: left; }.choice-button:hover { border-color: var(--blue); background: #f4f7ff; }.choice-button.selected { color: var(--blue-dark); background: #edf2ff; border-color: var(--blue); box-shadow: 0 0 0 2px rgba(74, 119, 245, 0.16); }.answer-input { width: min(100%, 420px); margin-right: 8px; padding: 11px; border: 1px solid var(--line); border-radius: 10px; }.answer-feedback { min-height: 1.4em; margin: 12px 0 0; font-weight: 800; }.audio-fallback { padding: 22px; background: #fff7e8; border: 1px solid #f2d493; border-radius: 15px; }.audio-fallback p { color: #775c20; line-height: 1.55; }
```

替換為（移除 panel/icon-button/question-card，保留並擴充共用規則）：

```css
.activity-instructions { color: var(--muted); line-height: 1.6; }.choice-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }.choice-button { padding: 11px; color: var(--ink); background: #fff; border: 1px solid var(--line); border-radius: 10px; text-align: left; }.choice-button:hover { border-color: var(--blue); background: #f4f7ff; }.choice-button.selected { color: var(--blue-dark); background: #edf2ff; border-color: var(--blue); box-shadow: 0 0 0 2px rgba(74, 119, 245, 0.16); }.answer-input { width: min(100%, 420px); margin-right: 8px; padding: 11px; border: 1px solid var(--line); border-radius: 10px; }.answer-feedback { min-height: 1.4em; margin: 12px 0 0; font-weight: 800; }.answer-feedback.is-passed { color: var(--mint-dark); }.answer-feedback.is-try-again { color: #9a6b1f; }.audio-fallback { padding: 22px; background: #fff7e8; border: 1px solid #f2d493; border-radius: 15px; }.audio-fallback p { color: #775c20; line-height: 1.55; }
.practice-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; }
.practice-progress { display: flex; align-items: center; gap: 12px; margin: 14px 0 0; color: var(--muted); font-size: 0.95rem; font-weight: 800; }
.practice-dots { display: flex; gap: 8px; }
.practice-dot { width: 12px; height: 12px; border-radius: 50%; background: #d7deea; }
.practice-dot.is-done { background: var(--mint-dark); }
.practice-dot.is-current { background: var(--blue); box-shadow: 0 0 0 4px rgba(74, 119, 245, 0.16); }
.practice-card { max-width: 720px; margin: 0 auto; padding: clamp(22px, 4vw, 34px); }
.practice-question { padding: 18px; background: #f8fbff; border: 1px solid #e2eaf5; border-radius: 14px; }
.practice-prompt { font-size: 1.2rem; line-height: 1.5; }
.practice-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.practice-actions .primary-button, .practice-actions .secondary-button { flex: 1 1 auto; }
.practice-empty { color: var(--muted); }
.speech-feedback { min-height: 1.4em; margin: 10px 0 0; color: var(--muted); font-weight: 700; }
```

另外在 `@media (max-width: 600px)` 區塊內、`.lessons-list { gap: 10px; }` 之後加入：

```css
.practice-heading { align-items: flex-start; flex-direction: column; }
.practice-actions .primary-button, .practice-actions .secondary-button { width: 100%; }
```

注意：`@media (prefers-reduced-motion: reduce)` 區塊不可更動（既有測試對該區塊做整段比對）。

- [ ] **Step 4：確認綠燈**

Run: `uv run pytest tests/api/test_static_ui.py -q`
Expected: PASS — 22 passed。

- [ ] **Step 5：更新 `docs/PROGRESS.md`**

追加：

```markdown
### 2026-08-13 Task 2：practice 單卡、點狀進度與按鈕樣式（完成）

- 實作：`frontend/styles.css` 新增 `.practice-heading` / `.practice-progress` / `.practice-dots` / `.practice-card` / `.practice-question` / `.practice-actions` 與 `is-passed` / `is-try-again` 回饋色；移除 `.activity-panel` / `.activity-panel-header` / `.icon-button` / `.question-card` 無用樣式；600px 手機斷點加入單欄按鈕規則。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 22 passed。
- 已知問題：無。
- 下一步：Task 3（generateActivity 進入 practice 頁）。
```

- [ ] **Step 6：Commit**

```bash
git add frontend/styles.css tests/api/test_static_ui.py docs/PROGRESS.md
git commit -m "style: add practice card and dot progress styles"
```

---

## Task 3：JS — 練習狀態欄位 + generateActivity 進入 practice 頁

**Files:**
- Modify: `frontend/app.js`（state 物件、`generateActivity`）
- Test: `tests/api/test_static_ui.py`
- Docs: `docs/PROGRESS.md`

- [ ] **Step 1：寫失敗測試（新增 1 個 + 更新 3 個既有）**

新增：

```python
def test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    generate_activity = _source_between(
        script,
        "  async function generateActivity(",
        "  function resetForNewCourse()",
    )

    for marker in (
        "currentQuestionIndex: 0",
        "practiceAnswered: false",
        "practicePassed: false",
        "practiceResult: null",
        'practiceFeedback: ""',
    ):
        assert marker in script
    _assert_source_order(
        generate_activity,
        "state.currentActivityType = definition.type",
        "state.currentQuestionIndex = 0",
        'showError("#practice-error"',
        'showScreen("practice")',
        "Making your activity…",
    )
    assert 'showError("#activity-error"' not in generate_activity
    assert 'showScreen("overview")' not in generate_activity
```

更新 `test_child_ui_activity_generation_ignores_stale_async_continuations` 的 `generate_catch` 斷言，把 `'showError("#activity-error"'` 改為 `'showError("#practice-error"'`：

```python
    generate_catch = generate_activity[generate_activity.index("    } catch (error) {") :]
    _assert_source_order(
        generate_catch,
        'if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;',
        "isAudioProviderFallbackError(error)",
        'showError("#practice-error"',
    )
```

更新 `test_child_ui_audio_failure_has_retry_and_text_fallback`，把這一行：

```python
    assert 'showError("#activity-error"' in generate_activity
```

改為：

```python
    assert 'showError("#practice-error"' in generate_activity
```

更新 `test_child_ui_async_operations_require_navigation_and_latest_request_ownership`，把 `after_attempt_invalidation` 順序清單中的 `"showError(\"#activity-error\""` 改為 `"showError(\"#practice-error\""`：

```python
    _assert_source_order(
        after_attempt_invalidation,
        "const navigationEpoch = state.navigationEpoch",
        'const activityOwner = Symbol("activity")',
        "state.activityOwner = activityOwner",
        "state.currentActivityType = definition.type",
        "showError(\"#practice-error\"",
        "await api(`/api/sessions/${sessionId}/activities/generate`",
    )
```

- [ ] **Step 2：確認紅燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there tests/api/test_static_ui.py::test_child_ui_activity_generation_ignores_stale_async_continuations tests/api/test_static_ui.py::test_child_ui_audio_failure_has_retry_and_text_fallback tests/api/test_static_ui.py::test_child_ui_async_operations_require_navigation_and_latest_request_ownership -q`
Expected: FAIL — `currentQuestionIndex: 0` 不存在、`showScreen("practice")` 不存在。

- [ ] **Step 3：實作 `frontend/app.js`**

在 state 物件中，把：

```js
    currentActivityType: null,
```

改為：

```js
    currentActivityType: null,
    currentQuestionIndex: 0,
    practiceAnswered: false,
    practicePassed: false,
    practiceResult: null,
    practiceFeedback: "",
```

把整個 `generateActivity`（從 `  async function generateActivity(definition) {` 到 `  }`，目前位於 renderActivity 之後、resetForNewCourse 之前）替換為：

```js
  async function generateActivity(definition) {
    const generation = state.flowGeneration;
    const sessionId = state.sessionId;
    if (!sessionId || !state.lesson) {
      showError("#practice-error", "Start a lesson before choosing an activity.");
      return;
    }
    invalidatePracticeAttempt();
    const navigationEpoch = state.navigationEpoch;
    const activityOwner = Symbol("activity");
    state.activityOwner = activityOwner;
    state.currentActivityType = definition.type;
    state.currentQuestionIndex = 0;
    state.practiceAnswered = false;
    state.practicePassed = false;
    state.practiceResult = null;
    state.practiceFeedback = "";
    showError("#practice-error", "");
    updateStatus("GENERATING_ACTIVITY");
    showScreen("practice");
    setText("#practice-title", definition.title);
    setText("#practice-question-label", "");
    const dots = $("#practice-dots");
    if (dots) dots.replaceChildren();
    const body = $("#practice-body");
    if (body) {
      body.replaceChildren();
      const loading = document.createElement("p");
      loading.textContent = "Making your activity…";
      body.append(loading);
    }
    try {
      const result = await api(`/api/sessions/${sessionId}/activities/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_id: operationId("activity"), activity_type: definition.type }),
      });
      if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;
      if (!result.session || result.session.session_id !== sessionId) {
        throw new Error("The lesson session changed while generating the activity.");
      }
      const audioResult = definition.audio
        ? await requestActivityAudio(result.activity, sessionId)
        : null;
      if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;
      result.audio = audioResult;
      updateFromSession(result.session);
      state.activity = result.activity;
      renderActivity(result.activity, result.audio);
    } catch (error) {
      if (!ownsRequest("activityOwner", activityOwner, generation, sessionId, navigationEpoch)) return;
      if (definition.audio && isAudioProviderFallbackError(error)) {
        showAudioFallback(definition, "The audio provider is not configured or is currently unavailable.");
      } else {
        showError("#practice-error", error.message || "I could not make that activity yet.");
        const body = $("#practice-body");
        if (body) body.replaceChildren();
      }
    }
  }
```

- [ ] **Step 4：確認綠燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there tests/api/test_static_ui.py::test_child_ui_activity_generation_ignores_stale_async_continuations tests/api/test_static_ui.py::test_child_ui_audio_failure_has_retry_and_text_fallback tests/api/test_static_ui.py::test_child_ui_async_operations_require_navigation_and_latest_request_ownership -q`
Expected: PASS。

- [ ] **Step 5：更新 `docs/PROGRESS.md`**

追加：

```markdown
### 2026-08-13 Task 3：generateActivity 進入獨立 practice 頁（完成）

- 實作：`state` 新增 `currentQuestionIndex` / `practiceAnswered` / `practicePassed` / `practiceResult` / `practiceFeedback`；`generateActivity` 改為先 `showScreen("practice")` 再顯示「Making your activity…」載入中，成功後 `renderActivity`，失敗留在 practice 頁顯示 `#practice-error`（audio provider fallback 仍沿用）。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 23 passed。
- 已知問題：此時 renderActivity 仍是舊版（Task 4 會改為單題渲染）。
- 下一步：Task 4（單題渲染 + 點狀進度）。
```

- [ ] **Step 6：Commit**

```bash
git add frontend/app.js tests/api/test_static_ui.py docs/PROGRESS.md
git commit -m "feat: open practice screen when generating an activity"
```

---

## Task 4：JS — 一次一題渲染 + 點狀進度

**Files:**
- Modify: `frontend/app.js`（`renderActivity` + 新增 5 個輔助函式）
- Test: `tests/api/test_static_ui.py`
- Docs: `docs/PROGRESS.md`

- [ ] **Step 1：寫失敗測試（新增 1 個 + 更新 1 個既有）**

新增：

```python
def test_child_ui_practice_renders_one_question_at_a_time_with_dot_progress() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    activity_render = _source_between(
        script,
        "  function renderActivity(",
        "  async function generateActivity(",
    )
    progress = _source_between(
        script,
        "  function renderPracticeProgress(",
        "  function renderPracticeQuestion(",
    )
    question = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  function renderPracticeResultActions(",
    )

    for marker in (
        "function renderPracticeProgress(activity)",
        "function renderPracticeQuestion(activity)",
        "function renderPracticeResultActions(activity, actions)",
        "function isLastPracticeQuestion(activity)",
        "function advancePracticeQuestion(activity)",
    ):
        assert marker in script
    assert "Question ${current + 1}" in progress
    assert 'className = "practice-dot"' in progress
    assert "is-done" in progress
    assert "is-current" in progress
    assert "renderPracticeProgress(activity)" in activity_render
    assert "renderPracticeQuestion(activity)" in activity_render
    assert "items.forEach" not in activity_render
    assert "Check my answer" in question
    assert "practice-question" in question
    assert 'showScreen("results")' not in activity_render
```

把整個 `test_child_ui_activity_render_defers_answer_evaluation_to_activity_service` 替換為：

```python
def test_child_ui_activity_render_defers_answer_evaluation_to_activity_service() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    stylesheet = client.get("/styles.css").text
    activity_render = _source_between(
        script,
        "  function renderActivity(",
        "  async function generateActivity(",
    )
    practice_question = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  function renderPracticeResultActions(",
    )

    for forbidden in ("item.answer", "expected", "correct", "handleAnswer"):
        assert forbidden not in script
    assert "choice-button" in practice_question
    assert "aria-pressed" in practice_question
    assert ".choice-button.selected" in stylesheet
    assert "renderPracticeQuestion(activity)" in activity_render
    assert "renderPracticeProgress(activity)" in activity_render
    assert "items.forEach" not in activity_render
    assert 'showScreen("results")' not in activity_render
    assert "updateProgress" not in script
```

- [ ] **Step 2：確認紅燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_practice_renders_one_question_at_a_time_with_dot_progress tests/api/test_static_ui.py::test_child_ui_activity_render_defers_answer_evaluation_to_activity_service -q`
Expected: FAIL — `renderPracticeQuestion` 不存在、`items.forEach` 仍在 renderActivity。

- [ ] **Step 3：實作 `frontend/app.js`**

把整個舊 `renderActivity`（從 `  function renderActivity(activity, audioResult = null) {` 到 `  }`，內容是 `#activity-panel` / `items.forEach` 版本）替換為下列新函式群（順序：`renderActivity` → `renderPracticeProgress` → `renderPracticeQuestion` → `renderPracticeResultActions` → `isLastPracticeQuestion` → `advancePracticeQuestion`）：

```js
  function renderActivity(activity, audioResult = null) {
    const body = $("#practice-body");
    if (!body) return;
    const definition = activityDefinitions.find((item) => item.type === activity.type) || {};
    setText("#practice-title", activity.title || definition.title || "Let's practise");
    body.replaceChildren();
    const audioMessage = audioFallbackMessage(activity, audioResult, definition);
    if (audioMessage) {
      showAudioFallback(definition, audioMessage);
    } else {
      appendAudioPlayer(body, audioResult);
    }
    const instructions = document.createElement("p");
    instructions.className = "activity-instructions";
    instructions.textContent = activity.instructions || "Take your time and choose your best answer.";
    body.append(instructions);
    renderPracticeProgress(activity);
    renderPracticeQuestion(activity);
  }

  function renderPracticeProgress(activity) {
    const items = Array.isArray(activity && activity.items) ? activity.items : [];
    const total = items.length;
    const current = Math.min(state.currentQuestionIndex, Math.max(total - 1, 0));
    setText("#practice-question-label", total ? `Question ${current + 1}` : "");
    const dots = $("#practice-dots");
    if (!dots) return;
    dots.replaceChildren();
    for (let i = 0; i < total; i += 1) {
      const dot = document.createElement("span");
      dot.className = "practice-dot";
      if (i < current) dot.classList.add("is-done");
      if (i === current) dot.classList.add("is-current");
      dot.setAttribute("aria-hidden", "true");
      dots.append(dot);
    }
  }

  function renderPracticeQuestion(activity) {
    const body = $("#practice-body");
    if (!body) return;
    const existing = body.querySelector(".practice-question");
    if (existing) existing.remove();
    const items = Array.isArray(activity && activity.items) ? activity.items : [];
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "practice-empty";
      empty.textContent = "This activity has no questions yet. Try another activity or try again.";
      body.append(empty);
      return;
    }
    const index = Math.max(0, Math.min(state.currentQuestionIndex, items.length - 1));
    const item = items[index];
    const question = document.createElement("article");
    question.className = "practice-question";
    const prompt = document.createElement("h4");
    prompt.className = "practice-prompt";
    prompt.textContent = item.prompt || "Choose an answer.";
    question.append(prompt);
    let readAnswer;
    if (Array.isArray(item.choices) && item.choices.length) {
      const choices = document.createElement("div");
      choices.className = "choice-list";
      let selectedChoice = "";
      item.choices.forEach((choice) => {
        const button = document.createElement("button");
        button.className = "choice-button";
        button.type = "button";
        button.setAttribute("aria-pressed", "false");
        button.disabled = state.practiceAnswered;
        button.textContent = choice;
        button.addEventListener("click", () => {
          choices.querySelectorAll(".choice-button").forEach((option) => {
            const selected = option === button;
            option.classList.toggle("selected", selected);
            option.setAttribute("aria-pressed", String(selected));
          });
          selectedChoice = choice;
        });
        choices.append(button);
      });
      readAnswer = () => selectedChoice;
      question.append(choices);
    } else {
      const answer = document.createElement("input");
      answer.className = "answer-input";
      answer.type = "text";
      answer.placeholder = "Type your answer";
      answer.disabled = state.practiceAnswered;
      answer.setAttribute("aria-label", `Answer for question ${index + 1}`);
      readAnswer = () => answer.value;
      question.append(answer);
    }
    if (activity.type === "speaking_practice") {
      const record = document.createElement("button");
      record.className = "secondary-button speech-button";
      record.type = "button";
      record.textContent = "Record your voice";
      const speechFeedback = document.createElement("p");
      speechFeedback.className = "speech-feedback";
      speechFeedback.setAttribute("aria-live", "polite");
      record.addEventListener("click", () => transcribeSpeaking(record, speechFeedback));
      question.append(record, speechFeedback);
    }
    const feedback = document.createElement("p");
    feedback.className = "answer-feedback";
    feedback.setAttribute("aria-live", "polite");
    feedback.textContent = state.practiceAnswered ? state.practiceFeedback : "";
    if (state.practiceAnswered) {
      feedback.classList.add(state.practicePassed ? "is-passed" : "is-try-again");
    }
    const actions = document.createElement("div");
    actions.className = "practice-actions";
    if (state.practiceAnswered) {
      renderPracticeResultActions(activity, actions);
    } else {
      const check = document.createElement("button");
      check.className = "primary-button answer-button";
      check.type = "button";
      check.textContent = "Check my answer";
      check.addEventListener("click", () => submitActivityAnswer(activity, item, readAnswer, feedback, check));
      actions.append(check);
    }
    question.append(actions);
    question.append(feedback);
    body.append(question);
  }

  function renderPracticeResultActions(activity, actions) {
    const last = isLastPracticeQuestion(activity);
    if (state.practicePassed) {
      const next = document.createElement("button");
      next.className = "primary-button";
      next.type = "button";
      next.textContent = last ? "Finish" : "Next question";
      next.addEventListener("click", () => {
        if (last) {
          showAnswerResult(state.practiceResult);
        } else {
          advancePracticeQuestion(activity);
        }
      });
      actions.append(next);
      return;
    }
    const tryAgain = document.createElement("button");
    tryAgain.className = "secondary-button";
    tryAgain.type = "button";
    tryAgain.textContent = "Try again";
    tryAgain.addEventListener("click", () => {
      state.practiceAnswered = false;
      state.practicePassed = false;
      state.practiceFeedback = "";
      renderPracticeQuestion(activity);
    });
    const next = document.createElement("button");
    next.className = "primary-button";
    next.type = "button";
    next.textContent = last ? "Finish" : "Next question";
    next.addEventListener("click", () => {
      if (last) {
        showAnswerResult(state.practiceResult);
      } else {
        advancePracticeQuestion(activity);
      }
    });
    actions.append(tryAgain, next);
  }

  function isLastPracticeQuestion(activity) {
    const items = Array.isArray(activity && activity.items) ? activity.items : [];
    return state.currentQuestionIndex >= items.length - 1;
  }

  function advancePracticeQuestion(activity) {
    const items = Array.isArray(activity && activity.items) ? activity.items : [];
    if (state.currentQuestionIndex < items.length - 1) {
      state.currentQuestionIndex += 1;
      state.practiceAnswered = false;
      state.practicePassed = false;
      state.practiceResult = null;
      state.practiceFeedback = "";
      renderPracticeProgress(activity);
      renderPracticeQuestion(activity);
    }
  }
```

- [ ] **Step 4：確認綠燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_practice_renders_one_question_at_a_time_with_dot_progress tests/api/test_static_ui.py::test_child_ui_activity_render_defers_answer_evaluation_to_activity_service -q`
Expected: PASS。

- [ ] **Step 5：更新 `docs/PROGRESS.md`**

追加：

```markdown
### 2026-08-13 Task 4：一次一題渲染 + 點狀進度（完成）

- 實作：`renderActivity` 改渲染到 `#practice-body`，一次只渲染 `state.currentQuestionIndex` 對應的一題；新增 `renderPracticeProgress`（點狀 ●○ +「Question X」）、`renderPracticeQuestion`、`renderPracticeResultActions`、`isLastPracticeQuestion`、`advancePracticeQuestion`；不再 `items.forEach` 列出全部題目。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 24 passed。
- 已知問題：作答後仍會走舊 `showAnswerResult` 直進 results（Task 5 改為 Try again / Next / Finish 流程）。
- 下一步：Task 5（作答流程 + audio fallback / wireActions / reset 清理）。
```

- [ ] **Step 6：Commit**

```bash
git add frontend/app.js tests/api/test_static_ui.py docs/PROGRESS.md
git commit -m "feat: render one practice question at a time with dot progress"
```

---

## Task 5：JS — 作答流程（Check / Next / Try again / Finish）+ 清理

**Files:**
- Modify: `frontend/app.js`（`submitActivityAnswer`、`showAudioFallback`、`wireActions`、`resetForNewCourse`）
- Test: `tests/api/test_static_ui.py`
- Docs: `docs/PROGRESS.md`

- [ ] **Step 1：寫失敗測試（新增 2 個 + 更新 1 個既有）**

新增：

```python
def test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    practice_helpers = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  async function submitActivityAnswer(",
    )
    submit_answer = _source_between(
        script,
        "  async function submitActivityAnswer(",
        "  async function transcribeSpeaking(",
    )

    for marker in (
        "Check my answer",
        "Next question",
        "Try again",
        "Finish",
        'textContent = last ? "Finish" : "Next question"',
    ):
        assert marker in practice_helpers
    _assert_source_order(
        practice_helpers,
        "function renderPracticeQuestion(",
        "function renderPracticeResultActions(",
        "function advancePracticeQuestion(",
    )
    _assert_source_order(
        submit_answer,
        'const value = String(readAnswer() || "").trim()',
        "setBusy(button, true",
        "`/api/sessions/${sessionId}/activities/${activity.activity_id}/answer`",
        'ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)',
        "state.practiceResult = result",
        "state.practicePassed = Boolean(evaluation.passed)",
        "state.practiceAnswered = true",
        "renderPracticeQuestion(activity)",
    )
    for marker in (
        "That was a strong try!",
        "Good try! Check the word again.",
    ):
        assert marker in submit_answer
    assert "showAnswerResult(result)" not in submit_answer
    assert 'showScreen("results")' in script
    for forbidden in ("item.answer", "expected", "correct", "handleAnswer"):
        assert forbidden not in script
```

新增：

```python
def test_child_ui_practice_wiring_removes_inline_panel_controls() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    wire_actions = _source_between(
        script,
        "  function wireActions() {",
        "  function init()",
    )
    reset_handler = _source_between(
        script,
        "  function resetForNewCourse() {",
        "  function wireActions()",
    )

    assert '$("#close-activity")' not in script
    assert '"#activity-panel"' not in script
    assert '"#activity-error"' not in script
    assert "function showAudioFallback(definition, errorMessage)" in script
    assert '"#practice-body"' in script
    assert 'showError("#practice-error"' in reset_handler
    assert "practiceBody.replaceChildren()" in reset_handler
    assert "practiceDots.replaceChildren()" in reset_handler
    _assert_source_order(
        reset_handler,
        'state.practiceFeedback = ""',
        'showError("#practice-error"',
        'const practiceBody = $("#practice-body")',
    )
    assert "invalidateNavigation()" in wire_actions
```

把整個 `test_child_ui_answer_submission_ignores_stale_async_continuations` 替換為：

```python
def test_child_ui_answer_submission_ignores_stale_async_continuations() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    submit_answer = _source_between(
        script,
        "  async function submitActivityAnswer(",
        "  async function transcribeSpeaking(",
    )

    answer_try = submit_answer[: submit_answer.index("    } catch (error) {")]
    _assert_source_order(
        answer_try,
        "const generation = state.flowGeneration",
        "const sessionId = state.sessionId",
        "setBusy(button, true",
        "`/api/sessions/${sessionId}/activities/${activity.activity_id}/answer`",
        'if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;',
        "state.practiceResult = result",
        "state.practiceAnswered = true",
        "renderPracticeQuestion(activity)",
    )
    answer_catch = submit_answer[submit_answer.index("    } catch (error) {") :]
    _assert_source_order(
        answer_catch,
        'if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;',
        "feedback.textContent = error.message",
        'if (ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch))',
        "setBusy(button, false)",
    )
```

- [ ] **Step 2：確認紅燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results tests/api/test_static_ui.py::test_child_ui_practice_wiring_removes_inline_panel_controls tests/api/test_static_ui.py::test_child_ui_answer_submission_ignores_stale_async_continuations -q`
Expected: FAIL — 舊 `submitActivityAnswer` 直接呼叫 `showAnswerResult(result)`、`$("#close-activity")` 仍存在。

- [ ] **Step 3：實作 `frontend/app.js`**

把整個 `submitActivityAnswer`（從 `  async function submitActivityAnswer(activity, item, readAnswer, feedback, button) {` 到 `  }`，位於 transcribeSpeaking 之前）替換為：

```js
  async function submitActivityAnswer(activity, item, readAnswer, feedback, button) {
    const value = String(readAnswer() || "").trim();
    if (!value) {
      feedback.textContent = "Choose or type an answer first.";
      return;
    }
    const generation = state.flowGeneration;
    const sessionId = state.sessionId;
    const navigationEpoch = state.navigationEpoch;
    const answerOwner = Symbol("answer");
    state.answerOwner = answerOwner;
    if (!sessionId) return;
    setBusy(button, true, "Checking...");
    try {
      const result = await api(
        `/api/sessions/${sessionId}/activities/${activity.activity_id}/answer`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operation_id: operationId("answer"),
            item_id: item.activity_id,
            answer: value,
          }),
        },
      );
      if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;
      const evaluation = result && result.evaluation ? result.evaluation : {};
      state.practiceResult = result;
      state.practicePassed = Boolean(evaluation.passed);
      state.practiceAnswered = true;
      state.practiceFeedback = evaluation.feedback
        || (state.practicePassed ? "That was a strong try!" : "Good try! Check the word again.");
      feedback.textContent = state.practiceFeedback;
      renderPracticeQuestion(activity);
    } catch (error) {
      if (!ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) return;
      feedback.textContent = error.message || "I could not check that answer yet.";
    } finally {
      if (ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)) {
        setBusy(button, false);
      }
    }
  }
```

把整個 `showAudioFallback`（從 `  function showAudioFallback(definition, errorMessage) {` 到 `  }`）替換為：

```js
  function showAudioFallback(definition, errorMessage) {
    const body = $("#practice-body");
    if (!body) return;
    body.replaceChildren();
    const fallback = document.createElement("div");
    fallback.className = "audio-fallback";
    const title = document.createElement("h4");
    title.textContent = "Audio is taking a break";
    const message = document.createElement("p");
    message.textContent = errorMessage || "The audio helper is not ready yet.";
    const alternative = document.createElement("p");
    alternative.textContent = "Text alternative: read the lesson passage aloud, then tell a grown-up what you heard.";
    const retry = document.createElement("button");
    retry.className = "secondary-button";
    retry.type = "button";
    retry.textContent = "Retry audio activity";
    retry.addEventListener("click", () => generateActivity(definition));
    fallback.append(title, message, alternative, retry);
    body.append(fallback);
  }
```

在 `wireActions` 中刪除 close-activity 監聽區塊：

```js
    $("#close-activity").addEventListener("click", () => {
      invalidateNavigation();
      $("#activity-panel").hidden = true;
    });
```

在 `resetForNewCourse` 中，於 `state.savedLessonOwner = null;` 之後加入：

```js
    state.currentQuestionIndex = 0;
    state.practiceAnswered = false;
    state.practicePassed = false;
    state.practiceResult = null;
    state.practiceFeedback = "";
```

並把 `resetForNewCourse` 結尾的：

```js
    showError("#activity-error", "");
    const panel = $("#activity-panel");
    if (panel) panel.hidden = true;
```

替換為：

```js
    showError("#practice-error", "");
    const practiceBody = $("#practice-body");
    if (practiceBody) practiceBody.replaceChildren();
    const practiceDots = $("#practice-dots");
    if (practiceDots) practiceDots.replaceChildren();
    setText("#practice-question-label", "");
```

- [ ] **Step 4：確認綠燈**

Run: `uv run pytest tests/api/test_static_ui.py -q`
Expected: PASS — 26 passed。

- [ ] **Step 5：更新 `docs/PROGRESS.md`**

追加：

```markdown
### 2026-08-13 Task 5：作答流程（Check / Next / Try again / Finish）+ 清理（完成）

- 實作：`submitActivityAnswer` 不再直接進 results，改為寫入 `practiceResult` / `practicePassed` / `practiceAnswered` / `practiceFeedback` 後 `renderPracticeQuestion`；答對顯示正向訊息 + Next question（最後一題為 Finish），答錯顯示「Good try! Check the word again.」+ Try again / Next question（最後一題為 Finish），不揭曉正確答案；Finish 才呼叫 `showAnswerResult`。`showAudioFallback` 改指向 `#practice-body`；刪除 close-activity 監聽與 `#activity-panel` / `#activity-error` 殘留；`resetForNewCourse` 清練習狀態。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 26 passed。
- 已知問題：無。
- 下一步：Task 6（全量驗證 + 收尾）。
```

- [ ] **Step 6：Commit**

```bash
git add frontend/app.js tests/api/test_static_ui.py docs/PROGRESS.md
git commit -m "feat: add check, try again, skip, and finish answer flow"
```

---

## Task 6：全量驗證 + 收尾交接

**Files:**
- Docs: `docs/PROGRESS.md`

- [ ] **Step 1：全量 Python 測試**

Run: `uv run pytest -q`
Expected: 296 passed、9 skipped、1 warning（基準 291 passed；本計畫新增 5 個契約測試）。不得有 regression。

- [ ] **Step 2：Python compileall**

Run: `uv run python -m compileall -q src tests`
Expected: 無輸出（通過）。

- [ ] **Step 3：Node 語法與測試**

Run: `node --check frontend/app.js frontend/screen-flow.js`
Expected: 無輸出（通過）。

Run: `node --test frontend/test/screen-flow.test.cjs`
Expected: 3 passed。

- [ ] **Step 4：git diff --check**

Run: `git diff --check`
Expected: 無輸出（乾淨）。

- [ ] **Step 5：更新 `docs/PROGRESS.md`**

追加：

```markdown
### 2026-08-13 練習頁改版（獨立頁面 + 一次一題）全量驗證與收尾

- `uv run pytest -q` → 296 passed、9 skipped、1 warning（291 基準 + 5 新契約測試）。
- `uv run python -m compileall -q src tests` → 通過。
- `node --check frontend/app.js frontend/screen-flow.js` → 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed。
- `git diff --check` → 乾淨。
- 驗收重點：獨立 practice 頁（Option A 單卡）、一次一題、點狀進度 +「Question X」（不顯示總數）、答錯溫和提示 + Try again / Skip 且不揭曉正確答案（沿用兒童安全契約）、最後一題 Finish 進 results；只動前端，後端 API 完全未改。
- 已知限制：in-app Browser sandbox 限制，瀏覽器手動流程驗證仍以 static UI 契約與 node 測試為準（與前期相同）。
- 下一步（交接起點）：commit 已完成（見 git log）；如需手動驗證，啟動 `uv run uvicorn talkpath.main:app`，進入 overview → 點任一活動卡片 → 應進入 practice 頁一次一題練習。
```

並在文件最上方「目前執行位置」補一行：第四個子項目（練習頁改版）已於 2026-08-13 完成。

- [ ] **Step 6：Commit**

```bash
git add docs/PROGRESS.md
git commit -m "docs: record one-question practice implementation"
```

---

## Self-Review

**1. Spec coverage**

- 3.1 獨立 practice screen（Option A 單卡、max-width 720px）：Task 1（HTML）+ Task 2（CSS `.practice-card { max-width: 720px; }`）+ Task 4。
- 3.2 一次一題 + `state.currentQuestionIndex` + 點狀進度 +「第 X 題」（不顯示總數）：Task 3（state）+ Task 4（`renderPracticeProgress` / `renderPracticeQuestion`）。
- 3.3 作答與回饋（Check → POST answer → 答對正向 + Next / 答錯溫和 + Try again + Next 跳過、不揭曉答案、最後一題 Finish 進 results）：Task 5。
- 3.4 overview 移除 `#activity-panel` / `#activity-error`，點卡片 → `showScreen("practice")` + `generateActivity`：Task 1 + Task 3。
- 3.5 音訊與口說題保留並移到 practice 頁逐題呈現：Task 4（`appendAudioPlayer` / `transcribeSpeaking`）+ Task 5（`showAudioFallback` 改指向 `#practice-body`）。
- 3.6 樣式（薄荷答對 / 奶油答錯、primary/secondary 按鈕、手機單欄、reduced-motion 不動）：Task 2。
- 4. 測試與驗證（static 契約、node 檢查、全量 pytest、git diff --check）：Task 1-6。
- 5. 不變更範圍（後端、results、lessons、screen-flow.js）：全程未觸及。

**2. Placeholder scan**

- 每個 step 都有完整程式碼或精確替換片段；無 TBD / TODO /「類似 Task N」。

**3. Type consistency**

- 函式名：`renderPracticeProgress(activity)` / `renderPracticeQuestion(activity)` / `renderPracticeResultActions(activity, actions)` / `isLastPracticeQuestion(activity)` / `advancePracticeQuestion(activity)` 在 Task 4 定義、Task 5 的 `submitActivityAnswer` 呼叫 `renderPracticeQuestion(activity)`，名稱一致。
- state 欄位：`currentQuestionIndex` / `practiceAnswered` / `practicePassed` / `practiceResult` / `practiceFeedback` 在 Task 3 定義，Task 4-5 讀寫同一組名稱。
- DOM id：`#practice-title` / `#practice-dots` / `#practice-question-label` / `#practice-card` / `#practice-body` / `#practice-error` 在 Task 1 HTML 定義，Task 3-5 JS 使用相同 id。
- 按鈕文字與 class 在 Task 5 測試與實作一致；回饋 class 使用 `is-passed` / `is-try-again`，避免「correct」字串。

