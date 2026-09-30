from __future__ import annotations

from talkpath.domain.lesson_merge import (
    ImportBatch,
    legacy_batch,
    merge_lesson,
    normalize_pages,
    overlapping_pages,
)
from talkpath.domain.models import ContentItem, CourseScope, LessonDraft


def make_scope(pages: list[str], *, textbook: str | None = None) -> CourseScope:
    return CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
        textbook=textbook,
        pages=pages,
    )


def vocab(content_id: str, english: str, chinese: str = "翻譯", *, key: str = "english") -> ContentItem:
    return ContentItem(
        content_id=content_id,
        type="vocabulary",
        content={key: english, "chinese": chinese},
    )


def make_draft(
    pages: list[str],
    operation_id: str,
    items: list[ContentItem],
    *,
    title: str = "Lesson",
    passage: str = "",
    images: list[str] | None = None,
    status: str = "draft",
    provider: str = "fixture",
    textbook: str | None = None,
) -> LessonDraft:
    scope = make_scope(pages, textbook=textbook)
    return LessonDraft(
        lesson_id=scope.lesson_id,
        scope=scope,
        title=title,
        passage=passage,
        content_items=items,
        source_images=images if images is not None else [f"image-{operation_id}"],
        extraction_status=status,
        provider=provider,
        model="fixture-model",
        operation_id=operation_id,
    )


def test_merge_keeps_existing_items_and_appends_new_ones_in_order() -> None:
    existing = make_draft(["3"], "op-1", [vocab("apple", "apple"), vocab("book", "book")])
    incoming = make_draft(["4"], "op-2", [vocab("cat", "cat")])

    result = merge_lesson(existing, incoming)

    assert [item.content_id for item in result.lesson.content_items] == ["apple", "book", "cat"]
    assert result.lesson.content_items[:2] == existing.content_items
    assert result.skipped_duplicates == 0


def test_merge_renames_a_colliding_content_id_without_touching_the_old_one() -> None:
    existing = make_draft(["3"], "op-1", [vocab("word-1", "apple")])
    incoming = make_draft(
        ["4"],
        "op-2",
        [vocab("word-1", "cat"), vocab("word-1", "dog")],
    )

    result = merge_lesson(existing, incoming)

    ids = [item.content_id for item in result.lesson.content_items]
    assert ids == ["word-1", "word-1-2", "word-1-3"]
    assert result.lesson.content_items[0] == existing.content_items[0]
    assert result.batch.content_ids == ["word-1-2", "word-1-3"]


def test_same_content_id_in_a_different_type_is_not_a_collision() -> None:
    existing = make_draft(["3"], "op-1", [vocab("intro", "apple")])
    incoming = make_draft(
        ["4"],
        "op-2",
        [ContentItem(content_id="intro", type="grammar", content="Use am.")],
    )

    result = merge_lesson(existing, incoming)

    assert [(i.type, i.content_id) for i in result.lesson.content_items] == [
        ("vocabulary", "intro"),
        ("grammar", "intro"),
    ]


def test_merge_unions_pages_in_order_and_keeps_identity_fields() -> None:
    existing = make_draft(["3", "4"], "op-1", [vocab("a", "apple")], title="First title", textbook="康軒")
    incoming = make_draft(["4", "5"], "op-2", [vocab("b", "book")], title="Other title", textbook="康軒")

    result = merge_lesson(existing, incoming)

    assert result.lesson.scope.pages == ["3", "4", "5"]
    assert result.lesson.title == "First title"
    assert result.lesson.scope.textbook == "康軒"
    assert result.lesson.lesson_id == existing.lesson_id
    assert result.lesson.scope.lesson_id == existing.lesson_id


def test_merge_joins_passages_and_skips_an_empty_one() -> None:
    existing = make_draft(["3"], "op-1", [], passage="Page three text.")

    joined = merge_lesson(existing, make_draft(["4"], "op-2", [], passage="Page four text."))
    unchanged = merge_lesson(existing, make_draft(["4"], "op-3", [], passage="   "))

    assert joined.lesson.passage == "Page three text.\n\nPage four text."
    assert unchanged.lesson.passage == "Page three text."


def test_merge_appends_source_images_and_records_the_latest_import() -> None:
    existing = make_draft(["3"], "op-1", [vocab("a", "apple")], images=["image-1"], provider="p1")
    incoming = make_draft(["4"], "op-2", [vocab("b", "book")], images=["image-2"], provider="p2")

    result = merge_lesson(existing, incoming)

    assert result.lesson.source_images == ["image-1", "image-2"]
    assert result.lesson.operation_id == "op-2"
    assert result.lesson.provider == "p2"
    assert result.lesson.model == "fixture-model"


def test_merged_status_falls_back_to_draft_when_new_content_is_a_draft() -> None:
    existing = make_draft(["3"], "op-1", [vocab("a", "apple")], status="reviewed")

    result = merge_lesson(existing, make_draft(["4"], "op-2", [vocab("b", "book")], status="draft"))

    assert result.lesson.extraction_status == "draft"


def test_batch_describes_only_the_new_import() -> None:
    existing = make_draft(["3"], "op-1", [vocab("a", "apple")])
    incoming = make_draft(["4"], "op-2", [vocab("b", "book")], images=["image-9"])

    batch = merge_lesson(existing, incoming).batch

    assert batch.operation_id == "op-2"
    assert batch.pages == ["4"]
    assert batch.source_images == ["image-9"]
    assert batch.content_ids == ["b"]
    assert batch.imported_at is not None


def test_duplicate_vocabulary_is_skipped_case_insensitively_across_word_keys() -> None:
    existing = make_draft(["3"], "op-1", [vocab("apple", "Apple", "蘋果")])
    incoming = make_draft(
        ["4"],
        "op-2",
        [
            vocab("apple-again", "  apple ", "不同翻譯", key="word"),
            vocab("banana", "banana"),
        ],
    )

    result = merge_lesson(existing, incoming)

    assert [item.content_id for item in result.lesson.content_items] == ["apple", "banana"]
    assert result.lesson.content_items[0] == existing.content_items[0]
    assert result.skipped_duplicates == 1
    assert result.batch.content_ids == ["banana"]
    assert result.batch.skipped_duplicates == 1


def test_duplicate_vocabulary_inside_the_new_import_is_skipped_too() -> None:
    existing = make_draft(["3"], "op-1", [vocab("apple", "apple")])
    incoming = make_draft(
        ["4"],
        "op-2",
        [vocab("cat", "cat"), vocab("cat-2", "CAT")],
    )

    result = merge_lesson(existing, incoming)

    assert [item.content_id for item in result.lesson.content_items] == ["apple", "cat"]
    assert result.skipped_duplicates == 1


def test_other_types_are_deduplicated_only_when_content_is_identical() -> None:
    existing = make_draft(
        ["3"],
        "op-1",
        [ContentItem(content_id="g1", type="grammar", content="Use am with I.")],
    )
    incoming = make_draft(
        ["4"],
        "op-2",
        [
            ContentItem(content_id="g1-copy", type="grammar", content="Use am with I."),
            ContentItem(content_id="g2", type="grammar", content="Use is with he."),
            ContentItem(content_id="e1", type="exercise", content="Use am with I."),
        ],
    )

    result = merge_lesson(existing, incoming)

    assert [item.content_id for item in result.lesson.content_items] == ["g1", "g2", "e1"]
    assert result.skipped_duplicates == 1


def test_dict_content_is_compared_ignoring_key_order() -> None:
    existing = make_draft(
        ["3"],
        "op-1",
        [ContentItem(content_id="t1", type="table", content={"a": 1, "b": 2})],
    )
    incoming = make_draft(
        ["4"],
        "op-2",
        [ContentItem(content_id="t2", type="table", content={"b": 2, "a": 1})],
    )

    result = merge_lesson(existing, incoming)

    assert len(result.lesson.content_items) == 1
    assert result.skipped_duplicates == 1


def test_merge_does_not_mutate_its_inputs() -> None:
    existing = make_draft(["3"], "op-1", [vocab("a", "apple")])
    incoming = make_draft(["4"], "op-2", [vocab("a", "book")])
    existing_before = existing.model_copy(deep=True)
    incoming_before = incoming.model_copy(deep=True)

    merge_lesson(existing, incoming)

    assert existing == existing_before
    assert incoming == incoming_before


def test_legacy_batch_describes_the_whole_existing_lesson() -> None:
    lesson = make_draft(["3"], "op-1", [vocab("a", "apple"), vocab("b", "book")], images=["image-1"])

    batch = legacy_batch(lesson)

    assert batch == ImportBatch(
        operation_id="op-1",
        pages=["3"],
        source_images=["image-1"],
        content_ids=["a", "b"],
        imported_at=None,
    )


def test_normalize_pages_expands_ranges_and_lists() -> None:
    assert normalize_pages(["12-13", "5"]) == {"12", "13", "5"}
    assert normalize_pages(["3,4", " 06 "]) == {"3", "4", "6"}
    assert normalize_pages(["9–11"]) == {"9", "10", "11"}
    assert normalize_pages([]) == set()


def test_normalize_pages_keeps_non_numeric_labels_as_text() -> None:
    assert normalize_pages(["Cover", "iv"]) == {"cover", "iv"}


def test_normalize_pages_does_not_explode_a_huge_range() -> None:
    assert normalize_pages(["1-100000"]) == {"1-100000"}
    assert normalize_pages(["9-3"]) == {"9-3"}


def test_overlapping_pages_returns_sorted_shared_pages() -> None:
    assert overlapping_pages(["3", "10-11"], ["11", "3", "4"]) == ["3", "11"]
    assert overlapping_pages(["3"], ["4"]) == []
    assert overlapping_pages([], ["4"]) == []
