"""Persistence boundary for LessonLens lesson and activity documents."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from talkpath.domain.lesson_merge import ImportBatch
from talkpath.domain.models import ActivityDraft, CourseScope, ImageReference, LessonDraft


class LessonRepository(Protocol):
    """Repository contract implemented by the Obsidian Markdown adapter."""

    def save_lesson_draft(
        self,
        draft: LessonDraft,
        source_references: Iterable[ImageReference] | None = None,
        import_batches: Sequence[ImportBatch] | None = None,
    ) -> None:
        """Persist or replace a structured lesson draft."""

    def get_lesson(self, lesson_id: str) -> LessonDraft | None:
        """Return a lesson by stable ID, or ``None`` when it is absent."""

    def list_lessons(self, scope: CourseScope | None = None) -> list[LessonDraft]:
        """List stored lessons, optionally restricted to a course scope."""

    def get_import_batches(self, lesson_id: str) -> list[ImportBatch]:
        """Return the imports that built a lesson, oldest first."""

    def source_image_path(self, lesson_id: str, image_id: str) -> Path | None:
        """Return a stored source image of the lesson, or ``None`` if it has none."""

    def delete_lesson(self, lesson_id: str) -> None:
        """Remove a lesson and its generated content documents."""

    def save_activity_draft(self, draft: ActivityDraft) -> None:
        """Persist a generated activity set for a lesson."""

    def get_activity_draft(self, activity_id: str) -> ActivityDraft | None:
        """Return a generated activity set by stable ID, if present."""
