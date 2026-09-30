from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import talkpath.adapters.sqlite_progress as sqlite_progress_module
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.domain.errors import RepositoryError
from talkpath.domain.models import Session, SessionState


def make_repository(tmp_path: Path) -> SQLiteProgressRepository:
    return SQLiteProgressRepository(tmp_path / "progress.sqlite")


def test_first_use_creates_database_and_session_round_trips(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "progress.sqlite"
    repo = SQLiteProgressRepository(database_path)

    session = repo.create_session(
        "local-child",
        "junior-high-grade-1-english-lesson-01",
        operation_id="session-operation-1",
    )

    assert database_path.is_file()
    restored = repo.get_session(session.session_id)
    assert restored == session
    assert restored is not None
    assert restored.learner_key == "local-child"
    assert restored.lesson_id == "junior-high-grade-1-english-lesson-01"
    assert restored.state is SessionState.UPLOAD_IMAGE
    assert restored.created_at.tzinfo is not None
    assert restored.updated_at.tzinfo is not None


def test_create_session_with_same_operation_id_is_idempotent(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)

    first = repo.create_session(
        "local-child",
        "lesson-01",
        operation_id="session-operation-1",
    )
    second = repo.create_session(
        "local-child",
        "lesson-01",
        operation_id="session-operation-1",
    )

    assert second == first
    with pytest.raises(RepositoryError, match="operation_id"):
        repo.create_session(
            "another-child",
            "lesson-01",
            operation_id="session-operation-1",
        )
    with pytest.raises(RepositoryError, match="operation_id"):
        repo.create_session(
            "local-child",
            "lesson-02",
            operation_id="session-operation-1",
        )


def test_failed_attempt_creates_review_item_and_is_idempotent(
    tmp_path: Path,
) -> None:
    repo = make_repository(tmp_path)
    session = repo.create_session("local-child", "lesson-01")

    first = repo.record_attempt(
        session.session_id,
        "vocabulary-hello",
        correct=False,
        score=0.0,
        answer="goodbye",
        operation_id="attempt-operation-1",
        feedback="Try again.",
    )
    second = repo.record_attempt(
        session.session_id,
        "vocabulary-hello",
        correct=False,
        score=0.0,
        answer="goodbye",
        operation_id="attempt-operation-1",
        feedback="Try again.",
    )

    assert second == first
    assert first.attempt_id == "attempt-operation-1"
    assert first.lesson_id == "lesson-01"
    assert first.score == 0.0
    assert first.correct is False
    assert first.answer == "goodbye"
    items = repo.list_review_items(session.session_id, "lesson-01")
    assert len(items) == 1
    assert items[0].activity_id == "vocabulary-hello"
    assert items[0].mistake_count == 1
    assert items[0].last_seen_at.tzinfo is not None
    assert len(repo.list_attempts(session.session_id)) == 1

    with sqlite3.connect(tmp_path / "progress.sqlite") as connection:
        row = connection.execute(
            "SELECT feedback FROM attempts WHERE operation_id = ?",
            ("attempt-operation-1",),
        ).fetchone()
    assert row == ("Try again.",)


def test_reusing_operation_id_with_different_payload_is_rejected(
    tmp_path: Path,
) -> None:
    repo = make_repository(tmp_path)
    session = repo.create_session("local-child", "lesson-01")
    repo.record_attempt(
        session.session_id,
        "activity-1",
        correct=False,
        score=0.0,
        operation_id="attempt-operation-1",
    )

    with pytest.raises(RepositoryError, match="operation_id"):
        repo.record_attempt(
            session.session_id,
            "activity-1",
            correct=True,
            score=1.0,
            operation_id="attempt-operation-1",
        )

    assert len(repo.list_attempts(session.session_id)) == 1
    assert repo.list_review_items(session.session_id, "lesson-01")[0].mistake_count == 1


def test_existing_attempt_is_checked_before_current_lesson_validation(
    tmp_path: Path,
) -> None:
    repo = make_repository(tmp_path)
    session = repo.create_session("local-child", "lesson-01")
    first = repo.record_attempt(
        session.session_id,
        "activity-1",
        correct=False,
        score=0.0,
        operation_id="attempt-operation-1",
    )

    repo.save_session(
        session.model_copy(update={"lesson_id": None, "scope_confirmed": False})
    )

    assert repo.record_attempt(
        session.session_id,
        "activity-1",
        correct=False,
        score=0.0,
        operation_id="attempt-operation-1",
    ) == first
    with pytest.raises(RepositoryError, match="operation_id"):
        repo.record_attempt(
            session.session_id,
            "activity-1",
            correct=True,
            score=1.0,
            operation_id="attempt-operation-1",
        )


def test_correct_attempt_clears_existing_review_item(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    session = repo.create_session("local-child", "lesson-01")
    repo.record_attempt(
        session.session_id,
        "grammar-be",
        correct=False,
        score=0.25,
        operation_id="attempt-operation-1",
    )

    correct = repo.record_attempt(
        session.session_id,
        "grammar-be",
        correct=True,
        score=1.0,
        operation_id="attempt-operation-2",
        feedback="Great job!",
    )

    assert correct.correct is True
    assert correct.score == 1.0
    assert repo.list_review_items(session.session_id, "lesson-01") == []
    assert len(repo.list_attempts(session.session_id)) == 2


def test_record_attempt_resolves_lesson_from_session_and_orders_attempts(
    tmp_path: Path,
) -> None:
    repo = make_repository(tmp_path)
    session = repo.create_session("local-child", "lesson-01")
    first = repo.record_attempt(
        session.session_id,
        "activity-1",
        correct=True,
        score=1.0,
        operation_id="attempt-operation-1",
    )
    second = repo.record_attempt(
        session.session_id,
        "activity-2",
        correct=True,
        score=0.8,
        operation_id="attempt-operation-2",
        lesson_id="lesson-01",
    )

    attempts = repo.list_attempts(session.session_id)
    assert [attempt.attempt_id for attempt in attempts] == [
        first.attempt_id,
        second.attempt_id,
    ]
    assert all(attempt.lesson_id == "lesson-01" for attempt in attempts)


def test_unbound_session_cannot_record_attempt(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    session = repo.create_session("local-child")

    with pytest.raises(RepositoryError, match="lesson"):
        repo.record_attempt(
            session.session_id,
            "activity-1",
            correct=False,
            score=0.0,
            operation_id="attempt-operation-1",
        )

    assert repo.list_attempts(session.session_id) == []
    assert repo.list_review_items(session.session_id) == []


def test_missing_records_are_safe_and_missing_session_write_is_translated(
    tmp_path: Path,
) -> None:
    repo = make_repository(tmp_path)

    assert repo.get_session("missing-session") is None
    assert repo.list_attempts("missing-session") == []
    assert repo.list_review_items("missing-session") == []

    with pytest.raises(RepositoryError, match="session"):
        repo.record_attempt(
            "missing-session",
            "activity-1",
            correct=False,
            score=0.0,
            operation_id="attempt-operation-1",
        )


def test_save_session_round_trips_state_and_timestamps(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    original = repo.create_session("local-child", "lesson-01")
    changed = original.model_copy(
        update={
            "state": SessionState.CONFIRM_COURSE_SCOPE,
            "scope_confirmed": True,
            "updated_at": original.updated_at,
        }
    )

    repo.save_session(changed)

    assert repo.get_session(original.session_id) == changed


@pytest.mark.parametrize(
    "invalid_update",
    [
        {"state": "invalid"},
        {"state": SessionState.READY_FOR_PRACTICE, "lesson_id": None, "scope_confirmed": False},
    ],
)
def test_save_session_revalidates_invalid_model_copy_as_repository_error(
    tmp_path: Path,
    invalid_update: dict[str, object],
) -> None:
    repo = make_repository(tmp_path)
    session = repo.create_session("local-child", "lesson-01")

    with pytest.raises(RepositoryError, match="invalid session"):
        repo.save_session(session.model_copy(update=invalid_update))


def test_concurrent_same_operation_id_returns_one_attempt(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "progress.sqlite"
    repo = SQLiteProgressRepository(database_path)
    session = repo.create_session("local-child", "lesson-01")

    def record_from_independent_repository() -> object:
        return SQLiteProgressRepository(database_path).record_attempt(
            session.session_id,
            "activity-1",
            correct=False,
            score=0.0,
            operation_id="attempt-operation-concurrent",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(record_from_independent_repository)
        second_future = executor.submit(record_from_independent_repository)
        first = first_future.result(timeout=10)
        second = second_future.result(timeout=10)

    assert second == first
    assert len(repo.list_attempts(session.session_id)) == 1
    assert repo.list_review_items(session.session_id, "lesson-01")[0].mistake_count == 1


def test_save_session_preserves_attempts_and_review_items(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    session = repo.create_session("local-child", "lesson-01")
    repo.record_attempt(
        session.session_id,
        "activity-1",
        correct=False,
        score=0.0,
        operation_id="attempt-operation-1",
    )

    repo.save_session(
        session.model_copy(update={"updated_at": session.updated_at})
    )

    assert len(repo.list_attempts(session.session_id)) == 1
    assert len(repo.list_review_items(session.session_id, "lesson-01")) == 1


def test_repository_does_not_use_project_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_connect = sqlite_progress_module.sqlite3.connect
    connect_calls: list[Path] = []

    def connect_spy(
        database: str,
        *args: object,
        **kwargs: object,
    ) -> sqlite3.Connection:
        connect_calls.append(Path(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite_progress_module.sqlite3, "connect", connect_spy)

    repo = make_repository(tmp_path)
    repo.create_session("local-child", "lesson-01")

    expected_database = tmp_path / "progress.sqlite"
    assert repo.database_path == expected_database
    assert expected_database.exists()
    assert connect_calls
    assert all(
        database.resolve() == expected_database.resolve()
        for database in connect_calls
    )
