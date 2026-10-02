"""Durable background page import records and expected failures."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import Field

from talkpath.domain.errors import DomainError
from talkpath.domain.models import DomainModel


class PageImportNotFound(DomainError):
    """The requested import page does not exist."""


class InvalidPageImport(DomainError):
    """The import request or transition is invalid."""


class PageImportConflict(DomainError):
    """An operation receipt or active page conflicts with this request."""


@dataclass(frozen=True)
class PageUpload:
    page_label: str
    content: bytes
    mime_type: str


class PageStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ImportPage(DomainModel):
    page_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    page_label: str = Field(min_length=1)
    status: PageStatus
    source_key: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    import_operation_id: str = Field(min_length=1)
    attempt_count: int = Field(default=0, ge=0)
    retry_operation_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ImportJob(DomainModel):
    job_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    lesson_id: str = Field(min_length=1)
    scope_json: str
    fingerprint: str = Field(min_length=1)
    pages: list[ImportPage] = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    completion_revision: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def counts(self) -> dict[str, int]:
        return {
            "total": len(self.pages),
            **{
                status.value: sum(page.status == status for page in self.pages)
                for status in PageStatus
            },
        }

    @property
    def status(self) -> str:
        return (
            "processing"
            if any(
                page.status in (PageStatus.QUEUED, PageStatus.RUNNING)
                for page in self.pages
            )
            else "completed"
        )
