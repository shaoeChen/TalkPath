from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from talkpath.domain.errors import InvalidStateTransition
from talkpath.domain.models import (
    Activity,
    ActivityDraft,
    ContentItem,
    CourseScope,
    ImageReference,
    LessonDraft,
    Session,
    SessionState,
    TranscriptSegment,
    Transcript,
)


def test_course_scope_generates_stable_lesson_id() -> None:
    scope = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )

    assert scope.lesson_id == "junior-high-grade-1-english-lesson-01"


def test_course_scope_without_textbook_keeps_the_legacy_lesson_id() -> None:
    for textbook in (None, "", "   "):
        scope = CourseScope(
            program="junior high",
            grade="7",
            subject="English",
            lesson="1",
            textbook=textbook,
        )

        assert scope.lesson_id == "junior-high-grade-7-english-lesson-01"


def test_course_scope_with_textbook_adds_a_textbook_suffix() -> None:
    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
        textbook="康軒",
    )

    assert scope.lesson_id == "junior-high-grade-7-english-lesson-01--u5eb7-u8ed2"


def test_different_textbooks_do_not_share_a_lesson_id() -> None:
    def scope(textbook: str | None) -> CourseScope:
        return CourseScope(
            program="junior high",
            grade="7",
            subject="English",
            lesson="1",
            textbook=textbook,
        )

    ids = {scope("康軒").lesson_id, scope("翰林").lesson_id, scope(None).lesson_id}

    assert len(ids) == 3
    assert scope("Kang Hsuan").lesson_id.endswith("--kang-hsuan")


def test_saved_scope_with_textbook_and_legacy_lesson_id_is_still_accepted() -> None:
    legacy_id = "junior-high-grade-7-english-lesson-01"

    scope = CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
        textbook="康軒",
        lesson_id=legacy_id,
    )

    assert scope.lesson_id == legacy_id


@pytest.mark.parametrize(
    ("lesson", "expected_suffix"),
    [
        ("第一課", "lesson-01"),
        ("十一課", "lesson-11"),
        ("第二十一課", "lesson-21"),
        ("第二十二課", "lesson-22"),
    ],
)
def test_chinese_lesson_number_is_parsed_as_a_compound_number(
    lesson: str,
    expected_suffix: str,
) -> None:
    scope = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson=lesson,
    )

    assert scope.lesson_id.endswith(expected_suffix)


def test_chinese_lesson_numbers_that_differ_do_not_collide() -> None:
    second = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第二課",
    )
    twenty_second = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第二十二課",
    )

    assert second.lesson_id != twenty_second.lesson_id


@pytest.mark.parametrize("field", ["grade", "lesson"])
def test_course_scope_rejects_missing_required_scope_part(field: str) -> None:
    values = {
        "program": "國中",
        "grade": "一年級",
        "subject": "英文",
        "lesson": "第一課",
    }
    values.pop(field)

    with pytest.raises(ValidationError):
        CourseScope(**values)


@pytest.mark.parametrize("field", ["grade", "lesson"])
def test_course_scope_rejects_blank_scope_part(field: str) -> None:
    values = {
        "program": "國中",
        "grade": "一年級",
        "subject": "英文",
        "lesson": "第一課",
    }
    values[field] = "  "

    with pytest.raises(ValidationError):
        CourseScope(**values)


def test_content_item_has_explicit_extraction_metadata() -> None:
    item = ContentItem(
        content_id="vocabulary-hello",
        type="vocabulary",
        content={"word": "hello", "meaning": "你好"},
        source_page="12",
        confidence=0.96,
        status="draft",
    )

    assert item.content_id == "vocabulary-hello"
    assert item.type == "vocabulary"
    assert item.source_page == "12"
    assert item.confidence == 0.96
    assert item.status == "draft"


def test_list_defaults_are_not_shared_between_models() -> None:
    first = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )
    second = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第二課",
    )

    first.pages.append("12")

    assert first.pages == ["12"]
    assert second.pages == []


def test_lesson_draft_and_activity_contracts_are_constructible() -> None:
    scope = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )
    item = ContentItem(
        content_id="sentence-1",
        type="sentence",
        content="Hello, Amy.",
    )
    draft = LessonDraft(
        lesson_id=scope.lesson_id,
        scope=scope,
        title="第一課",
        passage="Hello, Amy.",
        content_items=[item],
        source_images=["image-1"],
        extraction_status="draft",
        provider="fake-vision",
        model="fixture",
        operation_id="op-1",
    )
    activity = Activity(
        activity_id="activity-1",
        lesson_id=scope.lesson_id,
        type="vocabulary_quiz",
        prompt="What does hello mean?",
        choices=["你好", "再見"],
    )
    activity_draft = ActivityDraft(
        activity_id="activity-set-1",
        lesson_id=scope.lesson_id,
        type="vocabulary_quiz",
        title="單字小測驗",
        instructions="Choose the best answer.",
        items=[activity],
        source_content_ids=[item.content_id],
        provider="fake-text",
        model="fixture",
        operation_id="op-2",
    )

    assert draft.content_items[0].content_id == item.content_id
    assert activity_draft.items[0].activity_id == activity.activity_id


def test_image_reference_and_transcript_preserve_provider_metadata() -> None:
    expires_at = datetime(2026, 8, 11, tzinfo=timezone.utc)
    image = ImageReference(
        image_id="image-1",
        path="uploads/image-1.jpg",
        mime_type="image/jpeg",
        size_bytes=1024,
        expires_at=expires_at,
    )
    transcript = Transcript(
        text="Hello.",
        language="en-US",
        provider="local-whisper",
        model="base",
        operation_id="op-3",
    )

    assert image.expires_at == expires_at
    assert transcript.text == "Hello."
    assert transcript.provider == "local-whisper"


def test_course_scope_rejects_a_caller_supplied_mismatched_lesson_id() -> None:
    with pytest.raises(ValidationError):
        CourseScope(
            program="國中",
            grade="一年級",
            subject="英文",
            lesson="第一課",
            lesson_id="not-the-derived-id",
        )


def test_course_scope_is_immutable_after_its_id_is_derived() -> None:
    scope = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )
    lesson_id = scope.lesson_id

    with pytest.raises(ValidationError):
        scope.grade = "二年級"

    assert scope.lesson_id == lesson_id


@pytest.mark.parametrize(
    ("program", "subject"),
    [("自訂課程甲", "英文"), ("自訂課程乙", "英文"), ("國中", "自訂科目甲"), ("國中", "自訂科目乙")],
)
def test_unknown_chinese_scope_parts_have_safe_deterministic_slugs(
    program: str,
    subject: str,
) -> None:
    scope = CourseScope(
        program=program,
        grade="一年級",
        subject=subject,
        lesson="第一課",
    )

    assert all(character.isascii() and (character.isalnum() or character == "-") for character in scope.lesson_id)


def test_unknown_chinese_scope_parts_do_not_collide() -> None:
    first = CourseScope(
        program="自訂課程甲",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )
    second = CourseScope(
        program="自訂課程乙",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )

    assert first.lesson_id != second.lesson_id


def test_lesson_draft_must_use_scope_lesson_id() -> None:
    scope = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )

    with pytest.raises(ValidationError):
        LessonDraft(
            lesson_id="different-lesson",
            scope=scope,
            title="第一課",
            passage="Hello, Amy.",
            extraction_status="draft",
            provider="fake-vision",
            model="fixture",
            operation_id="op-1",
        )


def test_transcript_segment_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(text="Hello", start_seconds=2.0, end_seconds=1.0)


def test_session_state_is_immutable_and_updates_only_through_transition() -> None:
    session = Session(state=SessionState.CONFIRM_COURSE_SCOPE)

    with pytest.raises(ValidationError):
        session.state = SessionState.FAILED

    updated = session.transition_to(SessionState.FAILED)

    assert session.state is SessionState.CONFIRM_COURSE_SCOPE
    assert updated.state is SessionState.FAILED


def test_session_confirm_scope_requires_confirm_course_scope_state() -> None:
    scope = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )
    session = Session()

    with pytest.raises(InvalidStateTransition):
        session.confirm_scope(scope)


def test_session_confirm_scope_returns_a_new_confirmed_session() -> None:
    scope = CourseScope(
        program="國中",
        grade="一年級",
        subject="英文",
        lesson="第一課",
    )
    session = Session(state=SessionState.CONFIRM_COURSE_SCOPE)

    confirmed = session.confirm_scope(scope)

    assert session.scope_confirmed is False
    assert confirmed.scope_confirmed is True
    assert confirmed.lesson_id == scope.lesson_id


@pytest.mark.parametrize(
    "state",
    [
        SessionState.EXTRACTING,
        SessionState.PREVIEW_DRAFT,
        SessionState.SAVE_LESSON,
        SessionState.ASK_GENERATE_ACTIVITY,
        SessionState.GENERATING_ACTIVITY,
        SessionState.READY_FOR_PRACTICE,
    ],
)
def test_active_session_states_require_confirmed_scope_and_lesson_id(
    state: SessionState,
) -> None:
    with pytest.raises(ValidationError):
        Session(state=state)

    with pytest.raises(ValidationError):
        Session(state=state, lesson_id="lesson-1", scope_confirmed=False)


def test_scope_confirmation_requires_a_lesson_id() -> None:
    with pytest.raises(ValidationError):
        Session(scope_confirmed=True)


def test_active_session_with_confirmed_scope_is_valid() -> None:
    session = Session(
        state=SessionState.EXTRACTING,
        lesson_id="junior-high-grade-1-english-lesson-01",
        scope_confirmed=True,
    )

    assert session.scope_confirmed is True


@pytest.mark.parametrize("state", [SessionState.FAILED, SessionState.RETRY])
def test_failure_states_may_remain_unbound_to_a_lesson(state: SessionState) -> None:
    session = Session(state=state)

    assert session.lesson_id is None
    assert session.scope_confirmed is False


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
