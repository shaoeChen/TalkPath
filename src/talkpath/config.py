"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from talkpath.adapters.provider_profiles import Capability, ProviderProfile, normalize_backend


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings for the TalkPath application.

    Provider selection, endpoints and optional credentials are loaded from the
    environment.  Credentials are used only to configure an adapter client;
    they are never stored in lesson content or application state.
    """

    model_config = SettingsConfigDict(
        env_prefix="TALKPATH_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    agent_backend: Literal["direct", "pi"] = "direct"
    lessonlens_root: Path = PROJECT_ROOT / "data" / "lessonlens"
    sqlite_path: Path = PROJECT_ROOT / "data" / "talkpath.sqlite"
    pi_command: str = "pi"
    pi_extension: Path = PROJECT_ROOT / "pi-extension" / "talkpath-tools.ts"
    upload_root: Path = PROJECT_ROOT / "data" / "uploads"
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    upload_expiry_seconds: int = Field(default=60 * 60, gt=0)
    internal_tool_token: SecretStr | None = None

    # Provider selection and endpoints are configuration only.  Secrets are
    # optional environment-backed values and are never part of lesson payloads.
    vision_backend: str | None = None
    text_backend: str | None = None
    stt_backend: str | None = None
    tts_backend: str | None = None
    vision_provider: str = "fake"
    text_provider: str = "fake"
    stt_provider: str = "fake"
    tts_provider: str = "fake"
    vision_base_url: str | None = None
    text_base_url: str | None = None
    stt_base_url: str | None = None
    tts_base_url: str | None = None
    vision_endpoint: str | None = None
    text_endpoint: str | None = None
    stt_endpoint: str | None = None
    tts_endpoint: str | None = None
    vision_api_key: SecretStr | None = None
    text_api_key: SecretStr | None = None
    stt_api_key: SecretStr | None = None
    tts_api_key: SecretStr | None = None
    provider_timeout_seconds: float = Field(default=120.0, gt=0)
    vision_model: str = "default"
    text_model: str = "default"
    stt_model: str = "default"
    tts_model: str = "default"
    vision_chat_path: str = "/chat/completions"
    text_chat_path: str = "/chat/completions"
    stt_chat_path: str = "/chat/completions"
    stt_protocol: str = "talkpath"
    stt_transcribe_path: str = "/transcribe"
    tts_chat_path: str = "/chat/completions"
    tts_protocol: str = "talkpath"
    tts_speech_path: str = "/synthesize"
    tts_voice: str | None = None
    tts_response_format: str = "mp3"
    tts_speed: float = Field(default=1.0, gt=0)

    def provider_profile(self, capability: Capability | str) -> ProviderProfile:
        """Return normalized settings for one capability-specific adapter."""

        try:
            normalized_capability = Capability(capability)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported capability: {capability}") from exc

        fields = {
            Capability.VISION: (
                "vision_backend",
                "vision_provider",
                "vision_base_url",
                "vision_endpoint",
                "vision_api_key",
                "vision_model",
                "vision_chat_path",
            ),
            Capability.TEXT: (
                "text_backend",
                "text_provider",
                "text_base_url",
                "text_endpoint",
                "text_api_key",
                "text_model",
                "text_chat_path",
            ),
            Capability.STT: (
                "stt_backend",
                "stt_provider",
                "stt_base_url",
                "stt_endpoint",
                "stt_api_key",
                "stt_model",
                "stt_chat_path",
            ),
            Capability.TTS: (
                "tts_backend",
                "tts_provider",
                "tts_base_url",
                "tts_endpoint",
                "tts_api_key",
                "tts_model",
                "tts_chat_path",
            ),
        }
        (
            backend_field,
            legacy_backend_field,
            base_url_field,
            legacy_base_url_field,
            api_key_field,
            model_field,
            chat_path_field,
        ) = fields[normalized_capability]

        backend = getattr(self, backend_field) or getattr(self, legacy_backend_field)
        base_url = getattr(self, base_url_field) or getattr(self, legacy_base_url_field)
        if normalized_capability is Capability.STT:
            protocol = self.stt_protocol
            transcribe_path = self.stt_transcribe_path
        elif normalized_capability is Capability.TTS:
            protocol = self.tts_protocol
            transcribe_path = "/transcribe"
        else:
            protocol = "talkpath"
            transcribe_path = "/transcribe"
        speech_path = self.tts_speech_path if normalized_capability is Capability.TTS else "/synthesize"
        voice = self.tts_voice if normalized_capability is Capability.TTS else None
        response_format = self.tts_response_format if normalized_capability is Capability.TTS else "mp3"
        speed = self.tts_speed if normalized_capability is Capability.TTS else 1.0
        return ProviderProfile(
            capability=normalized_capability,
            backend=normalize_backend(normalized_capability, backend),
            base_url=base_url,
            api_key=getattr(self, api_key_field),
            model=getattr(self, model_field),
            timeout=self.provider_timeout_seconds,
            chat_path=getattr(self, chat_path_field),
            protocol=protocol,
            transcribe_path=transcribe_path,
            speech_path=speech_path,
            voice=voice,
            response_format=response_format,
            speed=speed,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings."""

    return Settings()
