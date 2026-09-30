"""Application orchestration for the first TalkPath learning flow."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import tempfile
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from talkpath.domain.errors import (
    DomainError,
    InvalidStateTransition,
    ProviderResponseInvalid,
    OperationFailed,
    RepositoryError,
    ScopeNotConfirmed,
    UnsupportedOperation,
)
from talkpath.application.activity_service import (
    ActivityOperationConflict,
    ActivityService,
    normalize_spoken_answer,
)
from talkpath.application.safe_observability import log_operation_failure
from talkpath.domain.lesson_merge import (
    ImportBatch,
    initial_batch,
    merge_lesson,
    overlapping_pages,
)
from talkpath.domain.models import (
    Activity,
    ActivityDraft,
    AnswerEvaluation,
    AudioArtifact,
    ContentItem,
    CourseScope,
    ImageReference,
    LessonDraft,
    LearningAttempt,
    Session,
    SessionState,
    Transcript,
)
from talkpath.ports.lesson_repository import LessonRepository
from talkpath.ports.model_services import (
    SpeechToTextService,
    TextService,
    TextToSpeechService,
    VisionService,
)
from talkpath.ports.progress_repository import ProgressRepository



class SessionServiceError(DomainError):
    """Base class for expected application service failures."""


class SessionNotFound(SessionServiceError):
    """Raised when a public operation references an unknown session."""


class LessonNotFound(SessionServiceError):
    """Raised when a public operation references an unknown lesson."""


class VocabularyContentNotFound(SessionServiceError):
    """Raised when a vocabulary answer references an unknown content item."""


class NotVocabularyContent(SessionServiceError):
    """Raised when a vocabulary answer targets a non-vocabulary item."""


class UploadValidationError(SessionServiceError):
    """Raised when an uploaded textbook image is not safe or supported."""


class OperationConflict(SessionServiceError):
    """Raised when an operation ID is reused for a different request."""


class PiBoundary(Protocol):
    async def prompt(self, message: str, **kwargs: Any) -> Any:
        """Run one Pi prompt."""


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session: Session
    scope: CourseScope | None = None


@dataclass(frozen=True, slots=True)
class ImportResult:
    session: Session
    lesson: LessonDraft
    skipped_duplicates: int = 0


@dataclass(frozen=True, slots=True)
class ImportCheck:
    """What importing into a scope would do to a lesson that may already exist."""

    lesson_id: str
    exists: bool
    title: str | None
    existing_pages: list[str]
    overlapping_pages: list[str]
    content_item_count: int


@dataclass(frozen=True, slots=True)
class ActivityResult:
    session: Session
    activity: ActivityDraft


@dataclass(frozen=True, slots=True)
class VocabularyAnswerResult:
    content_id: str
    evaluation: AnswerEvaluation
    attempt: LearningAttempt


_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _vocabulary_word(item: ContentItem) -> str:
    """Return the English word from either provider content shape."""

    content = item.content
    if not isinstance(content, dict):
        return ""
    value = content.get("english") or content.get("word") or ""
    return str(value).strip()


class SessionService:
    """Coordinate repositories, model services and the Pi boundary.

    The service is deliberately provider-agnostic.  Routes receive this
    object through ``app.state`` and never construct a model client directly.
    Scope details are retained in memory for this first vertical slice; the
    stable lesson ID remains persisted in SQLite and the full scope is saved
    in the LessonLens lesson document during import.
    """

    def __init__(
        self,
        *,
        progress_repository: ProgressRepository,
        lesson_repository: LessonRepository,
        vision_service: VisionService,
        text_service: TextService,
        speech_to_text_service: SpeechToTextService,
        text_to_speech_service: TextToSpeechService,
        pi_client: PiBoundary | None = None,
        agent_backend: str = "direct",
        upload_root: str | Path,
        max_upload_bytes: int = 10 * 1024 * 1024,
        upload_expiry_seconds: int = 60 * 60,
        activity_service: ActivityService | None = None,
    ) -> None:
        if max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        if upload_expiry_seconds <= 0:
            raise ValueError("upload_expiry_seconds must be positive")
        normalized_agent_backend = agent_backend.strip().lower()
        if normalized_agent_backend not in {"direct", "pi"}:
            raise ValueError("agent_backend must be 'direct' or 'pi'")
        if normalized_agent_backend == "pi" and pi_client is None:
            raise ValueError("pi_client is required when agent_backend='pi'")
        self.progress_repository = progress_repository
        self.lesson_repository = lesson_repository
        self.vision_service = vision_service
        self.text_service = text_service
        self.speech_to_text_service = speech_to_text_service
        self.text_to_speech_service = text_to_speech_service
        self.pi_client = pi_client
        self.agent_backend = normalized_agent_backend
        self.upload_root = Path(upload_root).expanduser().resolve()
        self.max_upload_bytes = max_upload_bytes
        self.upload_expiry_seconds = upload_expiry_seconds
        self._scopes: dict[str, CourseScope] = {}
        self._imports: dict[tuple[str, str], ImportResult] = {}
        self._activities: dict[tuple[str, str], ActivityResult] = {}
        self.activity_service = activity_service or ActivityService(
            progress_repository=progress_repository,
            lesson_repository=lesson_repository,
            text_service=text_service,
            agent_backend=self.agent_backend,
        )
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._operation_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Close an injected Pi/provider boundary when it owns resources."""

        if self.pi_client is not None:
            close = getattr(self.pi_client, "close", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    await result

        for provider in (
            self.vision_service,
            self.text_service,
            self.speech_to_text_service,
            self.text_to_speech_service,
        ):
            close_provider = getattr(provider, "aclose", None)
            if close_provider is not None:
                result = close_provider()
                if inspect.isawaitable(result):
                    await result

    def create_session(
        self,
        *,
        learner_key: str = "local-child",
        operation_id: str | None = None,
        lesson_id: str | None = None,
    ) -> Session:
        saved_lesson = None
        if lesson_id is not None:
            saved_lesson = self.lesson_repository.get_lesson(lesson_id)
            if saved_lesson is None:
                raise LessonNotFound(f"lesson not found: {lesson_id}")
        session = self.progress_repository.create_session(
            learner_key=learner_key,
            lesson_id=lesson_id,
            operation_id=operation_id,
        )
        if saved_lesson is not None:
            self._scopes[session.session_id] = saved_lesson.scope
            if session.state is not SessionState.ASK_GENERATE_ACTIVITY:
                session = self._transition_and_save(
                    session,
                    SessionState.ASK_GENERATE_ACTIVITY,
                    "saved_lesson_opened",
                )
        self._publish(session, "session_created")
        return session

    def get_session(self, session_id: str) -> Session:
        session = self.progress_repository.get_session(session_id)
        if session is None:
            raise SessionNotFound(f"learning session not found: {session_id}")
        return session

    def get_snapshot(self, session_id: str) -> SessionSnapshot:
        session = self.get_session(session_id)
        return SessionSnapshot(session=session, scope=self._scopes.get(session_id))

    def upload_image(
        self,
        session_id: str,
        content: bytes,
        *,
        mime_type: str | None,
        original_filename: str | None = None,
    ) -> ImageReference:
        session = self.get_session(session_id)
        normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
        suffix = _IMAGE_TYPES.get(normalized_mime)
        if suffix is None:
            raise UploadValidationError("only JPEG, PNG, WEBP and GIF images are supported")
        if not content:
            raise UploadValidationError("uploaded image is empty")
        if len(content) > self.max_upload_bytes:
            raise UploadValidationError("uploaded image is too large")
        if session.state not in {
            SessionState.UPLOAD_IMAGE,
            SessionState.CONFIRM_COURSE_SCOPE,
        }:
            raise InvalidStateTransition(session.state, SessionState.UPLOAD_IMAGE)

        image_id = f"image-{uuid4().hex}"
        session_dir = self._safe_upload_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        image_path = session_dir / f"{image_id}{suffix}"
        self._write_upload(image_path, content)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self.upload_expiry_seconds
        )
        reference = ImageReference(
            image_id=image_id,
            path=str(image_path),
            mime_type=normalized_mime,
            size_bytes=len(content),
            expires_at=expires_at,
        )
        approve = getattr(self.lesson_repository, "approve_source_image", None)
        if approve is not None:
            approve(reference)

        updated = session
        if session.state is SessionState.UPLOAD_IMAGE:
            updated = session.transition_to(SessionState.CONFIRM_COURSE_SCOPE)
        updated = self._validated_session_update(
            updated,
            source_images=[*updated.source_images, reference],
        )
        self.progress_repository.save_session(updated)
        self._publish(updated, "image_uploaded", image_id=image_id)
        return reference

    def confirm_scope(self, session_id: str, scope: CourseScope) -> Session:
        session = self.get_session(session_id)
        updated = session.confirm_scope(scope)
        updated = self._validated_session_update(updated)
        self._scopes[session_id] = scope
        self.progress_repository.save_session(updated)
        self._publish(updated, "scope_confirmed", scope=scope.model_dump(mode="json"))
        return updated

    async def import_lesson(self, session_id: str, *, operation_id: str) -> ImportResult:
        started_at = time.perf_counter()
        stage = "validation"
        if not operation_id.strip():
            raise OperationConflict("operation_id cannot be blank")
        key = (session_id, operation_id)
        async with self._operation_lock:
            existing = self._imports.get(key)
            if existing is not None:
                return existing

            session = self.get_session(session_id)
            scope = self._scopes.get(session_id)
            if not session.scope_confirmed or scope is None:
                raise ScopeNotConfirmed(session.state, SessionState.EXTRACTING)
            if not session.source_images:
                raise UploadValidationError("at least one textbook image is required")
            if session.state is not SessionState.CONFIRM_COURSE_SCOPE:
                lesson = self.lesson_repository.get_lesson(scope.lesson_id)
                if lesson is not None and session.state in {
                    SessionState.ASK_GENERATE_ACTIVITY,
                    SessionState.READY_FOR_PRACTICE,
                }:
                    result = ImportResult(session=session, lesson=lesson)
                    self._imports[key] = result
                    return result
                raise InvalidStateTransition(session.state, SessionState.EXTRACTING)

            try:
                trusted_images = self.validate_image_references(
                    session_id, session.source_images
                )
                session = self._transition_and_save(session, SessionState.EXTRACTING, "extracting")
                if self.agent_backend == "direct":
                    stage = "vision"
                    draft = await self.vision_service.extract_lesson(
                        trusted_images,
                        scope,
                        operation_id=operation_id,
                    )
                else:
                    stage = "pi"
                    draft = await self._extract_lesson_via_pi(
                        session_id=session_id,
                        session=session,
                        scope=scope,
                        trusted_images=trusted_images,
                        operation_id=operation_id,
                    )
                stage = "identity"
                self._validate_draft_identity(draft, scope, operation_id)
                session = self._transition_and_save(
                    session, SessionState.PREVIEW_DRAFT, "draft_ready"
                )
                session = self._transition_and_save(
                    session, SessionState.SAVE_LESSON, "saving_lesson"
                )
                stage = "save"
                saved = self._save_lesson_draft(
                    draft, trusted_images, session_id=session_id
                )
                session = self._transition_and_save(
                    session,
                    SessionState.ASK_GENERATE_ACTIVITY,
                    "ready_to_generate_activity",
                )
                result = ImportResult(
                    session=session,
                    lesson=saved,
                    skipped_duplicates=self._skipped_duplicates(saved, operation_id),
                )
                self._imports[key] = result
                return result
            except Exception as exc:
                log_operation_failure(
                    event="lesson_import_failed",
                    session_id=session_id,
                    operation_id=operation_id,
                    agent_backend=self.agent_backend,
                    stage=stage,
                    started_at=started_at,
                    error=exc,
                )
                self._mark_failed(session_id, "lesson import failed")
                if isinstance(exc, DomainError):
                    raise
                raise OperationFailed("lesson import failed") from exc

    async def generate_activity(
        self,
        session_id: str,
        *,
        activity_type: str,
        operation_id: str,
    ) -> ActivityResult:
        if not operation_id.strip():
            raise OperationConflict("operation_id cannot be blank")
        key = (session_id, operation_id)
        async with self._operation_lock:
            existing = self._activities.get(key)
            if existing is not None:
                if existing.activity.type != activity_type.strip().lower():
                    raise OperationConflict(
                        "operation_id was already used for a different activity type"
                    )
                return existing
            session = self.get_session(session_id)
            normalized_type = activity_type.strip().lower()
            if session.state is SessionState.READY_FOR_PRACTICE:
                if normalized_type in self.activity_service.generated_activity_types(
                    session_id
                ):
                    raise ActivityOperationConflict(
                        f"activity type already generated for this session: {normalized_type}"
                    )
            elif session.state is not SessionState.ASK_GENERATE_ACTIVITY:
                raise InvalidStateTransition(
                    session.state, SessionState.GENERATING_ACTIVITY
                )
            if not session.lesson_id:
                raise ScopeNotConfirmed(session.state, SessionState.GENERATING_ACTIVITY)
            lesson = self.lesson_repository.get_lesson(session.lesson_id)
            if lesson is None:
                raise LessonNotFound(f"lesson not found: {session.lesson_id}")
            started_at = time.perf_counter()
            stage = "transition"
            try:
                session = self._transition_and_save(
                    session, SessionState.GENERATING_ACTIVITY, "generating_activity"
                )
                stage = "text"
                activity = await self.activity_service.generate_activity(
                    session_id,
                    activity_type=activity_type,
                    operation_id=operation_id,
                )
                session = self._transition_and_save(
                    session, SessionState.READY_FOR_PRACTICE, "ready_for_practice"
                )
                result = ActivityResult(session=session, activity=activity)
                self._activities[key] = result
                return result
            except Exception as exc:
                log_operation_failure(
                    event="activity_generation_failed",
                    session_id=session_id,
                    operation_id=operation_id,
                    agent_backend=self.agent_backend,
                    stage=stage,
                    started_at=started_at,
                    error=exc,
                )
                self._mark_failed(session_id, "activity generation failed")
                if isinstance(exc, DomainError):
                    raise
                raise RepositoryError("activity generation failed") from exc

    def get_lesson(self, lesson_id: str) -> LessonDraft:
        lesson = self.lesson_repository.get_lesson(lesson_id)
        if lesson is None:
            raise LessonNotFound(f"lesson not found: {lesson_id}")
        return lesson

    def list_lessons(self) -> list[LessonDraft]:
        """List every lesson saved in LessonLens, ordered by stable ID."""

        return self.lesson_repository.list_lessons()

    def check_import(self, scope: CourseScope) -> ImportCheck:
        """Report whether importing into ``scope`` would append to a saved lesson."""

        existing = self.lesson_repository.get_lesson(scope.lesson_id)
        if existing is None:
            return ImportCheck(
                lesson_id=scope.lesson_id,
                exists=False,
                title=None,
                existing_pages=[],
                overlapping_pages=[],
                content_item_count=0,
            )
        return ImportCheck(
            lesson_id=scope.lesson_id,
            exists=True,
            title=existing.title,
            existing_pages=list(existing.scope.pages),
            overlapping_pages=overlapping_pages(existing.scope.pages, scope.pages),
            content_item_count=len(existing.content_items),
        )

    def get_import_batches(self, lesson_id: str) -> list[ImportBatch]:
        self.get_lesson(lesson_id)
        return self.lesson_repository.get_import_batches(lesson_id)

    def lesson_image_path(self, lesson_id: str, image_id: str) -> Path:
        path = self.lesson_repository.source_image_path(lesson_id, image_id)
        if path is None:
            raise LessonNotFound(f"lesson image not found: {lesson_id}/{image_id}")
        return path

    def validate_image_references(
        self,
        session_id: str,
        images: list[ImageReference],
    ) -> list[ImageReference]:
        """Return trusted session-owned image references or reject the request.

        Internal Pi tools receive image metadata over HTTP, so the request is
        never allowed to introduce a new path or file identity.  The accepted
        references must be the exact set recorded for this session, still be
        unexpired, and resolve to regular files below its upload directory.
        """

        session = self.get_session(session_id)
        expected_by_id = {image.image_id: image for image in session.source_images}
        if not images or len(images) != len(expected_by_id):
            raise UploadValidationError("image references do not match session uploads")
        if len({image.image_id for image in images}) != len(images):
            raise UploadValidationError("duplicate image reference")

        trusted: list[ImageReference] = []
        for image in images:
            expected = expected_by_id.get(image.image_id)
            if expected is None:
                raise UploadValidationError(
                    f"image reference does not belong to session: {image.image_id}"
                )
            if (
                _as_utc(image.expires_at) <= datetime.now(timezone.utc)
                or _as_utc(expected.expires_at) <= datetime.now(timezone.utc)
            ):
                raise UploadValidationError(f"image reference is expired: {image.image_id}")
            if (
                image.mime_type != expected.mime_type
                or image.size_bytes != expected.size_bytes
                or _as_utc(image.expires_at) != _as_utc(expected.expires_at)
            ):
                raise UploadValidationError(
                    f"image reference does not match session upload: {image.image_id}"
                )
            expected_path = self._owned_image_path(session_id, expected.path)
            incoming_path = self._owned_image_path(session_id, image.path)
            if incoming_path != expected_path:
                raise UploadValidationError(
                    f"image reference path does not match session upload: {image.image_id}"
                )
            try:
                if incoming_path.stat().st_size != expected.size_bytes:
                    raise UploadValidationError(
                        f"image file size does not match metadata: {image.image_id}"
                    )
            except OSError as exc:
                raise UploadValidationError(
                    f"image file is unavailable: {image.image_id}"
                ) from exc
            trusted.append(expected)
        return trusted

    async def extract_lesson(
        self,
        *,
        session_id: str,
        images: list[ImageReference],
        scope: CourseScope,
        operation_id: str,
    ) -> LessonDraft:
        trusted_images = self.validate_image_references(session_id, images)
        draft = await self.vision_service.extract_lesson(
            trusted_images, scope, operation_id=operation_id
        )
        self._validate_draft_identity(draft, scope, operation_id)
        return draft

    def save_lesson_draft(
        self,
        draft: LessonDraft,
        *,
        session_id: str,
        operation_id: str,
        scope: CourseScope | None = None,
        source_references: list[ImageReference] | None = None,
    ) -> None:
        if not operation_id.strip():
            raise OperationConflict("operation_id cannot be blank")
        if scope is not None and draft.scope != scope:
            raise ProviderResponseInvalid(
                "save lesson scope does not match the draft scope"
            )
        session = self.get_session(session_id)
        trusted_images = self.validate_image_references(
            session_id,
            source_references or session.source_images,
        )
        unknown_source_ids = set(draft.source_images) - {
            image.image_id for image in trusted_images
        }
        if unknown_source_ids:
            raise UploadValidationError("draft references an image outside the session")
        self._save_lesson_draft(draft, trusted_images, session_id=session_id)

    async def generate_activity_for_lesson(
        self,
        *,
        lesson: LessonDraft,
        activity_type: str,
        operation_id: str,
        scope: CourseScope | None = None,
    ) -> ActivityDraft:
        if scope is not None and lesson.scope != scope:
            raise ProviderResponseInvalid(
                "generate activity scope does not match the lesson scope"
            )
        started_at = time.perf_counter()
        try:
            activity = await self.text_service.generate_activity(
                lesson, activity_type, operation_id=operation_id
            )
        except Exception as exc:
            log_operation_failure(
                event="internal_activity_text_generation_failed",
                session_id=lesson.lesson_id,
                operation_id=operation_id,
                agent_backend=self.agent_backend,
                stage="text_generate_activity",
                started_at=started_at,
                error=exc,
            )
            if isinstance(exc, DomainError):
                raise
            raise OperationFailed(
                "text provider failed during activity generation"
            ) from exc
        if activity.lesson_id != lesson.lesson_id or activity.operation_id != operation_id:
            raise ProviderResponseInvalid(
                "generated activity identity does not match the request"
            )
        return activity

    async def evaluate_answer(
        self,
        *,
        activity: Activity,
        answer: str,
        operation_id: str,
    ) -> AnswerEvaluation:
        started_at = time.perf_counter()
        try:
            return await self.text_service.evaluate_answer(
                activity, answer, operation_id=operation_id
            )
        except Exception as exc:
            log_operation_failure(
                event="internal_answer_text_evaluation_failed",
                session_id=activity.lesson_id,
                operation_id=operation_id,
                agent_backend=self.agent_backend,
                stage="text_evaluate_answer",
                started_at=started_at,
                error=exc,
            )
            if isinstance(exc, DomainError):
                raise
            raise OperationFailed(
                "text provider failed during answer evaluation"
            ) from exc

    async def transcribe_audio(
        self,
        *,
        audio: bytes,
        mime_type: str,
        operation_id: str,
        session_id: str | None = None,
    ) -> Transcript:
        started_at = time.perf_counter()
        context_id = session_id or "internal"
        try:
            return await self.speech_to_text_service.transcribe(
                audio, mime_type=mime_type, operation_id=operation_id
            )
        except Exception as exc:
            log_operation_failure(
                event="speech_transcription_failed",
                session_id=context_id,
                operation_id=operation_id,
                agent_backend=self.agent_backend,
                stage="speech_to_text",
                started_at=started_at,
                error=exc,
            )
            if isinstance(exc, DomainError):
                raise
            raise OperationFailed("speech to text provider failed") from exc

    async def synthesize_speech(
        self,
        *,
        text: str,
        voice: str | None,
        operation_id: str,
        session_id: str | None = None,
    ) -> AudioArtifact:
        started_at = time.perf_counter()
        context_id = session_id or "internal"
        try:
            return await self.text_to_speech_service.synthesize(
                text, voice=voice, operation_id=operation_id
            )
        except Exception as exc:
            log_operation_failure(
                event="speech_synthesis_failed",
                session_id=context_id,
                operation_id=operation_id,
                agent_backend=self.agent_backend,
                stage="text_to_speech",
                started_at=started_at,
                error=exc,
            )
            if isinstance(exc, DomainError):
                raise
            raise OperationFailed("text to speech provider failed") from exc

    def answer_vocabulary_word(
        self,
        *,
        session_id: str,
        content_id: str,
        answer: str,
        operation_id: str,
    ) -> VocabularyAnswerResult:
        """Judge one spoken vocabulary transcript with a local word compare."""

        session = self.get_session(session_id)
        if not session.lesson_id:
            raise LessonNotFound(f"lesson not found for session: {session_id}")
        lesson = self.lesson_repository.get_lesson(session.lesson_id)
        if lesson is None:
            raise LessonNotFound(f"lesson not found: {session.lesson_id}")
        content_item = next(
            (item for item in lesson.content_items if item.content_id == content_id),
            None,
        )
        if content_item is None:
            raise VocabularyContentNotFound(
                f"vocabulary content not found: {content_id}"
            )
        if content_item.type != "vocabulary":
            raise NotVocabularyContent(
                f"content item is not vocabulary: {content_id}"
            )
        word = _vocabulary_word(content_item)
        if not word:
            raise NotVocabularyContent(f"vocabulary item has no word: {content_id}")
        passed = normalize_spoken_answer(answer) == normalize_spoken_answer(word)
        evaluation = AnswerEvaluation(
            correct=passed,
            score=1.0 if passed else 0.0,
            feedback="Great job!" if passed else "Try again.",
            expected_answer=word,
        )
        activity_id = f"{lesson.lesson_id}-word-{content_id}"
        attempt = self.save_learning_result(
            session_id=session_id,
            activity_id=activity_id,
            operation_id=operation_id,
            correct=passed,
            score=evaluation.score,
            answer=answer,
            lesson_id=lesson.lesson_id,
            feedback=evaluation.feedback,
        )
        return VocabularyAnswerResult(
            content_id=content_id,
            evaluation=evaluation,
            attempt=attempt,
        )

    def save_learning_result(
        self,
        *,
        session_id: str,
        activity_id: str,
        operation_id: str,
        correct: bool,
        score: float,
        answer: str | None,
        lesson_id: str | None,
        feedback: str | None,
    ) -> LearningAttempt:
        self.get_session(session_id)
        method = self.progress_repository.record_attempt
        kwargs: dict[str, Any] = {
            "correct": correct,
            "score": score,
            "answer": answer,
            "lesson_id": lesson_id,
        }
        supported = inspect.signature(method).parameters
        if "operation_id" in supported:
            kwargs["operation_id"] = operation_id
        if "feedback" in supported:
            kwargs["feedback"] = feedback
        attempt = method(session_id, activity_id, **kwargs)
        session = self.get_session(session_id)
        self._publish(session, "learning_result_saved", activity_id=activity_id)
        return attempt

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[session_id].add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(session_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(session_id, None)

    async def events(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        queue = self.subscribe(session_id)
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(session_id, queue)

    def _publish(self, session: Session, event_type: str, **payload: Any) -> None:
        event = {
            "type": event_type,
            "session_id": session.session_id,
            "state": session.state.value,
            **payload,
        }
        for queue in tuple(self._subscribers.get(session.session_id, ())):
            queue.put_nowait(event)

    def _publish_agent_events(self, session: Session, result: Any) -> None:
        events: Any = getattr(result, "events", None)
        if events is None and isinstance(result, Mapping):
            events = result.get("events")
        if not events:
            return
        for agent_event in events:
            event_type = getattr(agent_event, "type", None)
            payload = getattr(agent_event, "payload", None)
            if isinstance(agent_event, Mapping):
                event_type = agent_event.get("type", event_type)
                payload = agent_event.get("payload", agent_event)
            if not isinstance(event_type, str) or not event_type:
                event_type = "unknown"
            if not isinstance(payload, Mapping):
                payload = {"value": payload}
            self._publish(
                session,
                "agent_event",
                agent_event_type=event_type,
                payload=_json_safe(dict(payload)),
            )

    def _transition_and_save(
        self,
        session: Session,
        target: SessionState,
        event_type: str,
    ) -> Session:
        updated = session.transition_to(target)
        self.progress_repository.save_session(updated)
        self._publish(updated, event_type)
        return updated

    def _mark_failed(self, session_id: str, public_message: str) -> None:
        try:
            session = self.get_session(session_id)
            failed = self._validated_session_update(
                session,
                state=SessionState.FAILED,
                updated_at=datetime.now(timezone.utc),
            )
            self.progress_repository.save_session(failed)
            self._publish(failed, "error", message=public_message)
        except Exception:
            # Keep the original operation error as the public failure.
            return

    async def _start_pi_if_needed(self) -> None:
        if self.pi_client is None:
            return
        start = getattr(self.pi_client, "start", None)
        if start is None:
            return
        running = getattr(self.pi_client, "is_running", True)
        if not running:
            result = start()
            if inspect.isawaitable(result):
                await result

    async def _extract_lesson_via_pi(
        self,
        *,
        session_id: str,
        session: Session,
        scope: CourseScope,
        trusted_images: list[ImageReference],
        operation_id: str,
    ) -> LessonDraft:
        await self._start_pi_if_needed()
        if self.pi_client is None:
            raise RepositoryError("pi backend is unavailable")
        pi_result = await self.pi_client.prompt(
            self._import_prompt(scope, trusted_images),
            operation_id=operation_id,
            write_type=True,
            write_tool="extract_lesson",
            write_payload={
                "session_id": session_id,
                "operation_id": operation_id,
                "scope": scope.model_dump(mode="json"),
                "images": [image.model_dump(mode="json") for image in trusted_images],
            },
        )
        self._publish_agent_events(session, pi_result)
        draft = self._draft_from_pi_result(pi_result)
        if draft is not None:
            return draft
        return await self.vision_service.extract_lesson(
            trusted_images,
            scope,
            operation_id=operation_id,
        )

    def _save_lesson_draft(
        self,
        draft: LessonDraft,
        source_references: list[ImageReference],
        *,
        session_id: str | None = None,
    ) -> LessonDraft:
        """Save a fresh extraction, appending it when the lesson already exists.

        This is the only place imports are merged.  Extraction is untouched: a
        new import is a complete draft of its own that is folded into the
        saved lesson here.  The Pi backend saves the same draft twice (once
        from its tool, once when the import finishes), so an import that is
        already recorded in the lesson's batches is left alone.
        """

        if source_references:
            approve = getattr(self.lesson_repository, "approve_source_image", None)
            if approve is not None:
                for reference in source_references:
                    approve(reference)
        repository = self.lesson_repository
        existing = repository.get_lesson(draft.lesson_id)
        if existing is None:
            saved, batches = draft, [initial_batch(draft)]
        else:
            batches = repository.get_import_batches(draft.lesson_id)
            if any(batch.operation_id == draft.operation_id for batch in batches):
                self._follow_saved_scope(session_id, existing)
                return existing
            merged = merge_lesson(existing, draft)
            saved, batches = merged.lesson, [*batches, merged.batch]
        repository.save_lesson_draft(
            saved,
            source_references=source_references,
            import_batches=batches,
        )
        self._follow_saved_scope(session_id, saved)
        return saved

    def _follow_saved_scope(self, session_id: str | None, lesson: LessonDraft) -> None:
        # Appending grows the lesson's pages; the session must keep matching it.
        if session_id is not None and session_id in self._scopes:
            self._scopes[session_id] = lesson.scope

    def _skipped_duplicates(self, lesson: LessonDraft, operation_id: str) -> int:
        for batch in self.lesson_repository.get_import_batches(lesson.lesson_id):
            if batch.operation_id == operation_id:
                return batch.skipped_duplicates
        return 0

    @staticmethod
    def _validated_session_update(session: Session, **updates: Any) -> Session:
        payload = session.model_dump(mode="python")
        payload.update(updates)
        return Session.model_validate(payload)

    @staticmethod
    def _validate_draft_identity(
        draft: LessonDraft,
        scope: CourseScope,
        operation_id: str,
    ) -> None:
        if (
            draft.lesson_id != scope.lesson_id
            or draft.scope != scope
            or draft.operation_id != operation_id
        ):
            raise ProviderResponseInvalid(
                "lesson draft identity does not match the confirmed course scope"
            )

    @staticmethod
    def _draft_from_pi_result(result: Any) -> LessonDraft | None:
        candidates: list[Any] = [result]
        response = getattr(result, "response", None)
        if response is not None:
            candidates.append(response)
        for candidate in tuple(candidates):
            if isinstance(candidate, LessonDraft):
                return candidate
            payload = getattr(candidate, "payload", None)
            if isinstance(payload, Mapping):
                candidates.extend(
                    [payload.get("draft"), payload.get("lesson_draft"), payload.get("lesson")]
                )
            if isinstance(candidate, Mapping):
                candidates.extend(
                    [candidate.get("draft"), candidate.get("lesson_draft"), candidate.get("lesson")]
                )
        for candidate in candidates:
            if isinstance(candidate, LessonDraft):
                return candidate
            if isinstance(candidate, Mapping):
                try:
                    return LessonDraft.model_validate(candidate)
                except Exception:
                    continue
        return None

    def _safe_upload_dir(self, session_id: str) -> Path:
        if not session_id or any(part in session_id for part in ("/", "\\", "..")):
            raise UploadValidationError("invalid session upload path")
        root = self.upload_root
        root.mkdir(parents=True, exist_ok=True)
        directory = (root / session_id).resolve()
        try:
            directory.relative_to(root)
        except ValueError as exc:
            raise UploadValidationError("upload path escapes the upload root") from exc
        return directory

    def _owned_image_path(self, session_id: str, path: str) -> Path:
        session_dir = self._safe_upload_dir(session_id)
        try:
            candidate = Path(path).expanduser().resolve(strict=True)
            candidate.relative_to(session_dir)
        except (OSError, ValueError) as exc:
            raise UploadValidationError(
                "image reference path is outside the session upload root"
            ) from exc
        if not candidate.is_file():
            raise UploadValidationError("image reference path is not a regular file")
        return candidate

    @staticmethod
    def _write_upload(path: Path, content: bytes) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
            ) as file:
                temporary = Path(file.name)
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
            temporary = None
        except OSError as exc:
            raise UploadValidationError("could not persist uploaded image") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _import_prompt(scope: CourseScope, images: list[ImageReference]) -> str:
        image_ids = ", ".join(image.image_id for image in images)
        return (
            "Extract the confirmed English lesson and save its structured draft. "
            "All Chinese output MUST use Traditional Chinese (繁體／正體中文, zh-TW) exclusively. "
            "Never output Simplified Chinese or mix Simplified and Traditional characters. "
            "This includes translations, vocabulary meanings, explanations, and titles. "
            "Convert any Simplified Chinese in source images to Traditional Chinese in the draft. "
            "Preserve English lesson text in English; preserve JSON keys and identifiers. "
            f"Scope: {scope.lesson_id}. Source image IDs: {image_ids}."
        )




def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return {"value": repr(value)}
