"""Transactional SQLite storage for background page import jobs."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from talkpath.domain.errors import RepositoryError
from talkpath.domain.page_import import (
    ImportJob,
    ImportPage,
    PageStatus,
    PageImportConflict,
    PageImportNotFound,
    InvalidPageImport,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lesson_page_import_jobs (
 job_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE, lesson_id TEXT NOT NULL,
 scope_json TEXT NOT NULL, fingerprint TEXT NOT NULL, revision INTEGER NOT NULL,
 completion_revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lesson_page_import_pages (
 page_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES lesson_page_import_jobs(job_id),
 lesson_id TEXT NOT NULL, ordinal INTEGER NOT NULL, page_label TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','interrupted')),
 source_key TEXT NOT NULL, sha256 TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
 import_operation_id TEXT NOT NULL UNIQUE, attempt_count INTEGER NOT NULL,
 retry_operation_id TEXT, error_code TEXT, error_message TEXT,
 UNIQUE(job_id,ordinal)
);
CREATE UNIQUE INDEX IF NOT EXISTS lesson_page_import_active
 ON lesson_page_import_pages(lesson_id,page_label,sha256) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS lesson_page_import_retries (
 operation_id TEXT PRIMARY KEY, page_id TEXT NOT NULL REFERENCES lesson_page_import_pages(page_id)
);
"""


class SQLitePageImportRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = None
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database_path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)
            yield connection
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise PageImportConflict(
                "import operation or active page already exists"
            ) from exc
        except (sqlite3.Error, OSError, ValidationError, ValueError) as exc:
            raise RepositoryError("could not persist page import records") from exc
        finally:
            if connection is not None:
                connection.close()

    def _job(self, connection: sqlite3.Connection, job_id: str) -> ImportJob | None:
        row = connection.execute(
            "SELECT * FROM lesson_page_import_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        rows = connection.execute(
            "SELECT * FROM lesson_page_import_pages WHERE job_id=? ORDER BY ordinal",
            (job_id,),
        ).fetchall()
        pages = [
            ImportPage.model_validate(
                {key: page[key] for key in ImportPage.model_fields}
            )
            for page in rows
        ]
        return ImportJob.model_validate({**dict(row), "pages": pages})

    def _page(self, connection: sqlite3.Connection, page_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM lesson_page_import_pages WHERE page_id=?", (page_id,)
        ).fetchone()
        if row is None:
            raise PageImportNotFound("import page not found")
        return row

    def create_job(self, job: ImportJob) -> ImportJob:
        try:
            job = ImportJob.model_validate(job.model_dump())
        except ValidationError as exc:
            raise InvalidPageImport("invalid import job") from exc
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT job_id,fingerprint FROM lesson_page_import_jobs WHERE operation_id=?",
                (job.operation_id,),
            ).fetchone()
            if row is not None:
                if row["fingerprint"] != job.fingerprint:
                    raise PageImportConflict(
                        "operation was used for different import content"
                    )
                return self._job(connection, row["job_id"])
            connection.execute(
                "INSERT INTO lesson_page_import_jobs VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    job.job_id,
                    job.operation_id,
                    job.lesson_id,
                    job.scope_json,
                    job.fingerprint,
                    job.revision,
                    job.completion_revision,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
            for page in job.pages:
                connection.execute(
                    "INSERT INTO lesson_page_import_pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        page.page_id,
                        job.job_id,
                        job.lesson_id,
                        page.ordinal,
                        page.page_label,
                        page.status.value,
                        page.source_key,
                        page.sha256,
                        page.mime_type,
                        page.size_bytes,
                        page.import_operation_id,
                        page.attempt_count,
                        page.retry_operation_id,
                        page.error_code,
                        page.error_message,
                    ),
                )
            return self._job(connection, job.job_id)

    def get_job(self, job_id: str) -> ImportJob | None:
        with self._transaction() as connection:
            return self._job(connection, job_id)

    def list_jobs(self, lesson_id: str | None = None) -> list[ImportJob]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT job_id FROM lesson_page_import_jobs"
                + (" WHERE lesson_id=?" if lesson_id is not None else "")
                + " ORDER BY created_at,job_id",
                (lesson_id,) if lesson_id is not None else (),
            ).fetchall()
            return [self._job(connection, row["job_id"]) for row in rows]

    def _bump(self, connection: sqlite3.Connection, before: ImportJob) -> ImportJob:
        after = self._job(connection, before.job_id)
        completed = int(before.status == "processing" and after.status == "completed")
        connection.execute(
            "UPDATE lesson_page_import_jobs SET revision=revision+1, completion_revision=completion_revision+?, updated_at=? WHERE job_id=?",
            (completed, datetime.now(timezone.utc).isoformat(), before.job_id),
        )
        return self._job(connection, before.job_id)

    def claim(self, page_id: str) -> bool:
        with self._transaction() as connection:
            page = self._page(connection, page_id)
            if page["status"] != PageStatus.QUEUED:
                return False
            before = self._job(connection, page["job_id"])
            changed = connection.execute(
                "UPDATE lesson_page_import_pages SET status='running', attempt_count=attempt_count+1 WHERE page_id=? AND status='queued'",
                (page_id,),
            ).rowcount
            if changed:
                self._bump(connection, before)
            return bool(changed)

    def finish(
        self,
        page_id: str,
        status: PageStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ImportJob:
        if status not in (
            PageStatus.SUCCEEDED,
            PageStatus.FAILED,
            PageStatus.INTERRUPTED,
        ):
            raise InvalidPageImport("finish requires a terminal page status")
        return self._transition(
            page_id, status, error_code, error_message, recovery=False
        )

    def reconcile(self, page_id: str, status: PageStatus) -> ImportJob:
        if status not in (PageStatus.SUCCEEDED, PageStatus.INTERRUPTED):
            raise InvalidPageImport("recovery requires succeeded or interrupted")
        return self._transition(page_id, status, recovery=True)

    def _transition(
        self,
        page_id: str,
        status: PageStatus,
        error_code: str | None = None,
        error_message: str | None = None,
        *,
        recovery: bool,
    ) -> ImportJob:
        with self._transaction() as connection:
            page = self._page(connection, page_id)
            before = self._job(connection, page["job_id"])
            if page["status"] == PageStatus.SUCCEEDED or page["status"] == status:
                return before
            can_transition = page["status"] in (
                PageStatus.QUEUED,
                PageStatus.RUNNING,
            ) or (recovery and status == PageStatus.SUCCEEDED)
            if not can_transition:
                raise PageImportConflict("page state does not allow this transition")
            connection.execute(
                "UPDATE lesson_page_import_pages SET status=?,error_code=?,error_message=? WHERE page_id=?",
                (str(status), error_code, error_message, page_id),
            )
            return self._bump(connection, before)

    def retry(self, page_id: str, operation_id: str) -> ImportJob:
        if not operation_id or not operation_id.strip():
            raise InvalidPageImport("retry operation ID is required")
        with self._transaction() as connection:
            page = self._page(connection, page_id)
            before = self._job(connection, page["job_id"])
            receipt = connection.execute(
                "SELECT page_id FROM lesson_page_import_retries WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if receipt is not None:
                if receipt["page_id"] != page_id:
                    raise PageImportConflict(
                        "retry operation was used for another page"
                    )
                return before
            if page["status"] not in (PageStatus.FAILED, PageStatus.INTERRUPTED):
                raise PageImportConflict(
                    "only failed or interrupted pages can be retried"
                )
            connection.execute(
                "UPDATE lesson_page_import_pages SET status='queued',retry_operation_id=?,error_code=NULL,error_message=NULL WHERE page_id=? AND status IN ('failed','interrupted')",
                (operation_id, page_id),
            )
            connection.execute(
                "INSERT INTO lesson_page_import_retries VALUES (?,?)",
                (operation_id, page_id),
            )
            return self._bump(connection, before)
