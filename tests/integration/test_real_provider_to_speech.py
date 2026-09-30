import base64
from datetime import datetime, timedelta, timezone

import pytest

from conftest import require_integration_profile
from talkpath.adapters.provider_registry import ProviderRegistry
from talkpath.adapters.provider_profiles import Capability
from talkpath.domain.models import Activity, CourseScope, ImageReference


pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("TALKPATH_LIVE_TESTS") != "1",
    reason="TALKPATH_LIVE_TESTS is not 1",
)


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
WAV_BYTES = base64.b64decode(
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA="
)


def _scope() -> CourseScope:
    return CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
    )


@pytest.mark.asyncio
async def test_live_provider_to_speech_end_to_end(
    live_integration_settings,
    tmp_path,
):
    for capability in Capability:
        require_integration_profile(live_integration_settings, capability)

    image_path = tmp_path / "lesson.png"
    image_path.write_bytes(PNG_BYTES)
    image = ImageReference(
        image_id="integration-image",
        path=str(image_path),
        mime_type="image/png",
        size_bytes=len(PNG_BYTES),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    registry = ProviderRegistry.from_settings(live_integration_settings)

    try:
        lesson = await registry.vision.extract_lesson(
            [image],
            _scope(),
            operation_id="e2e-vision",
        )
        activity_draft = await registry.text.generate_activity(
            lesson,
            "vocabulary_quiz",
            operation_id="e2e-activity",
        )
        assert activity_draft.items
        activity = Activity.model_validate(
            activity_draft.items[0].model_dump()
        )
        transcript = await registry.stt.transcribe(
            WAV_BYTES,
            mime_type="audio/wav",
            operation_id="e2e-stt",
        )
        evaluation = await registry.text.evaluate_answer(
            activity,
            transcript.text,
            operation_id="e2e-evaluate",
        )
        artifact = await registry.tts.synthesize(
            evaluation.feedback,
            operation_id="e2e-tts",
        )
    finally:
        await registry.aclose()

    assert lesson.lesson_id == _scope().lesson_id
    assert lesson.operation_id == "e2e-vision"
    assert activity_draft.lesson_id == lesson.lesson_id
    assert activity_draft.operation_id == "e2e-activity"
    assert transcript.operation_id == "e2e-stt"
    assert transcript.text.strip()
    assert 0.0 <= evaluation.score <= 1.0
    assert evaluation.feedback.strip()
    assert artifact.operation_id == "e2e-tts"
    assert artifact.mime_type.startswith("audio/")
    assert artifact.audio_bytes
