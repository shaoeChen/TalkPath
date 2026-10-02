"""Public page import snapshots; private paths never cross this boundary."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile
from talkpath.domain.page_import import InvalidPageImport, PageImportNotFound, PageStatus, PageUpload

router = APIRouter()


class PageResponse(BaseModel):
    page_id: str
    ordinal: int
    page_label: str
    status: PageStatus
    attempt_count: int
    error_code: str | None
    error_message: str | None


class JobResponse(BaseModel):
    job_id: str
    lesson_id: str
    status: str
    revision: int
    completion_revision: int
    counts: dict[str, int]
    created_at: datetime
    updated_at: datetime
    pages: list[PageResponse]

    @classmethod
    def from_job(cls, job):
        return cls(job_id=job.job_id, lesson_id=job.lesson_id, status=job.status,
            revision=job.revision, completion_revision=job.completion_revision,
            counts=job.counts, created_at=job.created_at, updated_at=job.updated_at,
            pages=[PageResponse(**{key: getattr(page, key) for key in PageResponse.model_fields}) for page in job.pages])


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pages: list[str] = Field(min_length=1)


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_id: str = Field(min_length=1)


def service_from(request):
    return request.app.state.page_import_service


@router.post("/api/lessons/{lesson_id}/page-imports/check")
def check_pages(lesson_id: str, payload: CheckRequest, request: Request):
    return {"lesson_id": lesson_id, "overlapping_pages": service_from(request).check(lesson_id, payload.pages)}


@router.post("/api/lessons/{lesson_id}/page-imports", status_code=202, response_model=JobResponse)
async def submit_pages(lesson_id: str, request: Request):
    service = service_from(request)
    async with request.form() as form:
        allowed = {"operation_id", "pages", "allow_overlap", "files"}
        if set(form.keys()) - allowed or any(len(form.getlist(key)) > 1 for key in allowed - {"files"}):
            raise InvalidPageImport("The page import form is invalid.")
        operation_id = form.get("operation_id")
        raw_pages = form.get("pages")
        overlap = form.get("allow_overlap", "false")
        if not isinstance(operation_id, str) or not isinstance(raw_pages, str) or overlap not in {"true", "false"}:
            raise InvalidPageImport("The page import form is invalid.")
        try:
            pages = json.loads(raw_pages)
        except (ValueError, TypeError) as exc:
            raise InvalidPageImport("Enter a page number for each photo.") from exc
        files = form.getlist("files")
        if not isinstance(pages, list) or not pages or len(files) != len(pages) or any(not isinstance(p, str) or not p.strip() for p in pages):
            raise InvalidPageImport("Enter a page number for each photo.")
        uploads = []
        for page, file in zip(pages, files, strict=True):
            if not isinstance(file, UploadFile):
                raise InvalidPageImport("Choose a photo for each page.")
            content = await file.read(service.session_service.max_upload_bytes + 1)
            uploads.append(PageUpload(page, content, (file.content_type or "").split(";", 1)[0].lower().strip()))
        job = await service.submit(lesson_id, operation_id, uploads, allow_overlap=overlap == "true")
    return JobResponse.from_job(job)


@router.get("/api/lesson-page-imports", response_model=list[JobResponse])
def list_jobs(request: Request, lesson_id: str | None = None):
    return [JobResponse.from_job(job) for job in service_from(request).repository.list_jobs(lesson_id)]


@router.get("/api/lesson-page-imports/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request):
    job = service_from(request).repository.get_job(job_id)
    if job is None:
        raise PageImportNotFound("This page import was not found.")
    return JobResponse.from_job(job)


@router.post("/api/lesson-page-imports/{job_id}/pages/{page_id}/retry", status_code=202, response_model=JobResponse)
async def retry_page(job_id: str, page_id: str, payload: RetryRequest, request: Request):
    return JobResponse.from_job(await service_from(request).retry_page(job_id, page_id, payload.operation_id))


@router.get("/api/lesson-page-imports/{job_id}/pages/{page_id}/image")
def page_image(job_id: str, page_id: str, request: Request):
    service = service_from(request)
    path = service.get_source_path(job_id, page_id)
    _, page = service._get_page(job_id, page_id)
    return FileResponse(path, media_type=page.mime_type, headers={"Cache-Control": "no-store"})


@router.websocket("/ws/lesson-page-imports")
async def job_events(websocket: WebSocket):
    await websocket.accept()
    service = service_from(websocket)
    queue = service.subscribe()
    receive_task = asyncio.create_task(websocket.receive())
    event_task = None
    try:
        jobs = await asyncio.to_thread(service.repository.list_jobs)
        await websocket.send_json({"type": "page_import_snapshot", "jobs": [JobResponse.from_job(j).model_dump(mode="json") for j in jobs]})
        while True:
            event_task = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait([receive_task, event_task], return_when=asyncio.FIRST_COMPLETED)
            if receive_task in done:
                if receive_task.result()["type"] == "websocket.disconnect":
                    break
                receive_task = asyncio.create_task(websocket.receive())
            if event_task in done:
                job = event_task.result()
                if job is None:
                    await websocket.close(code=1013)
                    break
                await websocket.send_json({"type": "page_import_updated", "job": JobResponse.from_job(job).model_dump(mode="json")})
            else:
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(queue)
        receive_task.cancel()
        if event_task is not None:
            event_task.cancel()
        await asyncio.gather(receive_task, *([event_task] if event_task else []), return_exceptions=True)
