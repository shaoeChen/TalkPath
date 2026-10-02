"""Exercise durable worker recovery through real service and repository boundaries."""

from __future__ import annotations

import asyncio
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService,
    FakeTextService,
    FakeTextToSpeechService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_page_import import SQLitePageImportRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.application.page_import_service import PageImportService
from talkpath.application.session_service import SessionService
from talkpath.domain.errors import RepositoryError
from talkpath.domain.models import ContentItem, CourseScope, ImageReference, LessonDraft
from talkpath.domain.page_import import PageStatus, PageUpload


class RecordingVision:
    def __init__(self):
        self.calls = Counter()
        self.images = {}
        self.block_page = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.fail_once = set()

    async def extract_lesson(self, images, scope, *, operation_id):
        page = scope.pages[0]
        self.calls[page] += 1
        self.images.setdefault(page, []).append(images)
        if page == self.block_page:
            self.entered.set()
            await self.release.wait()
        if page in self.fail_once:
            self.fail_once.remove(page)
            raise RuntimeError("transient vision failure")
        return LessonDraft(
            lesson_id=scope.lesson_id,
            scope=scope,
            title=f"Page {page}",
            passage=f"Passage {page}.",
            content_items=[
                ContentItem(
                    content_id="word",
                    type="vocabulary",
                    content={"english": f"word{page}", "chinese": "詞"},
                    source_page=page,
                )
            ],
            source_images=[image.image_id for image in images],
            extraction_status="draft",
            provider="fake",
            model="recording",
            operation_id=operation_id,
        )


class SavingPi:
    """Save via the internal boundary before returning the same draft to import."""

    def __init__(self):
        self.service = None
        self.saves = 0

    async def start(self):
        pass

    async def prompt(self, message, **kwargs):
        payload = kwargs["write_payload"]
        images = [ImageReference.model_validate(image) for image in payload["images"]]
        scope = CourseScope.model_validate(payload["scope"])
        draft = await self.service.extract_lesson(
            session_id=payload["session_id"],
            images=images,
            scope=scope,
            operation_id=payload["operation_id"],
        )
        self.service.save_lesson_draft(
            draft,
            session_id=payload["session_id"],
            operation_id=payload["operation_id"],
            scope=scope,
            source_references=images,
        )
        self.saves += 1
        return SimpleNamespace(
            response=SimpleNamespace(payload={"draft": draft}), events=()
        )


async def make_services(root, *, backend="direct"):
    vision = RecordingVision()
    lessons = LessonLensMarkdownRepository(root / "lessons")
    scope = CourseScope(
        program="junior high", grade="7", subject="English", lesson="1", pages=["1"]
    )
    seed = await vision.extract_lesson([], scope, operation_id="seed")
    lessons.save_lesson_draft(seed)
    vision.calls.clear()
    pi = SavingPi()
    sessions = SessionService(
        progress_repository=SQLiteProgressRepository(root / "progress.sqlite"),
        lesson_repository=lessons,
        vision_service=vision,
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=pi,
        agent_backend=backend,
        upload_root=root / "uploads",
    )
    pi.service = sessions
    imports = PageImportService(
        sessions,
        SQLitePageImportRepository(root / "progress.sqlite"),
        root / "retained-photos",
    )
    return imports, seed.lesson_id, vision, pi


def photos(*pages):
    return [PageUpload(page, f"photo {page}".encode(), "image/png") for page in pages]


@pytest.mark.asyncio
async def test_stop_and_fresh_start_preserve_success_interrupt_remaining_and_retry_only_selected(
    tmp_path,
):
    imports, lesson_id, vision, _ = await make_services(tmp_path)
    await imports.start()
    restarted = None
    try:
        vision.block_page = "3"
        job = await imports.submit(lesson_id, "submit", photos("2", "3", "4"))
        await asyncio.wait_for(vision.entered.wait(), 5)
        current = imports.repository.get_job(job.job_id)
        assert [page.status for page in current.pages] == [
            PageStatus.SUCCEEDED,
            PageStatus.RUNNING,
            PageStatus.QUEUED,
        ]
        await imports.stop()
        stopped = imports.repository.get_job(job.job_id)
        assert [page.status for page in stopped.pages] == [
            PageStatus.SUCCEEDED,
            PageStatus.INTERRUPTED,
            PageStatus.INTERRUPTED,
        ]
        assert stopped.completion_revision == 1
        calls_before = vision.calls.copy()
        restarted = PageImportService(
            imports.session_service,
            SQLitePageImportRepository(imports.repository.database_path),
            imports.source_root,
        )
        await restarted.start()
        await asyncio.wait_for(restarted.join(), 5)
        assert vision.calls == calls_before
        vision.block_page = None
        await restarted.retry_page(job.job_id, job.pages[1].page_id, "retry3")
        await asyncio.wait_for(restarted.join(), 5)
        final = restarted.repository.get_job(job.job_id)
        assert [page.status for page in final.pages] == [
            PageStatus.SUCCEEDED,
            PageStatus.SUCCEEDED,
            PageStatus.INTERRUPTED,
        ]
        assert vision.calls == Counter({"2": 1, "3": 2})
        assert final.completion_revision == 2
        assert imports.session_service.get_lesson(lesson_id).scope.pages == [
            "1",
            "2",
            "3",
        ]
    finally:
        if restarted is not None:
            await restarted.stop()
        await imports.stop()


@pytest.mark.asyncio
async def test_saved_lesson_with_failed_sql_finish_recovers_without_another_model_call(
    tmp_path, monkeypatch
):
    imports, lesson_id, vision, _ = await make_services(tmp_path)
    await imports.start()
    try:

        def unavailable(*args, **kwargs):
            raise RepositoryError("storage unavailable")

        with monkeypatch.context() as outage:
            outage.setattr(imports.repository, "finish", unavailable)
            outage.setattr(imports.repository, "reconcile", unavailable)
            job = await imports.submit(lesson_id, "submit", photos("2"))
            with pytest.raises(RepositoryError):
                await asyncio.wait_for(imports.join(), 5)
            assert (
                imports.repository.get_job(job.job_id).pages[0].status
                == PageStatus.RUNNING
            )
            batches = imports.session_service.lesson_repository.get_import_batches(
                lesson_id
            )
            assert [batch.operation_id for batch in batches].count(
                job.pages[0].import_operation_id
            ) == 1
        await imports.stop()
        restarted = PageImportService(
            imports.session_service,
            SQLitePageImportRepository(imports.repository.database_path),
            imports.source_root,
        )
        await restarted.start()
        try:
            await asyncio.wait_for(restarted.join(), 5)
            final = restarted.repository.get_job(job.job_id)
            assert final.pages[0].status == PageStatus.SUCCEEDED
            assert final.completion_revision == 1
            assert vision.calls == Counter({"2": 1})
            assert (
                imports.session_service.get_lesson(lesson_id).passage.count(
                    "Passage 2."
                )
                == 1
            )
        finally:
            await restarted.stop()
    finally:
        await imports.stop()


@pytest.mark.asyncio
async def test_retry_uses_retained_photo_and_fresh_session_after_old_upload_expires(
    tmp_path,
):
    imports, lesson_id, vision, _ = await make_services(tmp_path)
    sessions = imports.session_service
    created_session_ids = []
    original_create = sessions.create_session

    def record_create(*args, **kwargs):
        session = original_create(*args, **kwargs)
        created_session_ids.append(session.session_id)
        return session

    sessions.create_session = record_create
    vision.fail_once.add("2")
    await imports.start()
    try:
        job = await imports.submit(lesson_id, "submit", photos("2"))
        await asyncio.wait_for(imports.join(), 5)
        assert (
            imports.repository.get_job(job.job_id).pages[0].status == PageStatus.FAILED
        )
        old_session = sessions.get_session(created_session_ids[0])
        old_image = old_session.source_images[0]
        expired = old_image.model_copy(
            update={"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}
        )
        sessions.progress_repository.save_session(
            old_session.model_copy(update={"source_images": [expired]})
        )
        Path(old_image.path).unlink()
        assert (
            imports.get_source_path(job.job_id, job.pages[0].page_id).read_bytes()
            == b"photo 2"
        )
        await imports.stop()
        await imports.start()
        await imports.retry_page(job.job_id, job.pages[0].page_id, "retry")
        await asyncio.wait_for(imports.join(), 5)
        assert (
            imports.repository.get_job(job.job_id).pages[0].status
            == PageStatus.SUCCEEDED
        )
        assert len(created_session_ids) == 2
        assert created_session_ids[0] != created_session_ids[1]
        fresh = sessions.get_session(created_session_ids[1]).source_images[0]
        assert fresh.image_id != old_image.image_id
        assert fresh.expires_at > datetime.now(timezone.utc)
        assert vision.calls == Counter({"2": 2})
    finally:
        await imports.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["direct", "pi"])
async def test_worker_import_saves_each_page_once_with_pi_internal_double_save(
    tmp_path, backend
):
    imports, lesson_id, vision, pi = await make_services(tmp_path, backend=backend)
    await imports.start()
    try:
        job = await imports.submit(lesson_id, "submit", photos("2", "3"))
        await asyncio.wait_for(imports.join(), 5)
        assert imports.repository.get_job(job.job_id).counts["succeeded"] == 2
        lesson = imports.session_service.get_lesson(lesson_id)
        assert lesson.scope.pages == ["1", "2", "3"]
        assert lesson.passage == "Passage 1.\n\nPassage 2.\n\nPassage 3."
        assert [item.content["english"] for item in lesson.content_items] == [
            "word1",
            "word2",
            "word3",
        ]
        assert len(lesson.source_images) == 2
        assert len(imports.session_service.lesson_repository.list_lessons()) == 1
        batches = imports.session_service.lesson_repository.get_import_batches(
            lesson_id
        )
        assert [batch.operation_id for batch in batches] == [
            "seed",
            *[page.import_operation_id for page in job.pages],
        ]
        assert vision.calls == Counter({"2": 1, "3": 1})
        assert pi.saves == (2 if backend == "pi" else 0)
    finally:
        await imports.stop()


@pytest.mark.asyncio
async def test_pi_prompt_failure_after_internal_save_uses_marker_without_duplicate_import(
    tmp_path, monkeypatch
):
    imports, lesson_id, vision, pi = await make_services(tmp_path, backend="pi")
    original_prompt = pi.prompt

    async def save_then_fail(*args, **kwargs):
        await original_prompt(*args, **kwargs)
        raise RuntimeError("Pi response failed after internal save")

    monkeypatch.setattr(pi, "prompt", save_then_fail)
    await imports.start()
    try:
        job = await imports.submit(lesson_id, "submit", photos("2"))
        await asyncio.wait_for(imports.join(), 5)
        final = imports.repository.get_job(job.job_id)
        assert final.pages[0].status == PageStatus.SUCCEEDED
        assert final.pages[0].error_code is None
        assert final.completion_revision == 1
        assert pi.saves == 1
        assert vision.calls == Counter({"2": 1})
        await imports.stop()
        await imports.start()
        await asyncio.wait_for(imports.join(), 5)
        assert vision.calls == Counter({"2": 1})
        lesson = imports.session_service.get_lesson(lesson_id)
        assert lesson.passage == "Passage 1.\n\nPassage 2."
        assert len(lesson.source_images) == 1
        assert [item.content["english"] for item in lesson.content_items] == [
            "word1",
            "word2",
        ]
        batches = imports.session_service.lesson_repository.get_import_batches(
            lesson_id
        )
        assert [batch.operation_id for batch in batches] == [
            "seed",
            job.pages[0].import_operation_id,
        ]
    finally:
        await imports.stop()


@pytest.mark.asyncio
async def test_start_refuses_unreadable_saved_markers_and_preserves_unknown_page_states(
    tmp_path, monkeypatch
):
    imports, lesson_id, vision, _ = await make_services(tmp_path)
    await imports.start()
    vision.block_page = "3"
    try:
        job = await imports.submit(lesson_id, "submit", photos("2", "3", "4"))
        await asyncio.wait_for(vision.entered.wait(), 5)
        await imports.stop()
        # Restore the crash snapshot: the process could not mark unfinished work
        # interrupted during an abrupt exit, unlike graceful stop above.
        with sqlite3.connect(imports.repository.database_path) as connection:
            connection.execute(
                "UPDATE lesson_page_import_pages SET status='running' WHERE page_id=?",
                (job.pages[1].page_id,),
            )
            connection.execute(
                "UPDATE lesson_page_import_pages SET status='queued' WHERE page_id=?",
                (job.pages[2].page_id,),
            )
        before = imports.repository.get_job(job.job_id)
        calls_before = vision.calls.copy()
        restarted = PageImportService(
            imports.session_service,
            SQLitePageImportRepository(imports.repository.database_path),
            imports.source_root,
        )

        def unreadable(*args, **kwargs):
            raise RepositoryError("saved import markers unavailable")

        with monkeypatch.context() as outage:
            outage.setattr(
                imports.session_service.lesson_repository,
                "get_import_batches",
                unreadable,
            )
            with pytest.raises(RepositoryError, match="markers unavailable"):
                await restarted.start()
            assert restarted.repository.get_job(job.job_id) == before
            assert vision.calls == calls_before
            with pytest.raises(RepositoryError):
                await restarted.submit(lesson_id, "blocked", photos("5"))
        await restarted.start()
        try:
            await asyncio.wait_for(restarted.join(), 5)
            assert vision.calls == calls_before
            assert [
                page.status for page in restarted.repository.get_job(job.job_id).pages
            ] == [PageStatus.SUCCEEDED, PageStatus.INTERRUPTED, PageStatus.INTERRUPTED]
        finally:
            await restarted.stop()
    finally:
        await imports.stop()
