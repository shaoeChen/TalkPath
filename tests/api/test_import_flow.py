from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
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
from talkpath.agent.pi_rpc import ExtensionErrorEvent, MessageUpdateEvent, ToolExecutionEvent
from talkpath.domain.models import CourseScope


class FakePi:
    def __init__(self) -> None:
        self.is_running = False
        self.start_calls = 0
        self.prompts: list[dict[str, object]] = []

    async def start(self) -> None:
        self.start_calls += 1
        self.is_running = True

    async def prompt(self, message: str, **kwargs: object) -> SimpleNamespace:
        self.prompts.append({"message": message, **kwargs})
        return SimpleNamespace(
            response=SimpleNamespace(payload={}),
            events=(
                MessageUpdateEvent(
                    type="message_update",
                    payload={"type": "message_update", "delta": "Extracting"},
                    delta="Extracting",
                    assistant_event_type="text_delta",
                ),
                ToolExecutionEvent(
                    type="tool_execution_start",
                    payload={"type": "tool_execution_start", "toolName": "extract_lesson"},
                    event_type="tool_execution_start",
                    tool_call_id="tool-1",
                    tool_name="extract_lesson",
                    is_error=False,
                ),
                ExtensionErrorEvent(
                    type="extension_error",
                    payload={"type": "extension_error", "message": "recoverable"},
                    message="recoverable",
                ),
            ),
        )


def make_client(
    tmp_path: Path,
    *,
    agent_backend: str = "direct",
) -> tuple[TestClient, FakePi]:
    pi = FakePi()
    service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=FakeVisionService(),
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=pi,
        agent_backend=agent_backend,
        upload_root=tmp_path / "uploads",
    )
    return TestClient(create_app(services=service, testing=True)), pi


def create_scope_payload() -> dict[str, object]:
    return {
        "program": "junior high",
        "grade": "7",
        "subject": "English",
        "lesson": "1",
        "textbook": "TalkPath English",
        "edition": "2026",
        "pages": ["1", "2"],
    }


def test_child_session_import_flow_persists_lesson_and_activity(tmp_path: Path) -> None:
    client, pi = make_client(tmp_path)

    created = client.post("/api/sessions", json={"operation_id": "session-op-1"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    assert created.json()["learner_key"] == "local-child"

    uploaded = client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("../../book.png", b"book page", "image/png")},
    )
    assert uploaded.status_code == 200
    image = uploaded.json()
    assert image["image_id"].startswith("image-")
    assert image["mime_type"] == "image/png"
    assert "path" not in image
    assert "book.png" not in image["image_id"]

    confirmed = client.post(
        f"/api/sessions/{session_id}/scope",
        json=create_scope_payload(),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["state"] == "CONFIRM_COURSE_SCOPE"
    assert confirmed.json()["scope"]["lesson_id"] == "junior-high-grade-7-english-lesson-01--talkpath-english"

    imported = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-op-1"},
    )
    assert imported.status_code == 200
    assert imported.json()["session"]["state"] == "ASK_GENERATE_ACTIVITY"
    assert imported.json()["lesson"]["lesson_id"] == "junior-high-grade-7-english-lesson-01--talkpath-english"
    assert pi.start_calls == 0
    assert pi.prompts == []
    assert (tmp_path / "lessonlens" / "curricula").exists()

    generated = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={"operation_id": "activity-op-1", "activity_type": "vocabulary_practice"},
    )
    assert generated.status_code == 200
    assert generated.json()["session"]["state"] == "READY_FOR_PRACTICE"
    assert generated.json()["activity"]["lesson_id"] == imported.json()["lesson"]["lesson_id"]
    assert generated.json()["activity"]["items"]
    assert all("answer" not in item for item in generated.json()["activity"]["items"])

    session = client.get(f"/api/sessions/{session_id}")
    assert session.status_code == 200
    assert session.json()["source_images"][0]["image_id"] == image["image_id"]

    lesson = client.get("/api/lessons/junior-high-grade-7-english-lesson-01--talkpath-english")
    assert lesson.status_code == 200
    assert lesson.json()["content_items"]


def test_pi_backend_import_prompts_pi_with_write_payload(tmp_path: Path) -> None:
    client, pi = make_client(tmp_path, agent_backend="pi")
    session_id = client.post("/api/sessions", json={"operation_id": "pi-session-op"}).json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json=create_scope_payload(),
    ).status_code == 200

    imported = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "pi-import-op-1"},
    )

    assert imported.status_code == 200
    assert pi.start_calls == 1
    assert len(pi.prompts) == 1
    write_payload = pi.prompts[0]["write_payload"]
    assert write_payload["session_id"] == session_id
    assert write_payload["operation_id"] == "pi-import-op-1"
    assert write_payload["scope"]["lesson_id"] == "junior-high-grade-7-english-lesson-01--talkpath-english"
    assert write_payload["images"][0]["path"]
    assert write_payload["images"][0]["mime_type"] == "image/png"


def test_import_requires_confirmed_scope_and_websocket_has_session_event(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    session_id = client.post("/api/sessions").json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    )

    rejected = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-before-scope"},
    )
    assert rejected.status_code == 409

    with client.websocket_connect(f"/ws/sessions/{session_id}") as websocket:
        event = websocket.receive_json()
        assert event["type"] == "session"
        assert event["session"]["session_id"] == session_id


@pytest.mark.asyncio
async def test_session_event_stream_receives_serialized_agent_events_during_import(
    tmp_path: Path,
) -> None:
    service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=FakeVisionService(),
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=FakePi(),
        agent_backend="pi",
        upload_root=tmp_path / "uploads",
    )
    session_id = service.create_session().session_id
    service.upload_image(session_id, b"book page", mime_type="image/png")
    service.confirm_scope(session_id, CourseScope(**create_scope_payload()))
    queue = service.subscribe(session_id)
    try:
        await asyncio.wait_for(
            service.import_lesson(session_id, operation_id="import-events-1"),
            timeout=5,
        )
        received: list[dict[str, object]] = []
        while not queue.empty():
            event = queue.get_nowait()
            if event["type"] == "agent_event":
                received.append(event)
    finally:
        service.unsubscribe(session_id, queue)

    assert {event["payload"]["type"] for event in received} == {
        "message_update",
        "tool_execution_start",
        "extension_error",
    }
    assert all(event["session_id"] == session_id for event in received)
    assert all("state" in event for event in received)


def test_scope_requires_all_course_fields(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    session_id = client.post("/api/sessions").json()["session_id"]

    response = client.post(
        f"/api/sessions/{session_id}/scope",
        json={"program": "junior high", "grade": "7", "lesson": "1"},
    )

    assert response.status_code == 422
