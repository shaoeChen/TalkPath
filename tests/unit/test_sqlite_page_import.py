from concurrent.futures import ThreadPoolExecutor

import pytest

from talkpath.adapters.sqlite_page_import import SQLitePageImportRepository
from talkpath.domain.errors import RepositoryError
from talkpath.domain.page_import import (
    ImportJob,
    ImportPage,
    PageStatus,
    PageImportConflict,
    PageImportNotFound,
    InvalidPageImport,
)


def make_job(job_id="j", operation="o", label="1", fingerprint="f", page_id="p"):
    return ImportJob(
        job_id=job_id,
        operation_id=operation,
        lesson_id="lesson",
        scope_json="{}",
        fingerprint=fingerprint,
        pages=[
            ImportPage(
                page_id=page_id,
                ordinal=0,
                page_label=label,
                status=PageStatus.QUEUED,
                source_key="private/key",
                sha256="hash",
                mime_type="image/png",
                size_bytes=5,
                import_operation_id="import-" + page_id,
            )
        ],
    )


def test_persistence_idempotency_and_operation_conflict(tmp_path):
    repo = SQLitePageImportRepository(tmp_path / "jobs.sqlite")
    job = repo.create_job(make_job())
    reopened = SQLitePageImportRepository(repo.database_path)
    assert reopened.get_job("j") == job
    assert reopened.create_job(make_job(job_id="other")) == job
    assert reopened.list_jobs("lesson") == [job]
    assert reopened.list_jobs("other") == []
    assert reopened.get_job("missing") is None
    with pytest.raises(PageImportConflict):
        reopened.create_job(make_job(fingerprint="changed"))


def test_claim_is_atomic_across_connections(tmp_path):
    path = tmp_path / "jobs.sqlite"
    repo = SQLitePageImportRepository(path)
    repo.create_job(make_job())
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(
            pool.map(lambda _: SQLitePageImportRepository(path).claim("p"), range(2))
        )
    assert sorted(outcomes) == [False, True]
    job = repo.get_job("j")
    assert job.pages[0].attempt_count == 1
    assert job.pages[0].status == PageStatus.RUNNING
    assert job.revision == 2


def test_finish_is_idempotent_and_success_is_immutable(tmp_path):
    repo = SQLitePageImportRepository(tmp_path / "jobs.sqlite")
    repo.create_job(make_job())
    repo.claim("p")
    job = repo.finish("p", PageStatus.SUCCEEDED)
    assert (job.revision, job.completion_revision, job.status) == (3, 1, "completed")
    assert repo.finish("p", PageStatus.SUCCEEDED) == job
    assert repo.finish("p", PageStatus.FAILED, "error", "failed") == job
    with pytest.raises(InvalidPageImport):
        repo.finish("p", PageStatus.QUEUED)


def test_retry_receipts_survive_reopen_and_late_delivery(tmp_path):
    repo = SQLitePageImportRepository(tmp_path / "jobs.sqlite")
    repo.create_job(make_job())
    repo.claim("p")
    repo.finish("p", PageStatus.FAILED, "provider", "try again")
    queued = repo.retry("p", "r1")
    assert queued.pages[0].error_code is None
    assert queued.pages[0].retry_operation_id == "r1"
    assert queued.completion_revision == 1
    assert repo.retry("p", "r1") == queued
    repo.claim("p")
    failed = repo.finish("p", PageStatus.FAILED)
    assert failed.completion_revision == 2
    reopened = SQLitePageImportRepository(repo.database_path)
    assert reopened.retry("p", "r1") == failed
    queued_again = reopened.retry("p", "r2")
    assert queued_again.pages[0].status == PageStatus.QUEUED
    assert reopened.retry("p", "r1") == queued_again
    with pytest.raises(PageImportConflict):
        reopened.retry("p", "r3")
    reopened.create_job(make_job("j2", "o2", "2", page_id="p2"))
    with pytest.raises(PageImportConflict):
        reopened.retry("p2", "r1")


def test_active_duplicate_conflicts_and_terminal_releases(tmp_path):
    repo = SQLitePageImportRepository(tmp_path / "jobs.sqlite")
    repo.create_job(make_job())
    with pytest.raises(PageImportConflict):
        repo.create_job(make_job("j2", "o2", page_id="p2"))
    repo.reconcile("p", PageStatus.INTERRUPTED)
    repo.create_job(make_job("j2", "o2", page_id="p2"))
    with pytest.raises(PageImportConflict):
        repo.retry("p", "retry")


def test_reconcile_marks_interrupted_or_recovers_committed_success(tmp_path):
    repo = SQLitePageImportRepository(tmp_path / "jobs.sqlite")
    repo.create_job(make_job())
    interrupted = repo.reconcile("p", PageStatus.INTERRUPTED)
    assert interrupted.pages[0].status == PageStatus.INTERRUPTED
    assert interrupted.completion_revision == 1
    assert repo.reconcile("p", PageStatus.INTERRUPTED) == interrupted
    done = repo.reconcile("p", PageStatus.SUCCEEDED)
    assert done.pages[0].status == PageStatus.SUCCEEDED
    assert done.completion_revision == 1
    assert repo.reconcile("p", PageStatus.INTERRUPTED) == done


def test_unknown_pages_raise_not_found_and_storage_errors_are_wrapped(tmp_path):
    repo = SQLitePageImportRepository(tmp_path / "jobs.sqlite")
    for call in (
        lambda: repo.claim("missing"),
        lambda: repo.finish("missing", PageStatus.FAILED),
        lambda: repo.retry("missing", "r"),
        lambda: repo.reconcile("missing", PageStatus.INTERRUPTED),
    ):
        with pytest.raises(PageImportNotFound):
            call()
    invalid = SQLitePageImportRepository(tmp_path)
    with pytest.raises(RepositoryError) as error:
        invalid.list_jobs()
    assert str(tmp_path) not in str(error.value)


def test_multiple_pages_increment_completion_once_per_completed_round(tmp_path):
    repo = SQLitePageImportRepository(tmp_path / "jobs.sqlite")
    job = make_job()
    second = (
        make_job(label="2", page_id="p2").pages[0].model_copy(update={"ordinal": 1})
    )
    repo.create_job(job.model_copy(update={"pages": [job.pages[0], second]}))
    assert repo.finish("p", PageStatus.FAILED).completion_revision == 0
    done = repo.finish("p2", PageStatus.SUCCEEDED)
    assert done.completion_revision == 1
    assert done.counts == dict(
        total=2, queued=0, running=0, succeeded=1, failed=1, interrupted=0
    )
    repo.retry("p", "retry")
    done_again = repo.finish("p", PageStatus.SUCCEEDED)
    assert done_again.completion_revision == 2
    assert repo.finish("p", PageStatus.SUCCEEDED) == done_again


def test_failed_create_and_retry_roll_back_all_records(tmp_path):
    repo = SQLitePageImportRepository(tmp_path / "jobs.sqlite")
    repo.create_job(make_job())
    with pytest.raises(PageImportConflict):
        repo.create_job(make_job("j2", "o2", page_id="p2"))
    assert repo.get_job("j2") is None
    repo.finish("p", PageStatus.FAILED)
    repo.create_job(make_job("j2", "o2", page_id="p2"))
    before = repo.get_job("j")
    with pytest.raises(PageImportConflict):
        repo.retry("p", "retry")
    assert repo.get_job("j") == before
    repo.finish("p2", PageStatus.SUCCEEDED)
    assert repo.retry("p", "retry").pages[0].status == PageStatus.QUEUED


def test_concurrent_retry_receipt_increments_revision_once(tmp_path):
    path = tmp_path / "jobs.sqlite"
    repo = SQLitePageImportRepository(path)
    repo.create_job(make_job())
    before = repo.finish("p", PageStatus.FAILED)
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(
            pool.map(
                lambda _: SQLitePageImportRepository(path).retry("p", "retry"), range(2)
            )
        )
    assert outcomes[0] == outcomes[1]
    assert outcomes[0].revision == before.revision + 1
