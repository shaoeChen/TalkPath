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
from talkpath.config import Settings
from talkpath.domain.models import CourseScope


TOKEN = "internal-test-token"


def make_client(tmp_path: Path) -> tuple[TestClient, SessionService]:
    service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=FakeVisionService(),
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=object(),
        upload_root=tmp_path / "uploads",
    )
    settings = Settings(_env_file=None, internal_tool_token=TOKEN)
    return TestClient(create_app(settings=settings, services=service, testing=True)), service


def tool_headers() -> dict[str, str]:
    return {"X-TalkPath-Internal-Token": TOKEN}


def make_scope() -> CourseScope:
    return CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )


def test_internal_tools_call_injected_services_and_require_loopback_token(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id = service.create_session().session_id
    image = service.upload_image(session_id, b"approved image", mime_type="image/png")
    scope = make_scope()

    unauthorized = client.post(
        "/internal/tools/extract_lesson",
        json={"operation_id": "extract-1", "scope": scope.model_dump(), "images": []},
    )
    assert unauthorized.status_code == 401

    extracted = client.post(
        "/internal/tools/extract_lesson",
        headers=tool_headers(),
        json={
            "operation_id": "extract-1",
            "session_id": session_id,
            "scope": scope.model_dump(),
            "images": [image.model_dump(mode="json")],
        },
    )
    assert extracted.status_code == 200
    draft = extracted.json()["draft"]
    assert draft["lesson_id"] == scope.lesson_id
    assert draft["operation_id"] == "extract-1"

    saved = client.post(
        "/internal/tools/save_lesson_draft",
        headers=tool_headers(),
        json={
            "operation_id": "save-1",
            "session_id": session_id,
            "scope": scope.model_dump(),
            "draft": draft,
            "source_references": [image.model_dump(mode="json")],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["saved"] is True

    activity_response = client.post(
        "/internal/tools/generate_activity",
        headers=tool_headers(),
        json={
            "operation_id": "activity-1",
            "scope": scope.model_dump(),
            "lesson": draft,
            "activity_type": "vocabulary_practice",
        },
    )
    assert activity_response.status_code == 200
    activity = activity_response.json()["activity"]
    assert activity["lesson_id"] == scope.lesson_id

    evaluation = client.post(
        "/internal/tools/evaluate_answer",
        headers=tool_headers(),
        json={
            "operation_id": "evaluate-1",
            "activity": activity["items"][0],
            "answer": activity["items"][0]["answer"],
        },
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["evaluation"]["correct"] is True

    transcript = client.post(
        "/internal/tools/transcribe_audio",
        headers=tool_headers(),
        json={
            "operation_id": "stt-1",
            "mime_type": "audio/wav",
            "audio_base64": base64.b64encode(b"audio").decode("ascii"),
        },
    )
    assert transcript.status_code == 200
    assert transcript.json()["transcript"]["operation_id"] == "stt-1"

    speech = client.post(
        "/internal/tools/synthesize_speech",
        headers=tool_headers(),
        json={"operation_id": "tts-1", "text": "Hello"},
    )
    assert speech.status_code == 200
    assert speech.json()["audio"]["operation_id"] == "tts-1"

    session_id = client.post("/api/sessions").json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    )
    client.post(f"/api/sessions/{session_id}/scope", json=scope.model_dump())
    result = client.post(
        "/internal/tools/save_learning_result",
        headers=tool_headers(),
        json={
            "operation_id": "result-1",
            "session_id": session_id,
            "lesson_id": scope.lesson_id,
            "activity_id": activity["activity_id"],
            "correct": True,
            "score": 1.0,
            "answer": "school",
            "feedback": "Great job!",
        },
    )
    assert result.status_code == 200
    assert result.json()["attempt"]["activity_id"] == activity["activity_id"]


def test_internal_tool_rejects_credentials_in_payload(tmp_path: Path) -> None:
    client, service = make_client(tmp_path)
    session_id = service.create_session().session_id
    image = service.upload_image(session_id, b"approved image", mime_type="image/png")
    scope = make_scope()

    response = client.post(
        "/internal/tools/extract_lesson",
        headers=tool_headers(),
        json={
            "operation_id": "extract-credential",
            "session_id": session_id,
            "scope": scope.model_dump(),
            "images": [image.model_dump(mode="json")],
            "api_key": "must-not-be-accepted",
        },
    )

    assert response.status_code == 422


def test_internal_tools_reject_image_reference_outside_session_upload_root(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id = service.create_session().session_id
    uploaded = service.upload_image(session_id, b"approved image", mime_type="image/png")
    external = tmp_path / "outside.png"
    external.write_bytes(b"outside")
    forged = uploaded.model_copy(
        update={"path": str(external), "size_bytes": external.stat().st_size}
    )

    response = client.post(
        "/internal/tools/extract_lesson",
        headers=tool_headers(),
        json={
            "operation_id": "extract-external",
            "session_id": session_id,
            "scope": make_scope().model_dump(),
            "images": [forged.model_dump(mode="json")],
        },
    )

    assert response.status_code == 409
