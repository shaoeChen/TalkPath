"""Child-facing activity generation, retrieval and answer evaluation."""

from __future__ import annotations

import inspect
import time
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from talkpath.domain.errors import (
    DomainError,
    ProviderResponseInvalid,
    OperationFailed,
    RepositoryError,
    UnsupportedOperation,
)
from talkpath.application.safe_observability import log_operation_failure
from talkpath.domain.models import (
    Activity,
    ActivityDraft,
    AnswerEvaluation,
    LearningAttempt,
    LessonDraft,
)
from talkpath.ports.lesson_repository import LessonRepository
from talkpath.ports.model_services import TextService
from talkpath.ports.progress_repository import ProgressRepository


SUPPORTED_ACTIVITY_TYPES = frozenset(
    {
        "vocabulary_practice",
        "vocabulary_quiz",
        "grammar_practice",
        "grammar_quiz",
        "listening_practice",
        "listening_quiz",
        "reading_aloud",
        "speaking_practice",
    }
)

# Punctuation stripped from the *edges* of a spoken/typed answer before local
# comparison.  ASR models (e.g. Qwen3-ASR) append punctuation such as a
# trailing period ("Watermelon."), so a correct pronunciation must not be
# judged wrong because of it.  Internal apostrophes/hyphens (don't, ice-cream)
# are preserved.
_SPOKEN_EDGE_PUNCTUATION = ".,!?;:·…'\"‘’“”()[]{}<>-–—"


def normalize_spoken_answer(text: str) -> str:
    """Normalize a spoken transcript or typed answer for local comparison.

    Casefolds, strips edge punctuation and collapses internal whitespace on
    both sides so "School." matches "school" while "schoolyard" still does
    not.
    """
    return " ".join(
        (text or "").strip().casefold().strip(_SPOKEN_EDGE_PUNCTUATION).split()
    )


def normalize_reading_answer(text: str) -> str:
    """Compare recognized words without case, punctuation, or extra spacing."""
    words = "".join(
        char
        for char in text.casefold()
        if not unicodedata.category(char).startswith("P")
    )
    return " ".join(words.split())


class ActivityServiceError(DomainError):
    """Base class for child-facing activity failures."""


class ActivitySessionNotFound(ActivityServiceError):
    """Raised when an activity request references an unknown session."""


class ActivityLessonNotFound(ActivityServiceError):
    """Raised when a session is not backed by a saved LessonLens lesson."""


class ActivityNotFound(ActivityServiceError):
    """Raised when an activity was not generated for the requested session."""


class ActivityOperationConflict(ActivityServiceError):
    """Raised when an operation ID is retried with a different payload."""


class UnsupportedActivityType(ActivityServiceError):
    """Raised when the public UI asks for an activity type outside its contract."""


@dataclass(frozen=True, slots=True)
class ActivityAnswerResult:
    """Trusted answer result returned to the API boundary."""

    activity: ActivityDraft
    item: Activity
    evaluation: AnswerEvaluation
    attempt: LearningAttempt


class ActivityService:
    """Generate activities only from persisted lessons and retain them safely.

    The generated draft cache is intentionally session-scoped.  A child can
    submit only an activity that this service generated for that session (or a
    future repository-backed activity with the same identity), so the answer
    evaluator never trusts a client-provided answer key or activity payload.
    """

    def __init__(
        self,
        *,
        progress_repository: ProgressRepository,
        lesson_repository: LessonRepository,
        text_service: TextService,
        agent_backend: str = "direct",
    ) -> None:
        normalized_agent_backend = agent_backend.strip().lower()
        if normalized_agent_backend not in {"direct", "pi"}:
            raise ValueError("agent_backend must be 'direct' or 'pi'")
        self.progress_repository = progress_repository
        self.lesson_repository = lesson_repository
        self.text_service = text_service
        self.agent_backend = normalized_agent_backend
        self._activities: dict[tuple[str, str], ActivityDraft] = {}
        self._generation_operations: dict[tuple[str, str], tuple[str, ActivityDraft]] = {}
        self._answer_operations: dict[
            tuple[str, str], tuple[str, str, str, ActivityAnswerResult]
        ] = {}

    async def generate_activity(
        self,
        session_id: str,
        *,
        activity_type: str,
        operation_id: str,
    ) -> ActivityDraft:
        """Generate and retain one supported activity for a saved lesson."""

        operation_id = self._require_operation_id(operation_id)
        normalized_type = activity_type.strip().lower()
        if normalized_type not in SUPPORTED_ACTIVITY_TYPES:
            raise UnsupportedActivityType(
                f"unsupported activity type: {activity_type!r}"
            )

        self._get_session(session_id)
        lesson = self._saved_lesson_for_session(session_id)
        operation_key = (session_id, operation_id)
        existing_operation = self._generation_operations.get(operation_key)
        if existing_operation is not None:
            existing_type, existing_activity = existing_operation
            if existing_type != normalized_type:
                raise ActivityOperationConflict(
                    "operation_id was already used for a different activity type"
                )
            return existing_activity

        started_at = time.perf_counter()
        try:
            activity = await self.text_service.generate_activity(
                lesson,
                normalized_type,
                operation_id=operation_id,
            )
        except Exception as exc:
            log_operation_failure(
                event="activity_text_generation_failed",
                session_id=session_id,
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
        self._validate_generated_activity(activity, lesson, normalized_type, operation_id)
        activity = self._normalize_item_ids(activity)
        activity = self._ensure_unique_activity_id(activity, session_id)
        activity_key = (session_id, activity.activity_id)
        existing_activity = self._activities.get(activity_key)
        if existing_activity is not None and existing_activity != activity:
            raise ActivityOperationConflict(
                "generated activity ID was already used for different content"
            )

        self._activities[activity_key] = activity
        self._generation_operations[operation_key] = (normalized_type, activity)
        save = getattr(self.lesson_repository, "save_activity_draft", None)
        if save is not None:
            try:
                save(activity)
            except UnsupportedOperation:
                # LessonLens currently persists lessons; the service cache is
                # the authoritative MVP activity store until activity files are
                # added to that repository.
                pass
        return activity

    def get_activity(self, session_id: str, activity_id: str) -> ActivityDraft:
        """Return a generated activity after validating its session identity."""

        self._get_session(session_id)
        lesson = self._saved_lesson_for_session(session_id)
        activity = self._activities.get((session_id, activity_id))
        if activity is None:
            for candidate in self._activities.values():
                if candidate.lesson_id != lesson.lesson_id:
                    continue
                if any(item.activity_id == activity_id for item in candidate.items):
                    activity = candidate
                    break
        if activity is None:
            get_saved = getattr(self.lesson_repository, "get_activity_draft", None)
            if get_saved is not None:
                try:
                    candidate = get_saved(activity_id)
                except UnsupportedOperation:
                    candidate = None
                if candidate is not None:
                    activity = candidate
        if activity is None:
            raise ActivityNotFound(f"activity not found for session: {activity_id}")
        if activity.lesson_id != lesson.lesson_id:
            raise ActivityNotFound(f"activity does not belong to session: {activity_id}")
        return self._normalize_item_ids(activity)

    def generated_activity_types(self, session_id: str) -> set[str]:
        """Return the activity types already generated and cached for a session.

        The in-memory cache is the authoritative MVP activity store, so the
        returned set covers every type generated during this session even when
        the activity files were also persisted to LessonLens.
        """

        return {
            activity.type
            for (owner_session_id, _activity_id), activity in self._activities.items()
            if owner_session_id == session_id
        }

    @staticmethod
    def _normalize_item_ids(activity: ActivityDraft) -> ActivityDraft:
        """Give every item a stable, unique activity_id.

        Real text providers often copy the activity ID into every item, which
        makes item_id lookups ambiguous: every answer is then evaluated against
        the first item, so questions after the first are always marked wrong.
        Renaming positionally keeps ids deterministic across generation,
        repository reloads, and answer lookups.
        """

        items = [
            item.model_copy(
                update={"activity_id": f"{activity.activity_id}-item-{index + 1}"}
            )
            for index, item in enumerate(activity.items)
        ]
        return activity.model_copy(update={"items": items})

    def _ensure_unique_activity_id(
        self,
        activity: ActivityDraft,
        session_id: str,
    ) -> ActivityDraft:
        """Give a fresh id when a provider reuses an already-used activity id.

        Real providers often derive activity ids from the lesson and type, so
        regenerating the same activity for a saved lesson collides with the
        previously saved file and fails at save time. A short random suffix
        keeps every generation distinct without weakening the repository
        identity contract.
        """

        get_saved = getattr(self.lesson_repository, "get_activity_draft", None)
        while True:
            existing = self._activities.get((session_id, activity.activity_id))
            if existing is None and get_saved is not None:
                try:
                    existing = get_saved(activity.activity_id)
                except UnsupportedOperation:
                    existing = None
            if existing is None or existing == activity:
                return activity
            activity = activity.model_copy(
                update={"activity_id": f"{activity.activity_id}-{uuid4().hex[:8]}"}
            )
            activity = self._normalize_item_ids(activity)

    async def answer(
        self,
        session_id: str,
        activity_id: str,
        *,
        answer: str,
        operation_id: str,
        item_id: str | None = None,
    ) -> ActivityAnswerResult:
        """Evaluate a trusted generated item and persist one idempotent attempt."""

        operation_id = self._require_operation_id(operation_id)
        activity = self.get_activity(session_id, activity_id)
        item = self._find_item(activity, activity_id=activity_id, item_id=item_id)
        operation_key = (session_id, operation_id)
        existing_operation = self._answer_operations.get(operation_key)
        if existing_operation is not None:
            existing_activity_id, existing_item_id, existing_answer, result = existing_operation
            if (
                existing_activity_id != activity.activity_id
                or existing_item_id != item.activity_id
                or existing_answer != answer
            ):
                raise ActivityOperationConflict(
                    "operation_id was already used for a different answer"
                )
            return result

        started_at = time.perf_counter()
        try:
            if activity.type == "reading_aloud":
                expected = item.prompt
                correct = normalize_reading_answer(answer) == normalize_reading_answer(
                    expected
                )
                evaluation = AnswerEvaluation(
                    correct=correct,
                    score=1.0 if correct else 0.0,
                    feedback="Great job!" if correct else "Try again.",
                    expected_answer=expected,
                )
            elif item.choices or activity.type in {"vocabulary_practice", "vocabulary_quiz"}:
                # Choice questions, vocabulary practice, and the vocabulary quiz
                # have a standard answer (the word or meaning), so compare
                # locally for instant feedback instead of waiting on the text provider.
                evaluation = self._evaluate_standard_answer(item, answer)
            else:
                evaluation = await self.text_service.evaluate_answer(
                    item,
                    answer,
                    operation_id=operation_id,
                )
        except Exception as exc:
            log_operation_failure(
                event="answer_text_evaluation_failed",
                session_id=session_id,
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
        if not isinstance(evaluation, AnswerEvaluation):
            raise ProviderResponseInvalid("answer evaluation is not a valid response")
        attempt = self._record_attempt(
            session_id=session_id,
            lesson_id=activity.lesson_id,
            activity_id=item.activity_id,
            operation_id=operation_id,
            answer=answer,
            evaluation=evaluation,
        )
        result = ActivityAnswerResult(
            activity=activity,
            item=item,
            evaluation=evaluation,
            attempt=attempt,
        )
        self._answer_operations[operation_key] = (
            activity.activity_id,
            item.activity_id,
            answer,
            result,
        )
        return result

    @staticmethod
    def _evaluate_standard_answer(item: Activity, answer: str) -> AnswerEvaluation:
        """Evaluate a multiple-choice answer against its stored standard answer."""

        expected = item.answer
        correct = (
            expected is not None
            and normalize_spoken_answer(answer) == normalize_spoken_answer(expected)
        )
        return AnswerEvaluation(
            correct=correct,
            score=1.0 if correct else 0.0,
            feedback="Great job!" if correct else "Try again.",
            expected_answer=expected,
        )

    def _record_attempt(
        self,
        *,
        session_id: str,
        lesson_id: str,
        activity_id: str,
        operation_id: str,
        answer: str,
        evaluation: AnswerEvaluation,
    ) -> LearningAttempt:
        method = self.progress_repository.record_attempt
        kwargs: dict[str, Any] = {
            "correct": evaluation.correct,
            "score": evaluation.score,
            "answer": answer,
            "lesson_id": lesson_id,
        }
        supported = inspect.signature(method).parameters
        if "operation_id" in supported:
            kwargs["operation_id"] = operation_id
        if "feedback" in supported:
            kwargs["feedback"] = evaluation.feedback
        return method(session_id, activity_id, **kwargs)

    def _get_session(self, session_id: str):
        session = self.progress_repository.get_session(session_id)
        if session is None:
            raise ActivitySessionNotFound(f"learning session not found: {session_id}")
        return session

    def _saved_lesson_for_session(self, session_id: str) -> LessonDraft:
        session = self._get_session(session_id)
        if not session.lesson_id:
            raise ActivityLessonNotFound("session has no confirmed lesson scope")
        try:
            lesson = self.lesson_repository.get_lesson(session.lesson_id)
        except RepositoryError as exc:
            raise ActivityLessonNotFound(
                f"saved lesson not found: {session.lesson_id}"
            ) from exc
        if lesson is None:
            raise ActivityLessonNotFound(f"saved lesson not found: {session.lesson_id}")
        if lesson.lesson_id != session.lesson_id or lesson.scope.lesson_id != lesson.lesson_id:
            raise ProviderResponseInvalid("saved lesson identity does not match the session scope")
        return lesson

    @staticmethod
    def _find_item(
        activity: ActivityDraft,
        *,
        activity_id: str,
        item_id: str | None,
    ) -> Activity:
        if item_id:
            for item in activity.items:
                if item.activity_id == item_id:
                    return item
            raise ActivityNotFound(f"activity item not found: {item_id}")
        if len(activity.items) == 1:
            return activity.items[0]
        for item in activity.items:
            if item.activity_id == activity_id:
                return item
        raise ActivityNotFound("item_id is required for a multi-question activity")

    @staticmethod
    def _validate_generated_activity(
        activity: ActivityDraft,
        lesson: LessonDraft,
        activity_type: str,
        operation_id: str,
    ) -> None:
        if (
            activity.lesson_id != lesson.lesson_id
            or activity.type != activity_type
            or activity.operation_id != operation_id
        ):
            raise ProviderResponseInvalid(
                "generated activity identity does not match the saved lesson request"
            )
        if any(item.lesson_id != lesson.lesson_id for item in activity.items):
            raise ProviderResponseInvalid(
                "generated activity item identity does not match the saved lesson"
            )

    @staticmethod
    def _require_operation_id(operation_id: str) -> str:
        normalized = operation_id.strip()
        if not normalized:
            raise ActivityOperationConflict("operation_id cannot be blank")
        return normalized
