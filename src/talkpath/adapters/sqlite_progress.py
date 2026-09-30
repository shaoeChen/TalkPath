"""SQLite persistence for TalkPath child learning progress."""

from __future__ import annotations

import json
import sqlite3
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from pydantic import ValidationError

from talkpath.domain.errors import RepositoryError
from talkpath.domain.models import (
    LearningAttempt,
    ReviewItem,
    Session,
    SessionState,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_sessions (
    id TEXT PRIMARY KEY,
    learner_key TEXT NOT NULL,
    lesson_id TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    scope_confirmed INTEGER NOT NULL DEFAULT 0,
    operation_id TEXT NOT NULL UNIQUE DEFAULT '',
    source_images TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS attempts (
    operation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
    score REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
    feedback TEXT NOT NULL,
    created_at TEXT NOT NULL,
    lesson_id TEXT NOT NULL DEFAULT '',
    answer TEXT,
    FOREIGN KEY (session_id) REFERENCES learning_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_items (
    session_id TEXT NOT NULL,
    lesson_id TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    mistake_count INTEGER NOT NULL CHECK (mistake_count >= 0),
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (session_id, activity_id),
    FOREIGN KEY (session_id) REFERENCES learning_sessions(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_sessions_operation_id
ON learning_sessions(operation_id)
WHERE operation_id <> '';
"""
_SCHEMA_STATEMENTS = tuple(
    statement.strip() for statement in _SCHEMA.split(";") if statement.strip()
)


class SQLiteProgressRepository:
    """Store sessions, attempts and review items in a local SQLite database.

    A connection is opened per repository operation. This keeps the adapter
    safe for the synchronous FastAPI boundary and guarantees that a failed
    operation cannot leave a connection or transaction open.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def create_session(
        self,
        learner_key: str,
        lesson_id: str | None = None,
        *,
        operation_id: str | None = None,
    ) -> Session:
        """Create and persist a new child learning session."""

        provided_operation_id = operation_id
        try:
            session = Session(
                learner_key=learner_key,
                lesson_id=lesson_id,
                scope_confirmed=bool(lesson_id),
                operation_id=operation_id or str(uuid4()),
            )
        except ValidationError as exc:
            raise RepositoryError(f"invalid session: {exc}") from exc

        try:
            with self._transaction() as connection:
                if provided_operation_id:
                    existing = connection.execute(
                        """
                        SELECT * FROM learning_sessions
                        WHERE operation_id = ?
                        """,
                        (provided_operation_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            existing["learner_key"] != session.learner_key
                            or (existing["lesson_id"] or "")
                            != (session.lesson_id or "")
                        ):
                            raise RepositoryError(
                                "operation_id was already used for a different session"
                            )
                        return self._session_from_row(existing)
                self._insert_session(connection, session)
        except RepositoryError:
            raise
        except sqlite3.Error as exc:
            raise RepositoryError("could not create learning session") from exc
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Return a session by ID, or ``None`` when it is absent."""

        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM learning_sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                return self._session_from_row(row) if row is not None else None
        except RepositoryError:
            raise
        except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RepositoryError("could not read learning session") from exc

    def save_session(self, session: Session) -> None:
        """Insert or update a session in one transaction."""

        validated_session = self._validate_session(session)
        try:
            with self._transaction() as connection:
                self._insert_session(connection, validated_session, replace=True)
        except RepositoryError:
            raise
        except sqlite3.Error as exc:
            raise RepositoryError("could not save learning session") from exc

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
        """Record an answer and update review state transactionally.

        ``operation_id`` is optional for compatibility with the original port;
        callers performing retries should provide it so the operation is
        idempotent. The optional ``feedback`` value is persisted in SQLite,
        while the current domain model exposes the answer evaluation separately.
        """

        operation_id = operation_id or str(uuid4())
        feedback = (
            feedback
            if feedback is not None
            else ("Correct." if correct else "Keep practicing.")
        )
        now = _utc_now()
        created_at = _format_timestamp(now)

        try:
            with self._transaction() as connection:
                existing = connection.execute(
                    "SELECT * FROM attempts WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
                if existing is not None:
                    if not self._attempt_matches(
                        existing,
                        session_id=session_id,
                        activity_id=activity_id,
                        lesson_id=lesson_id,
                        correct=correct,
                        score=score,
                        answer=answer,
                        feedback=feedback,
                    ):
                        raise RepositoryError(
                            "operation_id was already used for a different attempt"
                        )
                    return self._attempt_from_row(existing)

                session_row = connection.execute(
                    "SELECT * FROM learning_sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                if session_row is None:
                    raise RepositoryError(f"learning session not found: {session_id}")

                stored_lesson_id = str(session_row["lesson_id"] or "")
                effective_lesson_id = lesson_id or stored_lesson_id
                if not effective_lesson_id:
                    raise RepositoryError(
                        "lesson_id is required for a session without a confirmed lesson"
                    )
                if lesson_id and stored_lesson_id and lesson_id != stored_lesson_id:
                    raise RepositoryError(
                        "lesson_id does not match the learning session"
                    )

                attempt = self._build_attempt(
                    operation_id=operation_id,
                    session_id=session_id,
                    lesson_id=effective_lesson_id,
                    activity_id=activity_id,
                    correct=correct,
                    score=score,
                    answer=answer,
                    created_at=now,
                )
                connection.execute(
                    """
                    INSERT INTO attempts (
                        operation_id, session_id, activity_id, correct, score,
                        feedback, created_at, lesson_id, answer
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id,
                        session_id,
                        activity_id,
                        int(correct),
                        score,
                        feedback,
                        created_at,
                        effective_lesson_id,
                        answer,
                    ),
                )

                if correct:
                    connection.execute(
                        """
                        DELETE FROM review_items
                        WHERE session_id = ? AND activity_id = ?
                        """,
                        (session_id, activity_id),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO review_items (
                            session_id, lesson_id, activity_id,
                            mistake_count, last_seen_at
                        ) VALUES (?, ?, ?, 1, ?)
                        ON CONFLICT(session_id, activity_id) DO UPDATE SET
                            lesson_id = excluded.lesson_id,
                            mistake_count = review_items.mistake_count + 1,
                            last_seen_at = excluded.last_seen_at
                        """,
                        (
                            session_id,
                            effective_lesson_id,
                            activity_id,
                            created_at,
                        ),
                    )
                return attempt
        except RepositoryError:
            raise
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise RepositoryError("could not record learning attempt") from exc

    def list_review_items(
        self,
        session_id: str,
        lesson_id: str | None = None,
    ) -> list[ReviewItem]:
        """Return review items for a session, optionally limited to a lesson."""

        try:
            with self._transaction() as connection:
                query = """
                    SELECT session_id, lesson_id, activity_id,
                           mistake_count, last_seen_at
                    FROM review_items
                    WHERE session_id = ?
                """
                parameters: list[str] = [session_id]
                if lesson_id is not None:
                    query += " AND lesson_id = ?"
                    parameters.append(lesson_id)
                query += " ORDER BY last_seen_at ASC, activity_id ASC"
                rows = connection.execute(query, parameters).fetchall()
                return [self._review_item_from_row(row) for row in rows]
        except RepositoryError:
            raise
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise RepositoryError("could not list review items") from exc

    def list_attempts(self, session_id: str) -> list[LearningAttempt]:
        """Return a session's attempts in chronological order."""

        try:
            with self._transaction() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM attempts
                    WHERE session_id = ?
                    ORDER BY created_at ASC, operation_id ASC
                    """,
                    (session_id,),
                ).fetchall()
                return [self._attempt_from_row(row) for row in rows]
        except RepositoryError:
            raise
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise RepositoryError("could not list learning attempts") from exc

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
            yield connection
            connection.commit()
        except RepositoryError:
            if connection is not None:
                connection.rollback()
            raise
        except (sqlite3.Error, OSError) as exc:
            if connection is not None:
                connection.rollback()
            raise RepositoryError("SQLite operation failed") from exc
        finally:
            if connection is not None:
                connection.close()

    def _connect(self) -> sqlite3.Connection:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.database_path), timeout=30.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection
        except (sqlite3.Error, OSError) as exc:
            raise RepositoryError("could not open progress database") from exc

    @staticmethod
    def _insert_session(
        connection: sqlite3.Connection,
        session: Session,
        *,
        replace: bool = False,
    ) -> None:
        images = json.dumps(
            [image.model_dump(mode="json") for image in session.source_images],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        query = """
            INSERT INTO learning_sessions (
                id, learner_key, lesson_id, state, created_at, updated_at,
                scope_confirmed, operation_id, source_images
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        values = (
            session.session_id,
            session.learner_key,
            session.lesson_id or "",
            session.state.value,
            _format_timestamp(session.created_at),
            _format_timestamp(session.updated_at),
            int(session.scope_confirmed),
            session.operation_id,
            images,
        )
        if replace:
            query += """
                ON CONFLICT(id) DO UPDATE SET
                    learner_key = excluded.learner_key,
                    lesson_id = excluded.lesson_id,
                    state = excluded.state,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    scope_confirmed = excluded.scope_confirmed,
                    operation_id = excluded.operation_id,
                    source_images = excluded.source_images
            """
        connection.execute(query, values)

    @staticmethod
    def _validate_session(session: Session) -> Session:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Pydantic serializer warnings:.*",
                    category=UserWarning,
                )
                payload = session.model_dump(mode="python")
            return Session.model_validate(payload)
        except (ValidationError, AttributeError, TypeError, ValueError) as exc:
            raise RepositoryError(f"invalid session: {exc}") from exc

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> Session:
        source_images = json.loads(row["source_images"] or "[]")
        return Session(
            session_id=row["id"],
            learner_key=row["learner_key"],
            lesson_id=row["lesson_id"] or None,
            state=SessionState(row["state"]),
            scope_confirmed=bool(row["scope_confirmed"]),
            source_images=source_images,
            operation_id=row["operation_id"] or str(uuid4()),
            created_at=_parse_timestamp(row["created_at"]),
            updated_at=_parse_timestamp(row["updated_at"]),
        )

    @staticmethod
    def _build_attempt(
        *,
        operation_id: str,
        session_id: str,
        lesson_id: str,
        activity_id: str,
        correct: bool,
        score: float,
        answer: str | None,
        created_at: datetime,
    ) -> LearningAttempt:
        try:
            return LearningAttempt(
                attempt_id=operation_id,
                session_id=session_id,
                lesson_id=lesson_id,
                activity_id=activity_id,
                answer=answer,
                correct=correct,
                score=score,
                created_at=created_at,
            )
        except ValidationError as exc:
            raise RepositoryError(f"invalid learning attempt: {exc}") from exc

    @classmethod
    def _attempt_from_row(cls, row: sqlite3.Row) -> LearningAttempt:
        return cls._build_attempt(
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            lesson_id=row["lesson_id"],
            activity_id=row["activity_id"],
            correct=bool(row["correct"]),
            score=float(row["score"]),
            answer=row["answer"] if "answer" in row.keys() else None,
            created_at=_parse_timestamp(row["created_at"]),
        )

    @staticmethod
    def _review_item_from_row(row: sqlite3.Row) -> ReviewItem:
        return ReviewItem(
            session_id=row["session_id"],
            lesson_id=row["lesson_id"],
            activity_id=row["activity_id"],
            mistake_count=row["mistake_count"],
            last_seen_at=_parse_timestamp(row["last_seen_at"]),
        )

    @staticmethod
    def _attempt_matches(
        row: sqlite3.Row,
        *,
        session_id: str,
        activity_id: str,
        lesson_id: str | None,
        correct: bool,
        score: float,
        answer: str | None,
        feedback: str,
    ) -> bool:
        return (
            row["session_id"] == session_id
            and row["activity_id"] == activity_id
            and (
                lesson_id is None
                or (row["lesson_id"] or "") == lesson_id
            )
            and bool(row["correct"]) == correct
            and float(row["score"]) == score
            and (row["answer"] if "answer" in row.keys() else None) == answer
            and row["feedback"] == feedback
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
