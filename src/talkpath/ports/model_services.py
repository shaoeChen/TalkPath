"""Provider-independent contracts for vision, text and speech services."""

from __future__ import annotations

from typing import AsyncIterator, Protocol

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


class VisionService(Protocol):
    async def extract_lesson(
        self,
        images: list[ImageReference],
        scope: CourseScope,
        *,
        operation_id: str,
    ) -> LessonDraft:
        """Extract a structured lesson draft from textbook images."""


class TextService(Protocol):
    async def explain_grammar(
        self,
        lesson: LessonDraft,
        content_item: ContentItem,
        *,
        operation_id: str,
    ) -> str:
        """Explain one grammar item in child-friendly language."""

    async def generate_activity(
        self,
        lesson: LessonDraft,
        activity_type: str,
        *,
        operation_id: str,
    ) -> ActivityDraft:
        """Generate a practice or assessment activity set."""

    async def evaluate_answer(
        self,
        activity: Activity,
        answer: str,
        *,
        operation_id: str,
    ) -> AnswerEvaluation:
        """Evaluate one child answer and return actionable feedback."""


class SpeechToTextService(Protocol):
    async def transcribe(
        self,
        audio: bytes,
        *,
        mime_type: str,
        operation_id: str,
    ) -> Transcript:
        """Convert recorded child speech to text."""


class TextToSpeechService(Protocol):
    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        operation_id: str,
    ) -> AudioArtifact:
        """Convert text to playable speech audio."""


class ModelService(VisionService, TextService, SpeechToTextService, TextToSpeechService, Protocol):
    """Combined service boundary used by the first application flow."""

    def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        mime_type: str,
        operation_id: str,
    ) -> AsyncIterator[str]:
        """Optionally stream partial transcription text."""

    def stream_synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        operation_id: str,
    ) -> AsyncIterator[bytes]:
        """Optionally stream encoded audio chunks."""

ModelServices = ModelService
