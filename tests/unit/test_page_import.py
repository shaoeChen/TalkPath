from dataclasses import FrozenInstanceError

import pytest

from talkpath.domain.page_import import ImportJob, ImportPage, PageStatus, PageUpload


def test_upload_is_immutable():
    upload = PageUpload("1", b"photo", "image/png")
    with pytest.raises(FrozenInstanceError):
        upload.content = b"changed"


def test_job_counts_and_completion():
    page = ImportPage(
        page_id="p",
        ordinal=0,
        page_label=" A1 ",
        status=PageStatus.QUEUED,
        source_key="private/key",
        sha256="hash",
        mime_type="image/png",
        size_bytes=5,
        import_operation_id="import-p",
    )
    job = ImportJob(
        job_id="j",
        operation_id="o",
        lesson_id="lesson",
        scope_json="{}",
        fingerprint="f",
        pages=[page],
    )
    assert page.page_label == "A1"
    assert job.status == "processing"
    assert job.counts == dict(
        total=1, queued=1, running=0, succeeded=0, failed=0, interrupted=0
    )
    assert job.created_at.utcoffset().total_seconds() == 0
    assert (
        job.model_copy(
            update={"pages": [page.model_copy(update={"status": PageStatus.FAILED})]}
        ).status
        == "completed"
    )
