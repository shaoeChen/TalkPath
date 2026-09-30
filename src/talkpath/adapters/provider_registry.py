"""Central provider construction boundary."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from talkpath.adapters.http_model_services import (
    HttpSpeechToTextService,
    HttpTextService,
    HttpTextToSpeechService,
    HttpVisionService,
)
from talkpath.adapters.provider_profiles import BackendKind, Capability, ProviderProfile
from talkpath.config import Settings


class ProviderRegistry:
    """Build capability services from normalized profiles."""

    def __init__(self, vision, text, stt, tts) -> None:
        self.vision = vision
        self.text = text
        self.stt = stt
        self.tts = tts
        self._closed = False

    async def aclose(self) -> None:
        """Close resources owned by registry-created adapters once."""

        if self._closed:
            return
        self._closed = True
        seen: set[int] = set()
        for provider in (self.vision, self.text, self.stt, self.tts):
            provider_id = id(provider)
            if provider_id in seen:
                continue
            seen.add(provider_id)
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        clients: Mapping[str, httpx.AsyncClient] | None = None,
        headers: Mapping[str, Mapping[str, str]] | None = None,
    ) -> ProviderRegistry:
        from talkpath.adapters.fake_services import (
            FakeSpeechToTextService,
            FakeTextService,
            FakeTextToSpeechService,
            FakeVisionService,
        )

        clients = clients or {}
        headers = headers or {}

        def build_headers(profile: ProviderProfile) -> dict[str, str]:
            result = dict(profile.request_headers)
            result.update(headers.get(profile.capability.value, {}))
            if profile.api_key is not None and "Authorization" not in result:
                result["Authorization"] = (
                    f"Bearer {profile.api_key.get_secret_value()}"
                )
            return result

        def require_base_url(profile: ProviderProfile) -> str:
            if profile.base_url is None:
                raise ValueError(
                    f"{profile.capability.value} backend {profile.backend.value} "
                    "requires base_url"
                )
            return profile.base_url

        def build(
            capability: Capability,
            profile: ProviderProfile,
            fake_type,
            talkpath_type,
        ):
            backend = profile.backend
            if backend is BackendKind.FAKE:
                return fake_type()

            endpoint = require_base_url(profile)
            client = clients.get(capability.value)
            common = {
                "client": client,
                "headers": build_headers(profile),
                "timeout": profile.timeout,
                "model": profile.model,
            }

            if capability in (Capability.VISION, Capability.TEXT):
                if backend is BackendKind.TALKPATH_HTTP:
                    return talkpath_type(endpoint, **common)
                if backend is BackendKind.OPENAI_COMPATIBLE:
                    from talkpath.adapters.openai_compatible_services import (
                        OpenAICompatibleTextService,
                        OpenAICompatibleVisionService,
                    )

                    adapter_type = (
                        OpenAICompatibleVisionService
                        if capability is Capability.VISION
                        else OpenAICompatibleTextService
                    )
                    return adapter_type(
                        endpoint,
                        chat_path=profile.chat_path,
                        **common,
                    )
                raise ValueError(
                    f"{capability.value} backend {backend.value} is not supported"
                )

            if backend is BackendKind.LOCAL_HTTP:
                from talkpath.adapters.local_speech_services import (
                    LocalHttpSpeechToTextService,
                    LocalHttpTextToSpeechService,
                )

                if capability is Capability.STT:
                    return LocalHttpSpeechToTextService(
                        endpoint,
                        protocol=profile.protocol,
                        transcribe_path=profile.transcribe_path,
                        **common,
                    )
                return LocalHttpTextToSpeechService(
                    endpoint,
                    protocol=profile.protocol,
                    speech_path=profile.speech_path,
                    voice=profile.voice,
                    response_format=profile.response_format,
                    speed=profile.speed,
                    **common,
                )

            if backend is BackendKind.TALKPATH_HTTP:
                return talkpath_type(endpoint, **common)

            raise ValueError(
                f"{capability.value} backend {backend.value} is not supported"
            )

        return cls(
            build(
                Capability.VISION,
                settings.provider_profile(Capability.VISION),
                FakeVisionService,
                HttpVisionService,
            ),
            build(
                Capability.TEXT,
                settings.provider_profile(Capability.TEXT),
                FakeTextService,
                HttpTextService,
            ),
            build(
                Capability.STT,
                settings.provider_profile(Capability.STT),
                FakeSpeechToTextService,
                HttpSpeechToTextService,
            ),
            build(
                Capability.TTS,
                settings.provider_profile(Capability.TTS),
                FakeTextToSpeechService,
                HttpTextToSpeechService,
            ),
        )


build_provider_registry = ProviderRegistry.from_settings


__all__ = ["ProviderRegistry", "build_provider_registry"]
