"""Durable page imports whose lifetime is independent of browser requests."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from talkpath.domain.errors import RepositoryError
from talkpath.domain.lesson_merge import overlapping_pages
from talkpath.domain.models import CourseScope
from talkpath.domain.page_import import (
    ImportJob, ImportPage, PageStatus, PageUpload,
    InvalidPageImport, PageImportConflict, PageImportNotFound,
)

logger = logging.getLogger(__name__)
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class PageImportService:
    def __init__(self, session_service, repository, source_root: Path):
        self.session_service = session_service
        self.repository = repository
        self.source_root = Path(source_root).resolve()
        self._queue = asyncio.Queue()
        self._worker = None
        self._accepting = False
        self._fatal = False
        self._submit_lock = asyncio.Lock()
        self._subscribers = set()

    async def start(self):
        if self._worker is not None and not self._worker.done():
            return
        await self.recover_pending()
        self._fatal = False
        self._accepting = True
        self._worker = asyncio.create_task(self._run(), name="lesson-page-import-worker")

    async def stop(self):
        async with self._submit_lock:
            self._accepting = False
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        await self.recover_pending()

    async def join(self):
        waiter = asyncio.create_task(self._queue.join())
        try:
            if self._worker is not None:
                done, _ = await asyncio.wait([waiter, self._worker], return_when=asyncio.FIRST_COMPLETED)
                if self._worker in done and not waiter.done():
                    raise RepositoryError("page import worker stopped")
            await waiter
            if self._fatal:
                raise RepositoryError("page import worker stopped")
        finally:
            if not waiter.done():
                waiter.cancel()

    def subscribe(self):
        queue = asyncio.Queue(maxsize=64)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue):
        self._subscribers.discard(queue)

    def _publish(self, job):
        for queue in tuple(self._subscribers):
            if queue.full():
                # Force a fresh snapshot rather than blocking the worker.
                self.unsubscribe(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
            else:
                queue.put_nowait(job)

    def _ready(self):
        if not self._accepting or self._fatal:
            raise RepositoryError("page import service is not available")

    def check(self, lesson_id, pages):
        lesson = self.session_service.get_lesson(lesson_id)
        if not pages or any(not isinstance(page, str) or not page.strip() for page in pages):
            raise InvalidPageImport("Enter a page number for each photo.")
        return overlapping_pages(lesson.scope.pages, pages)

    async def submit(self, lesson_id, operation_id, uploads: list[PageUpload], allow_overlap=False):
        accepting = asyncio.create_task(self._submit(lesson_id, operation_id, uploads, allow_overlap))
        try:
            return await asyncio.shield(accepting)
        except asyncio.CancelledError:
            await accepting
            raise

    async def _submit(self, lesson_id, operation_id, uploads, allow_overlap):
        async with self._submit_lock:
            self._ready()
            if not operation_id or not operation_id.strip() or not uploads:
                raise InvalidPageImport("Choose photos and enter their page numbers.")
            for upload in uploads:
                if not upload.page_label.strip() or upload.mime_type not in IMAGE_TYPES:
                    raise InvalidPageImport("Enter page numbers and choose JPEG, PNG, WEBP or GIF photos.")
                if not upload.content or len(upload.content) > self.session_service.max_upload_bytes:
                    raise InvalidPageImport("A photo is empty or exceeds the upload size limit.")
            fingerprint = self._fingerprint(lesson_id, uploads)
            existing = next((job for job in await asyncio.to_thread(self.repository.list_jobs)
                             if job.operation_id == operation_id), None)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise PageImportConflict("This submission ID was already used for different photos.")
                return existing
            lesson = await asyncio.to_thread(self.session_service.get_lesson, lesson_id)
            overlap = overlapping_pages(lesson.scope.pages, [u.page_label for u in uploads])
            if overlap and not allow_overlap:
                error = PageImportConflict("These pages are already in this lesson. Confirm Add anyway to continue.")
                error.overlapping_pages = overlap
                raise error
            active = next((job for job in await asyncio.to_thread(self.repository.list_jobs, lesson_id)
                if any(p.status in {PageStatus.QUEUED, PageStatus.RUNNING}
                    and any(p.page_label == u.page_label.strip() and p.sha256 == hashlib.sha256(u.content).hexdigest()
                            for u in uploads) for p in job.pages)), None)
            if active is not None:
                error = PageImportConflict("This photo is already being processed.")
                error.job_id = active.job_id
                raise error
            job_id = uuid4().hex
            pages = []
            for ordinal, upload in enumerate(uploads):
                page_id = uuid4().hex
                pages.append(ImportPage(
                    page_id=page_id, ordinal=ordinal, page_label=upload.page_label.strip(), status=PageStatus.QUEUED,
                    source_key=f"{job_id}/{page_id}", sha256=hashlib.sha256(upload.content).hexdigest(),
                    mime_type=upload.mime_type, size_bytes=len(upload.content),
                    import_operation_id=f"page-import:{page_id}",
                ))
            job = ImportJob(job_id=job_id, operation_id=operation_id, lesson_id=lesson.lesson_id,
                            scope_json=lesson.scope.model_dump_json(), fingerprint=fingerprint, pages=pages)
            await asyncio.to_thread(self._write_sources, job, uploads)
            try:
                created = await asyncio.to_thread(self.repository.create_job, job)
            except BaseException:
                # Commit may have succeeded even if the response was interrupted.
                saved = await asyncio.to_thread(self.repository.get_job, job_id)
                if saved is None:
                    await asyncio.to_thread(self._remove_candidate_sources, job_id)
                raise
            if created.job_id != job_id:
                await asyncio.to_thread(self._remove_candidate_sources, job_id)
                return created
            for page in created.pages:
                self._queue.put_nowait((job_id, page.page_id))
            self._publish(created)
            return created

    @staticmethod
    def _fingerprint(lesson_id, uploads):
        value = {"lesson_id": lesson_id, "pages": [
            [u.page_label.strip(), u.mime_type, hashlib.sha256(u.content).hexdigest()] for u in uploads
        ]}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _safe_source(self, source_key):
        relative = Path(source_key)
        if PureWindowsPath(source_key).is_absolute() or relative.is_absolute() or "\\" in source_key:
            raise InvalidPageImport("The saved photo is unavailable.")
        if len(relative.parts) != 2 or any(not part or part in {".", ".."} for part in relative.parts):
            raise InvalidPageImport("The saved photo is unavailable.")
        candidate = self.source_root / relative
        current = self.source_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or current.is_junction():
                raise InvalidPageImport("The saved photo is unavailable.")
        if not candidate.resolve().is_relative_to(self.source_root):
            raise InvalidPageImport("The saved photo is unavailable.")
        return candidate

    def _write_sources(self, job, uploads):
        try:
            for page, upload in zip(job.pages, uploads, strict=True):
                path = self._safe_source(page.source_key)
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                        temporary = Path(stream.name)
                        stream.write(upload.content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        except OSError as exc:
            self._remove_candidate_sources(job.job_id)
            raise RepositoryError("could not retain page photos") from exc

    def _remove_candidate_sources(self, job_id):
        folder = self.source_root / job_id
        if folder.is_symlink() or folder.is_junction() or not folder.resolve().is_relative_to(self.source_root):
            raise InvalidPageImport("The saved photo is unavailable.")
        if folder.is_dir():
            for child in folder.iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            folder.rmdir()

    def _get_page(self, job_id, page_id):
        job = self.repository.get_job(job_id)
        if job is not None:
            page = next((p for p in job.pages if p.page_id == page_id), None)
            if page is not None:
                return job, page
        raise PageImportNotFound("This page import was not found.")

    def get_source_path(self, job_id, page_id):
        _, page = self._get_page(job_id, page_id)
        path = self._safe_source(page.source_key)
        try:
            if not path.is_file() or path.stat().st_size != page.size_bytes:
                raise InvalidPageImport("The saved photo is unavailable.")
            if hashlib.sha256(path.read_bytes()).hexdigest() != page.sha256:
                raise InvalidPageImport("The saved photo is unavailable.")
        except OSError as exc:
            raise InvalidPageImport("The saved photo is unavailable.") from exc
        return path

    def _has_saved_batch(self, lesson_id, operation_id):
        return any(batch.operation_id == operation_id for batch in
                   self.session_service.lesson_repository.get_import_batches(lesson_id))

    async def recover_pending(self):
        for job in await asyncio.to_thread(self.repository.list_jobs):
            for page in job.pages:
                if page.status == PageStatus.SUCCEEDED:
                    continue
                saved = await asyncio.to_thread(self._has_saved_batch, job.lesson_id, page.import_operation_id)
                if saved:
                    updated = await asyncio.to_thread(self.repository.reconcile, page.page_id, PageStatus.SUCCEEDED)
                    self._publish(updated)
                elif page.status in {PageStatus.QUEUED, PageStatus.RUNNING}:
                    updated = await asyncio.to_thread(self.repository.reconcile, page.page_id, PageStatus.INTERRUPTED)
                    self._publish(updated)

    async def retry_page(self, job_id, page_id, operation_id):
        accepting = asyncio.create_task(self._retry_page(job_id, page_id, operation_id))
        try:
            return await asyncio.shield(accepting)
        except asyncio.CancelledError:
            await accepting
            raise

    async def _retry_page(self, job_id, page_id, operation_id):
        async with self._submit_lock:
            self._ready()
            if not operation_id or not operation_id.strip():
                raise InvalidPageImport("A retry ID is required.")
            job, page = await asyncio.to_thread(self._get_page, job_id, page_id)
            if page.status in {PageStatus.FAILED, PageStatus.INTERRUPTED}:
                if await asyncio.to_thread(self._has_saved_batch, job.lesson_id, page.import_operation_id):
                    updated = await asyncio.to_thread(self.repository.reconcile, page_id, PageStatus.SUCCEEDED)
                    self._publish(updated)
                    return updated
                await asyncio.to_thread(self.get_source_path, job_id, page_id)
            updated = await asyncio.to_thread(self.repository.retry, page_id, operation_id)
            # Duplicate receipts may return queued/running; claim CAS also makes
            # duplicate queue deliveries harmless without another model call.
            selected = next(p for p in updated.pages if p.page_id == page_id)
            if selected.status == PageStatus.QUEUED:
                self._queue.put_nowait((job_id, page_id))
            self._publish(updated)
            return updated

    async def _process_page(self, job_id, page_id):
        if not await asyncio.to_thread(self.repository.claim, page_id):
            return
        job, page = await asyncio.to_thread(self._get_page, job_id, page_id)
        self._publish(job)
        try:
            if not await asyncio.to_thread(self._has_saved_batch, job.lesson_id, page.import_operation_id):
                path = await asyncio.to_thread(self.get_source_path, job_id, page_id)
                content = await asyncio.to_thread(path.read_bytes)
                scope = CourseScope.model_validate({**json.loads(job.scope_json),
                    "lesson_id": job.lesson_id, "pages": [page.page_label]})
                # These fresh worker-owned sessions have no browser subscribers.
                # Upload publication and SQLite setup must not block the loop.
                preparing = asyncio.create_task(asyncio.to_thread(
                    self._prepare_session, content, page.mime_type, scope
                ))
                try:
                    session = await asyncio.shield(preparing)
                except asyncio.CancelledError:
                    await preparing
                    raise
                await self.session_service.import_lesson(session.session_id, operation_id=page.import_operation_id)
            updated = await asyncio.to_thread(self.repository.finish, page_id, PageStatus.SUCCEEDED)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Pi or publication may have succeeded before a later stage failed.
            if await asyncio.to_thread(self._has_saved_batch, job.lesson_id, page.import_operation_id):
                updated = await asyncio.to_thread(self.repository.reconcile, page_id, PageStatus.SUCCEEDED)
            else:
                updated = await asyncio.to_thread(self.repository.finish, page_id, PageStatus.FAILED,
                    "page_import_failed", "I could not finish this page. Please retry it.")
        self._publish(updated)

    def _prepare_session(self, content, mime_type, scope):
        session = self.session_service.create_session()
        self.session_service.upload_image(session.session_id, content, mime_type=mime_type)
        self.session_service.confirm_scope(session.session_id, scope)
        return session

    async def _run(self):
        while True:
            job_id, page_id = await self._queue.get()
            try:
                await self._process_page(job_id, page_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._fatal = True
                self._accepting = False
                logger.error("Page import storage failed; worker stopped.")
                return
            finally:
                self._queue.task_done()
