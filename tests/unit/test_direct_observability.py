from __future__ import annotations

from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService,
    FakeTextService,
    FakeTextToSpeechService,
    FakeVisionService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.api.app import create_app
from talkpath.application.activity_service import ActivityService
from talkpath.application.session_service import SessionService
from talkpath.application.safe_observability import log_operation_failure
from talkpath.domain.errors import OperationFailed
from talkpath.domain.models import Activity, ContentItem, CourseScope, LessonDraft


class NoopPi:
    async def prompt(self, message: str, **kwargs: object) -> object:
        return object()


class ExplodingText(FakeTextService):
    def __init__(self, method: str = "generate") -> None:
        self.method = method

    async def generate_activity(self, *args: object, **kwargs: object):
        if self.method == "generate":
            raise RuntimeError("secret-text-token private-lesson-payload")
        return await super().generate_activity(*args, **kwargs)

    async def evaluate_answer(self, *args: object, **kwargs: object):
        if self.method == "evaluate":
            raise RuntimeError("secret-text-token private-child-answer")
        return await super().evaluate_answer(*args, **kwargs)


class ExplodingTextAnswer(ExplodingText):
    """Explode only when evaluating a fill-in-the-blank item (no choices)."""

    async def generate_activity(self, *args: object, **kwargs: object):
        draft = await super().generate_activity(*args, **kwargs)
        base = draft.items[0]
        item = Activity(
            activity_id=base.activity_id,
            lesson_id=base.lesson_id,
            type="fill_blank",
            prompt="Type the missing word.",
            choices=[],
            answer="school",
            source_content_ids=base.source_content_ids,
        )
        return draft.model_copy(update={"items": [item]})


class ExplodingSTT(FakeSpeechToTextService):
    async def transcribe(self, *args: object, **kwargs: object):
        raise RuntimeError("secret-stt-token private-audio-bytes")


class ExplodingTTS(FakeTextToSpeechService):
    async def synthesize(self, *args: object, **kwargs: object):
        raise RuntimeError("secret-tts-token private-speech-text")


def lesson() -> LessonDraft:
    scope = CourseScope(
        program="junior high", grade="7", subject="English", lesson="1"
    )
    return LessonDraft(
        lesson_id=scope.lesson_id,
        scope=scope,
        title="A lesson",
        passage="I go to school.",
        content_items=[
            ContentItem(
                content_id="word-school",
                type="vocabulary",
                content={"word": "school", "meaning": "school"},
            )
        ],
        extraction_status="reviewed",
        provider="test",
        model="test",
        operation_id="lesson-op",
    )


def make_session_service(
    tmp_path: Path,
    *,
    text: object | None = None,
    stt: object | None = None,
    tts: object | None = None,
    agent_backend: str = "direct",
) -> SessionService:
    return SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=FakeVisionService(),
        text_service=text or FakeTextService(),
        speech_to_text_service=stt or FakeSpeechToTextService(),
        text_to_speech_service=tts or FakeTextToSpeechService(),
        pi_client=NoopPi(),
        agent_backend=agent_backend,
        upload_root=tmp_path / "uploads",
    )


def make_activity_service(
    tmp_path: Path, text: object, *, agent_backend: str = "direct"
) -> tuple[ActivityService, str]:
    saved_lesson = lesson()
    lesson_repository = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson_repository.save_lesson_draft(saved_lesson)
    progress_repository = SQLiteProgressRepository(tmp_path / "progress.sqlite")
    session = progress_repository.create_session("local-child", saved_lesson.lesson_id)
    return (
        ActivityService(
            progress_repository=progress_repository,
            lesson_repository=lesson_repository,
            text_service=text,
            agent_backend=agent_backend,
        ),
        session.session_id,
    )


@pytest.mark.asyncio
async def test_session_activity_unknown_error_has_safe_orchestration_log_and_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service = make_session_service(tmp_path, text=ExplodingText())
    session_id = service.create_session().session_id
    service.upload_image(session_id, b"image", mime_type="image/png")
    service.confirm_scope(session_id, lesson().scope)
    await service.import_lesson(session_id, operation_id="activity-import")
    events = service.subscribe(session_id)

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        with pytest.raises(
            OperationFailed,
            match="^text provider failed during activity generation$",
        ):
            await service.generate_activity(
                session_id,
                activity_type="vocabulary_quiz",
                operation_id="activity-safe-op",
            )

    log = caplog.text
    assert "activity_generation_failed" in log
    assert session_id in log
    assert 'operation_id="activity-safe-op"' in log
    assert 'agent_backend="direct"' in log
    assert 'stage="text"' in log
    assert "elapsed_ms=" in log
    assert 'error_type="OperationFailed"' in log
    assert "session_service.py" in log
    assert "secret-text-token" not in log
    assert "private-lesson-payload" not in log
    error_events = []
    while not events.empty():
        event = events.get_nowait()
        if event["type"] == "error":
            error_events.append(event)
    assert error_events == [
        {
            "type": "error",
            "session_id": session_id,
            "state": "FAILED",
            "message": "activity generation failed",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "call", "event", "stage", "safe_message", "secret"),
    [
        (
            ExplodingSTT(),
            "transcribe",
            "speech_transcription_failed",
            "speech_to_text",
            "speech to text provider failed",
            "secret-stt-token",
        ),
        (
            ExplodingTTS(),
            "synthesize",
            "speech_synthesis_failed",
            "text_to_speech",
            "text to speech provider failed",
            "secret-tts-token",
        ),
    ],
)
async def test_speech_unknown_error_is_safely_logged_and_wrapped(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    provider: object,
    call: str,
    event: str,
    stage: str,
    safe_message: str,
    secret: str,
) -> None:
    kwargs = {"stt": provider} if call == "transcribe" else {"tts": provider}
    service = make_session_service(tmp_path, **kwargs)

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        with pytest.raises(OperationFailed, match=f"^{safe_message}$"):
            if call == "transcribe":
                await service.transcribe_audio(
                    audio=b"private-audio-bytes",
                    mime_type="audio/wav",
                    operation_id="speech-safe-op",
                )
            else:
                await service.synthesize_speech(
                    text="private-speech-text",
                    voice=None,
                    operation_id="speech-safe-op",
                )

    log = caplog.text
    assert event in log
    assert 'operation_id="speech-safe-op"' in log
    assert 'agent_backend="direct"' in log
    assert f'stage="{stage}"' in log
    assert "elapsed_ms=" in log
    assert 'error_type="RuntimeError"' in log
    assert "session_service.py" in log
    assert secret not in log
    assert "private-audio-bytes" not in log
    assert "private-speech-text" not in log


@pytest.mark.asyncio
async def test_activity_text_generation_unknown_error_is_safely_logged_and_wrapped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service, session_id = make_activity_service(tmp_path, ExplodingText("generate"))

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        with pytest.raises(
            OperationFailed,
            match="^text provider failed during activity generation$",
        ):
            await service.generate_activity(
                session_id,
                activity_type="vocabulary_quiz",
                operation_id="text-generate-op",
            )

    log = caplog.text
    assert "activity_text_generation_failed" in log
    assert session_id in log
    assert 'operation_id="text-generate-op"' in log
    assert 'agent_backend="direct"' in log
    assert 'stage="text_generate_activity"' in log
    assert "elapsed_ms=" in log
    assert 'error_type="RuntimeError"' in log
    assert "activity_service.py" in log
    assert "secret-text-token" not in log
    assert "private-lesson-payload" not in log


@pytest.mark.asyncio
async def test_activity_text_evaluation_unknown_error_is_safely_logged_and_wrapped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service, session_id = make_activity_service(tmp_path, ExplodingTextAnswer("evaluate"))
    generated = await service.generate_activity(
        session_id,
        activity_type="speaking_practice",
        operation_id="text-generate-ok",
    )

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        with pytest.raises(
            OperationFailed,
            match="^text provider failed during answer evaluation$",
        ):
            await service.answer(
                session_id,
                generated.activity_id,
                item_id=generated.items[0].activity_id,
                answer="private-child-answer",
                operation_id="text-evaluate-op",
            )

    log = caplog.text
    assert "answer_text_evaluation_failed" in log
    assert session_id in log
    assert 'operation_id="text-evaluate-op"' in log
    assert 'agent_backend="direct"' in log
    assert 'stage="text_evaluate_answer"' in log
    assert "elapsed_ms=" in log
    assert 'error_type="RuntimeError"' in log
    assert "activity_service.py" in log
    assert "secret-text-token" not in log
    assert "private-child-answer" not in log

def test_session_service_forwards_pi_backend_to_activity_service(tmp_path: Path) -> None:
    service = make_session_service(tmp_path, agent_backend="pi")

    assert service.activity_service.agent_backend == "pi"


@pytest.mark.asyncio
async def test_activity_text_log_uses_configured_pi_backend(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service, session_id = make_activity_service(
        tmp_path, ExplodingText("generate"), agent_backend="pi"
    )

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        with pytest.raises(OperationFailed):
            await service.generate_activity(
                session_id,
                activity_type="vocabulary_quiz",
                operation_id="pi-text-op",
            )

    assert 'agent_backend="pi"' in caplog.text
    assert "secret-text-token" not in caplog.text


@pytest.mark.parametrize(
    ("provider_name", "provider", "path", "request_kwargs", "secret"),
    [
        (
            "stt",
            ExplodingSTT(),
            "transcribe",
            {
                "data": {"operation_id": "public-speech-op"},
                "files": {
                    "audio": ("private.wav", b"private-audio-bytes", "audio/wav")
                },
            },
            "secret-stt-token",
        ),
        (
            "tts",
            ExplodingTTS(),
            "synthesize",
            {
                "json": {
                    "operation_id": "public-speech-op",
                    "text": "private-speech-text",
                }
            },
            "secret-tts-token",
        ),
    ],
)
def test_public_speech_failure_log_has_real_session_context_without_secret(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    provider_name: str,
    provider: object,
    path: str,
    request_kwargs: dict[str, object],
    secret: str,
) -> None:
    services = make_session_service(tmp_path, **{provider_name: provider})
    client = TestClient(create_app(services=services, testing=True))
    session_id = client.post("/api/sessions").json()["session_id"]

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        response = client.post(
            f"/api/sessions/{session_id}/speech/{path}", **request_kwargs
        )

    assert response.status_code == 500
    assert response.json()["code"] == "operation_failed"
    assert response.json()["retryable"] is False
    assert f'session_id="{session_id}"' in caplog.text
    assert 'agent_backend="direct"' in caplog.text
    assert 'operation_id="public-speech-op"' in caplog.text
    assert secret not in caplog.text
    assert "private-audio-bytes" not in caplog.text
    assert "private-speech-text" not in caplog.text

def test_error_type_is_json_quoted_and_cannot_inject_log_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    injected_error_type = type("Injected\nforged_field=owned", (Exception,), {})
    try:
        raise injected_error_type("secret-error-message")
    except Exception as error:
        with caplog.at_level("ERROR", logger="talkpath.operations"):
            log_operation_failure(
                event="safe_error_type_test",
                session_id="session-id",
                operation_id="operation-id",
                agent_backend="direct",
                stage="test",
                started_at=time.perf_counter(),
                error=error,
            )

    assert 'error_type="Injected_forged_field=owned"' in caplog.text
    assert "\nforged_field=owned" not in caplog.text
    assert "secret-error-message" not in caplog.text
