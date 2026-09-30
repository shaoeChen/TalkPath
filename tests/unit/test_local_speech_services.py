import base64
import json

import httpx
import pytest

from talkpath.adapters.local_speech_services import (
    LocalHttpSpeechToTextService,
    LocalHttpTextToSpeechService,
)
from talkpath.domain.errors import (
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_local_stt_sends_multipart_contract_and_parses_transcript():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "operation_id": "stt-operation",
                "text": "Hello TalkPath",
                "language": "en",
                "segments": [],
            },
        )

    service = LocalHttpSpeechToTextService(
        "http://stt.local/",
        client=_client(handler),
        model="stt-model",
    )

    transcript = await service.transcribe(
        b"WAV-BYTES",
        mime_type="audio/wav",
        operation_id="stt-operation",
    )

    request = requests[0]
    assert str(request.url) == "http://stt.local/transcribe"
    assert request.headers["content-type"].startswith("multipart/form-data;")
    body = request.content
    assert b'name="mime_type"' in body
    assert b"audio/wav" in body
    assert b'name="operation_id"' in body
    assert b"stt-operation" in body
    assert b"WAV-BYTES" in body
    assert transcript.text == "Hello TalkPath"
    assert transcript.provider == "local_http"
    assert transcript.model == "stt-model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"text": "missing operation"},
        {"operation_id": "stt-operation"},
        {"operation_id": "other", "text": "wrong operation"},
    ],
)
async def test_local_stt_invalid_schema_or_identity_maps_to_response_invalid(response):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    service = LocalHttpSpeechToTextService(
        "http://stt.local",
        client=_client(handler),
    )

    with pytest.raises(ProviderResponseInvalid):
        await service.transcribe(
            b"WAV-BYTES",
            mime_type="audio/wav",
            operation_id="stt-operation",
        )


@pytest.mark.asyncio
async def test_local_tts_sends_json_contract_and_parses_raw_audio():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=b"MP3-BYTES",
            headers={"content-type": "audio/mpeg"},
        )

    service = LocalHttpTextToSpeechService(
        "http://tts.local/",
        client=_client(handler),
        model="tts-model",
    )

    artifact = await service.synthesize(
        "Hello",
        voice=None,
        operation_id="tts-operation",
    )

    request = requests[0]
    assert str(request.url) == "http://tts.local/synthesize"
    assert json.loads(request.content) == {
        "text": "Hello",
        "operation_id": "tts-operation",
        "model": "tts-model",
    }
    assert artifact.audio_bytes == b"MP3-BYTES"
    assert artifact.mime_type == "audio/mpeg"
    assert artifact.provider == "local_http"
    assert artifact.model == "tts-model"
    assert artifact.operation_id == "tts-operation"


@pytest.mark.asyncio
async def test_local_tts_includes_voice_and_parses_json_base64_audio():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "operation_id": "tts-operation",
                "mime_type": "audio/wav",
                "audio_base64": base64.b64encode(b"WAV-BYTES").decode("ascii"),
            },
        )

    service = LocalHttpTextToSpeechService(
        "http://tts.local",
        client=_client(handler),
        model="tts-model",
    )

    artifact = await service.synthesize(
        "Hello",
        voice="child",
        operation_id="tts-operation",
    )

    assert artifact.audio_bytes == b"WAV-BYTES"
    assert artifact.mime_type == "audio/wav"
    assert artifact.operation_id == "tts-operation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        (b"", "audio/mpeg"),
        (b"not-json", "application/json"),
    ],
)
async def test_local_tts_rejects_empty_audio_or_invalid_json(response):
    content, content_type = response

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            headers={"content-type": content_type},
        )

    service = LocalHttpTextToSpeechService(
        "http://tts.local",
        client=_client(handler),
    )

    with pytest.raises(ProviderResponseInvalid):
        await service.synthesize("Hello", operation_id="tts-operation")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"operation_id": "tts-operation", "audio_base64": "not-base64"},
        {
            "operation_id": "other",
            "audio_base64": base64.b64encode(b"WAV-BYTES").decode("ascii"),
        },
        {
            "operation_id": "tts-operation",
            "audio_base64": base64.b64encode(b"").decode("ascii"),
        },
    ],
)
async def test_local_tts_rejects_invalid_json_audio(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    service = LocalHttpTextToSpeechService(
        "http://tts.local",
        client=_client(handler),
    )

    with pytest.raises(ProviderResponseInvalid):
        await service.synthesize("Hello", operation_id="tts-operation")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception, expected",
    [
        (httpx.ReadTimeout("timed out"), ProviderTimeout),
        (httpx.ConnectError("offline"), ProviderUnavailable),
    ],
)
async def test_local_speech_transport_errors_are_classified(exception, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    stt = LocalHttpSpeechToTextService("http://stt.local", client=_client(handler))
    tts = LocalHttpTextToSpeechService("http://tts.local", client=_client(handler))

    with pytest.raises(expected):
        await stt.transcribe(b"WAV-BYTES", mime_type="audio/wav", operation_id="stt-op")
    with pytest.raises(expected):
        await tts.synthesize("Hello", operation_id="tts-op")


@pytest.mark.asyncio
async def test_local_speech_http_5xx_error_does_not_echo_audio_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"WAV-SECRET-BYTES")

    stt = LocalHttpSpeechToTextService("http://stt.local", client=_client(handler))

    with pytest.raises(ProviderUnavailable) as exc_info:
        await stt.transcribe(
            b"WAV-SECRET-BYTES",
            mime_type="audio/wav",
            operation_id="stt-op",
        )

    assert "WAV-SECRET-BYTES" not in str(exc_info.value)

@pytest.mark.asyncio
async def test_local_stt_supports_openai_transcription_contract():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "task": "transcribe",
                "language": "Chinese",
                "text": "你好 TalkPath",
                "segments": [
                    {"id": 0, "start": 0.0, "end": 1.25, "text": "你好 TalkPath"}
                ],
            },
        )

    service = LocalHttpSpeechToTextService(
        "http://stt.local/",
        client=_client(handler),
        headers={"Authorization": "Bearer local-token"},
        model="qwen3-asr-0.6b",
        protocol="openai_transcription",
        transcribe_path="/v1/audio/transcriptions",
    )

    transcript = await service.transcribe(
        b"WAV-BYTES",
        mime_type="audio/wav",
        operation_id="stt-operation",
    )

    request = requests[0]
    assert str(request.url) == "http://stt.local/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer local-token"
    assert request.headers["content-type"].startswith("multipart/form-data;")
    body = request.content
    assert b'name="file"' in body
    assert b'name="model"' in body
    assert b"qwen3-asr-0.6b" in body
    assert b'name="response_format"' in body
    assert b"verbose_json" in body
    assert b'name="operation_id"' not in body
    assert transcript.text == "你好 TalkPath"
    assert transcript.language == "Chinese"
    assert transcript.segments[0].start_seconds == 0.0
    assert transcript.segments[0].end_seconds == 1.25
    assert transcript.provider == "local_http"
    assert transcript.model == "qwen3-asr-0.6b"
    assert transcript.operation_id == "stt-operation"


@pytest.mark.asyncio
async def test_openai_transcription_rejects_invalid_segment_schema():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"text": "hello", "segments": [{"start": 1.0, "text": "bad"}]},
        )

    service = LocalHttpSpeechToTextService(
        "http://stt.local",
        client=_client(handler),
        protocol="openai_transcription",
        transcribe_path="/v1/audio/transcriptions",
    )

    with pytest.raises(ProviderResponseInvalid):
        await service.transcribe(
            b"WAV-BYTES",
            mime_type="audio/wav",
            operation_id="stt-operation",
        )

@pytest.mark.asyncio
async def test_local_tts_supports_openai_speech_contract():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=b"WAV-BYTES",
            headers={"content-type": "audio/wav"},
        )

    service = LocalHttpTextToSpeechService(
        "http://tts.local/",
        client=_client(handler),
        model="kokoro",
        protocol="openai_speech",
        speech_path="/v1/audio/speech",
        voice="af_bella",
        response_format="wav",
        speed=0.9,
    )

    artifact = await service.synthesize(
        "Hello TalkPath",
        voice=None,
        operation_id="tts-operation",
    )

    request = requests[0]
    assert str(request.url) == "http://tts.local/v1/audio/speech"
    assert json.loads(request.content) == {
        "model": "kokoro",
        "input": "Hello TalkPath",
        "voice": "af_bella",
        "response_format": "wav",
        "speed": 0.9,
    }
    assert artifact.audio_bytes == b"WAV-BYTES"
    assert artifact.mime_type == "audio/wav"
    assert artifact.provider == "local_http"
    assert artifact.model == "kokoro"
    assert artifact.operation_id == "tts-operation"


@pytest.mark.asyncio
async def test_openai_speech_call_voice_overrides_configured_voice():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=b"MP3-BYTES",
            headers={"content-type": "audio/mpeg"},
        )

    service = LocalHttpTextToSpeechService(
        "http://tts.local",
        client=_client(handler),
        protocol="openai_speech",
        speech_path="/v1/audio/speech",
        voice="af_bella",
    )

    await service.synthesize(
        "Hello",
        voice="zf_xiaobei",
        operation_id="tts-operation",
    )

    assert json.loads(requests[0].content)["voice"] == "zf_xiaobei"


@pytest.mark.asyncio
async def test_openai_speech_rejects_empty_audio():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"content-type": "audio/wav"})

    service = LocalHttpTextToSpeechService(
        "http://tts.local",
        client=_client(handler),
        protocol="openai_speech",
        speech_path="/v1/audio/speech",
    )

    with pytest.raises(ProviderResponseInvalid):
        await service.synthesize("Hello", operation_id="tts-operation")
