from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService,
    FakeTextService,
    FakeTextToSpeechService,
    FakeVisionService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.api.app import create_app
from talkpath.application.session_service import SessionService


class NoopPi:
    async def prompt(self, message: str, **kwargs: object) -> object:
        return object()


def make_client(tmp_path: Path) -> TestClient:
    service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=FakeVisionService(),
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=NoopPi(),
        upload_root=tmp_path / "uploads",
    )
    return TestClient(create_app(services=service, testing=True))


def scope_payload(lesson: str = "1") -> dict[str, object]:
    return {
        "program": "junior high",
        "grade": "7",
        "subject": "English",
        "lesson": lesson,
        "textbook": "TalkPath English",
        "edition": "2026",
        "pages": ["1", "2"],
    }


def import_saved_lesson(client: TestClient, *, lesson: str, operation_id: str) -> str:
    """Run the upload -> scope -> import flow and return the saved lesson ID."""

    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json=scope_payload(lesson),
    ).status_code == 200
    imported = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": operation_id},
    )
    assert imported.status_code == 200
    return imported.json()["lesson"]["lesson_id"]


def test_lessons_list_is_empty_for_a_new_vault(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/lessons")

    assert response.status_code == 200
    assert response.json() == []


def test_lessons_list_returns_saved_lesson_summaries_without_passage(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    import_saved_lesson(client, lesson="1", operation_id="lesson-list-import-1")

    response = client.get("/api/lessons")

    assert response.status_code == 200
    lessons = response.json()
    assert len(lessons) == 1
    summary = lessons[0]
    assert summary["lesson_id"] == "junior-high-grade-7-english-lesson-01--talkpath-english"
    assert summary["title"] == "A Day at School"
    assert summary["scope"]["lesson_id"] == "junior-high-grade-7-english-lesson-01--talkpath-english"
    assert summary["source_image_count"] == 1
    assert summary["content_item_count"] == 2
    assert "passage" not in summary
    assert "content_items" not in summary


def test_lessons_list_sorts_multiple_saved_lessons_by_lesson_id(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    first = import_saved_lesson(client, lesson="1", operation_id="lesson-list-import-1")
    second = import_saved_lesson(client, lesson="2", operation_id="lesson-list-import-2")

    response = client.get("/api/lessons")

    assert response.status_code == 200
    assert [lesson["lesson_id"] for lesson in response.json()] == [first, second]


def test_create_session_with_saved_lesson_opens_practice_directly(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    lesson_id = import_saved_lesson(
        client,
        lesson="1",
        operation_id="saved-lesson-import-1",
    )

    created = client.post(
        "/api/sessions",
        json={
            "operation_id": "saved-session-1",
            "lesson_id": lesson_id,
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["lesson_id"] == lesson_id
    assert body["scope_confirmed"] is True
    assert body["state"] == "ASK_GENERATE_ACTIVITY"
    assert body["scope"]["lesson_id"] == lesson_id

    generated = client.post(
        f"/api/sessions/{body['session_id']}/activities/generate",
        json={
            "operation_id": "saved-activity-1",
            "activity_type": "vocabulary_quiz",
        },
    )
    assert generated.status_code == 200
    assert generated.json()["session"]["state"] == "READY_FOR_PRACTICE"


def test_create_session_with_unknown_lesson_returns_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/sessions",
        json={
            "operation_id": "missing-lesson-session",
            "lesson_id": "junior-high-grade-7-english-lesson-99",
        },
    )

    assert response.status_code == 404
    assert "lesson not found" in response.json()["detail"]


def test_create_session_with_blank_lesson_id_returns_422(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/sessions",
        json={
            "operation_id": "blank-lesson-session",
            "lesson_id": "",
        },
    )

    assert response.status_code == 422


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def import_pages(
    client: TestClient,
    pages: list[str],
    *,
    operation_id: str,
    image: bytes = PNG_BYTES,
) -> dict[str, object]:
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", image, "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json={**scope_payload(), "pages": pages},
    ).status_code == 200
    imported = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": operation_id},
    )
    assert imported.status_code == 200
    return imported.json()


def test_import_check_reports_a_new_lesson_as_not_existing(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/api/lessons/import-check", json=scope_payload("9"))

    assert response.status_code == 200
    assert response.json() == {
        "lesson_id": "junior-high-grade-7-english-lesson-09--talkpath-english",
        "exists": False,
        "title": None,
        "existing_pages": [],
        "overlapping_pages": [],
        "content_item_count": 0,
    }


def test_import_check_reports_existing_pages_and_overlap(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    import_pages(client, ["1", "2"], operation_id="check-import-1")

    response = client.post(
        "/api/lessons/import-check",
        json={**scope_payload(), "pages": ["2-3"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["title"] == "A Day at School"
    assert body["existing_pages"] == ["1", "2"]
    assert body["overlapping_pages"] == ["2"]
    assert body["content_item_count"] == 2


def test_import_check_treats_another_textbook_as_a_different_lesson(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    import_pages(client, ["1"], operation_id="check-import-1")

    response = client.post(
        "/api/lessons/import-check",
        json={**scope_payload(), "textbook": "Another Publisher", "pages": ["1"]},
    )

    assert response.status_code == 200
    assert response.json()["exists"] is False
    assert response.json()["overlapping_pages"] == []


def test_import_check_rejects_an_incomplete_scope(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    missing = client.post("/api/lessons/import-check", json={"program": "junior high"})
    blank = client.post("/api/lessons/import-check", json={**scope_payload(), "grade": "  "})

    assert missing.status_code == 422
    assert blank.status_code == 422


def test_import_response_appends_and_reports_skipped_duplicates(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = import_pages(client, ["1", "2"], operation_id="append-import-1")
    second = import_pages(client, ["3"], operation_id="append-import-2")

    assert first["skipped_duplicates"] == 0
    # The fake vision reads the same two items again, so both are skipped.
    assert second["skipped_duplicates"] == 2
    lesson = second["lesson"]
    assert lesson["lesson_id"] == first["lesson"]["lesson_id"]
    assert lesson["scope"]["pages"] == ["1", "2", "3"]
    assert len(lesson["content_items"]) == 2
    assert len(lesson["source_images"]) == 2
    assert second["session"]["scope"]["pages"] == ["1", "2", "3"]


def test_lesson_batches_list_each_import(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = import_pages(client, ["1", "2"], operation_id="batch-import-1")
    import_pages(client, ["3"], operation_id="batch-import-2")
    lesson_id = first["lesson"]["lesson_id"]

    response = client.get(f"/api/lessons/{lesson_id}/batches")

    assert response.status_code == 200
    batches = response.json()
    assert [batch["operation_id"] for batch in batches] == ["batch-import-1", "batch-import-2"]
    assert [batch["pages"] for batch in batches] == [["1", "2"], ["3"]]
    assert len(batches[0]["source_images"]) == 1
    assert batches[0]["content_ids"] == ["word-school", "grammar-simple-present"]
    assert batches[1]["content_ids"] == []
    assert batches[1]["skipped_duplicates"] == 2


def test_lesson_batches_for_an_unknown_lesson_is_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/lessons/junior-high-grade-9-english-lesson-09/batches")

    assert response.status_code == 404


def test_lesson_source_image_is_served_with_its_real_type(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    imported = import_pages(client, ["1"], operation_id="image-import-1")
    lesson = imported["lesson"]

    response = client.get(
        f"/api/lessons/{lesson['lesson_id']}/images/{lesson['source_images'][0]}"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == PNG_BYTES


def test_lesson_source_image_of_unknown_type_is_not_served_as_an_image(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    imported = import_pages(client, ["1"], operation_id="image-import-1", image=b"not an image")
    lesson = imported["lesson"]

    response = client.get(
        f"/api/lessons/{lesson['lesson_id']}/images/{lesson['source_images'][0]}"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"


def test_lesson_source_image_lookup_rejects_other_images_and_lessons(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    imported = import_pages(client, ["1"], operation_id="image-import-1")
    lesson = imported["lesson"]
    lesson_id = lesson["lesson_id"]

    assert client.get(f"/api/lessons/{lesson_id}/images/image-unknown").status_code == 404
    assert client.get(f"/api/lessons/{lesson_id}/images/..%5Clesson.md").status_code == 404
    assert client.get(
        f"/api/lessons/junior-high-grade-9-english-lesson-09/images/{lesson['source_images'][0]}"
    ).status_code == 404
