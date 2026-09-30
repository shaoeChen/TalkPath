"""Local HTTP speech-to-text and text-to-speech adapters."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from talkpath.domain.errors import (
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from talkpath.domain.models import AudioArtifact, Transcript


DEFAULT_LOCAL_SPEECH_TIMEOUT = 120.0


class _LocalHttpSpeechProvider:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_LOCAL_SPEECH_TIMEOUT,
        model: str = "default",
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("local speech base_url is required")
        if timeout <= 0:
            raise ValueError("local speech timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self._headers = dict(headers or {})
        self.timeout = timeout
        self.model = model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def _post(
        self,
        route: str,
        *,
        json_payload: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.post(
                f"{self.base_url}/{route.lstrip('/')}",
                json=dict(json_payload) if json_payload is not None else None,
                files=files,
                data=data,
                headers=self._headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"local speech provider timed out during {route}") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable(
                f"local speech provider request failed during {route}"
            ) from exc

        if not 200 <= response.status_code < 300:
            raise ProviderUnavailable(
                f"local speech provider returned HTTP {response.status_code} during {route}"
            )
        return response

    @staticmethod
    def _json(response: httpx.Response, route: str) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ProviderResponseInvalid(
                f"local speech provider returned invalid JSON during {route}"
            ) from exc


class LocalHttpSpeechToTextService(_LocalHttpSpeechProvider):
    _SUPPORTED_PROTOCOLS = frozenset({"talkpath", "openai_transcription"})

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_LOCAL_SPEECH_TIMEOUT,
        model: str = "default",
        protocol: str = "talkpath",
        transcribe_path: str = "/transcribe",
    ) -> None:
        super().__init__(
            base_url,
            client=client,
            headers=headers,
            timeout=timeout,
            model=model,
        )
        normalized_protocol = str(protocol).strip().lower() or "talkpath"
        if normalized_protocol not in self._SUPPORTED_PROTOCOLS:
            supported = ", ".join(sorted(self._SUPPORTED_PROTOCOLS))
            raise ValueError(
                f"unsupported local speech transcription protocol: {protocol}; "
                f"expected one of {supported}"
            )
        normalized_path = str(transcribe_path).strip()
        self.protocol = normalized_protocol
        self.transcribe_path = "/" + normalized_path.lstrip("/") if normalized_path else "/transcribe"

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime_type: str,
        operation_id: str,
    ) -> Transcript:
        if self.protocol == "openai_transcription":
            return await self._transcribe_openai(
                audio,
                mime_type=mime_type,
                operation_id=operation_id,
            )

        response = await self._post(
            self.transcribe_path,
            files={"audio": ("audio", audio, mime_type)},
            data={
                "mime_type": mime_type,
                "operation_id": operation_id,
            },
        )
        payload = self._json(response, self.transcribe_path)
        if not isinstance(payload, dict):
            raise ProviderResponseInvalid(
                "local speech transcription response must be a JSON object"
            )
        if payload.get("operation_id") != operation_id:
            raise ProviderResponseInvalid(
                "local speech transcription operation_id does not match request"
            )
        if not isinstance(payload.get("text"), str):
            raise ProviderResponseInvalid(
                "local speech transcription response is missing text"
            )
        payload = dict(payload)
        payload["provider"] = "local_http"
        payload["model"] = self.model
        try:
            return Transcript.model_validate(payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise ProviderResponseInvalid(
                "local speech transcription response does not match schema"
            ) from exc

    async def _transcribe_openai(
        self,
        audio: bytes,
        *,
        mime_type: str,
        operation_id: str,
    ) -> Transcript:
        response = await self._post(
            self.transcribe_path,
            files={"file": ("audio", audio, mime_type)},
            data={
                "model": self.model,
                "response_format": "verbose_json",
            },
        )
        payload = self._json(response, self.transcribe_path)
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise ProviderResponseInvalid(
                "openai transcription response is missing text"
            )

        language = payload.get("language", "en")
        if language is None:
            language = "en"
        if not isinstance(language, str):
            raise ProviderResponseInvalid(
                "openai transcription response contains invalid language"
            )

        raw_segments = payload.get("segments", [])
        if raw_segments is None:
            raw_segments = []
        if not isinstance(raw_segments, list):
            raise ProviderResponseInvalid(
                "openai transcription response contains invalid segments"
            )

        segments: list[dict[str, Any]] = []
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, Mapping):
                raise ProviderResponseInvalid(
                    "openai transcription response contains invalid segment"
                )
            text = raw_segment.get("text")
            start = raw_segment.get("start", raw_segment.get("start_seconds"))
            end = raw_segment.get("end", raw_segment.get("end_seconds"))
            if not isinstance(text, str) or start is None or end is None:
                raise ProviderResponseInvalid(
                    "openai transcription response contains incomplete segment"
                )
            try:
                segments.append(
                    {
                        "text": text,
                        "start_seconds": float(start),
                        "end_seconds": float(end),
                    }
                )
            except (TypeError, ValueError) as exc:
                raise ProviderResponseInvalid(
                    "openai transcription response contains invalid segment timing"
                ) from exc

        try:
            return Transcript.model_validate(
                {
                    "text": payload["text"],
                    "language": language,
                    "segments": segments,
                    "provider": "local_http",
                    "model": self.model,
                    "operation_id": operation_id,
                }
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise ProviderResponseInvalid(
                "openai transcription response does not match schema"
            ) from exc

class LocalHttpTextToSpeechService(_LocalHttpSpeechProvider):
    _SUPPORTED_PROTOCOLS = frozenset({"talkpath", "openai_speech"})

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_LOCAL_SPEECH_TIMEOUT,
        model: str = "default",
        protocol: str = "talkpath",
        speech_path: str = "/synthesize",
        voice: str | None = None,
        response_format: str = "mp3",
        speed: float = 1.0,
    ) -> None:
        super().__init__(
            base_url,
            client=client,
            headers=headers,
            timeout=timeout,
            model=model,
        )
        normalized_protocol = str(protocol).strip().lower() or "talkpath"
        if normalized_protocol not in self._SUPPORTED_PROTOCOLS:
            supported = ", ".join(sorted(self._SUPPORTED_PROTOCOLS))
            raise ValueError(
                f"unsupported local speech synthesis protocol: {protocol}; "
                f"expected one of {supported}"
            )
        normalized_path = str(speech_path).strip()
        if speed <= 0:
            raise ValueError("local speech speed must be positive")
        self.protocol = normalized_protocol
        self.speech_path = "/" + normalized_path.lstrip("/") if normalized_path else "/synthesize"
        self.voice = str(voice).strip() if voice and str(voice).strip() else None
        self.response_format = str(response_format).strip().lower() or "mp3"
        self.speed = float(speed)

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        operation_id: str,
    ) -> AudioArtifact:
        if self.protocol == "openai_speech":
            return await self._synthesize_openai_speech(
                text,
                voice=voice,
                operation_id=operation_id,
            )
        return await self._synthesize_talkpath(
            text,
            voice=voice,
            operation_id=operation_id,
        )

    async def _synthesize_openai_speech(
        self,
        text: str,
        *,
        voice: str | None,
        operation_id: str,
    ) -> AudioArtifact:
        effective_voice = voice or self.voice
        payload: dict[str, Any] = {
            "input": text,
            "model": self.model,
            "response_format": self.response_format,
            "speed": self.speed,
        }
        if effective_voice is not None:
            payload["voice"] = effective_voice
        response = await self._post(self.speech_path, json_payload=payload)
        return self._audio_artifact(response, self.speech_path, operation_id)

    async def _synthesize_talkpath(
        self,
        text: str,
        *,
        voice: str | None,
        operation_id: str,
    ) -> AudioArtifact:
        payload: dict[str, Any] = {
            "text": text,
            "operation_id": operation_id,
            "model": self.model,
        }
        if voice is not None:
            payload["voice"] = voice

        response = await self._post(self.speech_path, json_payload=payload)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()

        if content_type.startswith("audio/"):
            return self._audio_artifact(response, self.speech_path, operation_id)

        payload_response = self._json(response, self.speech_path)
        if not isinstance(payload_response, dict):
            raise ProviderResponseInvalid(
                "local speech synthesis response must be a JSON object"
            )
        if payload_response.get("operation_id") != operation_id:
            raise ProviderResponseInvalid(
                "local speech synthesis operation_id does not match request"
            )
        encoded = payload_response.get(
            "audio_base64",
            payload_response.get("audio_bytes"),
        )
        if not isinstance(encoded, str):
            raise ProviderResponseInvalid(
                "local speech synthesis response is missing base64 audio"
            )
        try:
            audio_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, TypeError, ValueError) as exc:
            raise ProviderResponseInvalid(
                "local speech synthesis response contains invalid base64 audio"
            ) from exc
        if not audio_bytes:
            raise ProviderResponseInvalid(
                "local speech synthesis response contains empty audio"
            )

        mime_type = payload_response.get("mime_type", "audio/mpeg")
        if not isinstance(mime_type, str) or not mime_type.lower().startswith("audio/"):
            raise ProviderResponseInvalid(
                "local speech synthesis response contains unsupported audio mime type"
            )
        return AudioArtifact(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            provider="local_http",
            model=self.model,
            operation_id=operation_id,
        )

    def _audio_artifact(
        self,
        response: httpx.Response,
        route: str,
        operation_id: str,
    ) -> AudioArtifact:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("audio/"):
            raise ProviderResponseInvalid(
                f"local speech synthesis response contains unsupported content type during {route}"
            )
        if not response.content:
            raise ProviderResponseInvalid(
                "local speech synthesis response contains empty audio"
            )
        return AudioArtifact(
            audio_bytes=response.content,
            mime_type=content_type,
            provider="local_http",
            model=self.model,
            operation_id=operation_id,
        )

__all__ = [
    "LocalHttpSpeechToTextService",
    "LocalHttpTextToSpeechService",
]
