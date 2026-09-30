from __future__ import annotations

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
from talkpath.domain.errors import (
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    RepositoryError,
)
from talkpath.agent.pi_rpc import PiProcessExited

import base64


FIXTURE_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def scope_payload() -> dict[str, object]:
    return {
        "program": "junior high",
        "grade": "7",
        "subject": "English",
        "lesson": "1",
    }


class FakePi:
    async def prompt(self, message: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(response=SimpleNamespace(payload={}), events=())


class PiExit(FakePi):
    async def prompt(self, message: str, **kwargs: object) -> SimpleNamespace:
        raise PiProcessExited(17)


class VisionTimeout(FakeVisionService):
    async def extract_lesson(self, *args: object, **kwargs: object):
        raise ProviderTimeout("vision timed out")


class VisionUnavailable(FakeVisionService):
    async def extract_lesson(self, *args: object, **kwargs: object):
        raise ProviderUnavailable("vision unavailable")


class VisionInvalid(FakeVisionService):
    async def extract_lesson(self, *args: object, **kwargs: object):
        raise ProviderResponseInvalid("vision response invalid")

class VisionUnknown(FakeVisionService):
    async def extract_lesson(self, *args: object, **kwargs: object):
        raise RuntimeError("secret-vision-token private-provider-payload")


class WriteFailureRepository(LessonLensMarkdownRepository):
    def save_lesson_draft(
        self, draft, source_references=None, import_batches=None
    ) -> None:
        raise RepositoryError("LessonLens Markdown write failed")


class TTSUnavailable(FakeTextToSpeechService):
    async def synthesize(self, *args: object, **kwargs: object):
        raise ProviderUnavailable("TTS unavailable")


def make_service(
    root: Path,
    *,
    vision=None,
    pi=None,
    tts=None,
    lessonlens=None,
    max_upload_bytes: int = 10 * 1024 * 1024,
    agent_backend: str = "direct",
) -> SessionService:
    return SessionService(
        progress_repository=SQLiteProgressRepository(root / "progress.sqlite"),
        lesson_repository=lessonlens or LessonLensMarkdownRepository(root / "lessonlens"),
        vision_service=vision or FakeVisionService(),
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=tts or FakeTextToSpeechService(),
        pi_client=pi or FakePi(),
        upload_root=root / "uploads",
        agent_backend=agent_backend,
        max_upload_bytes=max_upload_bytes,
    )


def error(response, status: int, code: str, retryable: bool) -> None:
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["retryable"] is retryable


def test_invalid_images_are_rejected_without_persisting_a_source(tmp_path: Path) -> None:
    service = make_service(tmp_path, max_upload_bytes=len(FIXTURE_IMAGE) - 1)
    client = TestClient(create_app(services=service, testing=True))
    session_id = client.post("/api/sessions").json()["session_id"]

    empty = client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("empty.png", b"", "image/png")},
    )
    error(empty, 409, "upload_validation_error", True)

    oversized = client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("large.png", FIXTURE_IMAGE, "image/png")},
    )
    error(oversized, 409, "upload_validation_error", True)

    service = make_service(tmp_path / "incomplete")
    client = TestClient(create_app(services=service, testing=True))
    incomplete_session = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{incomplete_session}/images",
        files={"file": ("partial.png", b"fake-image", "image/png")},
    ).status_code == 200
    reference = service.get_session(incomplete_session).source_images[0]
    Path(reference.path).write_bytes(b"partial")
    assert client.post(
        f"/api/sessions/{incomplete_session}/scope", json=scope_payload()
    ).status_code == 200
    incomplete = client.post(
        f"/api/sessions/{incomplete_session}/import",
        json={"operation_id": "incomplete-image"},
    )
    error(incomplete, 409, "upload_validation_error", True)
    assert client.get(f"/api/sessions/{incomplete_session}").json()["state"] == "FAILED"


def prepare_import(client: TestClient) -> str:
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("page.png", FIXTURE_IMAGE, "image/png")},
    ).status_code == 200
    return session_id


@pytest.mark.parametrize(
    ("name", "service_kwargs", "status", "code"),
    [
        ("vision_timeout", {"vision": VisionTimeout()}, 504, "provider_timeout"),
        (
            "vision_unavailable",
            {"vision": VisionUnavailable()},
            503,
            "provider_unavailable",
        ),
        (
            "vision_invalid",
            {"vision": VisionInvalid()},
            502,
            "provider_response_invalid",
        ),        (
            "vision_unknown",
            {"vision": VisionUnknown()},
            500,
            "operation_failed",
        ),
        (
            "pi_exit",
            {"pi": PiExit(), "agent_backend": "pi"},
            503,
            "pi_process_exited",
        ),
        (
            "markdown_write_failure",
            {"lessonlens": None},
            500,
            "repository_error",
        ),
    ],
)
def test_import_failures_mark_session_failed_without_half_written_data(
    tmp_path: Path,
    name: str,
    service_kwargs: dict[str, object],
    status: int,
    code: str,
) -> None:
    if name == "markdown_write_failure":
        service_kwargs["lessonlens"] = WriteFailureRepository(tmp_path / "lessonlens")
    service = make_service(tmp_path, **service_kwargs)
    client = TestClient(create_app(services=service, testing=True))
    session_id = prepare_import(client)
    assert client.post(f"/api/sessions/{session_id}/scope", json=scope_payload()).status_code == 200

    failed = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": f"{name}-op"},
    )
    error(failed, status, code, name not in {"vision_invalid", "vision_unknown"})
    if name == "vision_unknown":
        assert failed.json()["detail"] == "lesson import failed"
        assert failed.json()["retryable"] is False
        assert "secret-vision-token" not in failed.text
        assert "private-provider-payload" not in failed.text
    assert client.get(f"/api/sessions/{session_id}").json()["state"] == "FAILED"
    assert client.get("/api/lessons/junior-high-grade-7-english-lesson-01").status_code == 404
    assert client.get(f"/api/sessions/{session_id}/progress").status_code == 200
    assert client.get(f"/api/sessions/{session_id}/progress").json()["attempts"] == []


def test_scope_gate_does_not_start_import_or_write_lesson(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    client = TestClient(create_app(services=service, testing=True))
    session_id = prepare_import(client)

    rejected = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "scope-missing"},
    )
    error(rejected, 409, "scope_not_confirmed", True)
    assert client.get(f"/api/sessions/{session_id}").json()["state"] == "CONFIRM_COURSE_SCOPE"
    assert client.get("/api/lessons/junior-high-grade-7-english-lesson-01").status_code == 404


def test_tts_unavailable_is_retryable_and_does_not_create_learning_records(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path, tts=TTSUnavailable())
    client = TestClient(create_app(services=service, testing=True))
    session_id = client.post("/api/sessions").json()["session_id"]

    response = client.post(
        f"/api/sessions/{session_id}/speech/synthesize",
        json={"operation_id": "tts-failure", "text": "Hello"},
    )
    error(response, 503, "provider_unavailable", True)
    assert client.get(f"/api/sessions/{session_id}/progress").status_code == 200
    assert client.get(f"/api/sessions/{session_id}/progress").json()["attempts"] == []
