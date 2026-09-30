"""Persistence boundary for child sessions, attempts and review items."""

from __future__ import annotations

from typing import Protocol

from talkpath.domain.models import (
    LearningAttempt,
    ReviewItem,
    Session,
)


class ProgressRepository(Protocol):
    """Repository contract implemented by the SQLite progress adapter."""

    def create_session(
        self,
        learner_key: str,
        lesson_id: str | None = None,
        *,
        operation_id: str | None = None,
    ) -> Session:
        """Create a learning session for the single child user."""

    def get_session(self, session_id: str) -> Session | None:
        """Return a session by ID, or ``None`` when it is absent."""

    def save_session(self, session: Session) -> None:
        """Insert or update a learning session."""

    def record_attempt(
        self,
        session_id: str,
        activity_id: str,
        *,
        correct: bool,
        score: float,
        answer: str | None = None,
        lesson_id: str | None = None,
        operation_id: str | None = None,
        feedback: str | None = None,
    ) -> LearningAttempt:
        """Record an answer and update review state.

        When ``lesson_id`` is omitted, the implementation must resolve it from
        the persisted session and reject sessions that are not yet bound to a
        lesson.  This keeps the existing ``record_attempt(session_id,
        activity_id, correct=..., score=...)`` call style valid.
        """

    def list_review_items(
        self,
        session_id: str,
        lesson_id: str | None = None,
    ) -> list[ReviewItem]:
        """Return items that need review, optionally for one lesson."""

    def list_attempts(self, session_id: str) -> list[LearningAttempt]:
        """Return recorded attempts in chronological order."""
