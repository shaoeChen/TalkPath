"""FastAPI application factory for TalkPath."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from talkpath.adapters.provider_registry import ProviderRegistry
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.agent.pi_rpc import PiRpcClient
from talkpath.agent.pi_rpc import PiProcessExited, PiRpcError
from talkpath.application.session_service import (
    LessonNotFound,
    OperationConflict,
    SessionNotFound,
    SessionService,
    SessionServiceError,
    UploadValidationError,
)
from talkpath.application.activity_service import (
    ActivityLessonNotFound,
    ActivityNotFound,
    ActivityOperationConflict,
    ActivitySessionNotFound,
    UnsupportedActivityType,
)
from talkpath.api.internal_tools import router as internal_tools_router
from talkpath.api.provider_health import provider_health_report
from talkpath.api.routes import router as public_router
from talkpath.config import Settings, get_settings
from talkpath.domain.errors import (
    DomainError,
    InvalidStateTransition,
    OperationFailed,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    RepositoryError,
    ScopeNotConfirmed,
)


def _domain_status(error: DomainError) -> int:
    if isinstance(
        error,
        (
            SessionNotFound,
            LessonNotFound,
            ActivitySessionNotFound,
            ActivityLessonNotFound,
            ActivityNotFound,
        ),
    ):
        return 404
    if isinstance(
        error,
        (
            InvalidStateTransition,
            ScopeNotConfirmed,
            UploadValidationError,
            OperationConflict,
            ActivityOperationConflict,
            UnsupportedActivityType,
        ),
    ):
        return 409
    if isinstance(error, OperationFailed):
        return 500
    if isinstance(error, ProviderTimeout):
        return 504
    if isinstance(error, ProviderUnavailable):
        return 503
    if isinstance(error, ProviderResponseInvalid):
        return 502
    if isinstance(error, PiProcessExited):
        return 503
    if isinstance(error, PiRpcError):
        return 502
    if isinstance(error, RepositoryError):
        return 500
    if isinstance(error, SessionServiceError):
        return 400
    return 500


def _domain_code(error: DomainError) -> str:
    if isinstance(error, ScopeNotConfirmed):
        return "scope_not_confirmed"
    if isinstance(error, UploadValidationError):
        return "upload_validation_error"
    if isinstance(error, OperationFailed):
        return "operation_failed"
    if isinstance(error, ProviderTimeout):
        return "provider_timeout"
    if isinstance(error, ProviderUnavailable):
        return "provider_unavailable"
    if isinstance(error, ProviderResponseInvalid):
        return "provider_response_invalid"
    if isinstance(error, PiProcessExited):
        return "pi_process_exited"
    if isinstance(error, PiRpcError):
        return "pi_rpc_error"
    if isinstance(error, RepositoryError):
        return "repository_error"
    if isinstance(error, InvalidStateTransition):
        return "invalid_state_transition"
    if isinstance(error, ActivityOperationConflict):
        return "activity_operation_conflict"
    if isinstance(error, SessionServiceError):
        return "session_service_error"
    return "domain_error"


def _domain_retryable(error: DomainError) -> bool:
    return isinstance(
        error,
        (
            ScopeNotConfirmed,
            UploadValidationError,
            ProviderTimeout,
            ProviderUnavailable,
            PiRpcError,
            RepositoryError,
        ),
    )


def create_app(
    *,
    settings: Settings | None = None,
    services: SessionService | None = None,
    service: SessionService | None = None,
    testing: bool = False,
) -> FastAPI:
    """Create the TalkPath API with production defaults or injected fakes."""

    if services is not None and service is not None:
        raise ValueError("pass only one of services or service")
    settings = settings or get_settings()
    configured_service = services if services is not None else service
    service_is_internal = configured_service is None
    providers: ProviderRegistry | None = None
    if configured_service is None:
        providers = ProviderRegistry.from_settings(settings)
        pi_client = (
            PiRpcClient.from_settings(settings)
            if settings.agent_backend == 'pi'
            else None
        )
        configured_service = SessionService(
            progress_repository=SQLiteProgressRepository(settings.sqlite_path),
            lesson_repository=LessonLensMarkdownRepository(settings.lessonlens_root),
            vision_service=providers.vision,
            text_service=providers.text,
            speech_to_text_service=providers.stt,
            text_to_speech_service=providers.tts,
            pi_client=pi_client,
            agent_backend=settings.agent_backend,
            upload_root=settings.upload_root,
            max_upload_bytes=settings.max_upload_bytes,
            upload_expiry_seconds=settings.upload_expiry_seconds,
        )

    app = FastAPI(title="TalkPath", version="0.1.0")
    app.state.session_service = configured_service
    app.state.provider_registry = providers
    if service_is_internal:
        app.router.add_event_handler("shutdown", configured_service.aclose)
    app.state.settings = settings
    app.state.testing = testing
    app.state.internal_tool_token = (
        settings.internal_tool_token.get_secret_value()
        if settings.internal_tool_token is not None
        else None
    )

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=_domain_status(exc),
            content={
                "detail": str(exc),
                "code": _domain_code(exc),
                "retryable": _domain_retryable(exc),
            },
        )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/providers", tags=["system"])
    def provider_health() -> dict[str, object]:
        return provider_health_report(settings)

    app.include_router(public_router)
    app.include_router(internal_tools_router)
    frontend_root = Path(__file__).resolve().parents[3] / "frontend"
    app.mount("/", StaticFiles(directory=frontend_root, html=True), name="frontend")
    return app
