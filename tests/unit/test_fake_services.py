from datetime import datetime, timedelta, timezone

import pytest

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService,
    FakeTextService,
    FakeTextToSpeechService,
    FakeVisionService,
    ProviderRegistry,
)
from talkpath.config import Settings
from talkpath.domain.models import (
    ActivityDraft,
    AnswerEvaluation,
    AudioArtifact,
    CourseScope,
    ImageReference,
    LessonDraft,
    Transcript,
)


def make_scope() -> CourseScope:
    return CourseScope(
        program="junior-high",
        grade="1",
        subject="english",
        lesson="1",
    )


def make_image(tmp_path) -> ImageReference:
    image_path = tmp_path / "page-1.jpg"
    image_path.write_bytes(b"fixture textbook image")
    return ImageReference(
        image_id="page-1",
        path=str(image_path),
        mime_type="image/jpeg",
        size_bytes=image_path.stat().st_size,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_fake_vision_returns_deterministic_valid_lesson_draft(tmp_path):
    service = FakeVisionService()
    scope = make_scope()
    image = make_image(tmp_path)

    first = await service.extract_lesson([image], scope, operation_id="vision-op")
    second = await service.extract_lesson([image], scope, operation_id="vision-op")

    assert isinstance(first, LessonDraft)
    assert first == second
    assert first.lesson_id == scope.lesson_id
    assert first.source_images == [image.image_id]
    assert LessonDraft.model_validate(first.model_dump()) == first


@pytest.mark.asyncio
async def test_fake_text_supports_activity_grammar_and_answer_contracts():
    lesson = await FakeVisionService().extract_lesson([], make_scope(), operation_id="lesson-op")
    service = FakeTextService()

    activity = await service.generate_activity(
        lesson, "vocabulary_quiz", operation_id="activity-op"
    )
    explanation = await service.explain_grammar(
        lesson, lesson.content_items[-1], operation_id="grammar-op"
    )
    evaluation = await service.evaluate_answer(
        activity.items[0], activity.items[0].answer or "", operation_id="answer-op"
    )

    assert isinstance(activity, ActivityDraft)
    assert activity.type == "vocabulary_quiz"
    assert activity.items
    assert explanation
    assert isinstance(evaluation, AnswerEvaluation)
    assert evaluation.correct is True
    assert ActivityDraft.model_validate(activity.model_dump()) == activity
    assert AnswerEvaluation.model_validate(evaluation.model_dump()) == evaluation


@pytest.mark.asyncio
async def test_fake_vocabulary_quiz_emits_mixed_question_types():
    lesson = await FakeVisionService().extract_lesson([], make_scope(), operation_id="lesson-op")
    service = FakeTextService()

    activity = await service.generate_activity(
        lesson, "vocabulary_quiz", operation_id="quiz-op"
    )

    assert {item.question_type for item in activity.items} == {
        "dictation",
        "meaning_to_word",
        "word_to_meaning",
    }
    for item in activity.items:
        if item.question_type in {"dictation", "meaning_to_word"}:
            assert item.choices == []
            assert item.answer == "school"
        if item.question_type == "dictation":
            assert item.prompt == "school"
        if item.question_type == "meaning_to_word":
            assert item.prompt == "學校"
        if item.question_type == "word_to_meaning":
            assert item.prompt == "school"
            assert item.answer == "學校"
            assert len(item.choices) == 4


@pytest.mark.asyncio
async def test_fake_reading_aloud_uses_lesson_words_as_spoken_prompt():
    lesson = await FakeVisionService().extract_lesson([], make_scope(), operation_id="lesson-op")

    activity = await FakeTextService().generate_activity(
        lesson, "reading_aloud", operation_id="reading-op"
    )

    assert activity.type == "reading_aloud"
    assert activity.items
    assert activity.items[0].prompt == lesson.passage.split(". ")[0] + "."
    assert activity.items[0].choices == []
    assert activity.items[0].answer == activity.items[0].prompt


@pytest.mark.asyncio
async def test_fake_speech_services_return_valid_deterministic_models(tmp_path):
    stt = FakeSpeechToTextService()
    tts = FakeTextToSpeechService()

    transcript_a = await stt.transcribe(
        b"recorded audio", mime_type="audio/wav", operation_id="stt-op"
    )
    transcript_b = await stt.transcribe(
        b"recorded audio", mime_type="audio/wav", operation_id="stt-op"
    )
    audio_a = await tts.synthesize("Hello", voice="child", operation_id="tts-op")
    audio_b = await tts.synthesize("Hello", voice="child", operation_id="tts-op")

    assert isinstance(transcript_a, Transcript)
    assert transcript_a == transcript_b
    assert isinstance(audio_a, AudioArtifact)
    assert audio_a == audio_b
    assert audio_a.audio_bytes
    assert Transcript.model_validate(transcript_a.model_dump()) == transcript_a
    assert AudioArtifact.model_validate(audio_a.model_dump()) == audio_a


def test_registry_uses_fake_providers_by_default():
    registry = ProviderRegistry.from_settings(Settings(_env_file=None))

    assert isinstance(registry.vision, FakeVisionService)
    assert isinstance(registry.text, FakeTextService)
    assert isinstance(registry.stt, FakeSpeechToTextService)
    assert isinstance(registry.tts, FakeTextToSpeechService)


@pytest.mark.asyncio
async def test_registry_close_skips_fake_providers_safely():
    registry = ProviderRegistry.from_settings(Settings(_env_file=None))

    await registry.aclose()
    await registry.aclose()
