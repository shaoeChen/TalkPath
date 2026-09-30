"""Capability-specific provider configuration profiles."""

from __future__ import annotations

from enum import Enum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Capability(str, Enum):
    VISION = "vision"
    TEXT = "text"
    STT = "stt"
    TTS = "tts"


class BackendKind(str, Enum):
    FAKE = "fake"
    TALKPATH_HTTP = "talkpath_http"
    OPENAI_COMPATIBLE = "openai_compatible"
    LOCAL_HTTP = "local_http"


_CANONICAL_ENVIRONMENT_NAMES = {
    capability: {
        "backend": f"TALKPATH_{capability.value.upper()}_BACKEND",
        "base_url": f"TALKPATH_{capability.value.upper()}_BASE_URL",
        "api_key": f"TALKPATH_{capability.value.upper()}_API_KEY",
        "model": f"TALKPATH_{capability.value.upper()}_MODEL",
    }
    for capability in Capability
}


def canonical_environment_names(capability: Capability | str) -> dict[str, str]:
    """Return the explicit environment names for one capability."""

    try:
        normalized = Capability(capability)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported capability: {capability}") from exc
    return dict(_CANONICAL_ENVIRONMENT_NAMES[normalized])


def normalize_backend(capability: Capability | str, backend: str | None) -> BackendKind:
    """Normalize supported backend names and the first-phase ``http`` alias."""

    try:
        normalized_capability = Capability(capability)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported capability: {capability}") from exc

    raw_backend = (backend or BackendKind.FAKE.value).strip().lower()
    if raw_backend == "http":
        raw_backend = BackendKind.TALKPATH_HTTP.value
    try:
        return BackendKind(raw_backend)
    except ValueError as exc:
        raise ValueError(
            f"unsupported {normalized_capability.value} backend: {backend}"
        ) from exc


class ProviderProfile(BaseModel):
    """Immutable, capability-specific settings passed to an adapter boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: Capability
    backend: BackendKind
    base_url: str | None = None
    api_key: SecretStr | None = None
    model: str = "default"
    timeout: float = Field(gt=0)
    chat_path: str = "/chat/completions"
    protocol: str = "talkpath"
    transcribe_path: str = "/transcribe"
    speech_path: str = "/synthesize"
    voice: str | None = None
    response_format: str = "mp3"
    speed: float = Field(default=1.0, gt=0)
    request_headers: Mapping[str, str] = Field(default_factory=dict)

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().rstrip("/")
        return normalized or None

    @field_validator("chat_path", mode="before")
    @classmethod
    def normalize_chat_path(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            return "/chat/completions"
        return "/" + normalized.lstrip("/")

    @field_validator("protocol", mode="before")
    @classmethod
    def normalize_protocol(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        return normalized or "talkpath"

    @field_validator("transcribe_path", mode="before")
    @classmethod
    def normalize_transcribe_path(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            return "/transcribe"
        return "/" + normalized.lstrip("/")

    @field_validator("speech_path", mode="before")
    @classmethod
    def normalize_speech_path(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            return "/synthesize"
        return "/" + normalized.lstrip("/")

    @field_validator("voice", mode="before")
    @classmethod
    def normalize_voice(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("response_format", mode="before")
    @classmethod
    def normalize_response_format(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        return normalized or "mp3"


__all__ = [
    "BackendKind",
    "Capability",
    "ProviderProfile",
    "canonical_environment_names",
    "normalize_backend",
]
