"""Restricted loopback API consumed by the Pi TypeScript extension."""

from __future__ import annotations

import base64
import binascii
import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from talkpath.application.session_service import SessionService
from talkpath.domain.models import (
    Activity,
    ActivityDraft,
    AnswerEvaluation,
    AudioArtifact,
    CourseScope,
    ImageReference,
    LessonDraft,
    LearningAttempt,
    Transcript,
)


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExtractLessonRequest(ToolModel):
    operation_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    scope: CourseScope
    images: list[ImageReference]


class SaveLessonDraftRequest(ToolModel):
    operation_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    scope: CourseScope | None = None
    draft: LessonDraft
    source_references: list[ImageReference] = Field(default_factory=list)


class GenerateActivityRequest(ToolModel):
    operation_id: str = Field(min_length=1)
    scope: CourseScope | None = None
    lesson: LessonDraft
    activity_type: str = Field(min_length=1)


class EvaluateAnswerRequest(ToolModel):
    operation_id: str = Field(min_length=1)
    activity: Activity
    answer: str


class TranscribeAudioRequest(ToolModel):
    operation_id: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    audio_base64: str = Field(min_length=1)


class SynthesizeSpeechRequest(ToolModel):
    operation_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    voice: str | None = None


class SaveLearningResultRequest(ToolModel):
    operation_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    lesson_id: str | None = None
    activity_id: str = Field(min_length=1)
    correct: bool
    score: float = Field(ge=0.0, le=1.0)
    answer: str | None = None
    feedback: str | None = None


class SavedResponse(ToolModel):
    operation_id: str
    saved: bool = True


router = APIRouter(prefix="/internal/tools", tags=["internal-tools"])


def _is_loopback(request: Request) -> bool:
    client = request.client
    host = client.host if client is not None else ""
    if host in {"127.0.0.1", "::1", "localhost"}:
        return True
    return bool(getattr(request.app.state, "testing", False) and host == "testclient")


def require_internal_access(request: Request) -> None:
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="internal tools require loopback access")
    expected = getattr(request.app.state, "internal_tool_token", None)
    if expected:
        provided = request.headers.get("X-TalkPath-Internal-Token", "")
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid internal tool token")


def service_from(request: Request) -> SessionService:
    return request.app.state.session_service


def decode_audio(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="audio_base64 is invalid") from exc


@router.post("/extract_lesson", dependencies=[Depends(require_internal_access)])
async def extract_lesson(payload: ExtractLessonRequest, request: Request) -> dict[str, Any]:
    draft = await service_from(request).extract_lesson(
        session_id=payload.session_id,
        images=payload.images,
        scope=payload.scope,
        operation_id=payload.operation_id,
    )
    return {"operation_id": payload.operation_id, "draft": draft.model_dump(mode="json")}


@router.post("/save_lesson_draft", dependencies=[Depends(require_internal_access)])
def save_lesson_draft(
    payload: SaveLessonDraftRequest,
    request: Request,
) -> SavedResponse:
    service_from(request).save_lesson_draft(
        payload.draft,
        session_id=payload.session_id,
        operation_id=payload.operation_id,
        scope=payload.scope,
        source_references=payload.source_references,
    )
    return SavedResponse(operation_id=payload.operation_id)


@router.post("/generate_activity", dependencies=[Depends(require_internal_access)])
async def generate_activity(
    payload: GenerateActivityRequest,
    request: Request,
) -> dict[str, Any]:
    activity = await service_from(request).generate_activity_for_lesson(
        lesson=payload.lesson,
        activity_type=payload.activity_type,
        operation_id=payload.operation_id,
        scope=payload.scope,
    )
    return {"operation_id": payload.operation_id, "activity": activity.model_dump(mode="json")}


@router.post("/evaluate_answer", dependencies=[Depends(require_internal_access)])
async def evaluate_answer(
    payload: EvaluateAnswerRequest,
    request: Request,
) -> dict[str, Any]:
    evaluation = await service_from(request).evaluate_answer(
        activity=payload.activity,
        answer=payload.answer,
        operation_id=payload.operation_id,
    )
    return {"operation_id": payload.operation_id, "evaluation": evaluation.model_dump(mode="json")}


@router.post("/transcribe_audio", dependencies=[Depends(require_internal_access)])
async def transcribe_audio(
    payload: TranscribeAudioRequest,
    request: Request,
) -> dict[str, Any]:
    transcript = await service_from(request).transcribe_audio(
        audio=decode_audio(payload.audio_base64),
        mime_type=payload.mime_type,
        operation_id=payload.operation_id,
    )
    return {"operation_id": payload.operation_id, "transcript": transcript.model_dump(mode="json")}


@router.post("/synthesize_speech", dependencies=[Depends(require_internal_access)])
async def synthesize_speech(
    payload: SynthesizeSpeechRequest,
    request: Request,
) -> dict[str, Any]:
    audio = await service_from(request).synthesize_speech(
        text=payload.text,
        voice=payload.voice,
        operation_id=payload.operation_id,
    )
    artifact = audio.model_dump(mode="json")
    artifact["audio_bytes"] = base64.b64encode(audio.audio_bytes).decode("ascii")
    return {"operation_id": payload.operation_id, "audio": artifact}


@router.post("/save_learning_result", dependencies=[Depends(require_internal_access)])
def save_learning_result(
    payload: SaveLearningResultRequest,
    request: Request,
) -> dict[str, Any]:
    attempt = service_from(request).save_learning_result(
        session_id=payload.session_id,
        lesson_id=payload.lesson_id,
        activity_id=payload.activity_id,
        operation_id=payload.operation_id,
        correct=payload.correct,
        score=payload.score,
        answer=payload.answer,
        feedback=payload.feedback,
    )
    return {"operation_id": payload.operation_id, "attempt": attempt.model_dump(mode="json")}
