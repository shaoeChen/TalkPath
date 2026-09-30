from __future__ import annotations

from pathlib import Path

import pytest

from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.domain.errors import RepositoryError
from talkpath.domain.models import Activity, ActivityDraft, ContentItem, CourseScope, LessonDraft


def make_lesson() -> LessonDraft:
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    return LessonDraft(
        lesson_id=scope.lesson_id,
        scope=scope,
        title="A saved lesson",
        passage="I go to school every day.",
        content_items=[
            ContentItem(
                content_id="word-school",
                type="vocabulary",
                content={"word": "school", "meaning": "學校"},
            )
        ],
        extraction_status="reviewed",
        provider="test",
        model="test-model",
        operation_id="lesson-op",
    )


def make_activity(lesson: LessonDraft, *, operation_id: str = "activity-op") -> ActivityDraft:
    return ActivityDraft(
        activity_id="vocabulary-quiz-1",
        lesson_id=lesson.lesson_id,
        type="vocabulary_quiz",
        title="Vocabulary quiz",
        instructions="Choose the best answer.",
        items=[
            Activity(
                activity_id="school-item-1",
                lesson_id=lesson.lesson_id,
                type="multiple_choice",
                prompt="What does school mean?",
                choices=["學校", "老師"],
                answer="學校",
                source_content_ids=["word-school"],
            )
        ],
        source_content_ids=["word-school"],
        provider="test-text",
        model="test-model",
        operation_id=operation_id,
    )


def make_repository(tmp_path: Path) -> tuple[LessonLensMarkdownRepository, LessonDraft]:
    repository = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson = make_lesson()
    repository.save_lesson_draft(lesson)
    return repository, lesson


def test_activity_round_trips_through_lessonlens(tmp_path: Path) -> None:
    repository, lesson = make_repository(tmp_path)
    activity = make_activity(lesson)

    repository.save_activity_draft(activity)

    activity_path = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-7"
        / "english"
        / "lesson-01"
        / "activities"
        / "vocabulary-quiz-1.md"
    )
    assert activity_path.is_file()
    assert "answer: 學校" in activity_path.read_text(encoding="utf-8")

    reopened = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    assert reopened.get_activity_draft(activity.activity_id) == activity


def test_activity_save_is_idempotent_and_rejects_conflicting_reuse(tmp_path: Path) -> None:
    repository, lesson = make_repository(tmp_path)
    activity = make_activity(lesson)
    repository.save_activity_draft(activity)
    repository.save_activity_draft(activity)

    with pytest.raises(RepositoryError, match="operation_id|activity ID"):
        repository.save_activity_draft(
            make_activity(lesson, operation_id="different-operation")
        )


def test_activity_rejects_cross_lesson_source_and_unsafe_identity(tmp_path: Path) -> None:
    repository, lesson = make_repository(tmp_path)
    invalid_source = make_activity(lesson).model_copy(
        update={"source_content_ids": ["not-in-lesson"]}
    )
    with pytest.raises(RepositoryError, match="source_content_ids"):
        repository.save_activity_draft(invalid_source)

    invalid_id = make_activity(lesson).model_copy(update={"activity_id": "../escape"})
    with pytest.raises(RepositoryError):
        repository.save_activity_draft(invalid_id)
