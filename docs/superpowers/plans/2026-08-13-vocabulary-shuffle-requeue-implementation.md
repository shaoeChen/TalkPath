# 單字練習：隨機出題 + 錯題再出現 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 Vocabulary practice 的題目每次隨機出題，且答錯過的題目會排回佇列尾端再次出現，達到加強記憶的效果。

**Architecture:** 純前端變更。`frontend/app.js` 以「題目索引佇列」取代現行依 `activity.items` 原始順序逐題 +1 的機制：`generateActivity` 載入活動後對 `vocabulary_practice` 做 Fisher–Yates 洗牌建立佇列，其他類型維持原始順序；`submitActivityAnswer` 答對時若該次出現曾答錯，把目前題目索引 push 回佇列尾端；`renderPracticeProgress` / `renderPracticeQuestion` / `isLastPracticeQuestion` / `advancePracticeQuestion` 全部改以佇列為準。後端 API 完全不動（評分以 `item.activity_id` 為準，順序不影響）。

**Tech Stack:** Vanilla JS（`frontend/app.js`）、Python 來源契約測試（`tests/api/test_static_ui.py`）、uv/pytest、node。

---

## File Structure

- Modify: `frontend/app.js` — 唯一行為變更檔案。新增 `shufflePracticeQueue` helper；`state` 新增 `practiceQueue`；改 `generateActivity`（重置 + 洗牌）、`renderPracticeProgress`、`renderPracticeQuestion`、`isLastPracticeQuestion`、`advancePracticeQuestion`（以佇列為準）、`submitActivityAnswer`（答錯過就排回）、`resetForNewCourse`（重置佇列）。
- Modify: `tests/api/test_static_ui.py` — 擴充四個既有來源契約測試的 marker 與順序斷言（先紅燈後綠燈，不新增測試函式）。
- Modify: `docs/PROGRESS.md` — Task 4 記錄實作結果與驗證（AGENTS.md 要求）。

不改：後端、`frontend/index.html`、`frontend/styles.css`、`frontend/screen-flow.js`、`frontend/test/screen-flow.test.cjs`。

## 前置確認（執行者請先做）

- 讀 `docs/PROGRESS.md`（目前執行位置）與 `docs/superpowers/specs/2026-08-13-vocabulary-shuffle-requeue-design.md`（本計畫的規格來源）。
- 工作目錄必須是 `D:\python\TalkPath`；若不是，先確認路徑限制再動手。
- 基準測試數量：`uv run pytest -q` → 302 passed、9 skipped、1 warning。

### Task 1: 佇列狀態與隨機出題（state + shuffle helper + generateActivity）

**Files:**
- Modify: `frontend/app.js:27-40`（state）、`frontend/app.js:748-756`（showAnswerResult 之後插入 helper）、`frontend/app.js:1057-1119`（generateActivity）
- Test: `tests/api/test_static_ui.py:1162`（`test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there`）

- [ ] **Step 1: 寫失敗測試（更新契約）**

在 `test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there` 中，把 marker 迴圈改為：

```python
    for marker in (
        "currentQuestionIndex: 0",
        "practiceQueue: []",
        "practiceAnswered: false",
        "practicePassed: false",
        "practiceResult: null",
        'practiceFeedback: ""',
        "practiceWrongChoices: []",
        "practiceAutoAdvance: null",
        "PRACTICE_AUTO_ADVANCE_MS = 500",
    ):
        assert marker in script
```

把既有 `_assert_source_order` 的參數改為（新增 `"state.practiceQueue = []"`）：

```python
    _assert_source_order(
        generate_activity,
        "state.currentActivityType = definition.type",
        "state.currentQuestionIndex = 0",
        "state.practiceQueue = []",
        'showError("#practice-error", "")',
        'showScreen("practice")',
        "Making your activity…",
    )
```

在 `assert 'showScreen("overview")' not in generate_activity` 之後新增：

```python
    _assert_source_order(
        generate_activity,
        "state.activity = result.activity",
        'state.practiceQueue = result.activity.type === "vocabulary_practice"',
        "renderActivity(result.activity, result.audio)",
    )
    for marker in (
        "function shufflePracticeQueue(items)",
        "Math.floor(Math.random()",
        "items.map((_, index) => index)",
    ):
        assert marker in script
```

- [ ] **Step 2: 執行確認紅燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there -q`

Expected: FAIL（`practiceQueue: []`、`function shufflePracticeQueue(items)` 等 marker 不存在）

- [ ] **Step 3: 最小實作**

state 物件中 `currentQuestionIndex: 0,` 的下一行新增：

```js
    practiceQueue: [],
```

在 `showAnswerResult` 函式結束的 `}` 之後、`function renderPracticeProgress(activity) {` 之前插入：

```js
  function shufflePracticeQueue(items) {
    const indexes = items.map((_, index) => index);
    for (let i = indexes.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [indexes[i], indexes[j]] = [indexes[j], indexes[i]];
    }
    return indexes;
  }
```

`generateActivity` 開頭 `state.currentQuestionIndex = 0;` 的下一行新增：

```js
    state.practiceQueue = [];
```

`generateActivity` 中 `state.activity = result.activity;` 與 `renderActivity(result.activity, result.audio);` 之間插入：

```js
      const items = Array.isArray(result.activity.items) ? result.activity.items : [];
      state.practiceQueue = result.activity.type === "vocabulary_practice"
        ? shufflePracticeQueue(items)
        : items.map((_, index) => index);
```

- [ ] **Step 4: 執行確認綠燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js tests/api/test_static_ui.py
git commit -m "feat: shuffle vocabulary practice question queue"
```

### Task 2: 佇列化渲染與推進

**Files:**
- Modify: `frontend/app.js:757-774`（`renderPracticeProgress`）、`frontend/app.js:775-865`（`renderPracticeQuestion`）、`frontend/app.js:883-887`（`isLastPracticeQuestion`）、`frontend/app.js:888-902`（`advancePracticeQuestion`）
- Test: `tests/api/test_static_ui.py:1195`（`test_child_ui_practice_renders_one_question_at_a_time_with_dot_progress`）

- [ ] **Step 1: 寫失敗測試（更新契約）**

在 `test_child_ui_practice_renders_one_question_at_a_time_with_dot_progress` 中，宣告 `question` 切片之後新增 `advance` 切片：

```python
    advance = _source_between(
        script,
        "  function advancePracticeQuestion(",
        "  async function submitActivityAnswer(",
    )
```

在既有 `assert "items.forEach" not in activity_render` 附近新增：

```python
    assert "const total = state.practiceQueue.length" in progress
    assert "const item = items[queue[index]]" in question
    assert "state.practiceQueue.length - 1" in advance
    assert "state.practiceQueue.length - 1" in _source_between(
        script,
        "  function isLastPracticeQuestion(",
        "  function advancePracticeQuestion(",
    )
```

- [ ] **Step 2: 執行確認紅燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_practice_renders_one_question_at_a_time_with_dot_progress -q`

Expected: FAIL（`const total = state.practiceQueue.length` 等 marker 不存在）

- [ ] **Step 3: 最小實作（完整替換四個函式）**

`renderPracticeProgress` 完整替換為：

```js
  function renderPracticeProgress(activity) {
    const total = state.practiceQueue.length;
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
```

`renderPracticeQuestion` 完整替換為（只改 empty 判斷與 item 取值兩處，其餘保留）：

```js
  function renderPracticeQuestion(activity) {
    const body = $("#practice-body");
    if (!body) return;
    const existing = body.querySelector(".practice-question");
    if (existing) existing.remove();
    const items = Array.isArray(activity && activity.items) ? activity.items : [];
    const queue = Array.isArray(state.practiceQueue) ? state.practiceQueue : [];
    if (!items.length || !queue.length) {
      const empty = document.createElement("p");
      empty.className = "practice-empty";
      empty.textContent = "This activity has no questions yet. Try another activity or try again.";
      body.append(empty);
      return;
    }
    const index = Math.max(0, Math.min(state.currentQuestionIndex, queue.length - 1));
    const item = items[queue[index]];
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
        const wasWrong = state.practiceWrongChoices.includes(choice);
        button.disabled = state.practiceAnswered || wasWrong;
        if (wasWrong) button.classList.add("is-wrong");
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
    feedback.textContent = state.practiceFeedback || "";
    if (state.practiceFeedback) {
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
```

`isLastPracticeQuestion` 完整替換為：

```js
  function isLastPracticeQuestion(activity) {
    return state.currentQuestionIndex >= state.practiceQueue.length - 1;
  }
```

`advancePracticeQuestion` 完整替換為：

```js
  function advancePracticeQuestion(activity) {
    if (state.currentQuestionIndex < state.practiceQueue.length - 1) {
      clearTimeout(state.practiceAutoAdvance);
      state.practiceAutoAdvance = null;
      state.currentQuestionIndex += 1;
      state.practiceAnswered = false;
      state.practicePassed = false;
      state.practiceResult = null;
      state.practiceFeedback = "";
      state.practiceWrongChoices = [];
      renderPracticeProgress(activity);
      renderPracticeQuestion(activity);
    }
  }
```

- [ ] **Step 4: 執行確認綠燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_practice_renders_one_question_at_a_time_with_dot_progress -q`

Expected: PASS

Run: `node --check frontend/app.js frontend/screen-flow.js`

Expected: 無輸出（語法正確）

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js tests/api/test_static_ui.py
git commit -m "feat: drive practice rendering from question queue"
```

### Task 3: 錯題排回佇列尾端

**Files:**
- Modify: `frontend/app.js:904-965`（`submitActivityAnswer`）、`frontend/app.js:1120-1171`（`resetForNewCourse`）
- Test: `tests/api/test_static_ui.py:1235`（`test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results`）、`tests/api/test_static_ui.py:1292`（`test_child_ui_practice_wiring_removes_inline_panel_controls`）

- [ ] **Step 1: 寫失敗測試（更新契約）**

在 `test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results` 中，`submit_answer` 的 `_assert_source_order` 參數改為（在 `state.practiceWrongChoices.push(value)` 之後新增排回 marker）：

```python
    _assert_source_order(
        submit_answer,
        'const value = String(readAnswer() || "").trim()',
        "setBusy(button, true",
        "`/api/sessions/${sessionId}/activities/${activity.activity_id}/answer`",
        'ownsRequest("answerOwner", answerOwner, generation, sessionId, navigationEpoch)',
        "state.practiceResult = result",
        "state.practicePassed = Boolean(evaluation.passed)",
        "state.practiceAnswered = Boolean(evaluation.passed)",
        "state.practiceWrongChoices.push(value)",
        'activity.type === "vocabulary_practice"',
        "state.practiceQueue.push(state.practiceQueue[state.currentQuestionIndex])",
        "renderPracticeQuestion(activity)",
        "state.practiceAutoAdvance = setTimeout",
    )
```

該測試的 `submit_answer` marker 迴圈加入：

```python
        "state.practiceQueue.push(state.practiceQueue[state.currentQuestionIndex])",
```

在 `test_child_ui_practice_wiring_removes_inline_panel_controls` 中，`reset_handler` 斷言新增：

```python
    assert "state.practiceQueue = []" in reset_handler
    _assert_source_order(
        reset_handler,
        "state.currentQuestionIndex = 0",
        "state.practiceQueue = []",
        "state.practiceAnswered = false",
    )
```

- [ ] **Step 2: 執行確認紅燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results tests/api/test_static_ui.py::test_child_ui_practice_wiring_removes_inline_panel_controls -q`

Expected: FAIL（排回 marker 與 `state.practiceQueue = []` 不存在）

- [ ] **Step 3: 最小實作**

`submitActivityAnswer` 中，`state.practiceWrongChoices.push(value);` 所在的 if 區塊之後、`feedback.textContent = state.practiceFeedback;` 之前插入：

```js
      if (state.practicePassed && state.practiceWrongChoices.length > 0 && activity.type === "vocabulary_practice") {
        state.practiceQueue.push(state.practiceQueue[state.currentQuestionIndex]);
      }
```

注意：push 的是「題目索引」（佇列位置對應的元素），不是佇列位置本身；因為洗牌後 `currentQuestionIndex` 只是位置。此判斷在自動跳題 / 最後一題判斷之前，因此最後一題答錯過也會正確排回。條件含 `activity.type === "vocabulary_practice"` gate（規格 3.1：其他類型維持現狀、不重排錯題）。

`resetForNewCourse` 中 `state.currentQuestionIndex = 0;` 之後插入：

```js
    state.practiceQueue = [];
```

- [ ] **Step 4: 執行確認綠燈**

Run: `uv run pytest tests/api/test_static_ui.py::test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results tests/api/test_static_ui.py::test_child_ui_practice_wiring_removes_inline_panel_controls -q`

Expected: PASS

Run: `node --check frontend/app.js frontend/screen-flow.js`

Expected: 無輸出

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js tests/api/test_static_ui.py
git commit -m "feat: requeue wrong vocabulary questions"
```

### Task 4: 全量驗證 + 進度文件收尾

**Files:**
- Modify: `docs/PROGRESS.md`

- [ ] **Step 1: 全量驗證**

Run: `uv run pytest -q`

Expected: `302 passed、9 skipped、1 warning`（本計畫只擴充既有契約測試斷言，不新增測試函式，故數量不變；若數量不同需先查明）

Run: `uv run python -m compileall -q src tests`

Expected: 無輸出（通過）

Run: `node --check frontend/app.js frontend/screen-flow.js`

Expected: 無輸出

Run: `node --test frontend/test/screen-flow.test.cjs`

Expected: `3 passed`

Run: `git diff --check`

Expected: 乾淨（無 whitespace 錯誤）

- [ ] **Step 2: 更新 `docs/PROGRESS.md`**

依 AGENTS.md 在 `docs/PROGRESS.md` 末尾新增執行紀錄，內容須包含：更新日期（2026-08-13）、實作摘要（佇列洗牌 + 錯題排回、只套用 vocabulary_practice）、TDD 紅燈→綠燈過程、全量驗證數字、已知限制（in-app Browser sandbox 限制，以 static 契約與 node 測試為準）、下一步（如需手動驗證，啟動 `uv run uvicorn talkpath.main:app` 進入單字練習，確認每次題序不同、答錯題目會再出現）。同時把「第四期後續：單字練習隨機出題 + 錯題再出現（設計階段）」段落改為已完成並指向本計畫。

- [ ] **Step 3: Commit**

```bash
git add docs/PROGRESS.md
git commit -m "docs: record vocabulary shuffle and requeue implementation"
```

---

## 驗收對照（規格 → 計畫）

- 規格 3.1（只套用 Vocabulary practice）→ Task 1 的 `result.activity.type === "vocabulary_practice"` 分支。
- 規格 3.2（隨機出題佇列）→ Task 1（shuffle helper + 佇列建立）+ Task 2（渲染/推進以佇列為準）。
- 規格 3.3（錯題再出現、不設上限、最後一題也排回）→ Task 3 的 push 位置（自動跳題判斷之前）。
- 規格 3.4（進度以佇列長度顯示）→ Task 2 的 `renderPracticeProgress`。
- 規格 4（TDD + 全量驗證）→ 各 Task 紅燈/綠燈 + Task 4。
- 規格 3.5（不變更範圍）→ 本計畫只動 `frontend/app.js`、`tests/api/test_static_ui.py`、`docs/PROGRESS.md`。
