from __future__ import annotations

from pathlib import Path

import pytest

from talkpath.adapters.fake_services import FakeTextService
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.application.activity_service import (
    ActivityLessonNotFound,
    ActivityNotFound,
    ActivityOperationConflict,
    ActivityService,
)
from talkpath.domain.models import Activity, ActivityDraft, ContentItem, CourseScope, LessonDraft


SUPPORTED_ACTIVITY_TYPES = (
    "vocabulary_practice",
    "vocabulary_quiz",
    "grammar_practice",
    "grammar_quiz",
    "listening_practice",
    "listening_quiz",
    "reading_aloud",
    "speaking_practice",
)


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
            ),
            ContentItem(
                content_id="grammar-present",
                type="grammar",
                content={"name": "simple present"},
            ),
        ],
        extraction_status="reviewed",
        provider="test",
        model="test-model",
        operation_id="lesson-op",
    )


class CountingTextService(FakeTextService):
    def __init__(self) -> None:
        self.generate_calls = 0
        self.evaluate_calls = 0

    async def generate_activity(self, *args, **kwargs):
        self.generate_calls += 1
        return await super().generate_activity(*args, **kwargs)

    async def evaluate_answer(self, *args, **kwargs):
        self.evaluate_calls += 1
        return await super().evaluate_answer(*args, **kwargs)


class DuplicateItemIdTextService(FakeTextService):
    """Simulate real text providers that copy the activity ID into every item."""

    async def generate_activity(self, lesson, activity_type, *, operation_id):
        draft = await super().generate_activity(
            lesson, activity_type, operation_id=operation_id
        )
        items = [
            Activity(
                activity_id=draft.activity_id,
                lesson_id=lesson.lesson_id,
                type="multiple_choice",
                prompt=f"What does word {index} mean?",
                choices=[f"meaning-{index}", "other"],
                answer=f"meaning-{index}",
                source_content_ids=draft.items[0].source_content_ids,
            )
            for index in range(1, 4)
        ]
        return draft.model_copy(update={"items": items})


class FixedActivityIdTextService(FakeTextService):
    """Simulate real providers that derive the activity ID from the lesson."""

    async def generate_activity(self, lesson, activity_type, *, operation_id):
        draft = await super().generate_activity(
            lesson, activity_type, operation_id=operation_id
        )
        return draft.model_copy(update={"activity_id": f"fixed-{activity_type}"})


class TextAnswerTextService(FakeTextService):
    """Generate a single fill-in-the-blank item with no choices."""

    async def generate_activity(self, lesson, activity_type, *, operation_id):
        draft = await super().generate_activity(
            lesson, activity_type, operation_id=operation_id
        )
        base = draft.items[0]
        item = Activity(
            activity_id=base.activity_id,
            lesson_id=lesson.lesson_id,
            type="fill_blank",
            prompt="Type the missing word.",
            choices=[],
            answer="school",
            source_content_ids=base.source_content_ids,
        )
        return draft.model_copy(update={"items": [item]})


class CountingTextAnswerTextService(TextAnswerTextService):
    def __init__(self) -> None:
        self.generate_calls = 0
        self.evaluate_calls = 0

    async def generate_activity(self, *args, **kwargs):
        self.generate_calls += 1
        return await super().generate_activity(*args, **kwargs)

    async def evaluate_answer(self, *args, **kwargs):
        self.evaluate_calls += 1
        return await super().evaluate_answer(*args, **kwargs)


def make_service(
    tmp_path: Path,
) -> tuple[ActivityService, SQLiteProgressRepository, CountingTextService, object]:
    lesson = make_lesson()
    lesson_repository = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson_repository.save_lesson_draft(lesson)
    progress_repository = SQLiteProgressRepository(tmp_path / "progress.sqlite")
    session = progress_repository.create_session("local-child", lesson.lesson_id)
    text_service = CountingTextService()
    service = ActivityService(
        progress_repository=progress_repository,
        lesson_repository=lesson_repository,
        text_service=text_service,
    )
    return service, progress_repository, text_service, session


@pytest.mark.asyncio
@pytest.mark.parametrize("activity_type", SUPPORTED_ACTIVITY_TYPES)
async def test_generates_supported_activity_from_saved_lesson_and_can_retrieve_it(
    tmp_path: Path,
    activity_type: str,
) -> None:
    service, progress_repository, _, session = make_service(tmp_path)
    session_id = session.session_id

    generated = await service.generate_activity(
        session_id,
        activity_type=activity_type,
        operation_id=f"generate-{activity_type}",
    )

    assert generated.type == activity_type
    assert generated.lesson_id == make_lesson().lesson_id
    assert service.get_activity(session_id, generated.activity_id) == generated


@pytest.mark.asyncio
async def test_generation_rejects_unsaved_lesson_and_client_activity_ids(tmp_path: Path) -> None:
    lesson_repository = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    progress_repository = SQLiteProgressRepository(tmp_path / "progress.sqlite")
    session = progress_repository.create_session("local-child", "missing-lesson")
    service = ActivityService(
        progress_repository=progress_repository,
        lesson_repository=lesson_repository,
        text_service=FakeTextService(),
    )

    with pytest.raises(ActivityLessonNotFound):
        await service.generate_activity(
            session.session_id,
            activity_type="vocabulary_quiz",
            operation_id="generate-missing",
        )

    with pytest.raises(ActivityLessonNotFound):
        service.get_activity(session.session_id, "client-invented-activity")

    saved_service, _, _, saved_session = make_service(tmp_path / "saved")
    with pytest.raises(ActivityNotFound):
        saved_service.get_activity(saved_session.session_id, "client-invented-activity")


@pytest.mark.asyncio
async def test_regenerating_same_lesson_activity_gets_a_fresh_unique_activity_id(
    tmp_path: Path,
) -> None:
    lesson_repository = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson_repository.save_lesson_draft(make_lesson())
    progress_repository = SQLiteProgressRepository(tmp_path / "progress.sqlite")
    session = progress_repository.create_session("local-child", make_lesson().lesson_id)
    service = ActivityService(
        progress_repository=progress_repository,
        lesson_repository=lesson_repository,
        text_service=FixedActivityIdTextService(),
    )

    first = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_practice",
        operation_id="regenerate-1",
    )
    second = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_practice",
        operation_id="regenerate-2",
    )

    assert first.activity_id == "fixed-vocabulary_practice"
    assert second.activity_id != first.activity_id
    assert second.lesson_id == first.lesson_id
    assert second.type == first.type
    assert service.get_activity(session.session_id, first.activity_id) == first
    assert service.get_activity(session.session_id, second.activity_id) == second


@pytest.mark.asyncio
async def test_answer_uses_trusted_activity_and_operation_retry_writes_once(tmp_path: Path) -> None:
    service, progress_repository, text_service, session = make_service(tmp_path)
    generated = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_quiz",
        operation_id="generate-answer-test",
    )
    item_id = generated.items[0].activity_id

    first = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item_id,
        answer="not the word",
        operation_id="answer-retry-1",
    )
    second = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item_id,
        answer="not the word",
        operation_id="answer-retry-1",
    )

    assert second == first
    assert first.evaluation.correct is False
    assert first.attempt.activity_id == item_id
    assert len(progress_repository.list_attempts(session.session_id)) == 1
    assert len(progress_repository.list_review_items(session.session_id, make_lesson().lesson_id)) == 1
    assert text_service.evaluate_calls == 0

    with pytest.raises(ActivityOperationConflict):
        await service.answer(
            session.session_id,
            generated.activity_id,
            item_id=item_id,
            answer="a different retry payload",
            operation_id="answer-retry-1",
        )


@pytest.mark.asyncio
async def test_answer_uses_correct_item_when_provider_reuses_activity_id_for_every_item(
    tmp_path: Path,
) -> None:
    lesson_repository = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson_repository.save_lesson_draft(make_lesson())
    progress_repository = SQLiteProgressRepository(tmp_path / "progress.sqlite")
    session = progress_repository.create_session("local-child", make_lesson().lesson_id)
    service = ActivityService(
        progress_repository=progress_repository,
        lesson_repository=lesson_repository,
        text_service=DuplicateItemIdTextService(),
    )

    generated = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_quiz",
        operation_id="generate-duplicate-item-ids",
    )
    assert len(generated.items) == 3
    # The provider reused the activity ID for every item, so the service must
    # assign stable unique ids (one per item) before caching and answering.
    assert len({item.activity_id for item in generated.items}) == len(generated.items)

    for index, item in enumerate(generated.items, start=1):
        result = await service.answer(
            session.session_id,
            generated.activity_id,
            item_id=item.activity_id,
            answer=f"meaning-{index}",
            operation_id=f"answer-duplicate-{index}",
        )
        assert result.item.activity_id == item.activity_id
        assert result.evaluation.correct is True
        assert result.attempt.activity_id == item.activity_id


@pytest.mark.asyncio
async def test_answer_uses_correct_item_when_saved_activity_has_duplicate_item_ids(
    tmp_path: Path,
) -> None:
    lesson_repository = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson_repository.save_lesson_draft(make_lesson())
    lesson = lesson_repository.get_lesson(make_lesson().lesson_id)
    legacy = ActivityDraft(
        activity_id="legacy-activity",
        lesson_id=lesson.lesson_id,
        type="vocabulary_quiz",
        title="Legacy quiz",
        instructions="Choose one.",
        items=[
            Activity(
                activity_id="legacy-activity",  # duplicate on purpose
                lesson_id=lesson.lesson_id,
                type="multiple_choice",
                prompt=f"What does word {index} mean?",
                choices=[f"meaning-{index}", "other"],
                answer=f"meaning-{index}",
            )
            for index in range(1, 3)
        ],
        source_content_ids=[],
        provider="legacy",
        model="legacy",
        operation_id="legacy-op",
    )
    lesson_repository.save_activity_draft(legacy)

    progress_repository = SQLiteProgressRepository(tmp_path / "progress.sqlite")
    session = progress_repository.create_session("local-child", lesson.lesson_id)
    service = ActivityService(
        progress_repository=progress_repository,
        lesson_repository=lesson_repository,
        text_service=FakeTextService(),
    )

    loaded = service.get_activity(session.session_id, "legacy-activity")
    assert len({item.activity_id for item in loaded.items}) == 2

    first = await service.answer(
        session.session_id,
        "legacy-activity",
        item_id=loaded.items[0].activity_id,
        answer="meaning-1",
        operation_id="legacy-answer-1",
    )
    second = await service.answer(
        session.session_id,
        "legacy-activity",
        item_id=loaded.items[1].activity_id,
        answer="meaning-2",
        operation_id="legacy-answer-2",
    )
    assert first.evaluation.correct is True
    assert second.evaluation.correct is True


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
        answer="not the word",
        operation_id="answer-local-wrong",
    )

    assert correct.evaluation.correct is True
    assert correct.evaluation.feedback == "Great job!"
    assert wrong.evaluation.correct is False
    assert wrong.evaluation.feedback == "Try again."
    assert text_service.evaluate_calls == 0


@pytest.mark.asyncio
async def test_vocabulary_practice_items_are_word_cards_compared_locally(
    tmp_path: Path,
) -> None:
    service, progress_repository, text_service, session = make_service(tmp_path)
    generated = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_practice",
        operation_id="generate-speaking-practice",
    )
    item = generated.items[0]

    assert item.choices == []
    assert item.prompt == item.answer == "school"

    passed = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer="school",
        operation_id="answer-speaking-pass",
    )
    missed = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer="teacher",
        operation_id="answer-speaking-miss",
    )

    assert passed.evaluation.correct is True
    assert passed.evaluation.feedback == "Great job!"
    assert missed.evaluation.correct is False
    assert missed.evaluation.feedback == "Try again."
    assert text_service.evaluate_calls == 0


@pytest.mark.asyncio
async def test_vocabulary_practice_accepts_punctuated_asr_transcript(
    tmp_path: Path,
) -> None:
    """ASR transcripts carry trailing punctuation ("School."); the local
    comparison must still accept the correct word."""

    service, progress_repository, text_service, session = make_service(tmp_path)
    generated = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_practice",
        operation_id="generate-speaking-punctuation",
    )
    item = generated.items[0]

    passed = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer="School.",
        operation_id="answer-speaking-punct-pass",
    )
    missed = await service.answer(
        session.session_id,
        generated.activity_id,
        item_id=item.activity_id,
        answer="schoolyard.",
        operation_id="answer-speaking-punct-miss",
    )

    assert passed.evaluation.correct is True
    assert passed.evaluation.feedback == "Great job!"
    assert missed.evaluation.correct is False
    assert text_service.evaluate_calls == 0


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
