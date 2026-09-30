"""HTTP provider adapters."""

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
from talkpath.domain.models import (
    Activity,
    ActivityDraft,
    AnswerEvaluation,
    AudioArtifact,
    ContentItem,
    CourseScope,
    ImageReference,
    LessonDraft,
    Transcript,
)


DEFAULT_PROVIDER_TIMEOUT = 120.0


class _HttpProvider:
    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_PROVIDER_TIMEOUT,
        model: str = "http",
    ) -> None:
        if not endpoint or not endpoint.strip():
            raise ValueError("provider endpoint is required")
        if timeout <= 0:
            raise ValueError("provider timeout must be positive")
        self.endpoint = endpoint.rstrip("/")
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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.aclose()

    async def _post_json(self, route: str, payload: Mapping[str, Any]) -> httpx.Response:
        try:
            response = await self._client.post(
                f"{self.endpoint}/{route.lstrip('/')}",
                json=dict(payload),
                headers=self._headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"provider timed out during {route}") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"provider request failed during {route}") from exc

        if not 200 <= response.status_code < 300:
            raise ProviderUnavailable(
                f"provider returned HTTP {response.status_code} during {route}"
            )
        return response

    @staticmethod
    def _json(response: httpx.Response, route: str) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise ProviderResponseInvalid(
                f"provider returned invalid JSON during {route}"
            ) from exc

    @staticmethod
    def _model(model_type, payload: Any, route: str):
        try:
            return model_type.model_validate(payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise ProviderResponseInvalid(
                f"provider response does not match {route} contract"
            ) from exc

    @staticmethod
    def _require_identity(condition: bool, message: str) -> None:
        if not condition:
            raise ProviderResponseInvalid(message)


class HttpVisionService(_HttpProvider):
    async def extract_lesson(
        self,
        images: list[ImageReference],
        scope: CourseScope,
        *,
        operation_id: str,
    ) -> LessonDraft:
        payload = {
            "scope": scope.model_dump(mode="json"),
            "images": [self._image_payload(image) for image in images],
            "operation_id": operation_id,
            "model": self.model,
        }
        response = await self._post_json("/extract", payload)
        draft = self._model(LessonDraft, self._json(response, "/extract"), "/extract")
        self._require_identity(
            draft.lesson_id == scope.lesson_id,
            "provider extract response lesson identity does not match request",
        )
        self._require_identity(
            draft.scope == scope,
            "provider extract response scope does not match request",
        )
        self._require_identity(
            draft.operation_id == operation_id,
            "provider extract response operation identity does not match request",
        )
        return draft

    @staticmethod
    def _image_payload(image: ImageReference) -> dict[str, Any]:
        try:
            with open(image.path, "rb") as image_file:
                image_bytes = image_file.read()
        except OSError as exc:
            raise ProviderResponseInvalid(
                f"vision source image could not be read: {image.image_id}"
            ) from exc
        return {
            "image_id": image.image_id,
            "mime_type": image.mime_type,
            "size_bytes": image.size_bytes,
            "data_base64": base64.b64encode(image_bytes).decode("ascii"),
        }


class HttpTextService(_HttpProvider):
    async def explain_grammar(
        self,
        lesson: LessonDraft,
        content_item: ContentItem,
        *,
        operation_id: str,
    ) -> str:
        response = await self._post_json(
            "/grammar",
            {
                "lesson": lesson.model_dump(mode="json"),
                "content_item": content_item.model_dump(mode="json"),
                "operation_id": operation_id,
                "model": self.model,
            },
        )
        payload = self._json(response, "/grammar")
        if isinstance(payload, dict) and isinstance(payload.get("explanation"), str):
            return payload["explanation"]
        if isinstance(payload, str):
            return payload
        raise ProviderResponseInvalid("provider response does not match /grammar contract")

    async def generate_activity(
        self,
        lesson: LessonDraft,
        activity_type: str,
        *,
        operation_id: str,
    ) -> ActivityDraft:
        response = await self._post_json(
            "/activity",
            {
                "lesson": lesson.model_dump(mode="json"),
                "activity_type": activity_type,
                "operation_id": operation_id,
                "model": self.model,
            },
        )
        draft = self._model(ActivityDraft, self._json(response, "/activity"), "/activity")
        self._require_identity(
            draft.lesson_id == lesson.lesson_id,
            "provider activity response lesson identity does not match request",
        )
        self._require_identity(
            draft.operation_id == operation_id,
            "provider activity response operation identity does not match request",
        )
        for item in draft.items:
            self._require_identity(
                item.lesson_id == lesson.lesson_id,
                "provider activity item lesson identity does not match request",
            )
        return draft

    async def evaluate_answer(
        self,
        activity: Activity,
        answer: str,
        *,
        operation_id: str,
    ) -> AnswerEvaluation:
        response = await self._post_json(
            "/evaluate",
            {
                "activity": activity.model_dump(mode="json"),
                "answer": answer,
                "operation_id": operation_id,
                "model": self.model,
            },
        )
        return self._model(AnswerEvaluation, self._json(response, "/evaluate"), "/evaluate")


class HttpSpeechToTextService(_HttpProvider):
    async def transcribe(
        self,
        audio: bytes,
        *,
        mime_type: str,
        operation_id: str,
    ) -> Transcript:
        response = await self._post_json(
            "/transcribe",
            {
                "audio_base64": base64.b64encode(audio).decode("ascii"),
                "mime_type": mime_type,
                "operation_id": operation_id,
                "model": self.model,
            },
        )
        transcript = self._model(
            Transcript, self._json(response, "/transcribe"), "/transcribe"
        )
        self._require_identity(
            transcript.operation_id == operation_id,
            "provider transcript operation identity does not match request",
        )
        return transcript


class HttpTextToSpeechService(_HttpProvider):
    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        operation_id: str,
    ) -> AudioArtifact:
        response = await self._post_json(
            "/synthesize",
            {
                "text": text,
                "voice": voice,
                "operation_id": operation_id,
                "model": self.model,
            },
        )
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type.startswith("audio/"):
            return AudioArtifact(
                audio_bytes=response.content,
                mime_type=content_type,
                provider="http-tts",
                model=self.model,
                operation_id=operation_id,
            )

        payload = self._json(response, "/synthesize")
        if not isinstance(payload, dict):
            raise ProviderResponseInvalid(
                "provider response does not match /synthesize contract"
            )
        encoded = payload.get("audio_base64", payload.get("audio_bytes"))
        if not isinstance(encoded, str):
            raise ProviderResponseInvalid(
                "provider response does not contain base64 audio bytes"
            )
        try:
            audio_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise ProviderResponseInvalid("provider returned invalid base64 audio") from exc
        artifact_payload = {
            key: value for key, value in payload.items() if key not in {"audio_base64", "audio_bytes"}
        }
        artifact = self._model(
            AudioArtifact,
            {
                **artifact_payload,
                "audio_bytes": audio_bytes,
            },
            "/synthesize",
        )
        self._require_identity(
            artifact.operation_id == operation_id,
            "provider audio response operation identity does not match request",
        )
        return artifact


# Short aliases keep the adapter boundary convenient for configuration code.
HttpSttService = HttpSpeechToTextService
HttpTtsService = HttpTextToSpeechService


def __getattr__(name: str):
    """Lazily expose the registry without coupling HTTP adapters to it."""

    if name == "ProviderRegistry":
        from talkpath.adapters.provider_registry import ProviderRegistry

        return ProviderRegistry
    if name == "build_provider_registry":
        from talkpath.adapters.provider_registry import build_provider_registry

        return build_provider_registry
    raise AttributeError(name)

__all__ = [
    "DEFAULT_PROVIDER_TIMEOUT",
    "HttpSpeechToTextService",
    "HttpSttService",
    "HttpTextService",
    "HttpTextToSpeechService",
    "HttpTtsService",
    "HttpVisionService",
    "ProviderRegistry",
    "build_provider_registry",
]
