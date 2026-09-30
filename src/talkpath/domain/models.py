"""Domain models and workflow state for TalkPath."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from talkpath.domain.errors import InvalidStateTransition, ScopeNotConfirmed


class DomainModel(BaseModel):
    """Shared validation defaults for data crossing TalkPath boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


_PROGRAM_SLUGS = {
    "國中": "junior-high",
    "國民中學": "junior-high",
    "junior high": "junior-high",
    "junior-high": "junior-high",
}
_SUBJECT_SLUGS = {
    "英文": "english",
    "英語": "english",
    "english": "english",
}
_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _slug(value: str, mapping: dict[str, str]) -> str:
    normalized = value.strip().lower()
    if normalized in mapping:
        return mapping[normalized]
    if any(not character.isascii() for character in normalized):
        return "-".join(
            character if character.isascii() and character.isalnum() else f"u{ord(character):x}"
            for character in normalized
        )
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return ascii_slug or "unknown"


def _number_from_label(value: str) -> int | None:
    return _parse_scope_number(value)


def _parse_scope_number(value: str) -> int | None:
    """Parse Arabic or compound Chinese numbers used by scope labels."""

    arabic_match = re.search(r"\d+", value)
    if arabic_match:
        return int(arabic_match.group())

    chinese_digits = "".join(character for character in value if character in _CHINESE_DIGITS)
    chinese_ten = chr(0x5341)
    if chinese_ten in chinese_digits:
        tens_part, ones_part = chinese_digits.split(chinese_ten, 1)
        tens = _CHINESE_DIGITS[tens_part[-1]] if tens_part else 1
        ones = _CHINESE_DIGITS[ones_part[0]] if ones_part else 0
        return tens * 10 + ones
    if chinese_digits:
        return _CHINESE_DIGITS[chinese_digits[0]]
    return None


def _grade_slug(grade: str) -> str:
    number = _parse_scope_number(grade)
    return f"grade-{number}" if number is not None else _slug(grade, {})


def _lesson_slug(lesson: str) -> str:
    number = _parse_scope_number(lesson)
    return f"lesson-{number:02d}" if number is not None else _slug(lesson, {})


class CourseScope(DomainModel):
    """The textbook location confirmed by the child before extraction."""

    model_config = ConfigDict(frozen=True)

    program: str
    grade: str
    subject: str
    textbook: str | None = None
    edition: str | None = None
    lesson: str
    pages: list[str] = Field(default_factory=list)
    lesson_id: str = ""

    @field_validator("program", "grade", "subject", "lesson")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scope values cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_lesson_id(self) -> CourseScope:
        base_lesson_id = "-".join(
            (
                _slug(self.program, _PROGRAM_SLUGS),
                _grade_slug(self.grade),
                _slug(self.subject, _SUBJECT_SLUGS),
                _lesson_slug(self.lesson),
            )
        )
        textbook = (self.textbook or "").strip()
        derived_lesson_id = (
            f"{base_lesson_id}--{_slug(textbook, {})}" if textbook else base_lesson_id
        )
        # Lessons saved before the textbook joined the identity keep the ID
        # without a suffix, so their files and progress records stay valid.
        accepted_ids = {derived_lesson_id, base_lesson_id}
        if self.lesson_id and self.lesson_id not in accepted_ids:
            raise ValueError("lesson_id must match the stable ID derived from the scope")
        if not self.lesson_id:
            object.__setattr__(self, "lesson_id", derived_lesson_id)
        return self


class ImageReference(DomainModel):
    image_id: str
    path: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    expires_at: datetime


ContentStatus = Literal["draft", "reviewed", "published"]


class ContentItem(DomainModel):
    """A piece of textbook information extracted from an image."""

    content_id: str
    type: str
    content: str | dict[str, Any]
    source_page: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: ContentStatus = "draft"


class LessonDraft(DomainModel):
    lesson_id: str
    scope: CourseScope
    title: str
    passage: str
    content_items: list[ContentItem] = Field(default_factory=list)
    source_images: list[str] = Field(default_factory=list)
    extraction_status: ContentStatus
    provider: str
    model: str
    operation_id: str

    @model_validator(mode="after")
    def validate_scope_identity(self) -> LessonDraft:
        if self.lesson_id != self.scope.lesson_id:
            raise ValueError("lesson_id must match scope.lesson_id")
        return self


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


class ActivityDraft(DomainModel):
    """A generated set of activities derived from lesson content."""

    activity_id: str
    lesson_id: str
    type: str
    title: str
    instructions: str
    items: list[Activity] = Field(default_factory=list)
    source_content_ids: list[str] = Field(default_factory=list)
    provider: str
    model: str
    operation_id: str


class TranscriptSegment(DomainModel):
    text: str
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_time_order(self) -> TranscriptSegment:
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must be greater than or equal to start_seconds")
        return self


class Transcript(DomainModel):
    text: str
    language: str = "en"
    segments: list[TranscriptSegment] = Field(default_factory=list)
    provider: str = "unknown"
    model: str = "unknown"
    operation_id: str = ""


class AudioArtifact(DomainModel):
    audio_bytes: bytes
    mime_type: str = "audio/mpeg"
    provider: str = "unknown"
    model: str = "unknown"
    operation_id: str = ""


class AnswerEvaluation(DomainModel):
    correct: bool
    score: float = Field(ge=0.0, le=1.0)
    feedback: str
    expected_answer: str | None = None


class LearningAttempt(DomainModel):
    attempt_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    lesson_id: str
    activity_id: str
    answer: str | None = None
    correct: bool
    score: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewItem(DomainModel):
    session_id: str
    lesson_id: str
    activity_id: str
    mistake_count: int = Field(default=0, ge=0)
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionState(str, Enum):
    UPLOAD_IMAGE = "UPLOAD_IMAGE"
    CONFIRM_COURSE_SCOPE = "CONFIRM_COURSE_SCOPE"
    EXTRACTING = "EXTRACTING"
    PREVIEW_DRAFT = "PREVIEW_DRAFT"
    SAVE_LESSON = "SAVE_LESSON"
    ASK_GENERATE_ACTIVITY = "ASK_GENERATE_ACTIVITY"
    GENERATING_ACTIVITY = "GENERATING_ACTIVITY"
    READY_FOR_PRACTICE = "READY_FOR_PRACTICE"
    FAILED = "FAILED"
    RETRY = "RETRY"


_ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.UPLOAD_IMAGE: {
        SessionState.CONFIRM_COURSE_SCOPE,
        SessionState.ASK_GENERATE_ACTIVITY,
    },
    SessionState.CONFIRM_COURSE_SCOPE: {SessionState.EXTRACTING},
    SessionState.EXTRACTING: {SessionState.PREVIEW_DRAFT},
    SessionState.PREVIEW_DRAFT: {SessionState.SAVE_LESSON},
    SessionState.SAVE_LESSON: {SessionState.ASK_GENERATE_ACTIVITY},
    SessionState.ASK_GENERATE_ACTIVITY: {SessionState.GENERATING_ACTIVITY},
    SessionState.GENERATING_ACTIVITY: {SessionState.READY_FOR_PRACTICE},
    SessionState.READY_FOR_PRACTICE: {SessionState.GENERATING_ACTIVITY},
    SessionState.FAILED: {SessionState.RETRY},
    SessionState.RETRY: {SessionState.UPLOAD_IMAGE},
}

_SCOPE_REQUIRED_STATES = frozenset(
    {
        SessionState.EXTRACTING,
        SessionState.PREVIEW_DRAFT,
        SessionState.SAVE_LESSON,
        SessionState.ASK_GENERATE_ACTIVITY,
        SessionState.GENERATING_ACTIVITY,
        SessionState.READY_FOR_PRACTICE,
    }
)


class SessionStateMachine:
    """Small explicit state machine for textbook import and activity generation."""

    def __init__(
        self,
        state: SessionState = SessionState.UPLOAD_IMAGE,
        *,
        scope_confirmed: bool = False,
    ) -> None:
        self.state = state
        self.scope_confirmed = scope_confirmed

    def confirm_scope(self) -> None:
        if self.state is not SessionState.CONFIRM_COURSE_SCOPE:
            raise InvalidStateTransition(
                self.state,
                SessionState.CONFIRM_COURSE_SCOPE,
            )
        self.scope_confirmed = True

    def can_transition_to(self, target: SessionState) -> bool:
        if target is SessionState.FAILED:
            return True
        if (
            self.state is SessionState.CONFIRM_COURSE_SCOPE
            and target is SessionState.EXTRACTING
            and not self.scope_confirmed
        ):
            return False
        if (
            self.state is SessionState.UPLOAD_IMAGE
            and target is SessionState.ASK_GENERATE_ACTIVITY
            and not self.scope_confirmed
        ):
            return False
        return target in _ALLOWED_TRANSITIONS.get(self.state, set())

    def transition_to(self, target: SessionState) -> SessionState:
        if (
            self.state is SessionState.CONFIRM_COURSE_SCOPE
            and target is SessionState.EXTRACTING
            and not self.scope_confirmed
        ):
            raise ScopeNotConfirmed(self.state, target)
        if (
            self.state is SessionState.UPLOAD_IMAGE
            and target is SessionState.ASK_GENERATE_ACTIVITY
            and not self.scope_confirmed
        ):
            raise ScopeNotConfirmed(self.state, target)
        if not self.can_transition_to(target):
            raise InvalidStateTransition(self.state, target)
        self.state = target
        if target is SessionState.UPLOAD_IMAGE:
            self.scope_confirmed = False
        return self.state

    def transition(self, target: SessionState) -> SessionState:
        """Alias for callers that use the shorter state-machine vocabulary."""

        return self.transition_to(target)


# ``ProcessState`` is kept as a domain-language alias for application code.
ProcessState = SessionState


class Session(DomainModel):
    """The child learning session persisted by the progress repository."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    learner_key: str = "local-child"
    lesson_id: str | None = None
    state: SessionState = SessionState.UPLOAD_IMAGE
    scope_confirmed: bool = False
    source_images: list[ImageReference] = Field(default_factory=list)
    operation_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_scope_invariants(self) -> Session:
        if self.scope_confirmed and not self.lesson_id:
            raise ValueError("scope_confirmed sessions must have a lesson_id")
        if self.state in _SCOPE_REQUIRED_STATES and (
            not self.scope_confirmed or not self.lesson_id
        ):
            raise ValueError(
                "active session states require scope_confirmed=True and a lesson_id"
            )
        return self

    def confirm_scope(self, scope: CourseScope) -> Session:
        """Return a new session after confirming scope in the correct state."""

        machine = SessionStateMachine(
            self.state,
            scope_confirmed=self.scope_confirmed,
        )
        machine.confirm_scope()
        return self.model_copy(
            update={
                "lesson_id": scope.lesson_id,
                "scope_confirmed": True,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def transition_to(self, target: SessionState) -> Session:
        """Return a new session after a validated workflow transition."""

        machine = SessionStateMachine(
            self.state,
            scope_confirmed=self.scope_confirmed,
        )
        new_state = machine.transition_to(target)
        return self.model_copy(
            update={
                "state": new_state,
                "scope_confirmed": machine.scope_confirmed,
                "updated_at": datetime.now(timezone.utc),
            }
        )
