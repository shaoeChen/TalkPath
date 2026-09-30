import os

import pytest
from pydantic import ValidationError

from talkpath.config import PROJECT_ROOT, Settings


def _clear_talkpath_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("TALKPATH_"):
            monkeypatch.delenv(name, raising=False)


def test_settings_default_paths_are_project_relative_and_cwd_independent(
    monkeypatch, tmp_path
):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)

    assert settings.lessonlens_root == PROJECT_ROOT / "data" / "lessonlens"
    assert settings.sqlite_path == PROJECT_ROOT / "data" / "talkpath.sqlite"
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8000
    assert settings.agent_backend == "direct"
    assert settings.pi_command == "pi"
    assert settings.pi_extension == PROJECT_ROOT / "pi-extension" / "talkpath-tools.ts"
    assert settings.vision_provider == "fake"
    assert settings.text_provider == "fake"
    assert settings.stt_provider == "fake"
    assert settings.tts_provider == "fake"
    assert settings.vision_endpoint is None
    assert settings.text_endpoint is None
    assert settings.stt_endpoint is None
    assert settings.tts_endpoint is None
    assert settings.provider_timeout_seconds == 120
    assert settings.vision_model == "default"
    assert settings.text_model == "default"
    assert settings.stt_model == "default"
    assert settings.tts_model == "default"


def test_settings_reads_explicit_environment_overrides(monkeypatch, tmp_path):
    _clear_talkpath_environment(monkeypatch)
    lessonlens_root = tmp_path / "lessonlens"
    sqlite_path = tmp_path / "progress.sqlite"
    pi_extension = tmp_path / "tools.ts"
    monkeypatch.setenv("TALKPATH_APP_HOST", "0.0.0.0")
    monkeypatch.setenv("TALKPATH_APP_PORT", "9000")
    monkeypatch.setenv("TALKPATH_AGENT_BACKEND", "pi")
    monkeypatch.setenv("TALKPATH_LESSONLENS_ROOT", str(lessonlens_root))
    monkeypatch.setenv("TALKPATH_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("TALKPATH_PI_COMMAND", "pi-dev")
    monkeypatch.setenv("TALKPATH_PI_EXTENSION", str(pi_extension))
    monkeypatch.setenv("TALKPATH_PROVIDER_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("TALKPATH_VISION_MODEL", "vision-local")
    monkeypatch.setenv("TALKPATH_TEXT_MODEL", "text-local")
    monkeypatch.setenv("TALKPATH_STT_MODEL", "stt-local")
    monkeypatch.setenv("TALKPATH_TTS_MODEL", "tts-local")

    settings = Settings(_env_file=None)

    assert settings.app_host == "0.0.0.0"
    assert settings.app_port == 9000
    assert settings.agent_backend == "pi"
    assert settings.lessonlens_root == lessonlens_root
    assert settings.sqlite_path == sqlite_path
    assert settings.pi_command == "pi-dev"
    assert settings.pi_extension == pi_extension
    assert settings.provider_timeout_seconds == 7.5
    assert settings.vision_model == "vision-local"
    assert settings.text_model == "text-local"
    assert settings.stt_model == "stt-local"
    assert settings.tts_model == "tts-local"


def test_provider_timeout_must_be_positive():
    with pytest.raises(ValueError):
        Settings(_env_file=None, provider_timeout_seconds=0)


def test_agent_backend_rejects_unknown_value(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_AGENT_BACKEND", "mystery")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_env_file_is_project_relative():
    assert Settings.model_config["env_file"] == PROJECT_ROOT / ".env"
def test_settings_provider_profile_reads_capability_specific_openai_configuration(
    monkeypatch,
):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_VISION_BACKEND", "openai_compatible")
    monkeypatch.setenv("TALKPATH_VISION_BASE_URL", "https://vision.example/v1/")
    monkeypatch.setenv("TALKPATH_VISION_API_KEY", "vision-secret")
    monkeypatch.setenv("TALKPATH_VISION_MODEL", "glm-4v")

    settings = Settings(_env_file=None)
    profile = settings.provider_profile("vision")

    assert profile.capability == "vision"
    assert profile.backend == "openai_compatible"
    assert profile.base_url == "https://vision.example/v1"
    assert profile.model == "glm-4v"
    assert profile.api_key.get_secret_value() == "vision-secret"
    assert profile.chat_path == "/chat/completions"


def test_settings_provider_profile_normalizes_legacy_http_provider_and_endpoint(
    monkeypatch,
):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_TEXT_PROVIDER", "http")
    monkeypatch.setenv("TALKPATH_TEXT_ENDPOINT", "http://text.local/")

    profile = Settings(_env_file=None).provider_profile("text")

    assert profile.backend == "talkpath_http"
    assert profile.base_url == "http://text.local"


@pytest.mark.parametrize(
    "backend", ["fake", "talkpath_http", "openai_compatible", "local_http"]
)
def test_settings_provider_profile_accepts_supported_backends(monkeypatch, backend):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_STT_BACKEND", backend)

    profile = Settings(_env_file=None).provider_profile("stt")

    assert profile.backend == backend


def test_settings_provider_profile_rejects_unknown_backend(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_VISION_BACKEND", "vendor_magic")

    with pytest.raises(ValueError, match="unsupported vision backend"):
        Settings(_env_file=None).provider_profile("vision")


def test_settings_provider_profile_allows_local_speech_without_api_key(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_STT_BACKEND", "local_http")
    monkeypatch.setenv("TALKPATH_STT_BASE_URL", "http://stt.local")
    monkeypatch.setenv("TALKPATH_TTS_BACKEND", "local_http")
    monkeypatch.setenv("TALKPATH_TTS_BASE_URL", "http://tts.local")

    settings = Settings(_env_file=None)

    assert settings.provider_profile("stt").api_key is None
    assert settings.provider_profile("tts").api_key is None

def test_settings_provider_profile_supports_openai_transcription_path(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_STT_BACKEND", "local_http")
    monkeypatch.setenv("TALKPATH_STT_BASE_URL", "http://127.0.0.1:11435")
    monkeypatch.setenv("TALKPATH_STT_PROTOCOL", "openai_transcription")
    monkeypatch.setenv(
        "TALKPATH_STT_TRANSCRIBE_PATH", "/v1/audio/transcriptions"
    )

    profile = Settings(_env_file=None).provider_profile("stt")

    assert profile.protocol == "openai_transcription"
    assert profile.transcribe_path == "/v1/audio/transcriptions"


def test_settings_provider_profile_supports_openai_speech_tts(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_TTS_BACKEND", "local_http")
    monkeypatch.setenv("TALKPATH_TTS_BASE_URL", "http://127.0.0.1:8880")
    monkeypatch.setenv("TALKPATH_TTS_PROTOCOL", "openai_speech")
    monkeypatch.setenv("TALKPATH_TTS_SPEECH_PATH", "/v1/audio/speech")
    monkeypatch.setenv("TALKPATH_TTS_VOICE", "af_bella")
    monkeypatch.setenv("TALKPATH_TTS_RESPONSE_FORMAT", "mp3")
    monkeypatch.setenv("TALKPATH_TTS_SPEED", "0.9")

    profile = Settings(_env_file=None).provider_profile("tts")

    assert profile.protocol == "openai_speech"
    assert profile.speech_path == "/v1/audio/speech"
    assert profile.voice == "af_bella"
    assert profile.response_format == "mp3"
    assert profile.speed == 0.9

def test_settings_provider_profile_uses_positive_provider_timeout(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_PROVIDER_TIMEOUT_SECONDS", "4.5")

    profile = Settings(_env_file=None).provider_profile("text")

    assert profile.timeout == 4.5


def test_settings_provider_profile_does_not_expose_secret_in_string_representation(
    monkeypatch,
):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_VISION_API_KEY", "vision-secret")

    profile = Settings(_env_file=None).provider_profile("vision")

    assert "vision-secret" not in str(profile)
    assert "vision-secret" not in repr(profile)


def test_missing_base_url_is_deferred_until_non_fake_provider_is_built(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_TEXT_BACKEND", "openai_compatible")

    profile = Settings(_env_file=None).provider_profile("text")

    assert profile.base_url is None
