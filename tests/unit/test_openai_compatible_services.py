import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from talkpath.adapters.openai_compatible_services import (
    OpenAICompatibleTextService,
    OpenAICompatibleVisionService,
    _ACTIVITY_OUTPUT_INSTRUCTION,
)
from talkpath.domain.errors import (
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
)
from talkpath.domain.models import Activity, ContentItem, CourseScope, LessonDraft


def _scope() -> CourseScope:
    return CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )


def _image(tmp_path):
    path = tmp_path / "book.png"
    path.write_bytes(b"PNG-BYTES")
    from talkpath.domain.models import ImageReference

    return ImageReference(
        image_id="image-1",
        path=str(path),
        mime_type="image/png",
        size_bytes=9,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


def _lesson_payload(scope: CourseScope) -> dict[str, object]:
    return {
        "lesson_id": scope.lesson_id,
        "scope": scope.model_dump(mode="json"),
        "title": "A Day at School",
        "passage": "I go to school every day.",
        "content_items": [],
        "source_images": ["image-1"],
        "extraction_status": "draft",
    }


def _activity_payload(lesson_id: str) -> dict[str, object]:
    return {
        "activity_id": "activity-1",
        "lesson_id": lesson_id,
        "type": "vocabulary_quiz",
        "title": "Vocabulary Quiz",
        "instructions": "Choose the best answer.",
        "items": [
            {
                "activity_id": "item-1",
                "lesson_id": lesson_id,
                "type": "multiple_choice",
                "prompt": "What does school mean?",
                "choices": ["學校", "老師"],
                "answer": "學校",
                "explanation": "School means 學校.",
                "source_content_ids": [],
            }
        ],
        "source_content_ids": [],
    }


def _evaluation_payload() -> dict[str, object]:
    return {
        "correct": True,
        "score": 1.0,
        "feedback": "Great job!",
        "expected_answer": "學校",
    }


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_vision_sends_scope_and_image_data_url_and_parses_lesson(tmp_path):
    scope = _scope()
    image = _image(tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(_lesson_payload(scope))}}
                ]
            },
        )

    service = OpenAICompatibleVisionService(
        "https://vision.example/v1/",
        client=_client(handler),
        headers={"Authorization": "Bearer vision-secret"},
        model="vision-model",
    )

    draft = await service.extract_lesson(
        [image],
        scope,
        operation_id="vision-operation-1",
    )

    request = requests[0]
    assert str(request.url) == "https://vision.example/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer vision-secret"
    body = json.loads(request.content)
    assert body["model"] == "vision-model"
    assert body["response_format"] == {"type": "json_object"}
    assert "lesson_id" in body["messages"][0]["content"]
    assert "content_id" in body["messages"][0]["content"]
    assert "extraction_status" in body["messages"][0]["content"]
    user_content = body["messages"][-1]["content"]
    scope_message = json.loads(user_content[0]["text"])
    assert scope_message["scope"]["lesson_id"] == scope.lesson_id
    assert scope_message["operation_id"] == "vision-operation-1"
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"] == "data:image/png;base64,UE5HLUJZVEVT"
    assert "audio" not in request.content.decode()
    assert draft.lesson_id == scope.lesson_id
    assert draft.provider == "openai_compatible"
    assert draft.model == "vision-model"
    assert draft.operation_id == "vision-operation-1"


@pytest.mark.asyncio
async def test_vision_normalizes_common_provider_schema_variations():
    scope = _scope()
    payload = {
        "lesson_id": scope.lesson_id,
        "scope": scope.model_dump(mode="json"),
        "title": None,
        "passage": None,
        "content_items": [
            {"item_number": 1, "english": "fruit", "chinese": "水果", "notes": "plural"},
            {
                "content_id": "grammar-1",
                "type": "grammar",
                "content": {"name": "simple present"},
            },
        ],
        "source_images": [],
        "extraction_status": "completed",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    service = OpenAICompatibleVisionService(
        "https://vision.example",
        client=_client(handler),
    )

    draft = await service.extract_lesson([], scope, operation_id="normalized-operation")

    assert draft.title == ""
    assert draft.passage == ""
    assert draft.extraction_status == "draft"
    assert len(draft.content_items) == 2
    vocabulary = draft.content_items[0]
    assert vocabulary.content_id == "content-1"
    assert vocabulary.type == "vocabulary"
    assert vocabulary.content == {
        "english": "fruit",
        "chinese": "水果",
        "notes": "plural",
    }
    assert draft.content_items[1] == ContentItem(
        content_id="grammar-1",
        type="grammar",
        content={"name": "simple present"},
    )
    assert draft.operation_id == "normalized-operation"


@pytest.mark.asyncio
async def test_vision_rejects_content_item_that_cannot_be_mapped():
    scope = _scope()
    payload = _lesson_payload(scope)
    payload["content_items"] = [{"unexpected": "shape"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    service = OpenAICompatibleVisionService(
        "https://vision.example",
        client=_client(handler),
    )

    with pytest.raises(ProviderResponseInvalid):
        await service.extract_lesson([], scope, operation_id="unmappable-operation")


@pytest.mark.asyncio
async def test_vision_uses_real_upload_identity_and_draft_status(tmp_path):
    scope = _scope()
    image = _image(tmp_path)
    payload = _lesson_payload(scope)
    payload["source_images"] = ["invented-provider-id"]
    payload["extraction_status"] = "published"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    service = OpenAICompatibleVisionService(
        "https://vision.example",
        client=_client(handler),
    )

    draft = await service.extract_lesson(
        [image],
        scope,
        operation_id="identity-operation",
    )

    assert draft.source_images == [image.image_id]
    assert draft.extraction_status == "draft"


@pytest.mark.asyncio
async def test_text_operations_share_chat_contract_and_structured_user_messages():
    lesson = LessonDraft(
        **_lesson_payload(_scope()),
        provider="fixture",
        model="fixture-model",
        operation_id="lesson-operation",
    )
    content_item = ContentItem(
        content_id="grammar-1",
        type="grammar",
        content={"name": "simple present"},
    )
    activity = Activity(
        activity_id="item-1",
        lesson_id=lesson.lesson_id,
        type="multiple_choice",
        prompt="What does school mean?",
        choices=["學校", "老師"],
        answer="學校",
    )
    requests: list[dict[str, object]] = []
    responses = [
        {"explanation": "Use it for routines."},
        _activity_payload(lesson.lesson_id),
        _evaluation_payload(),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(responses[len(requests) - 1])}}
                ]
            },
        )

    service = OpenAICompatibleTextService(
        "https://text.example/v1",
        client=_client(handler),
        model="text-model",
    )

    explanation = await service.explain_grammar(
        lesson, content_item, operation_id="grammar-operation"
    )
    activity_draft = await service.generate_activity(
        lesson, "vocabulary_quiz", operation_id="activity-operation"
    )
    evaluation = await service.evaluate_answer(
        activity, "學校", operation_id="evaluate-operation"
    )

    assert explanation == "Use it for routines."
    assert activity_draft.lesson_id == lesson.lesson_id
    assert activity_draft.operation_id == "activity-operation"
    assert evaluation.correct is True
    assert len(requests) == 3
    assert all(request["model"] == "text-model" for request in requests)
    assert all(request["response_format"] == {"type": "json_object"} for request in requests)
    assert all(request["messages"][0]["role"] == "system" for request in requests)
    assert all("json" in request["messages"][0]["content"].lower() for request in requests)
    assert "explanation" in requests[0]["messages"][0]["content"]
    assert "activity_id" in requests[1]["messages"][0]["content"]
    assert "prompt" in requests[1]["messages"][0]["content"]
    assert "choices" in requests[1]["messages"][0]["content"]
    assert "correct" in requests[2]["messages"][0]["content"]
    grammar_message = json.loads(requests[0]["messages"][-1]["content"])
    activity_message = json.loads(requests[1]["messages"][-1]["content"])
    evaluate_message = json.loads(requests[2]["messages"][-1]["content"])
    assert grammar_message["content_item"]["content"]["name"] == "simple present"
    assert activity_message["activity_type"] == "vocabulary_quiz"
    assert evaluate_message["answer"] == "學校"
    assert "data:image" not in json.dumps(requests)
    assert "audio_base64" not in json.dumps(requests)
    assert "audio_bytes" not in json.dumps(requests)


@pytest.mark.asyncio
async def test_openai_response_accepts_single_json_fence():
    scope = _scope()
    payload = json.dumps(_lesson_payload(scope))
    fenced = "\x60\x60\x60json\n" + payload + "\n" + "\x60\x60\x60"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": fenced}}]},
        )

    service = OpenAICompatibleVisionService(
        "https://vision.example",
        client=_client(handler),
    )

    draft = await service.extract_lesson([], scope, operation_id="fenced-operation")

    assert draft.operation_id == "fenced-operation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": "not-json"}}]},
        {"choices": [{"message": {"content": json.dumps({"title": "missing fields"})}}]},
    ],
)
async def test_invalid_openai_response_maps_to_provider_response_invalid(response):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    service = OpenAICompatibleVisionService(
        "https://vision.example",
        client=_client(handler),
    )

    with pytest.raises(ProviderResponseInvalid):
        await service.extract_lesson([], _scope(), operation_id="invalid-operation")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception, expected",
    [
        (httpx.ReadTimeout("timed out"), ProviderTimeout),
        (httpx.ConnectError("offline"), ProviderUnavailable),
    ],
)
async def test_openai_transport_errors_are_classified(exception, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    service = OpenAICompatibleTextService(
        "https://text.example",
        client=_client(handler),
    )

    lesson = LessonDraft(
        **_lesson_payload(_scope()),
        provider="fixture",
        model="fixture-model",
        operation_id="lesson-operation",
    )
    content_item = ContentItem(
        content_id="grammar-1",
        type="grammar",
        content={"name": "simple present"},
    )

    with pytest.raises(expected):
        await service.explain_grammar(lesson, content_item, operation_id="timeout-operation")


@pytest.mark.asyncio
async def test_openai_http_5xx_is_unavailable_without_secret_in_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="provider secret should not leak")

    service = OpenAICompatibleTextService(
        "https://text.example",
        client=_client(handler),
        headers={"Authorization": "Bearer text-secret"},
    )
    lesson = LessonDraft(
        **_lesson_payload(_scope()),
        provider="fixture",
        model="fixture-model",
        operation_id="lesson-operation",
    )
    content_item = ContentItem(
        content_id="grammar-1",
        type="grammar",
        content={"name": "simple present"},
    )

    with pytest.raises(ProviderUnavailable) as exc_info:
        await service.explain_grammar(lesson, content_item, operation_id="http-error")

    assert "text-secret" not in str(exc_info.value)
    assert "provider secret" not in str(exc_info.value)
@pytest.mark.asyncio
async def test_vision_rejects_operation_identity_mismatch(tmp_path):
    scope = _scope()
    payload = _lesson_payload(scope)
    payload["operation_id"] = "provider-operation"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    service = OpenAICompatibleVisionService(
        "https://vision.example",
        client=_client(handler),
    )

    with pytest.raises(ProviderResponseInvalid, match="operation_id"):
        await service.extract_lesson([], scope, operation_id="requested-operation")


def test_activity_output_instruction_specifies_vocabulary_quiz_question_types() -> None:
    assert "For vocabulary_quiz" in _ACTIVITY_OUTPUT_INSTRUCTION
    assert "dictation" in _ACTIVITY_OUTPUT_INSTRUCTION
    assert "meaning_to_word" in _ACTIVITY_OUTPUT_INSTRUCTION
    assert "word_to_meaning" in _ACTIVITY_OUTPUT_INSTRUCTION
    assert "listen_to_meaning" in _ACTIVITY_OUTPUT_INSTRUCTION
