from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService as FakeSTT,
    FakeTextService as FakeText,
    FakeTextToSpeechService as FakeTTS,
    FakeVisionService as FakeVision,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.api.app import create_app
from talkpath.application.session_service import SessionService


FIXTURE_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakePi:
    async def prompt(self, message: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(response=SimpleNamespace(payload={}), events=())


def make_service(root: Path, *, lessonlens: LessonLensMarkdownRepository | None = None) -> SessionService:
    return SessionService(
        progress_repository=SQLiteProgressRepository(root / "progress.sqlite"),
        lesson_repository=lessonlens or LessonLensMarkdownRepository(root / "lessonlens"),
        vision_service=FakeVision(),
        text_service=FakeText(),
        speech_to_text_service=FakeSTT(),
        text_to_speech_service=FakeTTS(),
        pi_client=FakePi(),
        upload_root=root / "uploads",
    )


def scope_payload() -> dict[str, object]:
    return {
        "program": "junior high",
        "grade": "7",
        "subject": "English",
        "lesson": "1",
    }


def test_textbook_image_to_activity_and_restart_persists_public_flow(tmp_path: Path) -> None:
    lessonlens_root = tmp_path / "lessonlens"
    service = make_service(tmp_path)
    client = TestClient(create_app(services=service, testing=True))

    session = client.post("/api/sessions", json={"operation_id": "session-op"})
    assert session.status_code == 200
    session_id = session.json()["session_id"]

    uploaded = client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("textbook-page.png", FIXTURE_IMAGE, "image/png")},
    )
    assert uploaded.status_code == 200

    confirmed = client.post(f"/api/sessions/{session_id}/scope", json=scope_payload())
    assert confirmed.status_code == 200
    assert confirmed.json()["scope"]["lesson_id"] == "junior-high-grade-7-english-lesson-01"

    imported = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-op"},
    )
    assert imported.status_code == 200
    lesson_id = imported.json()["lesson"]["lesson_id"]
    lesson_dir = lessonlens_root / "curricula" / "junior-high" / "grade-7" / "english" / "lesson-01"
    assert (lesson_dir / "lesson.md").is_file()
    assert (lesson_dir / "vocabulary" / "word-school.md").is_file()
    assert (lesson_dir / "grammar" / "grammar-simple-present.md").is_file()

    generated = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={"operation_id": "activity-op", "activity_type": "vocabulary_quiz"},
    )
    assert generated.status_code == 200
    activity = generated.json()["activity"]
    item = activity["items"][0]
    assert "answer" not in item
    assert "expected_answer" not in generated.text

    answered = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "answer-op",
            "item_id": item["activity_id"],
            "answer": "wrong",
        },
    )
    assert answered.status_code == 200
    assert answered.json()["evaluation"]["passed"] is False
    assert '"answer":' not in answered.text
    assert len(service.progress_repository.list_attempts(session_id)) == 1
    assert len(service.progress_repository.list_review_items(session_id, lesson_id)) == 1

    progress = client.get(f"/api/sessions/{session_id}/progress")
    assert progress.status_code == 200
    assert len(progress.json()["attempts"]) == 1
    assert len(progress.json()["review_items"]) == 1
    assert '"answer":' not in progress.text

    reopened = LessonLensMarkdownRepository(lessonlens_root)
    restarted_service = make_service(tmp_path, lessonlens=reopened)
    restarted = TestClient(create_app(services=restarted_service, testing=True))
    public_activity = restarted.get(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}"
    )
    assert public_activity.status_code == 200
    assert all("answer" not in item for item in public_activity.json()["activity"]["items"])
    assert "expected_answer" not in public_activity.text
    assert restarted.get(f"/api/lessons/{lesson_id}").status_code == 200
    assert restarted.get(f"/api/sessions/{session_id}/progress").status_code == 200
