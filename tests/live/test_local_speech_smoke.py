import base64

import pytest

from conftest import require_live_profile
from talkpath.adapters.provider_profiles import Capability
from talkpath.adapters.provider_registry import ProviderRegistry


WAV_BYTES = base64.b64decode(
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA="
)


@pytest.mark.asyncio
async def test_live_local_stt_smoke(live_settings):
    require_live_profile(live_settings, Capability.STT)
    registry = ProviderRegistry.from_settings(live_settings)

    try:
        transcript = await registry.stt.transcribe(
            WAV_BYTES,
            mime_type="audio/wav",
            operation_id="live-stt-smoke",
        )
    finally:
        await registry.aclose()

    assert transcript.operation_id == "live-stt-smoke"
    assert transcript.text.strip()


@pytest.mark.asyncio
async def test_live_local_tts_smoke(live_settings):
    require_live_profile(live_settings, Capability.TTS)
    registry = ProviderRegistry.from_settings(live_settings)

    try:
        profile = live_settings.provider_profile(Capability.TTS)
        artifact = await registry.tts.synthesize(
            "Hello TalkPath",
            voice=profile.voice,
            operation_id="live-tts-smoke",
        )
    finally:
        await registry.aclose()

    assert artifact.operation_id == "live-tts-smoke"
    assert artifact.mime_type.startswith("audio/")
    assert artifact.audio_bytes
