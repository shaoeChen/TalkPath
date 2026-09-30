"""Public child-facing HTTP and WebSocket routes."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from talkpath.application.session_service import (
    SessionService,
    SessionSnapshot,
)
from talkpath.application.activity_service import ActivityAnswerResult
from talkpath.domain.lesson_merge import ImportBatch
from talkpath.domain.models import (
    Activity,
    ActivityDraft,
    CourseScope,
    ImageReference,
    LessonDraft,
    SessionState,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateSessionRequest(ApiModel):
    operation_id: str | None = None
    lesson_id: str | None = Field(default=None, min_length=1)


class ScopeRequest(ApiModel):
    program: str
    grade: str
    subject: str
    lesson: str
    textbook: str | None = None
    edition: str | None = None
    pages: list[str] = Field(default_factory=list)

    def to_scope(self) -> CourseScope:
        return CourseScope(**self.model_dump())


class ImportRequest(ApiModel):
    operation_id: str = Field(min_length=1)


class GenerateActivityRequest(ApiModel):
    operation_id: str = Field(min_length=1)
    activity_type: str = Field(min_length=1)


class ActivityAnswerRequest(ApiModel):
    operation_id: str = Field(min_length=1)
    answer: str
    item_id: str | None = None


class VocabularyAnswerRequest(ApiModel):
    operation_id: str = Field(min_length=1)
    answer: str


class SpeechSynthesisRequest(ApiModel):
    operation_id: str | None = None
    text: str = Field(min_length=1)
    voice: str | None = None


class ImageResponse(ApiModel):
    image_id: str
    mime_type: str
    size_bytes: int
    expires_at: datetime

    @classmethod
    def from_reference(cls, reference: ImageReference) -> "ImageResponse":
        return cls.model_validate(reference.model_dump(exclude={"path"}))


class SessionResponse(ApiModel):
    session_id: str
    learner_key: str
    lesson_id: str | None
    state: SessionState
    scope_confirmed: bool
    source_images: list[ImageResponse]
    created_at: datetime
    updated_at: datetime
    scope: CourseScope | None = None

    @classmethod
    def from_snapshot(cls, snapshot: SessionSnapshot) -> "SessionResponse":
        session = snapshot.session
        return cls(
            session_id=session.session_id,
            learner_key=session.learner_key,
            lesson_id=session.lesson_id,
            state=session.state,
            scope_confirmed=session.scope_confirmed,
            source_images=[ImageResponse.from_reference(image) for image in session.source_images],
            created_at=session.created_at,
            updated_at=session.updated_at,
            scope=snapshot.scope,
        )


class LessonSummary(ApiModel):
    """Lightweight saved-lesson summary for the child-facing lesson list."""

    lesson_id: str
    title: str
    scope: CourseScope
    source_image_count: int
    content_item_count: int

    @classmethod
    def from_lesson(cls, lesson: LessonDraft) -> "LessonSummary":
        return cls(
            lesson_id=lesson.lesson_id,
            title=lesson.title,
            scope=lesson.scope,
            source_image_count=len(lesson.source_images),
            content_item_count=len(lesson.content_items),
        )


class ImportResponse(ApiModel):
    operation_id: str
    session: SessionResponse
    lesson: LessonDraft
    skipped_duplicates: int = 0


class ImportCheckResponse(ApiModel):
    """What importing into a scope would do to a lesson that may already exist."""

    lesson_id: str
    exists: bool
    title: str | None
    existing_pages: list[str]
    overlapping_pages: list[str]
    content_item_count: int


class PublicActivityItem(ApiModel):
    """Child-facing activity item with the answer withheld at the API boundary."""

    activity_id: str
    lesson_id: str
    type: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    question_type: str | None = None
    explanation: str | None = None
    source_content_ids: list[str] = Field(default_factory=list)

    @classmethod
    def from_activity(cls, activity: Activity) -> "PublicActivityItem":
        return cls(
            activity_id=activity.activity_id,
            lesson_id=activity.lesson_id,
            type=activity.type,
            prompt=activity.prompt,
            choices=activity.choices,
            question_type=activity.question_type,
            # Provider explanations can accidentally contain the expected
            # answer, so they stay server-side for this child-facing contract.
            explanation=None,
            source_content_ids=activity.source_content_ids,
        )


class PublicActivityDraft(ApiModel):
    """Child-facing activity draft whose nested items never contain answers."""

    activity_id: str
    lesson_id: str
    type: str
    title: str
    instructions: str
    items: list[PublicActivityItem] = Field(default_factory=list)
    source_content_ids: list[str] = Field(default_factory=list)
    provider: str
    model: str
    operation_id: str

    @classmethod
    def from_activity(cls, activity: ActivityDraft) -> "PublicActivityDraft":
        return cls(
            activity_id=activity.activity_id,
            lesson_id=activity.lesson_id,
            type=activity.type,
            title=activity.title,
            instructions=activity.instructions,
            items=[PublicActivityItem.from_activity(item) for item in activity.items],
            source_content_ids=activity.source_content_ids,
            provider=activity.provider,
            model=activity.model,
            operation_id=activity.operation_id,
        )


class ActivityResponse(ApiModel):
    operation_id: str
    session: SessionResponse
    activity: PublicActivityDraft


class PublicAnswerEvaluation(ApiModel):
    passed: bool
    score: float
    feedback: str


class PublicAttempt(ApiModel):
    attempt_id: str
    session_id: str
    lesson_id: str
    activity_id: str
    passed: bool
    score: float
    created_at: datetime


class ActivityAnswerResponse(ApiModel):
    operation_id: str
    activity_id: str
    item_id: str
    evaluation: PublicAnswerEvaluation
    attempt: PublicAttempt
    correction: str | None = None


class VocabularyAnswerResponse(ApiModel):
    operation_id: str
    content_id: str
    passed: bool
    score: float
    feedback: str
    attempt: PublicAttempt


class TranscriptResponse(ApiModel):
    operation_id: str
    transcript: dict[str, object]


class SpeechSynthesisResponse(ApiModel):
    operation_id: str
    mime_type: str
    audio_base64: str
    audio_data_url: str


class PublicReviewItem(ApiModel):
    session_id: str
    lesson_id: str
    activity_id: str
    mistake_count: int
    last_seen_at: datetime


class PublicProgressResponse(ApiModel):
    session_id: str
    lesson_id: str | None
    attempts: list[PublicAttempt] = Field(default_factory=list)
    review_items: list[PublicReviewItem] = Field(default_factory=list)


def _safe_child_feedback(result: ActivityAnswerResult, submitted_answer: str) -> str:
    """Prevent provider feedback from echoing either side of the answer key."""

    feedback = result.evaluation.feedback.strip()
    lowered = feedback.casefold()
    hidden_values = {
        value.strip().casefold()
        for value in (result.evaluation.expected_answer, result.item.answer, submitted_answer)
        if value and value.strip()
    }
    if "expected_answer" in lowered or any(value in lowered for value in hidden_values):
        return "Try again and check the lesson."
    return feedback or "Try again and check the lesson."


router = APIRouter(tags=["learning"])


def service_from(request: Request) -> SessionService:
    return request.app.state.session_service


@router.post("/api/sessions", response_model=SessionResponse)
def create_session(
    request: Request,
    payload: CreateSessionRequest | None = None,
) -> SessionResponse:
    service = service_from(request)
    session = service.create_session(
        operation_id=payload.operation_id if payload else None,
        lesson_id=payload.lesson_id if payload else None,
    )
    return SessionResponse.from_snapshot(service.get_snapshot(session.session_id))


@router.post("/api/sessions/{session_id}/images", response_model=ImageResponse)
async def upload_image(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> ImageResponse:
    content = await file.read()
    reference = service_from(request).upload_image(
        session_id,
        content,
        mime_type=file.content_type,
        original_filename=file.filename,
    )
    return ImageResponse.from_reference(reference)


@router.post("/api/sessions/{session_id}/scope", response_model=SessionResponse)
def confirm_scope(
    session_id: str,
    payload: ScopeRequest,
    request: Request,
) -> SessionResponse:
    service = service_from(request)
    service.confirm_scope(session_id, payload.to_scope())
    return SessionResponse.from_snapshot(service.get_snapshot(session_id))


@router.post("/api/sessions/{session_id}/import", response_model=ImportResponse)
async def import_lesson(
    session_id: str,
    payload: ImportRequest,
    request: Request,
) -> ImportResponse:
    service = service_from(request)
    result = await service.import_lesson(session_id, operation_id=payload.operation_id)
    return ImportResponse(
        operation_id=payload.operation_id,
        session=SessionResponse.from_snapshot(service.get_snapshot(session_id)),
        lesson=result.lesson,
        skipped_duplicates=result.skipped_duplicates,
    )


@router.post(
    "/api/sessions/{session_id}/activities/generate",
    response_model=ActivityResponse,
)
async def generate_activity(
    session_id: str,
    payload: GenerateActivityRequest,
    request: Request,
) -> ActivityResponse:
    service = service_from(request)
    result = await service.generate_activity(
        session_id,
        activity_type=payload.activity_type,
        operation_id=payload.operation_id,
    )
    return ActivityResponse(
        operation_id=payload.operation_id,
        session=SessionResponse.from_snapshot(service.get_snapshot(session_id)),
        activity=PublicActivityDraft.from_activity(result.activity),
    )


@router.get(
    "/api/sessions/{session_id}/activities/{activity_id}",
    response_model=ActivityResponse,
)
def get_activity(session_id: str, activity_id: str, request: Request) -> ActivityResponse:
    service = service_from(request)
    activity = service.activity_service.get_activity(session_id, activity_id)
    return ActivityResponse(
        operation_id=activity.operation_id,
        session=SessionResponse.from_snapshot(service.get_snapshot(session_id)),
        activity=PublicActivityDraft.from_activity(activity),
    )


@router.post(
    "/api/sessions/{session_id}/activities/{activity_id}/answer",
    response_model=ActivityAnswerResponse,
)
async def answer_activity(
    session_id: str,
    activity_id: str,
    payload: ActivityAnswerRequest,
    request: Request,
) -> ActivityAnswerResponse:
    service = service_from(request)
    result: ActivityAnswerResult = await service.activity_service.answer(
        session_id,
        activity_id,
        item_id=payload.item_id,
        answer=payload.answer,
        operation_id=payload.operation_id,
    )
    attempt = result.attempt
    return ActivityAnswerResponse(
        operation_id=payload.operation_id,
        activity_id=result.activity.activity_id,
        item_id=result.item.activity_id,
        evaluation=PublicAnswerEvaluation(
            passed=result.evaluation.correct,
            score=result.evaluation.score,
            feedback=_safe_child_feedback(result, payload.answer),
        ),
        attempt=PublicAttempt(
            attempt_id=attempt.attempt_id,
            session_id=attempt.session_id,
            lesson_id=attempt.lesson_id,
            activity_id=attempt.activity_id,
            passed=attempt.correct,
            score=attempt.score,
            created_at=attempt.created_at,
        ),
        correction=(
            result.item.answer
            if result.activity.type == "vocabulary_quiz"
            else None
        ),
    )


@router.post(
    "/api/sessions/{session_id}/vocabulary/{content_id}/answer",
    response_model=VocabularyAnswerResponse,
)
def answer_vocabulary_word(
    session_id: str,
    content_id: str,
    payload: VocabularyAnswerRequest,
    request: Request,
) -> VocabularyAnswerResponse:
    service = service_from(request)
    result = service.answer_vocabulary_word(
        session_id=session_id,
        content_id=content_id,
        answer=payload.answer,
        operation_id=payload.operation_id,
    )
    attempt = result.attempt
    return VocabularyAnswerResponse(
        operation_id=payload.operation_id,
        content_id=content_id,
        passed=result.evaluation.correct,
        score=result.evaluation.score,
        feedback=result.evaluation.feedback,
        attempt=PublicAttempt(
            attempt_id=attempt.attempt_id,
            session_id=attempt.session_id,
            lesson_id=attempt.lesson_id,
            activity_id=attempt.activity_id,
            passed=attempt.correct,
            score=attempt.score,
            created_at=attempt.created_at,
        ),
    )


def _public_operation_id(value: str | None, prefix: str) -> str:
    return value.strip() if value and value.strip() else f"{prefix}-{uuid4().hex}"


@router.post(
    "/api/sessions/{session_id}/speech/transcribe",
    response_model=TranscriptResponse,
)
async def transcribe_speech(
    session_id: str,
    request: Request,
    audio: UploadFile = File(...),
    operation_id: str = Form(""),
) -> TranscriptResponse:
    service = service_from(request)
    service.get_session(session_id)
    transcript = await service.transcribe_audio(
        audio=await audio.read(),
        mime_type=audio.content_type or "application/octet-stream",
        operation_id=_public_operation_id(operation_id, "transcribe"),
        session_id=session_id,
    )
    return TranscriptResponse(
        operation_id=transcript.operation_id,
        transcript=transcript.model_dump(mode="json"),
    )


@router.post(
    "/api/sessions/{session_id}/speech/synthesize",
    response_model=SpeechSynthesisResponse,
)
async def synthesize_speech(
    session_id: str,
    payload: SpeechSynthesisRequest,
    request: Request,
) -> SpeechSynthesisResponse:
    service = service_from(request)
    service.get_session(session_id)
    operation_id = _public_operation_id(payload.operation_id, "synthesize")
    audio = await service.synthesize_speech(
        text=payload.text,
        voice=payload.voice,
        operation_id=operation_id,
        session_id=session_id,
    )
    encoded = base64.b64encode(audio.audio_bytes).decode("ascii")
    return SpeechSynthesisResponse(
        operation_id=audio.operation_id,
        mime_type=audio.mime_type,
        audio_base64=encoded,
        audio_data_url=f"data:{audio.mime_type};base64,{encoded}",
    )


@router.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, request: Request) -> SessionResponse:
    return SessionResponse.from_snapshot(service_from(request).get_snapshot(session_id))


@router.get(
    "/api/sessions/{session_id}/progress",
    response_model=PublicProgressResponse,
)
def get_progress(session_id: str, request: Request) -> PublicProgressResponse:
    service = service_from(request)
    session = service.get_session(session_id)
    attempts = service.progress_repository.list_attempts(session_id)
    review_items = service.progress_repository.list_review_items(
        session_id, session.lesson_id
    )
    return PublicProgressResponse(
        session_id=session_id,
        lesson_id=session.lesson_id,
        attempts=[
            PublicAttempt(
                attempt_id=attempt.attempt_id,
                session_id=attempt.session_id,
                lesson_id=attempt.lesson_id,
                activity_id=attempt.activity_id,
                passed=attempt.correct,
                score=attempt.score,
                created_at=attempt.created_at,
            )
            for attempt in attempts
        ],
        review_items=[PublicReviewItem.model_validate(item.model_dump()) for item in review_items],
    )


@router.get("/api/lessons/{lesson_id}", response_model=LessonDraft)
def get_lesson(lesson_id: str, request: Request) -> LessonDraft:
    return service_from(request).get_lesson(lesson_id)


@router.post("/api/lessons/import-check", response_model=ImportCheckResponse)
def check_lesson_import(payload: ScopeRequest, request: Request) -> ImportCheckResponse:
    try:
        scope = payload.to_scope()
    except ValueError as error:
        raise HTTPException(status_code=422, detail="The lesson details are incomplete.") from error
    check = service_from(request).check_import(scope)
    return ImportCheckResponse(
        lesson_id=check.lesson_id,
        exists=check.exists,
        title=check.title,
        existing_pages=check.existing_pages,
        overlapping_pages=check.overlapping_pages,
        content_item_count=check.content_item_count,
    )


@router.get("/api/lessons/{lesson_id}/batches", response_model=list[ImportBatch])
def get_lesson_batches(lesson_id: str, request: Request) -> list[ImportBatch]:
    return service_from(request).get_import_batches(lesson_id)


@router.get("/api/lessons/{lesson_id}/images/{image_id}")
def get_lesson_image(lesson_id: str, image_id: str, request: Request) -> FileResponse:
    path = service_from(request).lesson_image_path(lesson_id, image_id)
    return FileResponse(
        path,
        media_type=_sniff_image_type(path),
        headers={"X-Content-Type-Options": "nosniff"},
    )


_JPEG_SIGNATURE = bytes.fromhex("ffd8ff")
_PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")


def _sniff_image_type(path: Path) -> str:
    """Name the image type from its bytes; a stored file is never trusted by name."""

    with path.open("rb") as image:
        header = image.read(12)
    if header.startswith(_JPEG_SIGNATURE):
        return "image/jpeg"
    if header.startswith(_PNG_SIGNATURE):
        return "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


@router.get("/api/lessons", response_model=list[LessonSummary])
def list_lessons(request: Request) -> list[LessonSummary]:
    service = service_from(request)
    return [LessonSummary.from_lesson(lesson) for lesson in service.list_lessons()]


@router.websocket("/ws/sessions/{session_id}")
async def session_events(websocket: WebSocket, session_id: str) -> None:
    service: SessionService = websocket.app.state.session_service
    try:
        snapshot = service.get_snapshot(session_id)
    except Exception:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "type": "session",
            "session": SessionResponse.from_snapshot(snapshot).model_dump(mode="json"),
        }
    )
    event_stream = service.events(session_id)
    try:
        async for event in event_stream:
            await websocket.send_json(event)
    except WebSocketDisconnect:
        return
    finally:
        await event_stream.aclose()
