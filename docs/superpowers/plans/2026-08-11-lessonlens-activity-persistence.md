# LessonLens Activity Persistence Implementation Plan

> **目前狀態（2026-08-11）：** Task 1～Task 3 已完成；activity round-trip、operation-id idempotency、identity conflict、unsafe ID、跨 repository instance reload 與公開答案遮罩均有程式與測試證據。
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Persist `ActivityDraft` documents in the LessonLens activity directory and reload them safely across repository instances without exposing answers through the public API.

**Architecture:** Extend the existing Markdown adapter with an atomic activity document writer and a strict activity parser. Activity files live below the lesson path, contain the complete internal draft in YAML frontmatter, and use stable IDs plus lesson identity checks to enforce idempotency and ownership.

**Tech Stack:** Python 3.12, Pydantic domain models, PyYAML, pytest.

---

### Task 1: Specify activity persistence behavior with failing tests

**Files:**
- Create: `tests/unit/test_lessonlens_activities.py`
- Modify: `tests/api/test_activity_flow.py` only if an API redaction regression assertion needs to be tied to the persisted file.

- [x] **Step 1: Add fixtures and tests for round-trip persistence, idempotency, identity conflicts, unsafe IDs, and internal answer storage.**
- [x] **Step 2: Run the new test module and confirm the failures are caused by the adapter's unsupported activity methods.**

### Task 2: Implement strict LessonLens activity persistence

**Files:**
- Modify: `src/talkpath/adapters/lessonlens_markdown.py`
- Modify: `src/talkpath/application/activity_service.py` only if its persistence fallback/comment or repository read path requires a narrowly scoped adjustment.
- Modify: `src/talkpath/ports/lesson_repository.py` only if the protocol contract needs to match the implemented behavior.

- [x] **Step 1: Add safe activity path, metadata rendering, and parsing helpers.**
- [x] **Step 2: Implement atomic save with operation-id idempotency and activity-ID conflict checks.**
- [x] **Step 3: Implement cross-instance lookup with lesson and nested-item identity validation.**
- [x] **Step 4: Run the new tests and the existing LessonLens/activity service tests.**

### Task 3: Verify the bounded follow-up and update handoff progress

**Files:**
- Modify: `docs/PROGRESS.md`

- [x] **Step 1: Run the focused repository and related LessonLens regression commands.**
- [x] **Step 2: Inspect the diff and confirm no UI or unrelated API files changed.**
- [x] **Step 3: Record exact test results, known limitations, workspace path limitation, and next development start.**
