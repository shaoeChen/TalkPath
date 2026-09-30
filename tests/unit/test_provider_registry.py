import httpx
import pytest

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService,
    FakeTextService,
    FakeTextToSpeechService,
    FakeVisionService,
)
from talkpath.adapters.http_model_services import HttpVisionService
from talkpath.adapters.provider_registry import ProviderRegistry
from talkpath.config import Settings


def test_registry_builds_fake_services_from_default_profiles():
    registry = ProviderRegistry.from_settings(Settings(_env_file=None))

    assert isinstance(registry.vision, FakeVisionService)
    assert isinstance(registry.text, FakeTextService)
    assert isinstance(registry.stt, FakeSpeechToTextService)
    assert isinstance(registry.tts, FakeTextToSpeechService)


def test_registry_builds_talkpath_http_from_canonical_profile():
    settings = Settings(
        _env_file=None,
        vision_backend="talkpath_http",
        vision_base_url="https://vision.example/v1/",
        vision_model="vision-model",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    registry = ProviderRegistry.from_settings(settings, clients={"vision": client})

    assert isinstance(registry.vision, HttpVisionService)
    assert registry.vision.endpoint == "https://vision.example/v1"
    assert registry.vision.model == "vision-model"


def test_registry_requires_base_url_only_when_building_non_fake_provider():
    settings = Settings(
        _env_file=None,
        vision_backend="talkpath_http",
        vision_api_key="vision-secret",
    )

    with pytest.raises(ValueError, match="vision.*talkpath_http.*base_url") as exc_info:
        ProviderRegistry.from_settings(settings)

    assert "vision-secret" not in str(exc_info.value)


def test_registry_rejects_local_http_for_vision_with_capability_in_error():
    settings = Settings(
        _env_file=None,
        vision_backend="local_http",
        vision_base_url="http://vision.local",
    )

    with pytest.raises(ValueError, match="vision.*local_http"):
        ProviderRegistry.from_settings(settings)


def test_registry_rejects_openai_compatible_for_speech_capability():
    settings = Settings(
        _env_file=None,
        stt_backend="openai_compatible",
        stt_base_url="https://speech.example/v1",
    )

    with pytest.raises(ValueError, match="stt.*openai_compatible"):
        ProviderRegistry.from_settings(settings)


def test_registry_can_be_imported_from_legacy_http_adapter_module():
    from talkpath.adapters.http_model_services import ProviderRegistry as LegacyRegistry

    assert LegacyRegistry is ProviderRegistry
def test_registry_builds_openai_compatible_vision_adapter():
    from talkpath.adapters.openai_compatible_services import (
        OpenAICompatibleVisionService,
    )

    settings = Settings(
        _env_file=None,
        vision_backend="openai_compatible",
        vision_base_url="https://vision.example/v1",
    )

    registry = ProviderRegistry.from_settings(settings)

    assert isinstance(registry.vision, OpenAICompatibleVisionService)
def test_registry_builds_local_http_speech_adapters():
    from talkpath.adapters.local_speech_services import (
        LocalHttpSpeechToTextService,
        LocalHttpTextToSpeechService,
    )

    settings = Settings(
        _env_file=None,
        stt_backend="local_http",
        stt_base_url="http://stt.local",
        tts_backend="local_http",
        tts_base_url="http://tts.local",
    )

    registry = ProviderRegistry.from_settings(settings)

    assert isinstance(registry.stt, LocalHttpSpeechToTextService)
    assert isinstance(registry.tts, LocalHttpTextToSpeechService)

def test_registry_passes_openai_transcription_settings_to_local_stt():
    from talkpath.adapters.local_speech_services import LocalHttpSpeechToTextService

    settings = Settings(
        _env_file=None,
        stt_backend="local_http",
        stt_base_url="http://stt.local",
        stt_protocol="openai_transcription",
        stt_transcribe_path="/v1/audio/transcriptions",
        stt_model="qwen3-asr-0.6b",
    )

    registry = ProviderRegistry.from_settings(settings)

    assert isinstance(registry.stt, LocalHttpSpeechToTextService)
    assert registry.stt.protocol == "openai_transcription"
    assert registry.stt.transcribe_path == "/v1/audio/transcriptions"
    assert registry.stt.model == "qwen3-asr-0.6b"

def test_registry_passes_openai_speech_settings_to_local_tts():
    from talkpath.adapters.local_speech_services import LocalHttpTextToSpeechService

    settings = Settings(
        _env_file=None,
        tts_backend="local_http",
        tts_base_url="http://tts.local",
        tts_protocol="openai_speech",
        tts_speech_path="/v1/audio/speech",
        tts_model="kokoro",
        tts_voice="af_bella",
        tts_response_format="wav",
        tts_speed=0.9,
    )

    registry = ProviderRegistry.from_settings(settings)

    assert isinstance(registry.tts, LocalHttpTextToSpeechService)
    assert registry.tts.protocol == "openai_speech"
    assert registry.tts.speech_path == "/v1/audio/speech"
    assert registry.tts.voice == "af_bella"
    assert registry.tts.response_format == "wav"
    assert registry.tts.speed == 0.9
