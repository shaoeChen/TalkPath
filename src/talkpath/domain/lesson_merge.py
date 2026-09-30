"""Append-only merging of a newly extracted lesson into a saved one.

Extraction stays untouched: a new import produces its own ``LessonDraft`` and
this module folds it into the existing lesson just before it is saved.  Old
content items keep their text and IDs, so activities and learning records that
refer to them remain valid.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import Field

from talkpath.domain.models import ContentItem, CourseScope, DomainModel, LessonDraft

_MAX_PAGE_RANGE = 1000
_PAGE_RANGE = re.compile(r"^(\d+)\s*[-–—~]\s*(\d+)$")
_PAGE_NUMBER = re.compile(r"^\d+$")


class ImportBatch(DomainModel):
    """One import (a set of source images) that contributed to a lesson."""

    operation_id: str
    pages: list[str] = Field(default_factory=list)
    source_images: list[str] = Field(default_factory=list)
    content_ids: list[str] = Field(default_factory=list)
    skipped_duplicates: int = 0
    imported_at: datetime | None = None


@dataclass(frozen=True)
class MergeResult:
    lesson: LessonDraft
    batch: ImportBatch
    skipped_duplicates: int


def merge_lesson(existing: LessonDraft, incoming: LessonDraft) -> MergeResult:
    """Return ``existing`` extended with the non-duplicate content of ``incoming``."""

    items = list(existing.content_items)
    used_identities = {(item.type, item.content_id) for item in items}
    seen_keys = {_duplicate_key(item) for item in items}
    added_ids: list[str] = []
    skipped = 0

    for item in incoming.content_items:
        key = _duplicate_key(item)
        if key in seen_keys:
            skipped += 1
            continue
        seen_keys.add(key)
        content_id = _unique_content_id(item, used_identities)
        used_identities.add((item.type, content_id))
        items.append(item.model_copy(update={"content_id": content_id}))
        added_ids.append(content_id)

    scope = CourseScope.model_validate(
        {
            **existing.scope.model_dump(),
            "pages": _ordered_union(existing.scope.pages, incoming.scope.pages),
        }
    )
    lesson = LessonDraft(
        lesson_id=existing.lesson_id,
        scope=scope,
        title=existing.title,
        passage=_join_passages(existing.passage, incoming.passage),
        content_items=items,
        source_images=_ordered_union(existing.source_images, incoming.source_images),
        extraction_status=(
            "draft" if incoming.extraction_status == "draft" else existing.extraction_status
        ),
        provider=incoming.provider,
        model=incoming.model,
        operation_id=incoming.operation_id,
    )
    batch = ImportBatch(
        operation_id=incoming.operation_id,
        pages=list(incoming.scope.pages),
        source_images=list(incoming.source_images),
        content_ids=added_ids,
        skipped_duplicates=skipped,
        imported_at=datetime.now(timezone.utc),
    )
    return MergeResult(lesson=lesson, batch=batch, skipped_duplicates=skipped)


def legacy_batch(lesson: LessonDraft) -> ImportBatch:
    """Describe a lesson saved before batches existed as a single import."""

    return ImportBatch(
        operation_id=lesson.operation_id,
        pages=list(lesson.scope.pages),
        source_images=list(lesson.source_images),
        content_ids=[item.content_id for item in lesson.content_items],
        imported_at=None,
    )


def initial_batch(lesson: LessonDraft) -> ImportBatch:
    """Describe the very first import of a lesson."""

    return legacy_batch(lesson).model_copy(update={"imported_at": datetime.now(timezone.utc)})


def normalize_pages(pages: Iterable[str]) -> set[str]:
    """Expand page labels such as ``"12-13"`` into a comparable set of pages."""

    normalized: set[str] = set()
    for entry in pages:
        for label in str(entry).split(","):
            label = label.strip()
            if not label:
                continue
            range_match = _PAGE_RANGE.match(label)
            if range_match:
                start, end = int(range_match.group(1)), int(range_match.group(2))
                if start <= end and end - start < _MAX_PAGE_RANGE:
                    normalized.update(str(number) for number in range(start, end + 1))
                else:
                    normalized.add(label.casefold())
            elif _PAGE_NUMBER.match(label):
                normalized.add(str(int(label)))
            else:
                normalized.add(label.casefold())
    return normalized


def overlapping_pages(existing_pages: Iterable[str], new_pages: Iterable[str]) -> list[str]:
    """Return the pages present in both lists, numbers first in numeric order."""

    shared = normalize_pages(existing_pages) & normalize_pages(new_pages)
    return sorted(shared, key=lambda page: (not page.isdigit(), int(page) if page.isdigit() else 0, page))


def _duplicate_key(item: ContentItem) -> tuple[str, str]:
    if item.type == "vocabulary":
        word = _vocabulary_word(item)
        if word:
            return ("vocabulary", word.casefold())
    return (item.type, json.dumps(_normalized_content(item.content), sort_keys=True, ensure_ascii=False))


def _vocabulary_word(item: ContentItem) -> str:
    content = item.content
    if isinstance(content, dict):
        return str(content.get("english") or content.get("word") or "").strip()
    return str(content).strip()


def _normalized_content(content: object) -> object:
    return content.strip() if isinstance(content, str) else content


def _unique_content_id(item: ContentItem, used: set[tuple[str, str]]) -> str:
    if (item.type, item.content_id) not in used:
        return item.content_id
    suffix = 2
    while (item.type, f"{item.content_id}-{suffix}") in used:
        suffix += 1
    return f"{item.content_id}-{suffix}"


def _ordered_union(first: Iterable[str], second: Iterable[str]) -> list[str]:
    merged = list(first)
    known = set(merged)
    for value in second:
        if value not in known:
            known.add(value)
            merged.append(value)
    return merged


def _join_passages(existing: str, incoming: str) -> str:
    if not incoming.strip():
        return existing
    if not existing.strip():
        return incoming
    return f"{existing}\n\n{incoming}"
