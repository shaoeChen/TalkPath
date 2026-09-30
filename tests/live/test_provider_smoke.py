import base64
from datetime import datetime, timedelta, timezone

import pytest

from conftest import require_live_profile
from talkpath.adapters.provider_registry import ProviderRegistry
from talkpath.adapters.provider_profiles import Capability
from talkpath.domain.models import (
    Activity,
    ContentItem,
    CourseScope,
    ImageReference,
    LessonDraft,
)


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _scope() -> CourseScope:
    return CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )


def _lesson() -> LessonDraft:
    scope = _scope()
    return LessonDraft(
        lesson_id=scope.lesson_id,
        scope=scope,
        title="Live smoke lesson",
        passage="I go to school every day.",
        content_items=[
            ContentItem(
                content_id="grammar-1",
                type="grammar",
                content={"name": "simple present"},
            )
        ],
        source_images=[],
        extraction_status="draft",
        provider="live-fixture",
        model="live-fixture",
        operation_id="live-lesson",
    )


@pytest.mark.asyncio
async def test_live_vision_smoke(live_settings, tmp_path):
    require_live_profile(live_settings, Capability.VISION)
    image_path = tmp_path / "live.png"
    image_path.write_bytes(PNG_BYTES)
    image = ImageReference(
        image_id="live-image",
        path=str(image_path),
        mime_type="image/png",
        size_bytes=len(PNG_BYTES),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    registry = ProviderRegistry.from_settings(live_settings)

    try:
        draft = await registry.vision.extract_lesson(
            [image],
            _scope(),
            operation_id="live-vision-smoke",
        )
    finally:
        await registry.aclose()

    assert draft.lesson_id == _scope().lesson_id
    assert draft.operation_id == "live-vision-smoke"
    assert draft.title.strip()
    assert draft.passage.strip()


@pytest.mark.asyncio
async def test_live_text_smoke(live_settings):
    require_live_profile(live_settings, Capability.TEXT)
    lesson = _lesson()
    registry = ProviderRegistry.from_settings(live_settings)

    try:
        explanation = await registry.text.explain_grammar(
            lesson,
            lesson.content_items[0],
            operation_id="live-grammar-smoke",
        )
        activity_draft = await registry.text.generate_activity(
            lesson,
            "vocabulary_quiz",
            operation_id="live-activity-smoke",
        )
        assert activity_draft.items
        activity = Activity.model_validate(
            activity_draft.items[0].model_dump()
        )
        evaluation = await registry.text.evaluate_answer(
            activity,
            "school",
            operation_id="live-evaluate-smoke",
        )
    finally:
        await registry.aclose()

    assert explanation.strip()
    assert activity_draft.lesson_id == lesson.lesson_id
    assert activity_draft.operation_id == "live-activity-smoke"
    assert 0.0 <= evaluation.score <= 1.0
    assert evaluation.feedback.strip()
