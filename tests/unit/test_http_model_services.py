import base64
import json

import httpx
import pytest

from talkpath.adapters.http_model_services import (
    HttpSpeechToTextService,
    HttpTextService,
    HttpTextToSpeechService,
    HttpVisionService,
    ProviderRegistry,
)
from talkpath.config import Settings
from talkpath.domain.errors import (
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from talkpath.domain.models import (
    ActivityDraft,
    AudioArtifact,
    ContentItem,
    CourseScope,
    LessonDraft,
    Transcript,
)


def make_scope(lesson: str = "1") -> CourseScope:
    return CourseScope(
        program="junior-high",
        grade="1",
        subject="english",
        lesson=lesson,
    )


def make_lesson(
    scope: CourseScope | None = None,
    operation_id: str = "lesson-op",
) -> LessonDraft:
    scope = scope or make_scope()
    return LessonDraft(
        lesson_id=scope.lesson_id,
        scope=scope,
        title="A Day at School",
        passage="I go to school every day.",
        content_items=[
            ContentItem(
                content_id="word-school",
                type="vocabulary",
                content={"word": "school", "meaning": "學校"},
            )
        ],
        source_images=[],
        extraction_status="draft",
        provider="fixture",
        model="fixture-v1",
        operation_id=operation_id,
    )


def response_for(path: str, response_body):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        return httpx.Response(200, json=response_body)

    return handler


@pytest.mark.asyncio
async def test_http_vision_posts_scope_and_returns_lesson_draft_without_credentials():
    lesson = make_lesson()
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer injected-secret"
        return httpx.Response(200, json=lesson.model_dump(mode="json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HttpVisionService(
            "https://vision.test",
            client=client,
            headers={"Authorization": "Bearer injected-secret"},
        )
        result = await service.extract_lesson([], make_scope(), operation_id="lesson-op")

    assert isinstance(result, LessonDraft)
    assert result.lesson_id == lesson.lesson_id
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["scope"]["lesson_id"] == make_scope().lesson_id
    assert payload["model"] == "http"
    assert "injected-secret" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_http_text_posts_activity_and_returns_activity_draft():
    activity_payload = {
        "activity_id": "activity-1",
        "lesson_id": make_lesson().lesson_id,
        "type": "vocabulary_quiz",
        "title": "Vocabulary Quiz",
        "instructions": "Choose the correct answer.",
        "items": [
            {
                "activity_id": "item-1",
                "lesson_id": make_lesson().lesson_id,
                "type": "multiple_choice",
                "prompt": "What does school mean?",
                "choices": ["學校", "老師"],
                "answer": "學校",
                "explanation": "School is 學校.",
                "source_content_ids": ["word-school"],
            }
        ],
        "source_content_ids": ["word-school"],
        "provider": "http-text",
        "model": "text-v1",
        "operation_id": "activity-op",
    }

    def activity_handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "http"
        return httpx.Response(200, json=activity_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(activity_handler)) as client:
        service = HttpTextService("https://text.test", client=client)
        result = await service.generate_activity(
            make_lesson(), "vocabulary_quiz", operation_id="activity-op"
        )

    assert isinstance(result, ActivityDraft)
    assert result.type == "vocabulary_quiz"
    assert ActivityDraft.model_validate(result.model_dump()) == result


@pytest.mark.asyncio
async def test_http_speech_services_return_transcript_and_audio_artifact():
    transcript_payload = {
        "text": "Hello TalkPath.",
        "language": "en",
        "segments": [{"text": "Hello TalkPath.", "start_seconds": 0, "end_seconds": 1}],
        "provider": "http-stt",
        "model": "stt-v1",
        "operation_id": "stt-op",
    }

    def stt_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/transcribe"
        request_payload = json.loads(request.content)
        assert request_payload["audio_base64"] == base64.b64encode(b"audio").decode()
        assert request_payload["model"] == "http"
        return httpx.Response(200, json=transcript_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(stt_handler)) as client:
        stt = HttpSpeechToTextService("https://speech.test", client=client)
        transcript = await stt.transcribe(
            b"audio", mime_type="audio/wav", operation_id="stt-op"
        )

    assert isinstance(transcript, Transcript)
    assert transcript.text == "Hello TalkPath."

    def tts_handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "http"
        return httpx.Response(
            200, content=b"fake-mp3", headers={"content-type": "audio/mpeg"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(tts_handler)) as client:
        tts = HttpTextToSpeechService("https://speech.test", client=client)
        audio = await tts.synthesize("Hello", operation_id="tts-op")

    assert isinstance(audio, AudioArtifact)
    assert audio.audio_bytes == b"fake-mp3"
    assert audio.mime_type == "audio/mpeg"
    assert audio.model == "http"


@pytest.mark.asyncio
async def test_http_synthesize_accepts_json_audio_artifact():
    payload = {
        "audio_base64": base64.b64encode(b"json-audio").decode(),
        "mime_type": "audio/wav",
        "provider": "http-tts",
        "model": "tts-v1",
        "operation_id": "tts-op",
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        service = HttpTextToSpeechService("https://speech.test", client=client)
        result = await service.synthesize("Hello", operation_id="tts-op")

    assert result.audio_bytes == b"json-audio"
    assert result.mime_type == "audio/wav"
    assert result.operation_id == "tts-op"


@pytest.mark.asyncio
async def test_http_extract_rejects_response_identity_mismatch():
    response = make_lesson(operation_id="response-op")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response.model_dump(mode="json"))
        )
    ) as client:
        service = HttpVisionService("https://vision.test", client=client)
        with pytest.raises(ProviderResponseInvalid):
            await service.extract_lesson([], make_scope(), operation_id="request-op")

    other_scope_response = make_lesson(make_scope("2"), operation_id="request-op")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=other_scope_response.model_dump(mode="json")
            )
        )
    ) as client:
        service = HttpVisionService("https://vision.test", client=client)
        with pytest.raises(ProviderResponseInvalid):
            await service.extract_lesson([], make_scope(), operation_id="request-op")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override", [{"operation_id": "response-op"}, {"lesson_id": "other-lesson"}]
)
async def test_http_activity_rejects_response_identity_mismatch(override):
    activity_payload = {
        "activity_id": "activity-1",
        "lesson_id": make_lesson().lesson_id,
        "type": "vocabulary_quiz",
        "title": "Vocabulary Quiz",
        "instructions": "Choose the correct answer.",
        "items": [],
        "source_content_ids": [],
        "provider": "http-text",
        "model": "text-v1",
        "operation_id": "activity-op",
    }
    activity_payload.update(override)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=activity_payload)
        )
    ) as client:
        service = HttpTextService("https://text.test", client=client)
        with pytest.raises(ProviderResponseInvalid):
            await service.generate_activity(
                make_lesson(), "vocabulary_quiz", operation_id="activity-op"
            )


@pytest.mark.asyncio
async def test_http_activity_rejects_cross_lesson_activity_item():
    lesson = make_lesson()
    activity_payload = {
        "activity_id": "activity-1",
        "lesson_id": lesson.lesson_id,
        "type": "vocabulary_quiz",
        "title": "Vocabulary Quiz",
        "instructions": "Choose the correct answer.",
        "items": [
            {
                "activity_id": "item-1",
                "lesson_id": "other-lesson",
                "type": "multiple_choice",
                "prompt": "What does school mean?",
                "choices": ["學校", "老師"],
                "answer": "學校",
                "explanation": "School means 學校.",
                "source_content_ids": ["word-school"],
            }
        ],
        "source_content_ids": ["word-school"],
        "provider": "http-text",
        "model": "text-v1",
        "operation_id": "activity-op",
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=activity_payload)
        )
    ) as client:
        service = HttpTextService("https://text.test", client=client)
        with pytest.raises(ProviderResponseInvalid):
            await service.generate_activity(
                lesson, "vocabulary_quiz", operation_id="activity-op"
            )


@pytest.mark.asyncio
async def test_http_transcribe_rejects_response_operation_mismatch():
    payload = {
        "text": "Hello",
        "language": "en",
        "segments": [],
        "provider": "http-stt",
        "model": "stt-v1",
        "operation_id": "response-op",
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        service = HttpSpeechToTextService("https://speech.test", client=client)
        with pytest.raises(ProviderResponseInvalid):
            await service.transcribe(b"audio", mime_type="audio/wav", operation_id="request-op")


@pytest.mark.asyncio
async def test_http_synthesize_rejects_json_operation_mismatch():
    payload = {
        "audio_base64": base64.b64encode(b"json-audio").decode(),
        "mime_type": "audio/wav",
        "provider": "http-tts",
        "model": "tts-v1",
        "operation_id": "response-op",
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        service = HttpTextToSpeechService("https://speech.test", client=client)
        with pytest.raises(ProviderResponseInvalid):
            await service.synthesize("Hello", operation_id="request-op")


@pytest.mark.asyncio
async def test_http_provider_maps_non_2xx_to_provider_unavailable():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="down"))
    ) as client:
        service = HttpVisionService("https://vision.test", client=client)

        with pytest.raises(ProviderUnavailable):
            await service.extract_lesson([], make_scope(), operation_id="op")


@pytest.mark.asyncio
async def test_http_provider_maps_redirect_to_provider_unavailable():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "/extract"})
        )
    ) as client:
        service = HttpVisionService("https://vision.test", client=client)

        with pytest.raises(ProviderUnavailable):
            await service.extract_lesson([], make_scope(), operation_id="op")


@pytest.mark.asyncio
async def test_http_provider_maps_timeout_to_provider_timeout():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler)) as client:
        service = HttpVisionService("https://vision.test", client=client)

        with pytest.raises(ProviderTimeout):
            await service.extract_lesson([], make_scope(), operation_id="op")


@pytest.mark.asyncio
async def test_http_provider_maps_invalid_json_and_schema_to_response_invalid():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"not-json",
                headers={"content-type": "application/json"},
            )
        )
    ) as client:
        service = HttpVisionService("https://vision.test", client=client)
        with pytest.raises(ProviderResponseInvalid):
            await service.extract_lesson([], make_scope(), operation_id="op")


@pytest.mark.asyncio
async def test_http_provider_maps_invalid_schema_to_response_invalid():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"oops": True})
        )
    ) as client:
        service = HttpVisionService("https://vision.test", client=client)
        with pytest.raises(ProviderResponseInvalid):
            await service.extract_lesson([], make_scope(), operation_id="op")


@pytest.mark.asyncio
async def test_registry_selects_http_provider_and_keeps_env_credential_out_of_payload():
    response_lesson = make_lesson(operation_id="registry-op")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        assert request.headers["authorization"] == "Bearer from-settings"
        return httpx.Response(200, json=response_lesson.model_dump(mode="json"))

    settings = Settings(
        _env_file=None,
        vision_provider="http",
        vision_endpoint="https://vision.test",
        vision_api_key="from-settings",
        provider_timeout_seconds=7.5,
        vision_model="vision-model",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = ProviderRegistry.from_settings(
            settings,
            clients={"vision": client},
        )
        result = await registry.vision.extract_lesson(
            [], make_scope(), operation_id="registry-op"
        )

    assert isinstance(registry.vision, HttpVisionService)
    assert isinstance(result, LessonDraft)
    assert b"from-settings" not in seen["body"]
    payload = json.loads(seen["body"])
    assert payload["model"] == "vision-model"
    assert registry.vision.timeout == 7.5


class RecordingAsyncClient(httpx.AsyncClient):
    def __init__(self, *args, **kwargs):
        self.post_timeouts: list[object] = []
        super().__init__(*args, **kwargs)

    async def post(self, *args, timeout=None, **kwargs):
        self.post_timeouts.append(timeout)
        return await super().post(*args, timeout=timeout, **kwargs)


class CountingAsyncClient(httpx.AsyncClient):
    def __init__(self, *args, **kwargs):
        self.close_calls = 0
        super().__init__(*args, **kwargs)

    async def aclose(self):
        self.close_calls += 1
        await super().aclose()


@pytest.mark.asyncio
async def test_registry_passes_timeout_to_injected_client_on_each_request():
    response_lesson = make_lesson(operation_id="timeout-op")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_lesson.model_dump(mode="json"))

    client = RecordingAsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(
        _env_file=None,
        vision_provider="http",
        vision_endpoint="https://vision.test",
        provider_timeout_seconds=7.5,
    )
    registry = ProviderRegistry.from_settings(settings, clients={"vision": client})

    await registry.vision.extract_lesson([], make_scope(), operation_id="timeout-op")

    assert client.post_timeouts == [7.5]
    await client.aclose()


@pytest.mark.asyncio
async def test_registry_closes_owned_http_clients_once(monkeypatch):
    created: list[CountingAsyncClient] = []

    def client_factory(*args, **kwargs):
        client = CountingAsyncClient(*args, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(
        "talkpath.adapters.http_model_services.httpx.AsyncClient", client_factory
    )
    settings = Settings(
        _env_file=None,
        vision_provider="http",
        text_provider="http",
        stt_provider="http",
        tts_provider="http",
        vision_endpoint="https://vision.test",
        text_endpoint="https://text.test",
        stt_endpoint="https://stt.test",
        tts_endpoint="https://tts.test",
    )
    registry = ProviderRegistry.from_settings(settings)

    await registry.aclose()
    await registry.aclose()

    assert len(created) == 4
    assert [client.close_calls for client in created] == [1, 1, 1, 1]


@pytest.mark.asyncio
async def test_registry_does_not_close_reused_injected_client():
    shared_client = CountingAsyncClient()
    settings = Settings(
        _env_file=None,
        vision_provider="http",
        text_provider="http",
        vision_endpoint="https://vision.test",
        text_endpoint="https://text.test",
    )
    registry = ProviderRegistry.from_settings(
        settings,
        clients={"vision": shared_client, "text": shared_client},
    )

    await registry.aclose()
    await registry.aclose()
    assert shared_client.close_calls == 0

    await shared_client.aclose()
    assert shared_client.close_calls == 1
