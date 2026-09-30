"""Deterministic local provider implementations for development and tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    TranscriptSegment,
)

if TYPE_CHECKING:
    from talkpath.adapters.provider_registry import ProviderRegistry


class FakeVisionService:
    """Return a small, stable lesson fixture without accessing a model."""

    async def extract_lesson(
        self,
        images: list[ImageReference],
        scope: CourseScope,
        *,
        operation_id: str,
    ) -> LessonDraft:
        return LessonDraft(
            lesson_id=scope.lesson_id,
            scope=scope,
            title="A Day at School",
            passage="I go to school every day. I learn English with my friends.",
            content_items=[
                ContentItem(
                    content_id="word-school",
                    type="vocabulary",
                    content={
                        "word": "school",
                        "meaning": "學校",
                        "example": "I go to school every day.",
                    },
                    source_page="1",
                ),
                ContentItem(
                    content_id="grammar-simple-present",
                    type="grammar",
                    content={
                        "name": "simple present",
                        "explanation": "Use the simple present for routines.",
                        "example": "I go to school every day.",
                    },
                    source_page="1",
                ),
            ],
            source_images=[image.image_id for image in images],
            extraction_status="draft",
            provider="fake-vision",
            model="talkpath-fixture-vision-v1",
            operation_id=operation_id,
        )


class FakeTextService:
    """Return deterministic child-facing activities and answer feedback."""

    async def explain_grammar(
        self,
        lesson: LessonDraft,
        content_item: ContentItem,
        *,
        operation_id: str,
    ) -> str:
        name = content_item.content.get("name", content_item.content_id) if isinstance(
            content_item.content, dict
        ) else content_item.content_id
        return f"{name} talks about things that happen regularly. Example: I go to school."

    async def generate_activity(
        self,
        lesson: LessonDraft,
        activity_type: str,
        *,
        operation_id: str,
    ) -> ActivityDraft:
        vocabulary = next(
            (
                item
                for item in lesson.content_items
                if item.type == "vocabulary"
            ),
            None,
        )
        word = "school"
        meaning = "學校"
        source_content_ids: list[str] = []
        if vocabulary is not None:
            source_content_ids.append(vocabulary.content_id)
            if isinstance(vocabulary.content, dict):
                word = str(vocabulary.content.get("word", word))
                meaning = str(vocabulary.content.get("meaning", meaning))

        normalized_type = activity_type.strip() or "practice"
        if normalized_type == "vocabulary_practice":
            # Vocabulary practice is a speaking drill: one word card per item,
            # judged by comparing the STT transcript with the word itself.
            item = Activity(
                activity_id=f"{normalized_type}-item-1",
                lesson_id=lesson.lesson_id,
                type="speaking",
                prompt=word,
                choices=[],
                answer=word,
                explanation=f"Say {word} out loud.",
                source_content_ids=source_content_ids,
            )
            instructions = "Listen to the word, then say it out loud."
            items = [item]
        elif normalized_type == "vocabulary_quiz":
            # Vocabulary quiz mixes teacher-style assessment: dictation,
            # Chinese-to-English spelling, and meaning recognition.
            distractors = ["朋友", "天氣", "食物"]
            items = [
                Activity(
                    activity_id=f"{normalized_type}-item-1",
                    lesson_id=lesson.lesson_id,
                    type="dictation",
                    prompt=word,
                    choices=[],
                    answer=word,
                    question_type="dictation",
                    explanation=f"Spell {word}.",
                    source_content_ids=source_content_ids,
                ),
                Activity(
                    activity_id=f"{normalized_type}-item-2",
                    lesson_id=lesson.lesson_id,
                    type="fill_blank",
                    prompt=meaning,
                    choices=[],
                    answer=word,
                    question_type="meaning_to_word",
                    explanation=f"{meaning} is {word}.",
                    source_content_ids=source_content_ids,
                ),
                Activity(
                    activity_id=f"{normalized_type}-item-3",
                    lesson_id=lesson.lesson_id,
                    type="multiple_choice",
                    prompt=word,
                    choices=[meaning, *distractors],
                    answer=meaning,
                    question_type="word_to_meaning",
                    explanation=f"{word} means {meaning}.",
                    source_content_ids=source_content_ids,
                ),
            ]
            instructions = "Listen, spell, and pick the right meaning."
        else:
            item = Activity(
                activity_id=f"{normalized_type}-item-1",
                lesson_id=lesson.lesson_id,
                type="multiple_choice",
                prompt=f"What does {word} mean?",
                choices=[meaning, "老師"],
                answer=meaning,
                explanation=f"{word} means {meaning}.",
                source_content_ids=source_content_ids,
            )
            instructions = "Choose the best answer."
            items = [item]
        return ActivityDraft(
            activity_id=f"{normalized_type}-fixture",
            lesson_id=lesson.lesson_id,
            type=normalized_type,
            title=f"{normalized_type.replace('_', ' ').title()}",
            instructions=instructions,
            items=items,
            source_content_ids=source_content_ids,
            provider="fake-text",
            model="talkpath-fixture-text-v1",
            operation_id=operation_id,
        )

    async def evaluate_answer(
        self,
        activity: Activity,
        answer: str,
        *,
        operation_id: str,
    ) -> AnswerEvaluation:
        expected = activity.answer
        correct = expected is not None and answer.strip().casefold() == expected.strip().casefold()
        return AnswerEvaluation(
            correct=correct,
            score=1.0 if correct else 0.0,
            feedback="Great job!" if correct else "Try again.",
            expected_answer=expected,
        )


class FakeSpeechToTextService:
    """Return a stable transcript for any recorded input."""

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime_type: str,
        operation_id: str,
    ) -> Transcript:
        return Transcript(
            text="Hello, TalkPath!",
            language="en",
            segments=[
                TranscriptSegment(
                    text="Hello, TalkPath!",
                    start_seconds=0.0,
                    end_seconds=1.0,
                )
            ],
            provider="fake-stt",
            model="talkpath-fixture-stt-v1",
            operation_id=operation_id,
        )


class FakeTextToSpeechService:
    """Return deterministic bytes that are suitable for adapter tests."""

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        operation_id: str,
    ) -> AudioArtifact:
        selected_voice = voice or "default"
        audio_bytes = f"TALKPATH-FAKE-AUDIO|{selected_voice}|{text}".encode("utf-8")
        return AudioArtifact(
            audio_bytes=audio_bytes,
            mime_type="audio/mpeg",
            provider="fake-tts",
            model="talkpath-fixture-tts-v1",
            operation_id=operation_id,
        )


# The registry is implemented with the HTTP adapter module to keep provider
# construction in one place.  Re-export it here for callers that start with
# the local fake provider module.
from talkpath.adapters.provider_registry import ProviderRegistry  # noqa: E402


__all__ = [
    "FakeSpeechToTextService",
    "FakeTextService",
    "FakeTextToSpeechService",
    "FakeVisionService",
    "ProviderRegistry",
]
