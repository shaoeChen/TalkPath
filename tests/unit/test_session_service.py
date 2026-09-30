from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService,
    FakeTextService,
    FakeTextToSpeechService,
    FakeVisionService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.application.session_service import (
    LessonNotFound,
    NotVocabularyContent,
    SessionService,
    UploadValidationError,
    VocabularyContentNotFound,
)
from talkpath.application.activity_service import ActivityOperationConflict
from talkpath.domain.errors import OperationFailed, RepositoryError
from talkpath.domain.models import (
    ContentItem,
    CourseScope,
    LessonDraft,
    SessionState,
)


class NoopPi:
    async def prompt(self, message: str, **kwargs: object) -> object:
        return object()


class PiSpy:
    def __init__(self) -> None:
        self.start_calls = 0
        self.prompt_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def prompt(self, message: str, **kwargs: object) -> object:
        self.prompt_calls += 1
        return object()


def make_service(
    tmp_path: Path,
    *,
    agent_backend: str = "direct",
    pi_client: object | None = None,
    vision_service: object | None = None,
) -> SessionService:
    return SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=vision_service or FakeVisionService(),
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=pi_client if pi_client is not None else NoopPi(),
        agent_backend=agent_backend,
        upload_root=tmp_path / "uploads",
    )


def seed_saved_lesson(
    service: SessionService,
    scope: CourseScope,
    *,
    operation_id: str = "seed-lesson-1",
) -> LessonDraft:
    """Persist a lesson directly through the repository for service tests."""

    draft = LessonDraft(
        lesson_id=scope.lesson_id,
        scope=scope,
        title="A Day at School",
        passage="I go to school every day.",
        content_items=[
            ContentItem(
                content_id="word-school",
                type="vocabulary",
                content={"word": "school", "meaning": "學校"},
                source_page="1",
            ),
        ],
        source_images=[],
        extraction_status="draft",
        provider="fake-vision",
        model="talkpath-fixture-vision-v1",
        operation_id=operation_id,
    )
    service.lesson_repository.save_lesson_draft(draft)
    return draft


class ExplodingVision(FakeVisionService):
    async def extract_lesson(self, *args: object, **kwargs: object):
        raise RuntimeError("secret-token full-provider-body")


def test_list_lessons_returns_repository_lessons(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)

    lessons = service.list_lessons()

    assert [lesson.lesson_id for lesson in lessons] == [scope.lesson_id]
    assert lessons[0].title == "A Day at School"


def test_answer_vocabulary_word_compares_transcript_and_records_attempt(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)
    session = service.create_session(lesson_id=scope.lesson_id)

    passed = service.answer_vocabulary_word(
        session_id=session.session_id,
        content_id="word-school",
        answer="school",
        operation_id="word-answer-pass",
    )
    missed = service.answer_vocabulary_word(
        session_id=session.session_id,
        content_id="word-school",
        answer="teacher",
        operation_id="word-answer-miss",
    )

    assert passed.evaluation.correct is True
    assert passed.evaluation.feedback == "Great job!"
    assert missed.evaluation.correct is False
    assert missed.evaluation.feedback == "Try again."
    assert passed.attempt.activity_id == f"{scope.lesson_id}-word-word-school"
    attempts = service.progress_repository.list_attempts(session.session_id)
    assert {attempt.correct for attempt in attempts} == {True, False}


def test_answer_vocabulary_word_accepts_punctuated_asr_transcript(
    tmp_path: Path,
) -> None:
    """ASR transcripts carry trailing punctuation ("School."); a correct
    pronunciation must not be judged wrong because of it."""

    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)
    session = service.create_session(lesson_id=scope.lesson_id)

    passed = service.answer_vocabulary_word(
        session_id=session.session_id,
        content_id="word-school",
        answer="School.",
        operation_id="word-answer-punct-pass",
    )
    padded = service.answer_vocabulary_word(
        session_id=session.session_id,
        content_id="word-school",
        answer="  school  ",
        operation_id="word-answer-padded-pass",
    )
    missed = service.answer_vocabulary_word(
        session_id=session.session_id,
        content_id="word-school",
        answer="schoolyard.",
        operation_id="word-answer-punct-miss",
    )

    assert passed.evaluation.correct is True
    assert passed.evaluation.feedback == "Great job!"
    assert padded.evaluation.correct is True
    assert missed.evaluation.correct is False


def test_answer_vocabulary_word_is_idempotent_by_operation_id(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)
    session = service.create_session(lesson_id=scope.lesson_id)

    first = service.answer_vocabulary_word(
        session_id=session.session_id,
        content_id="word-school",
        answer="school",
        operation_id="word-answer-idem",
    )
    second = service.answer_vocabulary_word(
        session_id=session.session_id,
        content_id="word-school",
        answer="school",
        operation_id="word-answer-idem",
    )

    assert second == first
    assert len(service.progress_repository.list_attempts(session.session_id)) == 1
    with pytest.raises(RepositoryError):
        service.answer_vocabulary_word(
            session_id=session.session_id,
            content_id="word-school",
            answer="teacher",
            operation_id="word-answer-idem",
        )


def test_answer_vocabulary_word_rejects_unknown_or_non_vocabulary_content(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)
    lesson = service.lesson_repository.get_lesson(scope.lesson_id)
    extended = lesson.model_copy(
        update={
            "content_items": [
                *lesson.content_items,
                ContentItem(
                    content_id="grammar-present",
                    type="grammar",
                    content={"name": "simple present"},
                ),
            ],
            "operation_id": "seed-lesson-extended",
        }
    )
    service.lesson_repository.save_lesson_draft(extended)
    session = service.create_session(lesson_id=scope.lesson_id)

    with pytest.raises(VocabularyContentNotFound):
        service.answer_vocabulary_word(
            session_id=session.session_id,
            content_id="missing",
            answer="x",
            operation_id="word-answer-missing",
        )
    with pytest.raises(NotVocabularyContent):
        service.answer_vocabulary_word(
            session_id=session.session_id,
            content_id="grammar-present",
            answer="x",
            operation_id="word-answer-grammar",
        )


def test_answer_vocabulary_word_requires_a_saved_lesson(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    session = service.create_session()

    with pytest.raises(LessonNotFound):
        service.answer_vocabulary_word(
            session_id=session.session_id,
            content_id="word-school",
            answer="school",
            operation_id="word-answer-no-lesson",
        )


def test_create_session_with_saved_lesson_reads_scope_and_starts_ready(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)

    session = service.create_session(lesson_id=scope.lesson_id)

    assert session.lesson_id == scope.lesson_id
    assert session.scope_confirmed is True
    assert session.state is SessionState.ASK_GENERATE_ACTIVITY
    snapshot = service.get_snapshot(session.session_id)
    assert snapshot.scope == scope


def test_create_session_with_unknown_lesson_raises_lesson_not_found(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    with pytest.raises(LessonNotFound, match="lesson not found"):
        service.create_session(lesson_id="junior-high-grade-7-english-lesson-99")


@pytest.mark.asyncio
async def test_saved_lesson_session_can_generate_activity_directly(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)
    session = service.create_session(lesson_id=scope.lesson_id)

    result = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_practice",
        operation_id="saved-activity-1",
    )

    assert result.session.state is SessionState.READY_FOR_PRACTICE
    assert result.activity.lesson_id == scope.lesson_id


@pytest.mark.asyncio
async def test_saved_lesson_session_can_generate_a_different_activity_type_after_ready(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)
    session = service.create_session(lesson_id=scope.lesson_id)

    first = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_practice",
        operation_id="saved-activity-1",
    )
    second = await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_quiz",
        operation_id="saved-activity-2",
    )

    assert first.session.state is SessionState.READY_FOR_PRACTICE
    assert second.session.state is SessionState.READY_FOR_PRACTICE
    assert second.activity.type == "vocabulary_quiz"
    assert second.activity.activity_id != first.activity.activity_id


@pytest.mark.asyncio
async def test_saved_lesson_session_rejects_regenerating_the_same_activity_type(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )
    seed_saved_lesson(service, scope)
    session = service.create_session(lesson_id=scope.lesson_id)

    await service.generate_activity(
        session.session_id,
        activity_type="vocabulary_practice",
        operation_id="saved-activity-1",
    )

    with pytest.raises(ActivityOperationConflict):
        await service.generate_activity(
            session.session_id,
            activity_type="vocabulary_practice",
            operation_id="saved-activity-3",
        )


def test_image_references_must_match_session_and_stay_inside_upload_root(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    session_id = service.create_session().session_id
    reference = service.upload_image(session_id, b"image", mime_type="image/png")

    assert service.validate_image_references(session_id, [reference]) == [reference]

    external = tmp_path / "outside.png"
    external.write_bytes(b"image")
    with pytest.raises(UploadValidationError, match="upload root"):
        service.validate_image_references(
            session_id,
            [reference.model_copy(update={"path": str(external)})],
        )


def test_image_references_must_be_unexpired_and_belong_to_that_session(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    first_session = service.create_session().session_id
    second_session = service.create_session().session_id
    first_image = service.upload_image(first_session, b"first", mime_type="image/png")
    second_image = service.upload_image(second_session, b"second", mime_type="image/png")

    with pytest.raises(UploadValidationError, match="does not belong"):
        service.validate_image_references(first_session, [second_image])

    with pytest.raises(UploadValidationError, match="expired"):
        service.validate_image_references(
            first_session,
            [
                first_image.model_copy(
                    update={
                        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)
                    }
                )
            ],
        )


def test_session_service_rejects_unsupported_agent_backend(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="agent_backend"):
        make_service(tmp_path, agent_backend="vision")


def test_session_service_requires_pi_client_only_for_pi_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pi_client"):
        SessionService(
            progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
            lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
            vision_service=FakeVisionService(),
            text_service=FakeTextService(),
            speech_to_text_service=FakeSpeechToTextService(),
            text_to_speech_service=FakeTextToSpeechService(),
            pi_client=None,
            agent_backend="pi",
            upload_root=tmp_path / "uploads",
        )


@pytest.mark.asyncio
async def test_import_lesson_uses_vision_directly_without_touching_pi(tmp_path: Path) -> None:
    pi = PiSpy()
    service = make_service(tmp_path, pi_client=pi)
    session_id = service.create_session().session_id
    service.upload_image(session_id, b"image", mime_type="image/png")
    service.confirm_scope(
        session_id,
        CourseScope(
            program="junior high",
            grade="7",
            subject="English",
            lesson="1",
        ),
    )

    result = await service.import_lesson(session_id, operation_id="direct-import-op")

    assert result.lesson.lesson_id == "junior-high-grade-7-english-lesson-01"
    assert result.lesson.operation_id == "direct-import-op"
    assert result.session.state.value == "ASK_GENERATE_ACTIVITY"
    assert pi.start_calls == 0
    assert pi.prompt_calls == 0


@pytest.mark.asyncio
async def test_import_logs_safe_failure_context_without_exception_message(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = make_service(tmp_path, vision_service=ExplodingVision())
    session_id = service.create_session().session_id
    service.upload_image(
        session_id,
        b"private-image-bytes",
        mime_type="image/png",
    )
    service.confirm_scope(
        session_id,
        CourseScope(
            program="junior high",
            grade="7",
            subject="English",
            lesson="1",
            pages=["private-prompt-payload"],
        ),
    )

    events = service.subscribe(session_id)

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        with pytest.raises(OperationFailed, match="^lesson import failed$"):
            await service.import_lesson(session_id, operation_id="safe-log-op")

    text = caplog.text
    assert "lesson_import_failed" in text
    assert session_id in text
    assert 'operation_id="safe-log-op"' in text
    assert 'agent_backend="direct"' in text
    assert 'stage="vision"' in text
    assert "elapsed_ms=" in text
    assert 'error_type="RuntimeError"' in text
    assert "session_service.py" in text
    assert "secret-token" not in text
    assert "full-provider-body" not in text
    assert "private-image-bytes" not in text
    assert "private-prompt-payload" not in text
    error_events = []
    while not events.empty():
        event = events.get_nowait()
        if event["type"] == "error":
            error_events.append(event)
    assert error_events == [
        {
            "type": "error",
            "session_id": session_id,
            "state": "FAILED",
            "message": "lesson import failed",
        }
    ]
    assert "secret-token" not in str(error_events)
    assert "full-provider-body" not in str(error_events)
    assert "private-image-bytes" not in str(error_events)
    assert "private-prompt-payload" not in str(error_events)


@pytest.mark.asyncio
async def test_import_sanitizes_untrusted_operation_id_in_failure_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = make_service(tmp_path, vision_service=ExplodingVision())
    session_id = service.create_session().session_id
    service.upload_image(session_id, b"image", mime_type="image/png")
    service.confirm_scope(
        session_id,
        CourseScope(
            program="junior high",
            grade="7",
            subject="English",
            lesson="1",
        ),
    )
    operation_id = 'safe-prefix stage=save error_type=Benign "quoted"\n' + ("x" * 220)

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        with pytest.raises(OperationFailed, match="^lesson import failed$"):
            await service.import_lesson(session_id, operation_id=operation_id)

    text = caplog.text
    assert 'operation_id="safe-prefix stage=save error_type=Benign \\"quoted\\"_' in text
    assert 'operation_id=safe-prefix stage=save error_type=Benign' not in text
    assert ' operation_id="safe-prefix stage=save error_type=Benign' in text
    assert "\nforged_field=owned" not in text
    assert operation_id not in text
    assert ("x" * 129) not in text
