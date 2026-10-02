from __future__ import annotations

import asyncio
import pytest

from talkpath.adapters.fake_services import (
    FakeVisionService, FakeTextService, FakeSpeechToTextService, FakeTextToSpeechService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.application.session_service import SessionService
from talkpath.domain.models import CourseScope


class GatedVision(FakeVisionService):
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def extract_lesson(self, images, scope, *, operation_id):
        self.entered.set()
        await self.release.wait()
        return await super().extract_lesson(images, scope, operation_id=operation_id)


@pytest.mark.asyncio
async def test_waiting_import_does_not_hold_activity_lock(tmp_path):
    repository = LessonLensMarkdownRepository(tmp_path / "lessons")
    scope = CourseScope(program="junior high", grade="7", subject="English", lesson="1", pages=["1"])
    seed = await FakeVisionService().extract_lesson([], scope, operation_id="seed")
    repository.save_lesson_draft(seed)
    vision = GatedVision()
    service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=repository, vision_service=vision, text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(), text_to_speech_service=FakeTextToSpeechService(),
        upload_root=tmp_path / "uploads",
    )
    reading = service.create_session(lesson_id=seed.lesson_id)
    uploading = service.create_session()
    service.upload_image(uploading.session_id, b"page", mime_type="image/png")
    service.confirm_scope(uploading.session_id, scope)
    importing = asyncio.create_task(service.import_lesson(uploading.session_id, operation_id="import"))
    await vision.entered.wait()
    try:
        activity = await asyncio.wait_for(service.generate_activity(
            reading.session_id, activity_type="vocabulary_practice", operation_id="activity"
        ), timeout=1)
        assert activity.activity.lesson_id == seed.lesson_id
    finally:
        vision.release.set()
        await importing


def test_repository_has_reentrant_publication_lock(tmp_path):
    repository = LessonLensMarkdownRepository(tmp_path / "lessons")
    with repository.locked():
        with repository.locked():
            assert repository.list_lessons() == []
