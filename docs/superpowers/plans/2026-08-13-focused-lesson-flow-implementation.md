# TalkPath Focused Lesson Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the vertically perceived lesson setup with a one-screen-at-a-time wizard, followed by a read-only extraction preview and a separate Practice Hub.

**Architecture:** Keep TalkPath as a single-page application and preserve all backend/session contracts. Extract screen visibility, immediate top positioning, and focus management into a small dependency-free controller; retain session, retry, WebSocket, flow-generation, import, and activity behavior in `frontend/app.js`.

**Tech Stack:** Semantic HTML, CSS, browser JavaScript, Node.js built-in test runner, FastAPI TestClient/pytest.

**Design reference:** `docs/superpowers/specs/2026-08-13-focused-lesson-flow-design.md`

**Workspace constraint:** `D:/python/TalkPath` contains verified, pre-existing uncommitted provider/speech and frontend changes. Preserve them. Before every commit, inspect the staged patch and include only task-specific content. If a modified existing file cannot be staged without mixing prior work, leave that task uncommitted, record the verified diff in `docs/PROGRESS.md`, and continue without destructive cleanup.

---

## File map

- Create `frontend/screen-flow.js`: dependency-free controller for one-visible-screen transitions, immediate top positioning, and destination focus.
- Create `frontend/test/screen-flow.test.cjs`: executable behavior tests using Node's built-in test runner and fake screen objects.
- Modify `frontend/index.html`: wizard steppers, focus targets, extraction progress, read-only preview layout, and explicit Preview ↔ Practice Hub actions.
- Modify `frontend/app.js`: initialize the controller and wire reset-safe navigation without altering API/session behavior.
- Modify `frontend/styles.css`: full-page screen geometry, wizard stepper, responsive preview, and reduced-motion-safe extraction treatment.
- Modify `tests/api/test_static_ui.py`: static HTML/wiring contracts for screen separation, stepper semantics, preview-before-practice order, and retained retry safety.
- Modify `docs/PROGRESS.md`: actual verification evidence, limitations, and next development point.

### Task 1: Add an executable screen-transition controller

**Files:**
- Create: `frontend/screen-flow.js`
- Create: `frontend/test/screen-flow.test.cjs`
- Modify: `frontend/index.html:12`
- Test: `frontend/test/screen-flow.test.cjs`

- [ ] **Step 1: Write the failing Node behavior tests**

Create `frontend/test/screen-flow.test.cjs`:

```javascript
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { createScreenController } = require("../screen-flow.js");

function fakeScreen(name) {
  const heading = {
    focusCalls: [],
    focus(options) { this.focusCalls.push(options); },
  };
  return {
    dataset: { screen: name },
    hidden: name !== "home",
    querySelector(selector) {
      return selector === "[data-screen-heading]" ? heading : null;
    },
    heading,
  };
}

test("show keeps exactly one screen visible and returns the active name", () => {
  const screens = [fakeScreen("home"), fakeScreen("new-course"), fakeScreen("scope")];
  const controller = createScreenController({ screens, scrollTo: () => {} });

  assert.equal(controller.show("scope"), "scope");
  assert.deepEqual(
    screens.filter((screen) => !screen.hidden).map((screen) => screen.dataset.screen),
    ["scope"],
  );
  assert.equal(controller.current(), "scope");
});

test("show positions the viewport immediately and focuses the destination heading", () => {
  const screens = [fakeScreen("home"), fakeScreen("preview")];
  const scrollCalls = [];
  const controller = createScreenController({
    screens,
    scrollTo: (options) => scrollCalls.push(options),
  });

  controller.show("preview");

  assert.deepEqual(scrollCalls, [{ top: 0, left: 0, behavior: "auto" }]);
  assert.deepEqual(screens[1].heading.focusCalls, [{ preventScroll: true }]);
});

test("show rejects an unknown screen without changing visibility", () => {
  const screens = [fakeScreen("home"), fakeScreen("preview")];
  const controller = createScreenController({ screens, scrollTo: () => {} });

  assert.throws(() => controller.show("missing"), /unknown screen/);
  assert.deepEqual(screens.map((screen) => screen.hidden), [false, true]);
});
```

- [ ] **Step 2: Run the behavior test and verify RED**

Run:

```powershell
node --test frontend/test/screen-flow.test.cjs
```

Expected: FAIL because `frontend/screen-flow.js` does not exist.

- [ ] **Step 3: Implement the controller**

Create `frontend/screen-flow.js`:

```javascript
(function exposeScreenFlow(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.TalkPathScreenFlow = api;
  }
})(typeof globalThis === "object" ? globalThis : this, function screenFlowFactory() {
  "use strict";

  function createScreenController({ screens, scrollTo }) {
    const screenList = Array.from(screens || []);
    if (!screenList.length) throw new Error("at least one screen is required");
    if (typeof scrollTo !== "function") throw new Error("scrollTo is required");
    let activeName = screenList.find((screen) => !screen.hidden)?.dataset.screen || null;

    function show(name) {
      const destination = screenList.find((screen) => screen.dataset.screen === name);
      if (!destination) throw new Error(`unknown screen: ${name}`);
      screenList.forEach((screen) => {
        screen.hidden = screen !== destination;
      });
      activeName = name;
      scrollTo({ top: 0, left: 0, behavior: "auto" });
      const heading = destination.querySelector("[data-screen-heading]");
      if (heading && typeof heading.focus === "function") {
        heading.focus({ preventScroll: true });
      }
      return activeName;
    }

    return { show, current: () => activeName };
  }

  return { createScreenController };
});
```

- [ ] **Step 4: Load the controller before the application**

In `frontend/index.html`, replace the single script declaration with:

```html
<script src="/screen-flow.js" defer></script>
<script src="/app.js" defer></script>
```

- [ ] **Step 5: Run the behavior and syntax checks and verify GREEN**

Run:

```powershell
node --test frontend/test/screen-flow.test.cjs
node --check frontend/screen-flow.js
```

Expected: `3 passed`; syntax check exits 0.

- [ ] **Step 6: Checkpoint Task 1 safely**

Run:

```powershell
git -c safe.directory=D:/python/TalkPath diff --check -- frontend/screen-flow.js frontend/test/screen-flow.test.cjs frontend/index.html
git -c safe.directory=D:/python/TalkPath status --short
```

If the staged patch can contain only Task 1 content, commit with:

```powershell
git -c safe.directory=D:/python/TalkPath add -- frontend/screen-flow.js frontend/test/screen-flow.test.cjs
git -c safe.directory=D:/python/TalkPath commit -m "test: add focused screen controller"
```

Leave the `index.html` hunk unstaged if it is mixed with later Task 2 markup.

### Task 2: Build the semantic three-step wizard and destination pages

**Files:**
- Modify: `frontend/index.html:28-158`
- Modify: `tests/api/test_static_ui.py`
- Test: `tests/api/test_static_ui.py`

- [ ] **Step 1: Write failing semantic layout contracts**

Add to `tests/api/test_static_ui.py`:

```python
def test_child_ui_uses_focused_wizard_then_preview_and_practice_hub() -> None:
    html = TestClient(create_app(testing=True)).get("/").text

    assert html.count('class="lesson-stepper"') == 3
    assert html.count('aria-label="Lesson setup progress"') == 3
    assert html.count('aria-current="step"') == 3
    for screen_id in ("new-course-screen", "scope-screen", "processing-screen"):
        section = _source_between(html, f'id="{screen_id}"', "</section>")
        assert 'class="lesson-stepper"' in section
        assert 'data-screen-heading' in section
    preview = _source_between(html, 'id="preview-screen"', "</section>")
    practice = _source_between(html, 'id="overview-screen"', 'id="results-screen"')
    assert 'class="lesson-stepper"' not in preview
    assert 'class="lesson-stepper"' not in practice
    assert "Extraction result" in preview
    assert "What we found" in preview
    assert "Choose a practice" in preview
    assert 'data-action="overview"' in preview
    assert "Pick a practice" in practice
    assert 'data-action="preview"' in practice
```

Extend `test_child_ui_homepage_serves_core_flow_sections` with:

```python
assert html.count("data-screen-heading") >= 8
assert '<script src="/screen-flow.js" defer></script>' in html
```

- [ ] **Step 2: Run the semantic test and verify RED**

Run:

```powershell
uv run pytest tests/api/test_static_ui.py -k "focused_wizard or homepage" -q
```

Expected: FAIL because the steppers, focus targets, and explicit Preview ↔ Practice actions are absent.

- [ ] **Step 3: Add the shared wizard stepper to Step 1**

Place this immediately inside `#new-course-screen`, before `.section-heading`, and add `data-screen-heading tabindex="-1"` to its heading:

```html
<ol class="lesson-stepper" aria-label="Lesson setup progress">
  <li aria-current="step"><span>1</span><strong>Upload</strong></li>
  <li><span>2</span><strong>Details</strong></li>
  <li><span>3</span><strong>Create</strong></li>
</ol>
<div class="section-heading">
  <p class="eyebrow">Step 1 of 3</p>
  <h2 data-screen-heading tabindex="-1">Show me your lesson</h2>
```

- [ ] **Step 4: Add the completed/current semantics to Steps 2 and 3**

Use this Step 2 list before the scope heading:

```html
<ol class="lesson-stepper" aria-label="Lesson setup progress">
  <li class="is-complete"><span aria-hidden="true">✓</span><strong>Upload</strong></li>
  <li aria-current="step"><span>2</span><strong>Details</strong></li>
  <li><span>3</span><strong>Create</strong></li>
</ol>
```

Use this Step 3 list before the processing content:

```html
<ol class="lesson-stepper" aria-label="Lesson setup progress">
  <li class="is-complete"><span aria-hidden="true">✓</span><strong>Upload</strong></li>
  <li class="is-complete"><span aria-hidden="true">✓</span><strong>Details</strong></li>
  <li aria-current="step"><span>3</span><strong>Create</strong></li>
</ol>
```

Add `data-screen-heading tabindex="-1"` to the Step 2 and Step 3 `h2` elements. Add this indeterminate treatment below `#status-label`:

```html
<div class="extraction-progress" aria-hidden="true"><span></span></div>
```

- [ ] **Step 5: Make Preview and Practice Hub explicit destinations**

In Preview, mark the destination heading and replace the action row with:

```html
<p class="eyebrow">Extraction result</p>
<h2 data-screen-heading tabindex="-1">Have a look before we practise</h2>
<!-- keep the existing lesson title, passage, content items, and safe error region -->
<div class="form-actions">
  <button class="secondary-button" type="button" data-action="new-course">Start a new lesson</button>
  <button id="start-practice" class="primary-button" type="button" data-action="overview">
    Choose a practice <span aria-hidden="true">→</span>
  </button>
</div>
```

In Practice Hub, mark `#overview-title` with `data-screen-heading tabindex="-1"` and add this beside the progress action:

```html
<button class="text-button" type="button" data-action="preview">← Lesson preview</button>
```

Change the Step 2 Back action from `data-action="new-course"` to:

```html
<button class="secondary-button" type="button" data-action="upload-step">Back</button>
```

Add `data-screen-heading tabindex="-1"` to the primary headings of Home, Results, and Progress so every destination has a focus target.

- [ ] **Step 6: Run the semantic tests and verify GREEN**

Run:

```powershell
uv run pytest tests/api/test_static_ui.py -k "focused_wizard or homepage" -q
```

Expected: selected tests pass.

- [ ] **Step 7: Checkpoint Task 2 safely**

Run:

```powershell
git -c safe.directory=D:/python/TalkPath diff --check -- frontend/index.html tests/api/test_static_ui.py
```

Do not commit these already-modified files unless `git diff --cached` proves the staged patch contains only focused-flow hunks.

### Task 3: Wire safe one-screen navigation into the existing lesson flow

**Files:**
- Modify: `frontend/app.js:77-82, 368-399, 797-888`
- Modify: `tests/api/test_static_ui.py`
- Test: `frontend/test/screen-flow.test.cjs`
- Test: `tests/api/test_static_ui.py`

- [ ] **Step 1: Write failing application-wiring contracts**

Add to `tests/api/test_static_ui.py`:

```python
def test_child_ui_routes_all_major_transitions_through_focused_screens() -> None:
    script = TestClient(create_app(testing=True)).get("/app.js").text
    show_screen = _source_between(
        script,
        "  function showScreen(name) {",
        "  function setText(",
    )
    wire_actions = _source_between(
        script,
        "  function wireActions() {",
        "  function init()",
    )
    import_helper = _source_between(
        script,
        "  async function runImport(",
        "  function renderLessonPreview(",
    )

    assert "screenController.show(name)" in show_screen
    assert "behavior: \"smooth\"" not in script
    assert 'showScreen("preview")' in import_helper
    for marker in (
        '[data-action="home"]',
        '[data-action="new-course"]',
        '[data-action="upload-step"]',
        '[data-action="preview"]',
        '[data-action="overview"]',
    ):
        assert marker in wire_actions
    _assert_source_order(
        wire_actions,
        '[data-action="home"]',
        "resetForNewCourse()",
        'showScreen("home")',
    )
```

Update the existing retry test so it continues to assert:

```python
assert 'showScreen("processing")' in retry_helper
assert 'showScreen("preview")' in import_helper
assert 'setRetry("Try the lesson again", () => retryFailedImport())' in import_helper
```

- [ ] **Step 2: Run the focused wiring tests and verify RED**

Run:

```powershell
uv run pytest tests/api/test_static_ui.py -k "focused_screens or failed_import_retry" -q
```

Expected: FAIL because `showScreen` still performs smooth scrolling and new actions are not wired.

- [ ] **Step 3: Initialize and use the screen controller**

Replace the current `showScreen` implementation in `frontend/app.js` with:

```javascript
let screenController = null;

function showScreen(name) {
  if (!screenController) throw new Error("screen controller is not initialized");
  return screenController.show(name);
}
```

At the beginning of `init()`, before `renderActivityCards()` and `wireActions()`, add:

```javascript
screenController = window.TalkPathScreenFlow.createScreenController({
  screens: $$('[data-screen]'),
  scrollTo: (options) => window.scrollTo(options),
});
```

- [ ] **Step 4: Make navigation actions preserve or invalidate state intentionally**

Replace the relevant action wiring with:

```javascript
$$('[data-action="home"]').forEach((button) => button.addEventListener("click", () => {
  resetForNewCourse();
  showScreen("home");
}));
$$('[data-action="new-course"]').forEach((button) => button.addEventListener("click", () => {
  resetForNewCourse();
  showScreen("new-course");
}));
$$('[data-action="upload-step"]').forEach((button) => button.addEventListener("click", () => {
  showScreen("new-course");
}));
$$('[data-action="preview"]').forEach((button) => button.addEventListener("click", () => {
  if (!state.lesson) return;
  renderLessonPreview(state.lesson);
  showScreen("preview");
}));
$$('[data-action="overview"]').forEach((button) => button.addEventListener("click", () => {
  if (!state.lesson) return;
  renderActivityCards();
  showScreen("overview");
}));
```

Remove the old single-element `[data-action=processing]` listener and the dedicated `#start-practice` listener. The semantic actions above replace both.

- [ ] **Step 5: Preserve the import → Preview → Practice order**

Keep `runImport()` in this exact success order:

```javascript
updateFromSession(result.session);
state.lesson = result.lesson;
renderLessonPreview(result.lesson);
state.uploadFile = null;
state.confirmedScope = null;
const fileInput = $("#course-image");
if (fileInput) fileInput.value = "";
showScreen("preview");
```

Do not call `renderActivityCards()` or `showScreen("overview")` inside `runImport()`.

- [ ] **Step 6: Run focused behavior, static, and syntax tests**

Run:

```powershell
node --test frontend/test/screen-flow.test.cjs
uv run pytest tests/api/test_static_ui.py -q
node --check frontend/screen-flow.js
node --check frontend/app.js
```

Expected: all commands exit 0.

- [ ] **Step 7: Checkpoint Task 3 safely**

Run:

```powershell
git -c safe.directory=D:/python/TalkPath diff --check -- frontend/app.js tests/api/test_static_ui.py
```

Do not stage unrelated pre-existing retry, provider, or activity hunks.

### Task 4: Style the focused wizard, preview, and Practice Hub responsively

**Files:**
- Modify: `frontend/styles.css:41-88`
- Modify: `tests/api/test_static_ui.py`
- Test: `tests/api/test_static_ui.py`

- [ ] **Step 1: Add failing stylesheet contracts**

Add to `tests/api/test_static_ui.py`:

```python
def test_child_ui_styles_focused_pages_without_smooth_scroll_layout() -> None:
    stylesheet = TestClient(create_app(testing=True)).get("/styles.css").text

    for selector in (
        ".lesson-stepper",
        '.lesson-stepper [aria-current="step"]',
        ".lesson-stepper .is-complete",
        ".extraction-progress",
        ".preview-layout",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert selector in stylesheet
    assert ".screen[hidden]" in stylesheet
    assert "min-height: calc(100" in stylesheet
```

- [ ] **Step 2: Run the stylesheet test and verify RED**

Run:

```powershell
uv run pytest tests/api/test_static_ui.py -k styles_focused_pages -q
```

Expected: FAIL because focused-flow styles do not exist.

- [ ] **Step 3: Add full-page geometry and wizard styles**

Add to `frontend/styles.css` near the existing `.screen` rules:

```css
main { min-height: calc(100vh - 130px); min-height: calc(100svh - 130px); }
.screen { min-height: calc(100vh - 150px); min-height: calc(100svh - 150px); padding: 42px 0 70px; }
.screen[hidden] { display: none !important; }
.screen [data-screen-heading]:focus { outline: none; }
.lesson-stepper { display: grid; max-width: 720px; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0 auto 30px; padding: 0; list-style: none; }
.lesson-stepper li { display: flex; align-items: center; justify-content: center; gap: 8px; min-width: 0; padding: 10px 12px; color: var(--muted); background: #edf1f5; border-radius: 999px; }
.lesson-stepper li span { display: grid; width: 24px; height: 24px; place-items: center; flex: 0 0 auto; background: #fff; border-radius: 50%; font-size: 0.78rem; }
.lesson-stepper [aria-current="step"] { color: #fff; background: var(--blue-dark); }
.lesson-stepper [aria-current="step"] span { color: var(--blue-dark); }
.lesson-stepper .is-complete { color: var(--mint-dark); background: var(--mint); }
.extraction-progress { width: min(100%, 520px); height: 10px; margin: 24px auto 0; overflow: hidden; background: #dfe6f0; border-radius: 999px; }
.extraction-progress span { display: block; width: 45%; height: 100%; background: var(--blue); border-radius: inherit; animation: extraction-slide 1.4s ease-in-out infinite alternate; }
@keyframes extraction-slide { from { transform: translateX(-10%); } to { transform: translateX(135%); } }
```

- [ ] **Step 4: Add an explicit preview layout**

Wrap the passage and content summary inside `.preview-layout` in `index.html`, then add:

```css
.preview-layout { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(260px, 0.75fr); gap: 22px; align-items: start; }
.preview-summary { min-width: 0; }
.preview-findings { min-width: 0; padding: 20px; background: #fff9e7; border-radius: 16px; }
```

Use this HTML structure inside `.lesson-preview-card`:

```html
<div class="preview-layout">
  <div class="preview-summary">
    <h3 id="lesson-title">Your English lesson</h3>
    <p id="lesson-passage" class="lesson-passage"></p>
  </div>
  <div class="preview-findings">
    <h4>What we found</h4>
    <ul id="lesson-content-items" class="content-item-list"></ul>
  </div>
</div>
```

- [ ] **Step 5: Add narrow-screen and reduced-motion rules**

Append:

```css
@media (max-width: 600px) {
  .lesson-stepper { gap: 5px; margin-bottom: 22px; }
  .lesson-stepper li { flex-direction: column; gap: 4px; padding: 8px 4px; font-size: 0.76rem; }
  .lesson-stepper li span { width: 21px; height: 21px; }
  .preview-layout { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .extraction-progress span { animation: none; width: 68%; }
}
```

- [ ] **Step 6: Run stylesheet, static, and syntax verification**

Run:

```powershell
uv run pytest tests/api/test_static_ui.py -q
node --test frontend/test/screen-flow.test.cjs
node --check frontend/app.js
node --check frontend/screen-flow.js
```

Expected: all commands exit 0.

- [ ] **Step 7: Checkpoint Task 4 safely**

Run:

```powershell
git -c safe.directory=D:/python/TalkPath diff --check -- frontend/index.html frontend/styles.css tests/api/test_static_ui.py
```

Do not create a mixed commit if existing frontend hunks cannot be isolated safely.

### Task 5: Verify the complete flow in API tests and a real browser

**Files:**
- Modify: `tests/api/test_static_ui.py`
- Modify: `docs/PROGRESS.md`
- Test: `tests/api/test_static_ui.py`
- Test: `tests/api/test_import_flow.py`
- Test: `tests/integration/test_failure_recovery.py`

- [ ] **Step 1: Add the final ordering and safety regression**

Add to `tests/api/test_static_ui.py`:

```python
def test_child_ui_success_path_cannot_skip_preview_for_practice() -> None:
    script = TestClient(create_app(testing=True)).get("/app.js").text
    import_helper = _source_between(
        script,
        "  async function runImport(",
        "  function renderLessonPreview(",
    )
    wire_actions = _source_between(script, "  function wireActions() {", "  function init()")

    assert 'showScreen("overview")' not in import_helper
    _assert_source_order(
        import_helper,
        "state.lesson = result.lesson",
        "renderLessonPreview(result.lesson)",
        'showScreen("preview")',
    )
    overview_action = wire_actions[wire_actions.index('[data-action="overview"]') :]
    _assert_source_order(
        overview_action,
        "if (!state.lesson) return",
        "renderActivityCards()",
        'showScreen("overview")',
    )
```

- [ ] **Step 2: Run focused Python and Node regression**

Run:

```powershell
uv run pytest tests/api/test_static_ui.py tests/api/test_import_flow.py tests/integration/test_failure_recovery.py -q
node --test frontend/test/screen-flow.test.cjs
node --check frontend/screen-flow.js
node --check frontend/app.js
```

Expected: all tests pass; only the documented Starlette/httpx warning may appear.

- [ ] **Step 3: Run full Python and retained Pi regression**

Run:

```powershell
uv run pytest -q
uv run python -m compileall -q src
npm test --prefix pi-extension
npm run typecheck --prefix pi-extension
git -c safe.directory=D:/python/TalkPath diff --check
```

Expected: all commands exit 0; live provider tests remain skipped unless explicitly enabled.

- [ ] **Step 4: Perform desktop browser verification**

Start TalkPath with fake providers to avoid the known Z.ai Vision availability issue:

```powershell
$env:TALKPATH_AGENT_BACKEND = "direct"
$env:TALKPATH_VISION_BACKEND = "fake"
$env:TALKPATH_TEXT_BACKEND = "fake"
$env:TALKPATH_STT_BACKEND = "fake"
$env:TALKPATH_TTS_BACKEND = "fake"
uv run uvicorn talkpath.api.app:create_app --factory --host 127.0.0.1 --port 8001
```

At approximately 1280 × 800, verify:

1. Home shows alone.
2. **Start a new lesson** replaces Home with Step 1 without smooth movement.
3. Upload advances to Step 2; Back returns to Step 1 without a vertical jump.
4. Confirming scope replaces Step 2 with Step 3.
5. Successful import replaces Step 3 with read-only Preview.
6. **Choose a practice** replaces Preview with Practice Hub.
7. **Lesson preview** returns from Practice Hub without recreating the lesson.
8. Browser console has no JavaScript errors.

- [ ] **Step 5: Perform narrow mobile verification**

At approximately 390 × 844, repeat the flow and verify:

- Step labels remain readable without horizontal scrolling.
- Preview collapses to one column.
- Practice cards remain usable.
- Focused screens do not reveal the next screen below them.
- Reduced-motion mode removes the moving extraction bar while preserving status.

- [ ] **Step 6: Update the sole progress handoff**

Append a dated section to `docs/PROGRESS.md` with:

```markdown
## 18. 2026-08-13 focused lesson flow

- Status: completed or partial, based only on code and verification evidence.
- Files changed: frontend/screen-flow.js, frontend/test/screen-flow.test.cjs,
  frontend/index.html, frontend/app.js, frontend/styles.css,
  tests/api/test_static_ui.py.
- Exact focused and full test results.
- Desktop and mobile browser verification results.
- Known limitation: executable controller behavior is covered without a full DOM;
  record any remaining browser-only timing risk honestly.
- Next development start.
```

- [ ] **Step 7: Final scope check**

Run:

```powershell
git -c safe.directory=D:/python/TalkPath status --short
git -c safe.directory=D:/python/TalkPath diff --check
git -c safe.directory=D:/python/TalkPath diff -- frontend/index.html frontend/app.js frontend/styles.css frontend/screen-flow.js frontend/test/screen-flow.test.cjs tests/api/test_static_ui.py docs/PROGRESS.md
```

Confirm there are no backend/provider contract changes and no lesson-editing feature. Commit only if a task-only staged patch can be proven; otherwise preserve the verified dirty worktree and document that limitation in `docs/PROGRESS.md`.
