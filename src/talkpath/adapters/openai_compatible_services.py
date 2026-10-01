"""OpenAI-compatible Vision and Text provider adapters."""

from __future__ import annotations

import base64
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
    ContentItem,
    CourseScope,
    ImageReference,
    LessonDraft,
)


DEFAULT_OPENAI_TIMEOUT = 120.0

_JSON_OUTPUT_INSTRUCTION = (
    "Return exactly one valid JSON object. Do not use Markdown fences or prose."
    " Escape all double quotes and backslashes inside JSON string values according to JSON syntax."
    " All Chinese output MUST use Traditional Chinese (繁體／正體中文, zh-TW) exclusively. "
    "Never output Simplified Chinese or mix Simplified and Traditional characters. "
    "This applies to translations, vocabulary meanings, explanations, titles, instructions, "
    "question prompts, choices, answers, and feedback. Convert any Simplified Chinese "
    "in source images or supplied lesson content to Traditional Chinese when producing output. "
    "Preserve English lesson text and English answers in English; preserve JSON keys and identifiers."
)

_VISION_OUTPUT_INSTRUCTION = (
    "For lesson extraction, return a JSON object with lesson_id, scope, title, passage, "
    "content_items, source_images, extraction_status, and operation_id. "
    "title and passage must be strings (passage may be an empty string). "
    "extraction_status must be exactly one of: draft, reviewed, published. "
    "Each content_items entry must be a JSON object with content_id (string), type "
    "(string such as vocabulary or grammar), content (a string or a JSON object with "
    "english and chinese keys), and optional source_page. Do not add other keys."
)
_GRAMMAR_OUTPUT_INSTRUCTION = (
    "Return a JSON object with exactly one field: explanation, whose value is a string."
)
_ACTIVITY_OUTPUT_INSTRUCTION = (
    "Return a JSON object with activity_id, lesson_id, type, title, instructions, "
    "items, and source_content_ids. Each item must contain activity_id, lesson_id, type, "
    "prompt, choices, answer, and question_type as a string; optional explanation and "
    "source_content_ids are allowed. "
    "Each item's activity_id must be unique, for example activity_id-item-1, activity_id-item-2. "
    "Do not use id, question, or options. "
    "For vocabulary_practice, every item is one vocabulary word from the lesson: "
    "prompt must be exactly the English word, answer must be exactly the same English word, "
    "and choices must be an empty list. "
    "For vocabulary_quiz, generate one item per vocabulary word in the lesson, shuffled "
    "into a random order, with question_type exactly one of: dictation, meaning_to_word, "
    "word_to_meaning, listen_to_meaning. For dictation and listen_to_meaning, prompt is the "
    "English word and is used for audio only. For meaning_to_word, prompt is the Chinese "
    "meaning and choices is an empty list. For word_to_meaning and listen_to_meaning, choices "
    "must contain 4 Chinese options including the correct meaning, and answer is the correct "
    "Chinese meaning. For dictation and meaning_to_word, choices is an empty list and answer is "
    "the English word. Mix question types so roughly half the items are dictation or "
    "meaning_to_word and the rest are word_to_meaning or listen_to_meaning. "
    "For reading_aloud, each prompt must be a short English sentence or passage from "
    "the lesson for the child to repeat aloud; answer must be exactly the same as prompt "
    "and choices must be an empty list. Do not create dictation or multiple-choice questions "
    "or ask the child to type."
)
_EVALUATION_OUTPUT_INSTRUCTION = (
    "Return a JSON object with correct as boolean, score as a number from 0 to 1, "
    "feedback as a string, and optional expected_answer."
)


class _OpenAICompatibleChatService:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_OPENAI_TIMEOUT,
        model: str = "default",
        chat_path: str = "/chat/completions",
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("openai-compatible base_url is required")
        if timeout <= 0:
            raise ValueError("openai-compatible timeout must be positive")
        normalized_path = chat_path.strip()
        self.endpoint = base_url.rstrip("/") + "/" + normalized_path.lstrip("/")
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

    async def _chat(
        self,
        messages: list[dict[str, Any]],
        *,
        output_instruction: str | None = None,
    ) -> Any:
        system_instruction = _JSON_OUTPUT_INSTRUCTION
        if output_instruction:
            system_instruction += " " + output_instruction

        invalid_content: str | None = None
        for attempt in range(2):
            instruction = system_instruction
            if attempt:
                instruction += (
                    " Correct the JSON syntax of your previous response."
                    " Keep the same lesson content, scope and identifiers."
                )
            retry_messages = messages
            if invalid_content is not None:
                retry_messages = [
                    *messages,
                    {"role": "assistant", "content": invalid_content},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response is invalid JSON. Return the full corrected"
                            " JSON object only. Escape quotes and backslashes inside string"
                            " values; preserve the original content and identifiers."
                        ),
                    },
                ]
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": instruction},
                    *retry_messages,
                ],
                "response_format": {"type": "json_object"},
            }
            try:
                response = await self._client.post(
                    self.endpoint,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout,
                )
            except httpx.TimeoutException as exc:
                raise ProviderTimeout("openai-compatible provider timed out") from exc
            except httpx.RequestError as exc:
                raise ProviderUnavailable(
                    "openai-compatible provider request failed"
                ) from exc

            if not 200 <= response.status_code < 300:
                raise ProviderUnavailable(
                    f"openai-compatible provider returned HTTP {response.status_code}"
                )

            try:
                response_payload = response.json()
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
                raise ProviderResponseInvalid(
                    "openai-compatible provider returned invalid JSON"
                ) from exc

            content = self._extract_content(response_payload)
            try:
                return self._parse_content(content)
            except ProviderResponseInvalid as exc:
                if attempt or not isinstance(exc.__cause__, json.JSONDecodeError):
                    raise
                invalid_content = content

        raise AssertionError("unreachable")

    @staticmethod
    def _extract_content(response_payload: Any) -> str:
        if not isinstance(response_payload, dict):
            raise ProviderResponseInvalid(
                "openai-compatible response is missing choices"
            )
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseInvalid(
                "openai-compatible response is missing choices"
            )
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ProviderResponseInvalid(
                "openai-compatible response is missing message"
            )
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise ProviderResponseInvalid(
                "openai-compatible response is missing message"
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderResponseInvalid(
                "openai-compatible response is missing message content"
            )
        return content

    @staticmethod
    def _parse_content(content: str) -> Any:
        normalized = content.strip()
        if normalized.startswith("\x60\x60\x60"):
            lines = normalized.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "\x60\x60\x60":
                raise ProviderResponseInvalid(
                    "openai-compatible response contains invalid JSON fence"
                )
            language = lines[0][3:].strip().lower()
            if language not in {"", "json"}:
                raise ProviderResponseInvalid(
                    "openai-compatible response contains unsupported JSON fence"
                )
            normalized = "\n".join(lines[1:-1]).strip()
        try:
            return json.loads(normalized)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ProviderResponseInvalid(
                "openai-compatible response content is not valid JSON"
            ) from exc

    @staticmethod
    def _validated(model_type, payload: Any, capability: str):
        try:
            return model_type.model_validate(payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise ProviderResponseInvalid(
                f"openai-compatible {capability} response does not match schema"
            ) from exc

    @staticmethod
    def _set_identity(
        payload: dict[str, Any],
        field: str,
        expected: Any,
        capability: str,
    ) -> None:
        if field in payload and payload[field] != expected:
            raise ProviderResponseInvalid(
                f"openai-compatible {capability} response {field} does not match request"
            )
        payload[field] = expected


class OpenAICompatibleVisionService(_OpenAICompatibleChatService):
    async def extract_lesson(
        self,
        images: list[ImageReference],
        scope: CourseScope,
        *,
        operation_id: str,
    ) -> LessonDraft:
        image_messages: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "scope": scope.model_dump(mode="json"),
                        "operation_id": operation_id,
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        for image in images:
            try:
                image_bytes = open(image.path, "rb").read()
            except OSError as exc:
                raise ProviderResponseInvalid(
                    f"vision source image could not be read: {image.image_id}"
                ) from exc
            encoded = base64.b64encode(image_bytes).decode("ascii")
            image_messages.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.mime_type};base64,{encoded}",
                    },
                }
            )

        payload = await self._chat(
            [
                {
                    "role": "user",
                    "content": image_messages,
                }
            ],
            output_instruction=_VISION_OUTPUT_INSTRUCTION,
        )
        if not isinstance(payload, dict):
            raise ProviderResponseInvalid(
                "openai-compatible vision response must be a JSON object"
            )
        payload = dict(payload)
        self._set_identity(payload, "lesson_id", scope.lesson_id, "vision")
        self._set_identity(payload, "scope", scope.model_dump(mode="json"), "vision")
        payload["source_images"] = [image.image_id for image in images]
        payload["provider"] = "openai_compatible"
        payload["model"] = self.model
        self._set_identity(payload, "operation_id", operation_id, "vision_or_text")
        payload["operation_id"] = operation_id
        self._normalize_vision_payload(payload)
        return self._validated(LessonDraft, payload, "vision")

    @staticmethod
    def _normalize_vision_payload(payload: dict[str, Any]) -> None:
        """Coerce common provider variations into the TalkPath lesson schema."""

        if "title" in payload and payload["title"] is None:
            payload["title"] = ""
        if "passage" in payload and payload["passage"] is None:
            payload["passage"] = ""
        payload["extraction_status"] = "draft"
        items = payload.get("content_items")
        if not isinstance(items, list):
            return
        normalized: list[dict[str, Any]] = []
        for index, raw in enumerate(items, start=1):
            if isinstance(raw, dict):
                try:
                    ContentItem.model_validate(raw)
                except (ValidationError, TypeError, ValueError):
                    mapped = OpenAICompatibleVisionService._vocab_content_item(raw, index)
                    if mapped is not None:
                        normalized.append(mapped)
                        continue
            normalized.append(raw)
        payload["content_items"] = normalized

    @staticmethod
    def _vocab_content_item(
        raw: Mapping[str, Any],
        index: int,
    ) -> dict[str, Any] | None:
        """Map a flat word/translation card into a vocabulary ContentItem."""

        english = raw.get("english")
        if not isinstance(english, str) or not english.strip():
            return None
        content: dict[str, Any] = {"english": english.strip()}
        chinese = raw.get("chinese")
        if isinstance(chinese, str) and chinese.strip():
            content["chinese"] = chinese.strip()
        notes = raw.get("notes")
        if isinstance(notes, str) and notes.strip():
            content["notes"] = notes.strip()
        return {
            "content_id": f"content-{index}",
            "type": "vocabulary",
            "content": content,
        }


class OpenAICompatibleTextService(_OpenAICompatibleChatService):
    async def explain_grammar(
        self,
        lesson: LessonDraft,
        content_item: ContentItem,
        *,
        operation_id: str,
    ) -> str:
        payload = await self._chat(
            [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "capability": "grammar",
                            "lesson": lesson.model_dump(mode="json"),
                            "content_item": content_item.model_dump(mode="json"),
                            "operation_id": operation_id,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            output_instruction=_GRAMMAR_OUTPUT_INSTRUCTION,
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("explanation"), str
        ):
            raise ProviderResponseInvalid(
                "openai-compatible grammar response does not match schema"
            )
        return payload["explanation"]

    async def generate_activity(
        self,
        lesson: LessonDraft,
        activity_type: str,
        *,
        operation_id: str,
    ) -> ActivityDraft:
        payload = await self._chat(
            [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "capability": "activity",
                            "lesson": lesson.model_dump(mode="json"),
                            "activity_type": activity_type,
                            "operation_id": operation_id,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            output_instruction=_ACTIVITY_OUTPUT_INSTRUCTION,
        )
        if not isinstance(payload, dict):
            raise ProviderResponseInvalid(
                "openai-compatible activity response must be a JSON object"
            )
        payload = dict(payload)
        if activity_type == "reading_aloud" and isinstance(payload.get("items"), list):
            payload["title"] = "Reading / read aloud"
            payload["instructions"] = "Listen, then read the sentence aloud."
            items = []
            for raw_item in payload["items"]:
                if not isinstance(raw_item, dict) or not isinstance(
                    raw_item.get("prompt"), str
                ):
                    raise ProviderResponseInvalid("reading aloud item requires a prompt")
                prompt = raw_item["prompt"].strip()
                if not prompt:
                    raise ProviderResponseInvalid("reading aloud item requires a prompt")
                items.append({**raw_item, "prompt": prompt, "choices": [], "answer": prompt})
            payload["items"] = items
        self._set_identity(payload, "lesson_id", lesson.lesson_id, "activity")
        payload.setdefault("activity_id", f"{activity_type}-{operation_id}")
        payload.setdefault("type", activity_type)
        payload["provider"] = "openai_compatible"
        payload["model"] = self.model
        self._set_identity(payload, "operation_id", operation_id, "vision_or_text")
        payload["operation_id"] = operation_id
        return self._validated(ActivityDraft, payload, "activity")

    async def evaluate_answer(
        self,
        activity: Activity,
        answer: str,
        *,
        operation_id: str,
    ) -> AnswerEvaluation:
        payload = await self._chat(
            [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "capability": "evaluate",
                            "activity": activity.model_dump(mode="json"),
                            "answer": answer,
                            "operation_id": operation_id,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            output_instruction=_EVALUATION_OUTPUT_INSTRUCTION,
        )
        return self._validated(AnswerEvaluation, payload, "evaluation")


__all__ = [
    "OpenAICompatibleTextService",
    "OpenAICompatibleVisionService",
]
