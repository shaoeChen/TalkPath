# Vocabulary Quiz (Dictation + Meaning-to-Word + Recognition) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the vocabulary quiz into a teacher-style mixed assessment (dictation, Chinese-to-English spelling, and recognition items) with local scoring, post-answer corrections, and a score/review results page.

**Architecture:** The quiz keeps the existing generated-activity flow (`vocabulary_quiz`), but every item carries a new public `question_type` field. All quiz answers are scored locally in `ActivityService` (no AI call), the answer endpoint returns `correction` only for quizzes and only after submission, and the frontend renders four question-type branches with one-shot answering plus a results screen that shows the score and wrong-word review.

**Tech Stack:** Python 3 / FastAPI / Pydantic / SQLite (schema unchanged), vanilla JS frontend (no framework), pytest + node test suites.

---

## File Structure

- `src/talkpath/domain/models.py` — add `question_type` to `Activity` (Task 1).
- `src/talkpath/adapters/fake_services.py` — `FakeTextService` emits mixed `vocabulary_quiz` items (Task 2).
- `src/talkpath/application/activity_service.py` — local compare for `vocabulary_quiz` (Task 3).
- `src/talkpath/api/routes.py` — `PublicActivityItem.question_type` + `ActivityAnswerResponse.correction` (Task 4).
- `src/talkpath/adapters/openai_compatible_services.py` — provider output instruction (Task 5).
- `frontend/app.js` — state, shuffle, render branches, submit behavior, results screen (Tasks 6-7).
- `frontend/index.html` — `#quiz-practice-words` button (Task 7).
- `frontend/styles.css` — `.answer-correction` (Task 7).
- `tests/unit/test_domain_models.py` — model field tests (Task 1).
- `tests/unit/test_fake_services.py` — fake quiz shape test (Task 2).
- `tests/unit/test_activity_service.py` — local scoring tests + updated legacy tests (Task 3).
- `tests/api/test_activity_flow.py` — public API contract tests (Task 4).
- `tests/unit/test_openai_compatible_services.py` — provider instruction test (Task 5).
- `tests/api/test_static_ui.py` — frontend contract tests + updated legacy tests (Tasks 6-7).
- `docs/PROGRESS.md` — progress record (Task 8).

All commands run from `D:\python\TalkPath` in PowerShell.

---

## Task 1: Add `question_type` to the Activity domain model

**Files:**
- Modify: `src/talkpath/domain/models.py:178-189` (`Activity` class)
- Test: `tests/unit/test_domain_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_domain_models.py`:

```python
def test_activity_defaults_question_type_to_none() -> None:
    item = Activity(
        activity_id="a-item-1",
        lesson_id="lesson-1",
        type="multiple_choice",
        prompt="What does school mean?",
        choices=["學校"],
        answer="學校",
    )

    assert item.question_type is None
    assert "question_type" in item.model_dump()


def test_activity_accepts_question_type() -> None:
    item = Activity(
        activity_id="a-item-1",
        lesson_id="lesson-1",
        type="dictation",
        prompt="school",
        choices=[],
        answer="school",
        question_type="dictation",
    )

    assert item.question_type == "dictation"
    assert Activity.model_validate(item.model_dump()) == item
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
uv run pytest tests/unit/test_domain_models.py::test_activity_defaults_question_type_to_none tests/unit/test_domain_models.py::test_activity_accepts_question_type -q
```

Expected: FAIL with `AttributeError: 'Activity' object has no attribute 'question_type'` (or Pydantic validation error).

- [ ] **Step 3: Write the minimal implementation**

In `src/talkpath/domain/models.py`, change `Activity` to:

```python
class Activity(DomainModel):
    """One child-facing practice or assessment item."""

    activity_id: str
    lesson_id: str
    type: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    answer: str | None = None
    explanation: str | None = None
    question_type: str | None = None
    source_content_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
uv run pytest tests/unit/test_domain_models.py -q
```

Expected: PASS (all domain model tests).

- [ ] **Step 5: Commit**

```bash
git add src/talkpath/domain/models.py tests/unit/test_domain_models.py
git commit -m "feat: add question_type to activity items"
```

---

## Task 2: Fake provider emits mixed vocabulary_quiz items

**Files:**
- Modify: `src/talkpath/adapters/fake_services.py:100-165` (`FakeTextService.generate_activity`)
- Test: `tests/unit/test_fake_services.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_fake_services.py`:

```python
@pytest.mark.asyncio
async def test_fake_vocabulary_quiz_emits_mixed_question_types():
    lesson = await FakeVisionService().extract_lesson([], make_scope(), operation_id="lesson-op")
    service = FakeTextService()

    activity = await service.generate_activity(
        lesson, "vocabulary_quiz", operation_id="quiz-op"
    )

    assert {item.question_type for item in activity.items} == {
        "dictation",
        "meaning_to_word",
        "word_to_meaning",
    }
    for item in activity.items:
        if item.question_type in {"dictation", "meaning_to_word"}:
            assert item.choices == []
            assert item.answer == "school"
        if item.question_type == "dictation":
            assert item.prompt == "school"
        if item.question_type == "meaning_to_word":
            assert item.prompt == "學校"
        if item.question_type == "word_to_meaning":
            assert item.prompt == "school"
            assert item.answer == "學校"
            assert len(item.choices) == 4
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
uv run pytest tests/unit/test_fake_services.py::test_fake_vocabulary_quiz_emits_mixed_question_types -q
```

Expected: FAIL (current fake returns one MC item with `question_type is None`).

- [ ] **Step 3: Write the minimal implementation**

In `src/talkpath/adapters/fake_services.py`, replace the branch starting at `normalized_type = activity_type.strip() or "practice"` with:

```python
        normalized_type = activity_type.strip() or "practice"
        if normalized_type == "vocabulary_practice":
            # Vocabulary practice is a speaking drill: one word card per item,
            # judged by comparing the STT transcript with the word itself.
            item = Activity(
                activity_id=f"{normalized_type}-item-1",
                lesson_id=lesson.lesson_id,
                type="speaking",
                prompt=word,
                choices=[],
                answer=word,
                explanation=f"Say {word} out loud.",
                source_content_ids=source_content_ids,
            )
            instructions = "Listen to the word, then say it out loud."
            items = [item]
        elif normalized_type == "vocabulary_quiz":
            # Vocabulary quiz mixes teacher-style assessment: dictation,
            # Chinese-to-English spelling, and meaning recognition.
            distractors = ["朋友", "天氣", "食物"]
            items = [
                Activity(
                    activity_id=f"{normalized_type}-item-1",
                    lesson_id=lesson.lesson_id,
                    type="dictation",
                    prompt=word,
                    choices=[],
                    answer=word,
                    question_type="dictation",
                    explanation=f"Spell {word}.",
                    source_content_ids=source_content_ids,
                ),
                Activity(
                    activity_id=f"{normalized_type}-item-2",
                    lesson_id=lesson.lesson_id,
                    type="fill_blank",
                    prompt=meaning,
                    choices=[],
                    answer=word,
                    question_type="meaning_to_word",
                    explanation=f"{meaning} is {word}.",
                    source_content_ids=source_content_ids,
                ),
                Activity(
                    activity_id=f"{normalized_type}-item-3",
                    lesson_id=lesson.lesson_id,
                    type="multiple_choice",
                    prompt=word,
                    choices=[meaning, *distractors],
                    answer=meaning,
                    question_type="word_to_meaning",
                    explanation=f"{word} means {meaning}.",
                    source_content_ids=source_content_ids,
                ),
            ]
            instructions = "Listen, spell, and pick the right meaning."
        else:
            item = Activity(
                activity_id=f"{normalized_type}-item-1",
                lesson_id=lesson.lesson_id,
                type="multiple_choice",
                prompt=f"What does {word} mean?",
                choices=[meaning, "學校"],
                answer=meaning,
                explanation=f"{word} means {meaning}.",
                source_content_ids=source_content_ids,
            )
            instructions = "Choose the best answer."
            items = [item]
        return ActivityDraft(
            activity_id=f"{normalized_type}-fixture",
            lesson_id=lesson.lesson_id,
            type=normalized_type,
            title=f"{normalized_type.replace('_', ' ').title()}",
            instructions=instructions,
            items=items,
            source_content_ids=source_content_ids,
            provider="fake-text",
            model="talkpath-fixture-text-v1",
            operation_id=operation_id,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
uv run pytest tests/unit/test_fake_services.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/talkpath/adapters/fake_services.py tests/unit/test_fake_services.py
git commit -m "feat: fake provider emits mixed vocabulary quiz question types"
```

---

## Task 3: Score all vocabulary_quiz answers locally

**Files:**
- Modify: `src/talkpath/application/activity_service.py:288`
- Test: `tests/unit/test_activity_service.py`

- [ ] **Step 1: Update legacy tests and write the failing test**

Replace `test_choice_answer_is_evaluated_locally_without_calling_text_provider` in `tests/unit/test_activity_service.py` with:

```python
@pytest.mark.asyncio
async def test_choice_answer_is_evaluated_locally_without_calling_text_provider(
    tmp_path: Path,
) -> None:
    service, progress_repository, text_service, session = make_service(tmp_path)
    generated = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_quiz",
        operation_id="generate-local-eval",
    )
    item = next(
        item for item in generated.items if item.question_type == "word_to_meaning"
    )
    assert item.choices

    correct = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer=item.answer,
        operation_id="answer-local-correct",
    )
    wrong = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer="not the meaning",
        operation_id="answer-local-wrong",
    )

    assert correct.evaluation.correct is True
    assert correct.evaluation.feedback == "Great job!"
    assert wrong.evaluation.correct is False
    assert wrong.evaluation.feedback == "Try again."
    assert text_service.evaluate_calls == 0
```

Replace `test_text_answer_still_uses_text_provider_for_evaluation` with:

```python
@pytest.mark.asyncio
async def test_text_answer_still_uses_text_provider_for_evaluation(
    tmp_path: Path,
) -> None:
    lesson_repository = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson_repository.save_lesson_draft(make_lesson())
    progress_repository = SQLiteProgressRepository(tmp_path / "progress.sqlite")
    session = progress_repository.create_session("local-child", make_lesson().lesson_id)
    text_service = CountingTextAnswerTextService()
    service = ActivityService(
        progress_repository=progress_repository,
        lesson_repository=lesson_repository,
        text_service=text_service,
    )
    generated = await service.generate_activity(
        session.session_id,
        activity_type="speaking_practice",
        operation_id="generate-text-eval",
    )
    item = generated.items[0]
    assert not item.choices

    result = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer="school",
        operation_id="answer-text-eval",
    )

    assert result.evaluation.correct is True
    assert text_service.evaluate_calls == 1
```

Append to `tests/unit/test_activity_service.py`:

```python
@pytest.mark.asyncio
async def test_vocabulary_quiz_dictation_is_compared_locally(
    tmp_path: Path,
) -> None:
    service, progress_repository, text_service, session = make_service(tmp_path)
    generated = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_quiz",
        operation_id="generate-dictation-eval",
    )
    item = next(item for item in generated.items if item.question_type == "dictation")
    assert item.choices == []
    assert item.prompt == item.answer == "school"

    passed = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer="school",
        operation_id="answer-dictation-pass",
    )
    missed = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer="scool",
        operation_id="answer-dictation-miss",
    )

    assert passed.evaluation.correct is True
    assert missed.evaluation.correct is False
    assert text_service.evaluate_calls == 0
```

- [ ] **Step 2: Run the tests to verify the new one fails**

```powershell
uv run pytest tests/unit/test_activity_service.py::test_vocabulary_quiz_dictation_is_compared_locally -q
```

Expected: FAIL with `assert text_service.evaluate_calls == 0` (currently dictation has no choices, so it calls the text provider).

- [ ] **Step 3: Write the minimal implementation**

In `src/talkpath/application/activity_service.py`, change the condition inside `answer()`:

```python
            if item.choices or activity.type in {"vocabulary_practice", "vocabulary_quiz"}:
                # Choice questions, vocabulary practice, and the vocabulary quiz
                # have a standard answer (the word or meaning), so compare
                # locally for instant feedback instead of waiting on the text provider.
                evaluation = self._evaluate_standard_answer(item, answer)
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
uv run pytest tests/unit/test_activity_service.py -q
```

Expected: PASS (all activity service tests).

- [ ] **Step 5: Commit**

```bash
git add src/talkpath/application/activity_service.py tests/unit/test_activity_service.py
git commit -m "feat: score vocabulary quiz answers locally"
```

---

## Task 4: Public API exposes question_type and post-answer correction

**Files:**
- Modify: `src/talkpath/api/routes.py:139-158, 217-225, 378-413`
- Test: `tests/api/test_activity_flow.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_activity_flow.py`:

```python
def test_vocabulary_quiz_public_items_include_question_type_and_hide_answer(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id, activity = prepare_activity(client)

    for item in activity["items"]:
        assert item["question_type"] in {
            "dictation",
            "meaning_to_word",
            "word_to_meaning",
        }
        assert "answer" not in item
        assert "expected_answer" not in item


def test_vocabulary_quiz_answer_returns_correction_and_records_attempt(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id, activity = prepare_activity(client)
    item = activity["items"][0]
    assert item["question_type"] == "dictation"

    answered = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "quiz-answer-correction",
            "item_id": item["activity_id"],
            "answer": "scool",
        },
    )

    assert answered.status_code == 200
    payload = answered.json()
    assert payload["evaluation"]["passed"] is False
    assert payload["correction"] == "school"
    assert "answer" not in payload
    assert "expected_answer" not in payload
    assert "expected_answer" not in payload["evaluation"]
    assert len(service.progress_repository.list_attempts(session_id)) == 1


def test_non_quiz_answer_has_no_correction(tmp_path: Path) -> None:
    client, service = make_client(tmp_path)
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json={
            "program": "junior high",
            "grade": "7",
            "subject": "English",
            "lesson": "1",
        },
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-no-correction"},
    ).status_code == 200
    generated = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={
            "operation_id": "generate-no-correction",
            "activity_type": "vocabulary_practice",
        },
    )
    assert generated.status_code == 200
    activity = generated.json()["activity"]
    item = activity["items"][0]

    answered = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "practice-answer-no-correction",
            "item_id": item["activity_id"],
            "answer": "school",
        },
    )

    assert answered.status_code == 200
    assert answered.json()["correction"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
uv run pytest tests/api/test_activity_flow.py::test_vocabulary_quiz_public_items_include_question_type_and_hide_answer tests/api/test_activity_flow.py::test_vocabulary_quiz_answer_returns_correction_and_records_attempt tests/api/test_activity_flow.py::test_non_quiz_answer_has_no_correction -q
```

Expected: FAIL (`question_type`/`correction` missing from responses).

- [ ] **Step 3: Write the minimal implementation**

In `src/talkpath/api/routes.py`, change `PublicActivityItem` to:

```python
class PublicActivityItem(ApiModel):
    """Child-facing activity item with the answer withheld at the API boundary."""

    activity_id: str
    lesson_id: str
    type: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    question_type: str | None = None
    explanation: str | None = None
    source_content_ids: list[str] = Field(default_factory=list)

    @classmethod
    def from_activity(cls, activity: Activity) -> "PublicActivityItem":
        return cls(
            activity_id=activity.activity_id,
            lesson_id=activity.lesson_id,
            type=activity.type,
            prompt=activity.prompt,
            choices=activity.choices,
            question_type=activity.question_type,
            # Provider explanations can accidentally contain the expected
            # answer, so they stay server-side for this child-facing contract.
            explanation=None,
            source_content_ids=activity.source_content_ids,
        )
```

Change `ActivityAnswerResponse` to:

```python
class ActivityAnswerResponse(ApiModel):
    operation_id: str
    activity_id: str
    item_id: str
    evaluation: PublicAnswerEvaluation
    attempt: PublicAttempt
    correction: str | None = None
```

Change the `answer_activity` endpoint return to:

```python
    return ActivityAnswerResponse(
        operation_id=payload.operation_id,
        activity_id=result.activity.activity_id,
        item_id=result.item.activity_id,
        evaluation=PublicAnswerEvaluation(
            passed=result.evaluation.correct,
            score=result.evaluation.score,
            feedback=_safe_child_feedback(result, payload.answer),
        ),
        attempt=PublicAttempt(
            attempt_id=attempt.attempt_id,
            session_id=attempt.session_id,
            lesson_id=attempt.lesson_id,
            activity_id=attempt.activity_id,
            passed=attempt.correct,
            score=attempt.score,
            created_at=attempt.created_at,
        ),
        correction=(
            result.item.answer
            if result.activity.type == "vocabulary_quiz"
            else None
        ),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
uv run pytest tests/api/test_activity_flow.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/talkpath/api/routes.py tests/api/test_activity_flow.py
git commit -m "feat: expose quiz question_type and post-answer correction in API"
```

---

## Task 5: Provider instruction for vocabulary_quiz question types

**Files:**
- Modify: `src/talkpath/adapters/openai_compatible_services.py:47-56` (`_ACTIVITY_OUTPUT_INSTRUCTION`)
- Test: `tests/unit/test_openai_compatible_services.py`

- [ ] **Step 1: Write the failing test**

Add to the import block in `tests/unit/test_openai_compatible_services.py`:

```python
from talkpath.adapters.openai_compatible_services import (
    OpenAICompatibleTextService,
    OpenAICompatibleVisionService,
    _ACTIVITY_OUTPUT_INSTRUCTION,
)
```

Append to the same file:

```python
def test_activity_output_instruction_specifies_vocabulary_quiz_question_types() -> None:
    assert "For vocabulary_quiz" in _ACTIVITY_OUTPUT_INSTRUCTION
    assert "dictation" in _ACTIVITY_OUTPUT_INSTRUCTION
    assert "meaning_to_word" in _ACTIVITY_OUTPUT_INSTRUCTION
    assert "word_to_meaning" in _ACTIVITY_OUTPUT_INSTRUCTION
    assert "listen_to_meaning" in _ACTIVITY_OUTPUT_INSTRUCTION
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
uv run pytest tests/unit/test_openai_compatible_services.py::test_activity_output_instruction_specifies_vocabulary_quiz_question_types -q
```

Expected: FAIL.

- [ ] **Step 3: Write the minimal implementation**

In `src/talkpath/adapters/openai_compatible_services.py`, replace `_ACTIVITY_OUTPUT_INSTRUCTION` with:

```python
_ACTIVITY_OUTPUT_INSTRUCTION = (
    "Return a JSON object with activity_id, lesson_id, type, title, instructions, "
    "items, and source_content_ids. Each item must contain activity_id, lesson_id, type, "
    "prompt, choices, answer, and question_type as a string; optional explanation and "
    "source_content_ids are allowed. "
    "Each item's activity_id must be unique, for example activity_id-item-1, activity_id-item-2. "
    "Do not use id, question, or options. "
    "For vocabulary_practice, every item is one vocabulary word from the lesson: "
    "prompt must be exactly the English word, answer must be exactly the same English word, "
    "and choices must be an empty list. "
    "For vocabulary_quiz, generate one item per vocabulary word in the lesson, shuffled "
    "into a random order, with question_type exactly one of: dictation, meaning_to_word, "
    "word_to_meaning, listen_to_meaning. For dictation and listen_to_meaning, prompt is the "
    "English word and is used for audio only. For meaning_to_word, prompt is the Chinese "
    "meaning and choices is an empty list. For word_to_meaning and listen_to_meaning, choices "
    "must contain 4 Chinese options including the correct meaning, and answer is the correct "
    "Chinese meaning. For dictation and meaning_to_word, choices is an empty list and answer is "
    "the English word. Mix question types so roughly half the items are dictation or "
    "meaning_to_word and the rest are word_to_meaning or listen_to_meaning."
)
```

- [ ] **Step 4: Run the test to verify it passes**

```powershell
uv run pytest tests/unit/test_openai_compatible_services.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/talkpath/adapters/openai_compatible_services.py tests/unit/test_openai_compatible_services.py
git commit -m "feat: instruct text provider on vocabulary quiz question types"
```

---

## Task 6: Frontend renders vocabulary_quiz question-type branches

**Files:**
- Modify: `frontend/app.js`
- Test: `tests/api/test_static_ui.py`

- [ ] **Step 1: Update legacy contract tests and write the failing test**

In `tests/api/test_static_ui.py`:

1. In `test_child_ui_generate_activity_opens_practice_screen_and_renders_loading_there`, the old shuffle marker appears twice (in the `for marker in (...)` tuple and in the `_assert_source_order(...)` call). Replace both occurrences of:

```python
        'state.practiceQueue = result.activity.type === "vocabulary_practice"',
```

with:

```python
        'result.activity.type === "vocabulary_practice" || result.activity.type === "vocabulary_quiz"',
```

2. In `test_child_ui_activity_render_defers_answer_evaluation_to_activity_service`, change:

```python
    for forbidden in ("item.answer", "expected", "correct", "handleAnswer"):
        assert forbidden not in script
```

to:

```python
    for forbidden in ("item.answer", "expected", "handleAnswer"):
        assert forbidden not in script
```

3. In `test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results`, change:

```python
    for forbidden in ("item.answer", "expected", "correct", "handleAnswer"):
        assert forbidden not in script
```

to:

```python
    for forbidden in ("item.answer", "expected", "handleAnswer"):
        assert forbidden not in script
```

4. Append the new render contract test:

```python
def test_child_ui_vocabulary_quiz_renders_question_type_branches() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    question = _source_between(
        script,
        "  function renderPracticeQuestion(",
        "  function renderPracticeResultActions(",
    )

    for marker in (
        'const isQuiz = activity.type === "vocabulary_quiz"',
        'item.question_type === "dictation"',
        'item.question_type === "meaning_to_word"',
        'item.question_type === "word_to_meaning"',
        'item.question_type === "listen_to_meaning"',
        "Listen and write the word.",
        "Listen and choose the meaning.",
        "playPracticeWord(item.prompt",
        "Show the word",
    ):
        assert marker in question
    assert "state.quizResults = []" in script
    assert 'state.practiceCorrection = ""' in script
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
uv run pytest tests/api/test_static_ui.py -q
```

Expected: FAIL (new markers missing).

- [ ] **Step 3: Write the minimal implementation**

In `frontend/app.js`:

1. In the `state` object, after `practiceTranscript: "",` add:

```js
    practiceCorrection: "",
    quizResults: [],
```

2. In `generateActivity`, after `state.practiceTranscript = "";` add:

```js
    state.practiceCorrection = "";
    state.quizResults = [];
```

3. In `generateActivity`, replace:

```js
      state.practiceQueue = result.activity.type === "vocabulary_practice"
        ? shufflePracticeQueue(items)
        : items.map((_, index) => index);
```

with:

```js
      state.practiceQueue = (result.activity.type === "vocabulary_practice"
        || result.activity.type === "vocabulary_quiz")
        ? shufflePracticeQueue(items)
        : items.map((_, index) => index);
```

4. In `advancePracticeQuestion`, after `state.practiceTranscript = "";` add:

```js
      state.practiceCorrection = "";
```

5. Replace `playPracticeWord` with:

```js
  async function playPracticeWord(word, feedback, onUnavailable) {
    const sessionId = state.sessionId;
    if (!sessionId || !word) return;
    try {
      const result = await api(`/api/sessions/${sessionId}/speech/synthesize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation_id: operationId("practice-word-audio"),
          text: word,
        }),
      });
      const source = result && (result.audio_data_url || result.audio_url);
      if (!source) throw new Error("Audio playback is not connected yet.");
      const player = new Audio(source);
      player.play().catch(() => {
        feedback.textContent = "Tap Listen again to hear the word.";
      });
    } catch (error) {
      feedback.textContent = isAudioProviderFallbackError(error)
        ? "The audio provider is not configured or is currently unavailable."
        : (error.message || "The audio helper is unavailable.");
      if (typeof onUnavailable === "function") onUnavailable();
    }
  }
```

6. Replace `renderPracticeQuestion` with:

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
    const isVocabularyPractice = activity.type === "vocabulary_practice";
    const isQuiz = activity.type === "vocabulary_quiz";
    const questionType = isQuiz ? (item.question_type || "") : "";
    const prompt = document.createElement("h4");
    prompt.className = "practice-prompt";
    if (isVocabularyPractice) {
      const word = document.createElement("h3");
      word.className = "practice-word";
      word.textContent = item.prompt || "";
      question.append(word);
    } else if (isQuiz && (questionType === "dictation" || questionType === "listen_to_meaning")) {
      prompt.textContent = questionType === "dictation"
        ? "Listen and write the word."
        : "Listen and choose the meaning.";
      question.append(prompt);
    } else {
      prompt.textContent = item.prompt || "Choose an answer.";
      question.append(prompt);
    }
    let readAnswer;
    let speechFeedback = null;
    if (isVocabularyPractice) {
      const controls = document.createElement("div");
      controls.className = "practice-speech-actions";
      const listen = document.createElement("button");
      listen.className = "secondary-button listen-button";
      listen.type = "button";
      listen.textContent = "Listen";
      listen.setAttribute("aria-label", "Hear the word");
      const record = document.createElement("button");
      record.className = "secondary-button speech-button";
      record.type = "button";
      record.textContent = "Record your voice";
      const recordFeedback = document.createElement("p");
      recordFeedback.className = "speech-feedback";
      recordFeedback.setAttribute("aria-live", "polite");
      listen.addEventListener("click", () => playPracticeWord(item.prompt, feedback));
      record.addEventListener("click", () => {
        transcribeSpeaking(record, recordFeedback, (transcript) => {
          if (!transcript) return;
          state.practiceTranscript = transcript;
          submitActivityAnswer(activity, item, () => state.practiceTranscript, feedback, record);
        });
      });
      controls.append(listen, record, recordFeedback);
      question.append(controls);
      readAnswer = () => state.practiceTranscript;
    } else {
      const needsAudio = questionType === "dictation" || questionType === "listen_to_meaning";
      if (needsAudio) {
        const listen = document.createElement("button");
        listen.className = "secondary-button listen-button";
        listen.type = "button";
        listen.textContent = "Listen";
        listen.setAttribute("aria-label", "Hear the word");
        speechFeedback = document.createElement("p");
        speechFeedback.className = "speech-feedback";
        speechFeedback.setAttribute("aria-live", "polite");
        if (questionType === "dictation") {
          const showWord = document.createElement("button");
          showWord.className = "text-button";
          showWord.type = "button";
          showWord.textContent = "Show the word";
          showWord.hidden = true;
          showWord.addEventListener("click", () => {
            prompt.textContent = item.prompt || "";
            showWord.hidden = true;
          });
          listen.addEventListener("click", () => {
            playPracticeWord(item.prompt, speechFeedback, () => { showWord.hidden = false; });
          });
          question.append(listen, showWord, speechFeedback);
        } else {
          listen.addEventListener("click", () => playPracticeWord(item.prompt, speechFeedback));
          question.append(listen, speechFeedback);
        }
      }
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
        const recordFeedback = document.createElement("p");
        recordFeedback.className = "speech-feedback";
        recordFeedback.setAttribute("aria-live", "polite");
        record.addEventListener("click", () => transcribeSpeaking(record, recordFeedback));
        question.append(record, recordFeedback);
      }
    }
    const feedback = document.createElement("p");
    feedback.className = "answer-feedback";
    feedback.setAttribute("aria-live", "polite");
    feedback.textContent = state.practiceFeedback || "";
    if (state.practiceFeedback) {
      feedback.classList.add(state.practicePassed ? "is-passed" : "is-try-again");
    }
    const correction = document.createElement("p");
    correction.className = "answer-correction";
    correction.setAttribute("aria-live", "polite");
    correction.textContent = state.practiceCorrection || "";
    if (state.practiceCorrection) correction.classList.add("is-try-again");
    const actions = document.createElement("div");
    actions.className = "practice-actions";
    if (state.practiceAnswered) {
      renderPracticeResultActions(activity, actions);
    } else if (!isVocabularyPractice) {
      const check = document.createElement("button");
      check.className = "primary-button answer-button";
      check.type = "button";
      check.textContent = "Check my answer";
      check.addEventListener("click", () => submitActivityAnswer(activity, item, readAnswer, feedback, check));
      actions.append(check);
    }
    question.append(actions);
    question.append(feedback, correction);
    body.append(question);
    if (questionType === "listen_to_meaning" && speechFeedback) {
      playPracticeWord(item.prompt, speechFeedback);
    }
  }
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
uv run pytest tests/api/test_static_ui.py -q
node --check frontend/app.js
```

Expected: PASS, syntax OK.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js tests/api/test_static_ui.py
git commit -m "feat: render vocabulary quiz question-type branches in practice screen"
```

---

## Task 7: Quiz submit behavior and score/review results page

**Files:**
- Modify: `frontend/app.js`, `frontend/index.html`, `frontend/styles.css`
- Test: `tests/api/test_static_ui.py`

- [ ] **Step 1: Update legacy order markers and write the failing tests**

In `tests/api/test_static_ui.py`:

1. In `test_child_ui_answer_submission_ignores_stale_async_continuations`, replace:

```python
        "state.practiceAnswered = Boolean(evaluation.passed)",
```

with:

```python
        "state.practiceAnswered = isQuiz ? true : Boolean(evaluation.passed)",
```

2. In `test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results`, replace:

```python
        "state.practiceAnswered = Boolean(evaluation.passed)",
```

with:

```python
        "state.practiceAnswered = isQuiz ? true : Boolean(evaluation.passed)",
```

3. Append the new contract tests:

```python
def test_child_ui_vocabulary_quiz_submits_once_and_shows_correction() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    submit = _source_between(
        script,
        "  async function submitActivityAnswer(",
        "  async function transcribeSpeaking(",
    )

    for marker in (
        'const isQuiz = activity.type === "vocabulary_quiz"',
        "state.practiceAnswered = isQuiz ? true : Boolean(evaluation.passed)",
        "state.quizResults.push",
        "Correct spelling",
        "Correct answer",
        "result.correction",
    ):
        assert marker in submit


def test_child_ui_vocabulary_quiz_results_show_score_and_review() -> None:
    client = TestClient(create_app(testing=True))

    script = client.get("/app.js").text
    results = _source_between(
        script,
        "  function showAnswerResult(",
        "  function shufflePracticeQueue(",
    )
    index_html = client.get("/index.html").text
    styles = client.get("/styles.css").text

    for marker in (
        'state.currentActivityType === "vocabulary_quiz"',
        "state.quizResults.filter",
        "quiz-practice-words",
        '"#review-list"',
    ):
        assert marker in results
    assert 'id="quiz-practice-words"' in index_html
    assert '"Practice these words"' in index_html
    assert ".answer-correction" in styles
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
uv run pytest tests/api/test_static_ui.py -q
```

Expected: FAIL (new markers missing).

- [ ] **Step 3: Write the minimal implementation**

In `frontend/app.js`:

1. In `submitActivityAnswer`, replace:

```js
      const evaluation = result && result.evaluation ? result.evaluation : {};
      state.practiceResult = result;
      state.practicePassed = Boolean(evaluation.passed);
      state.practiceAnswered = Boolean(evaluation.passed);
      state.practiceFeedback = evaluation.feedback
        || (state.practicePassed ? "That was a strong try!" : "Good try! Check the word again.");
      if (!state.practicePassed && !state.practiceWrongChoices.includes(value)) {
        state.practiceWrongChoices.push(value);
      }
      if (state.practicePassed && state.practiceWrongChoices.length > 0 && activity.type === "vocabulary_practice") {
        state.practiceQueue.push(state.practiceQueue[state.currentQuestionIndex]);
      }
      feedback.textContent = state.practiceFeedback;
      renderPracticeQuestion(activity);
      if (state.practicePassed) {
```

with:

```js
      const evaluation = result && result.evaluation ? result.evaluation : {};
      const isQuiz = activity.type === "vocabulary_quiz";
      state.practiceResult = result;
      state.practicePassed = Boolean(evaluation.passed);
      state.practiceAnswered = isQuiz ? true : Boolean(evaluation.passed);
      state.practiceFeedback = evaluation.feedback
        || (state.practicePassed ? "That was a strong try!" : "Good try! Check the word again.");
      const spellingTypes = new Set(["dictation", "meaning_to_word"]);
      state.practiceCorrection = isQuiz && !state.practicePassed && result.correction
        ? `${spellingTypes.has(item.question_type) ? "Correct spelling" : "Correct answer"}: ${result.correction}`
        : "";
      if (isQuiz) {
        state.quizResults.push({
          prompt: item.prompt || "",
          question_type: item.question_type || "",
          passed: state.practicePassed,
          correction: result.correction || "",
        });
      } else if (!state.practicePassed && !state.practiceWrongChoices.includes(value)) {
        state.practiceWrongChoices.push(value);
      }
      if (state.practicePassed && state.practiceWrongChoices.length > 0 && activity.type === "vocabulary_practice") {
        state.practiceQueue.push(state.practiceQueue[state.currentQuestionIndex]);
      }
      feedback.textContent = state.practiceFeedback;
      renderPracticeQuestion(activity);
      if (state.practicePassed && !isQuiz) {
```

2. Replace `showAnswerResult` with:

```js
  function showAnswerResult(result) {
    if (state.currentActivityType === "vocabulary_quiz") {
      const total = state.quizResults.length;
      const wrong = state.quizResults.filter((entry) => !entry.passed);
      const passedCount = total - wrong.length;
      setText("#result-message", `${passedCount} of ${total} correct`);
      setText("#result-title", wrong.length ? "Quiz finished" : "Perfect quiz");
      setText(
        "#result-detail",
        wrong.length
          ? "Check the words below, then practise them."
          : "You spelled and picked every word correctly.",
      );
      const list = $("#review-list");
      if (list) {
        list.replaceChildren();
        if (!wrong.length) {
          const item = document.createElement("li");
          item.textContent = "Every word was correct. Nice work!";
          list.append(item);
        } else {
          wrong.forEach((entry) => {
            const item = document.createElement("li");
            item.textContent = `${entry.prompt}: ${entry.correction || ""}`;
            list.append(item);
          });
        }
      }
      const practiceButton = $("#quiz-practice-words");
      if (practiceButton) practiceButton.hidden = !wrong.length;
      showScreen("results");
      return;
    }
    const evaluation = result && result.evaluation ? result.evaluation : {};
    const passed = Boolean(evaluation.passed);
    setText("#result-message", passed ? "That was a strong try!" : "Keep going; every try helps.");
    setText("#result-title", passed ? "Nice work" : "Good effort");
    setText("#result-detail", evaluation.feedback || "Take a breath and try another question.");
    showScreen("results");
  }
```

3. In `wireActions`, after the `$("#words-practice-all").addEventListener(...)` block, add:

```js
    $("#quiz-practice-words").addEventListener("click", () => openWordWall());
```

4. In `resetForNewCourse`, after `state.practiceTranscript = "";` add:

```js
    state.practiceCorrection = "";
    state.quizResults = [];
```

In `frontend/index.html`, in the results card, after `<p id="result-detail">Every try helps you remember a little more.</p>` add:

```html
              <button class="secondary-button" id="quiz-practice-words" type="button" hidden>Practice these words</button>
```

In `frontend/styles.css`, after the `.answer-feedback.is-try-again` rule add:

```css
.answer-correction { margin: 8px 0 0; color: #9a6b1f; font-weight: 800; }
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
uv run pytest tests/api/test_static_ui.py -q
node --check frontend/app.js
node --test frontend/test/screen-flow.test.cjs
```

Expected: PASS, syntax OK, node tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js frontend/index.html frontend/styles.css tests/api/test_static_ui.py
git commit -m "feat: one-shot quiz answers with corrections and score review results"
```

---

## Task 8: Full verification and progress record

**Files:**
- Modify: `docs/PROGRESS.md`

- [ ] **Step 1: Run the full verification suite**

```powershell
uv run pytest -q
uv run python -m compileall -q src tests
node --check frontend/app.js frontend/screen-flow.js
node --test frontend/test/screen-flow.test.cjs
git diff --check
```

Expected: all pytest tests pass (current baseline 315 passed, 9 skipped, 1 warning; regressions not allowed), compileall OK, node checks OK, `git diff --check` clean.

- [ ] **Step 2: Update `docs/PROGRESS.md`**

Append a section recording: the vocabulary quiz design was approved (2026-08-14), implementation tasks completed with TDD, verification results (exact pass counts and commands from Step 1), known limitations (quiz results list is session-memory based; real-provider generation needs live smoke; in-app Browser sandbox limit), and the next development start point (manual verification by restarting `uv run uvicorn talkpath.main:app` and opening the saved lesson → Vocabulary quiz).

- [ ] **Step 3: Commit**

```bash
git add docs/PROGRESS.md
git commit -m "docs: record vocabulary quiz implementation verification"
```
