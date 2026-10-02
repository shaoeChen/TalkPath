from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections import Counter
import pytest
import pytest_asyncio

from talkpath.adapters.fake_services import (
    FakeVisionService, FakeTextService, FakeSpeechToTextService, FakeTextToSpeechService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.adapters.sqlite_page_import import SQLitePageImportRepository
from talkpath.application.session_service import SessionService
from talkpath.application.page_import_service import PageImportService
from talkpath.domain.models import CourseScope, SessionState
from talkpath.domain.errors import RepositoryError
from talkpath.domain.page_import import PageUpload, PageImportConflict, InvalidPageImport


class PageVision(FakeVisionService):
    def __init__(self):
        self.calls = Counter()
        self.fail_once = set()
        self.gate = None
        self.entered = asyncio.Event()

    async def extract_lesson(self, images, scope, *, operation_id):
        page = scope.pages[0]
        self.calls[page] += 1
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if page in self.fail_once:
            self.fail_once.remove(page)
            raise RuntimeError("private provider details")
        draft = await super().extract_lesson(images, scope, operation_id=operation_id)
        return draft.model_copy(update={"passage": f"Text of page {page}."})


@pytest_asyncio.fixture
async def imports(tmp_path):
    lessons = LessonLensMarkdownRepository(tmp_path / "lessons")
    scope = CourseScope(program="junior high", grade="7", subject="English", lesson="1", textbook="Book", lesson_id="junior-high-grade-7-english-lesson-01", pages=["1"])
    seed = await FakeVisionService().extract_lesson([], scope, operation_id="seed")
    lessons.save_lesson_draft(seed)
    session = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=lessons, vision_service=PageVision(), text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(), text_to_speech_service=FakeTextToSpeechService(),
        upload_root=tmp_path / "uploads",
    )
    service = PageImportService(session, SQLitePageImportRepository(tmp_path / "progress.sqlite"), tmp_path / "uploads" / "page-imports")
    service.lesson_id = seed.lesson_id
    await service.start()
    try:
        yield service
    finally:
        await service.stop()


def uploads(*pages):
    return [PageUpload(str(page), f"photo{page}".encode(), "image/png") for page in pages]


@pytest.mark.asyncio
async def test_partial_failure_and_only_failed_page_retries(imports):
    vision = imports.session_service.vision_service
    vision.fail_once.add("13")
    job = await imports.submit(imports.lesson_id, "submit", uploads(12, 13, 14, 15, 16))
    await imports.join()
    job = imports.repository.get_job(job.job_id)
    assert [p.status.value for p in job.pages] == ["succeeded", "failed", "succeeded", "succeeded", "succeeded"]
    assert "private" not in job.pages[1].error_message
    assert imports.get_source_path(job.job_id, job.pages[1].page_id).read_bytes() == b"photo13"
    completion = job.completion_revision
    await imports.retry_page(job.job_id, job.pages[1].page_id, "retry13")
    await imports.join()
    final = imports.repository.get_job(job.job_id)
    assert final.counts["succeeded"] == 5
    assert final.completion_revision > completion
    assert vision.calls == Counter({"12": 1, "13": 2, "14": 1, "15": 1, "16": 1})
    lesson = imports.session_service.get_lesson(imports.lesson_id)
    assert lesson.scope.pages == ["1", "12", "14", "15", "16", "13"]
    assert len(imports.session_service.lesson_repository.list_lessons()) == 1


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_and_snapshot_is_durable(imports):
    queue = imports.subscribe()
    job = await imports.submit(imports.lesson_id, "submit", uploads(12))
    imports.unsubscribe(queue)
    await imports.join()
    reopened = SQLitePageImportRepository(imports.repository.database_path)
    assert reopened.get_job(job.job_id).pages[0].status.value == "succeeded"


@pytest.mark.asyncio
async def test_active_duplicate_and_retry_are_rejected(imports):
    vision = imports.session_service.vision_service
    vision.gate = asyncio.Event()
    job = await imports.submit(imports.lesson_id, "submit", uploads(12))
    await vision.entered.wait()
    try:
        duplicate = await imports.submit(imports.lesson_id, "submit", uploads(12))
        assert duplicate.job_id == job.job_id
        with pytest.raises(PageImportConflict) as conflict:
            await imports.submit(imports.lesson_id, "other", uploads(12))
        assert conflict.value.job_id == job.job_id
        with pytest.raises(PageImportConflict):
            await imports.retry_page(job.job_id, job.pages[0].page_id, "retry")
    finally:
        vision.gate.set()
        await imports.join()


@pytest.mark.asyncio
async def test_restart_interrupts_unsaved_pages_without_calling_model(imports):
    job = await imports.submit(imports.lesson_id, "submit", uploads(12))
    await imports.join()
    page = job.pages[0]
    with sqlite3.connect(imports.repository.database_path) as db:
        db.execute("UPDATE lesson_page_import_pages SET status='running', import_operation_id='unsaved' WHERE page_id=?", (page.page_id,))
    calls = imports.session_service.vision_service.calls.copy()
    await imports.recover_pending()
    assert imports.repository.get_job(job.job_id).pages[0].status.value == "interrupted"
    assert imports.session_service.vision_service.calls == calls


@pytest.mark.asyncio
async def test_saved_marker_reconciles_without_duplicate_model_call(imports):
    job = await imports.submit(imports.lesson_id, "submit", uploads(12))
    await imports.join()
    with sqlite3.connect(imports.repository.database_path) as db:
        db.execute("UPDATE lesson_page_import_pages SET status='running' WHERE page_id=?", (job.pages[0].page_id,))
    await imports.recover_pending()
    assert imports.repository.get_job(job.job_id).pages[0].status.value == "succeeded"
    assert imports.session_service.vision_service.calls == Counter({"12": 1})


@pytest.mark.asyncio
async def test_validation_is_before_job_creation(imports):
    for invalid in [PageUpload("", b"photo", "image/png"), PageUpload("12", b"", "image/png"), PageUpload("12", b"x", "text/plain")]:
        with pytest.raises(InvalidPageImport):
            await imports.submit(imports.lesson_id, "bad", [invalid])
    assert imports.repository.list_jobs() == []


@pytest.mark.asyncio
async def test_existing_page_overlap_requires_confirmation(imports):
    with pytest.raises(PageImportConflict):
        await imports.submit(imports.lesson_id, "submit", uploads(1))
    job = await imports.submit(imports.lesson_id, "submit", uploads(1), allow_overlap=True)
    await imports.join()
    assert imports.repository.get_job(job.job_id).counts["succeeded"] == 1


@pytest.mark.asyncio
async def test_cancelled_retry_still_enqueues_committed_page(imports, monkeypatch):
    imports.session_service.vision_service.fail_once.add("12")
    job = await imports.submit(imports.lesson_id, "submit", uploads(12))
    await imports.join()
    entered, release = threading.Event(), threading.Event()
    original = imports.repository.retry
    def slow_retry(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(imports.repository, "retry", slow_retry)
    task = asyncio.create_task(imports.retry_page(job.job_id, job.pages[0].page_id, "retry"))
    assert await asyncio.to_thread(entered.wait, 3)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await imports.join()
    assert imports.repository.get_job(job.job_id).counts["succeeded"] == 1


@pytest.mark.asyncio
async def test_photo_preparation_does_not_block_event_loop(imports, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = imports.session_service.upload_image
    def slow_upload(*args, **kwargs):
        entered.set()
        assert release.wait(0.5)
        return original(*args, **kwargs)
    monkeypatch.setattr(imports.session_service, "upload_image", slow_upload)
    await imports.submit(imports.lesson_id, "submit", uploads(12))
    assert await asyncio.to_thread(entered.wait, 3)
    release.set()
    await imports.join()
    assert imports.repository.get_job(imports.repository.list_jobs()[0].job_id).counts["succeeded"] == 1


@pytest.mark.asyncio
async def test_import_state_write_does_not_block_event_loop(imports, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = imports.session_service.progress_repository.save_session
    def slow_save(session):
        if session.state == SessionState.EXTRACTING:
            entered.set()
            assert release.wait(0.5)
        return original(session)
    monkeypatch.setattr(imports.session_service.progress_repository, "save_session", slow_save)
    job = await imports.submit(imports.lesson_id, "submit", uploads(12))
    assert await asyncio.to_thread(entered.wait, 3)
    release.set()
    await imports.join()
    assert imports.repository.get_job(job.job_id).counts["succeeded"] == 1


@pytest.mark.asyncio
async def test_cancelled_submit_still_processes_committed_job(imports, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = imports.repository.create_job
    def slow_create(job):
        entered.set()
        assert release.wait(5)
        return original(job)
    monkeypatch.setattr(imports.repository, "create_job", slow_create)
    task = asyncio.create_task(imports.submit(imports.lesson_id, "submit", uploads(12)))
    assert await asyncio.to_thread(entered.wait, 3)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await imports.join()
    assert imports.repository.list_jobs()[0].counts["succeeded"] == 1


@pytest.mark.asyncio
async def test_source_integrity_and_submission_limits(imports):
    job = await imports.submit(imports.lesson_id, "submit", uploads(12))
    await imports.join()
    with pytest.raises(PageImportConflict):
        await imports.submit(imports.lesson_id, "submit", uploads(14))
    imports.session_service.max_upload_bytes = 2
    with pytest.raises(InvalidPageImport):
        await imports.submit(imports.lesson_id, "too-large", uploads(14))
    path = imports.get_source_path(job.job_id, job.pages[0].page_id)
    path.write_bytes(b"altered")
    with pytest.raises(InvalidPageImport):
        imports.get_source_path(job.job_id, job.pages[0].page_id)
    for key in ["../outside", "a/../../outside", "C:/outside/photo", "a\\photo", "/outside/photo"]:
        with pytest.raises(InvalidPageImport):
            imports._safe_source(key)
    assert len(imports.repository.list_jobs()) == 1


@pytest.mark.asyncio
async def test_shutdown_waits_for_markdown_publication_and_reconciles(imports, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = imports.session_service.lesson_repository.save_lesson_draft
    def slow_save(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(imports.session_service.lesson_repository, "save_lesson_draft", slow_save)
    job = await imports.submit(imports.lesson_id, "submit", uploads(12))
    assert await asyncio.to_thread(entered.wait, 3)
    stopping = asyncio.create_task(imports.stop())
    try:
        await asyncio.sleep(0)
        assert not stopping.done()
    finally:
        release.set()
        await stopping
    assert imports.repository.get_job(job.job_id).counts["succeeded"] == 1
    batches = imports.session_service.get_import_batches(imports.lesson_id)
    assert [b.operation_id for b in batches].count(job.pages[0].import_operation_id) == 1


@pytest.mark.asyncio
async def test_concurrent_sessions_append_without_losing_either_page(imports):
    service = imports.session_service
    sessions = []
    for label in ["12", "13"]:
        session = service.create_session()
        service.upload_image(session.session_id, label.encode(), mime_type="image/png")
        service.confirm_scope(session.session_id, service.get_lesson(imports.lesson_id).scope.model_copy(update={"pages": [label]}))
        sessions.append(session)
    await asyncio.gather(*[
        service.import_lesson(s.session_id, operation_id=f"parallel-{i}")
        for i, s in enumerate(sessions)
    ])
    lesson = service.get_lesson(imports.lesson_id)
    assert set(lesson.scope.pages) == {"1", "12", "13"}
    assert set(b.operation_id for b in service.get_import_batches(imports.lesson_id)) == {"seed", "parallel-0", "parallel-1"}


@pytest.mark.asyncio
async def test_failed_database_acceptance_cleans_only_candidate_photos(imports, monkeypatch):
    accepted = await imports.submit(imports.lesson_id, "submit", uploads(12))
    await imports.join()
    def unavailable(job):
        raise RepositoryError("storage unavailable")
    monkeypatch.setattr(imports.repository, "create_job", unavailable)
    with pytest.raises(RepositoryError):
        await imports.submit(imports.lesson_id, "other", uploads(14))
    assert [p.name for p in imports.source_root.iterdir()] == [accepted.job_id]
    assert imports.get_source_path(accepted.job_id, accepted.pages[0].page_id).read_bytes() == b"photo12"
