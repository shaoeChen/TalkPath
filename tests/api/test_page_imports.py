import asyncio
import json
import threading
import pytest
from fastapi.testclient import TestClient

from talkpath.api.app import create_app
from talkpath.adapters.fake_services import FakeVisionService, FakeTextService, FakeSpeechToTextService, FakeTextToSpeechService
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.application.session_service import SessionService
from talkpath.domain.models import CourseScope


class BlockingVision(FakeVisionService):
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    async def extract_lesson(self, images, scope, *, operation_id):
        self.entered.set()
        await asyncio.to_thread(self.release.wait, 10)
        return await super().extract_lesson(images, scope, operation_id=operation_id)


@pytest.fixture
def api_client(tmp_path):
    lessons = LessonLensMarkdownRepository(tmp_path / "lessons")
    scope = CourseScope(program="junior high", grade="7", subject="English", lesson="1", pages=["1"])
    seed = asyncio.run(FakeVisionService().extract_lesson([], scope, operation_id="seed"))
    lessons.save_lesson_draft(seed)
    vision = BlockingVision()
    service = SessionService(progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=lessons, vision_service=vision, text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(), text_to_speech_service=FakeTextToSpeechService(),
        upload_root=tmp_path / "uploads")
    with TestClient(create_app(services=service, testing=True)) as client:
        try:
            yield client, service, vision, seed.lesson_id
        finally:
            vision.release.set()


def submit(client, lesson_id, **extra):
    return client.post(f"/api/lessons/{lesson_id}/page-imports",
        data={"operation_id": "submit", "pages": json.dumps(["12", "13"]), **extra},
        files=[("files", ("p12.png", b"photo12", "image/png")), ("files", ("p13.png", b"photo13", "image/png"))])


def test_submission_returns_202_and_other_operations_continue(api_client):
    client, service, vision, lesson_id = api_client
    response = submit(client, lesson_id)
    assert response.status_code == 202, response.text
    assert vision.entered.wait(3)
    job = response.json()
    assert "source_key" not in json.dumps(job)
    assert "scope_json" not in job
    assert client.get("/health").status_code == 200
    assert client.get("/api/lessons").status_code == 200
    session_id = client.post("/api/sessions", json={"lesson_id": lesson_id}).json()["session_id"]
    assert client.post(f"/api/sessions/{session_id}/activities/generate",
        json={"operation_id": "practice", "activity_type": "vocabulary_practice"}).status_code == 200
    assert submit(client, lesson_id).json()["job_id"] == job["job_id"]
    assert client.get(f"/api/lesson-page-imports/{job['job_id']}").status_code == 200
    page_id = job["pages"][0]["page_id"]
    image = client.get(f"/api/lesson-page-imports/{job['job_id']}/pages/{page_id}/image")
    assert image.content == b"photo12"
    assert client.get(f"/api/lesson-page-imports/{job['job_id']}/pages/other/image").status_code == 404


def test_server_owns_course_identity_and_validates_pairing(api_client):
    client, _, _, lesson_id = api_client
    assert submit(client, lesson_id, textbook="different").status_code == 422
    response = client.post(f"/api/lessons/{lesson_id}/page-imports",
        data={"operation_id": "bad", "pages": '["12","13"]'},
        files={"files": ("p.png", b"x", "image/png")})
    assert response.status_code == 422
    assert client.get("/api/lesson-page-imports").json() == []
    check = client.post(f"/api/lessons/{lesson_id}/page-imports/check", json={"pages": ["1"]})
    assert check.json()["overlapping_pages"] == ["1"]


def test_websocket_reconnect_snapshot_and_disconnect_does_not_cancel(api_client):
    client, _, vision, lesson_id = api_client
    response = submit(client, lesson_id)
    assert response.status_code == 202
    with client.websocket_connect("/ws/lesson-page-imports") as ws:
        event = ws.receive_json()
        assert event["type"] == "page_import_snapshot"
        assert event["jobs"][0]["job_id"] == response.json()["job_id"]
    vision.release.set()
    with client.websocket_connect("/ws/lesson-page-imports") as ws:
        event = ws.receive_json()
        while event["type"] != "page_import_updated" or event["job"]["status"] != "completed":
            if event["type"] == "page_import_snapshot" and event["jobs"][0]["status"] == "completed":
                break
            event = ws.receive_json()
    final = client.get(f"/api/lesson-page-imports/{response.json()['job_id']}").json()
    assert final["counts"]["succeeded"] == 2


def test_storage_error_does_not_expose_local_paths(api_client):
    client, service, _, lesson_id = api_client
    path = service.lesson_repository._lesson_dir(lesson_id) / "lesson.md"
    path.write_text("broken document", encoding="utf-8")
    response = client.post(f"/api/lessons/{lesson_id}/page-imports/check", json={"pages": ["12"]})
    assert response.status_code == 500
    assert response.json()["code"] == "repository_error"
    assert str(path) not in response.json()["detail"]
    assert "missing YAML" not in response.text
