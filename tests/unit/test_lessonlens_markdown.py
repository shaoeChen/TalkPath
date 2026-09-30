from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talkpath.adapters.lessonlens_markdown import (
    InvalidLessonIdError,
    LessonLensParseError,
    LessonLensMarkdownRepository,
    SourceImageNotApprovedError,
)
from talkpath.domain.errors import RepositoryError
from talkpath.domain.lesson_merge import legacy_batch, merge_lesson
from talkpath.domain.models import ContentItem, ImageReference, LessonDraft


FIXTURE = Path(__file__).parents[1] / "fixtures" / "lesson_draft.json"


def load_draft() -> LessonDraft:
    return LessonDraft.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def approve_image(tmp_path: Path, image_id: str = "page-001.jpg") -> ImageReference:
    source = tmp_path / "uploads" / image_id
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fixture image bytes")
    return ImageReference(
        image_id=image_id,
        path=str(source),
        mime_type="image/jpeg",
        size_bytes=source.stat().st_size,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def make_repository(tmp_path: Path) -> LessonLensMarkdownRepository:
    return LessonLensMarkdownRepository(
        tmp_path / "lessonlens",
        approved_sources=[approve_image(tmp_path)],
    )


def test_save_and_get_lesson_round_trip_writes_obsidian_layout(
    tmp_path: Path,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)

    repo.save_lesson_draft(draft)

    lesson_root = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
    )
    assert (lesson_root / "lesson.md").is_file()
    assert (lesson_root / "vocabulary" / "hello.md").is_file()
    assert (lesson_root / "grammar" / "be-verb.md").is_file()
    assert (lesson_root / "sources" / "page-001.jpg").read_bytes() == b"fixture image bytes"

    lesson_markdown = (lesson_root / "lesson.md").read_text(encoding="utf-8")
    assert lesson_markdown.startswith("---\n")
    assert "# Hello, Amy!" in lesson_markdown
    assert "## Passage" in lesson_markdown

    restored = repo.get_lesson(draft.lesson_id)

    assert restored == draft
    assert restored is not None
    assert restored.scope == draft.scope
    assert restored.content_items == draft.content_items
    assert restored.source_images == draft.source_images
    assert restored.operation_id == draft.operation_id


def test_retrying_same_operation_is_idempotent_and_does_not_append(
    tmp_path: Path,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)
    lesson_path = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
        / "lesson.md"
    )
    before = lesson_path.read_bytes()

    repo.save_lesson_draft(draft)

    assert lesson_path.read_bytes() == before
    assert lesson_path.read_text(encoding="utf-8").count("# Hello, Amy!") == 1


def test_same_operation_succeeds_without_reading_an_expired_original_source(
    tmp_path: Path,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)

    original_source = tmp_path / "uploads" / "page-001.jpg"
    original_source.unlink()
    expired_reference = ImageReference(
        image_id="page-001.jpg",
        path=str(original_source),
        mime_type="image/jpeg",
        size_bytes=0,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    retry_repo = LessonLensMarkdownRepository(
        tmp_path / "lessonlens",
        approved_sources=[expired_reference],
    )

    retry_repo.save_lesson_draft(draft)

    assert retry_repo.get_lesson(draft.lesson_id) == draft


@pytest.mark.parametrize(
    "relative_path",
    [
        Path("lesson.md"),
        Path("vocabulary") / "hello.md",
        Path("sources") / "page-001.jpg",
    ],
)
def test_read_rejects_symlinked_final_files(
    tmp_path: Path,
    relative_path: Path,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)
    lesson_root = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
    )
    target = lesson_root / relative_path
    outside = tmp_path / f"outside-{target.name}"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(RepositoryError, match="symlink|outside"):
        repo.get_lesson(draft.lesson_id)


def test_new_draft_removes_obsolete_managed_content_and_sources(
    tmp_path: Path,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)
    replacement = draft.model_copy(
        update={
            "content_items": [draft.content_items[0]],
            "source_images": [],
            "operation_id": "op-lesson-002",
        }
    )
    lesson_root = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
    )
    preserved_file = lesson_root / "grammar" / "manual-note.md"
    preserved_file.write_text("keep this user note", encoding="utf-8")

    repo.save_lesson_draft(replacement)

    assert (lesson_root / "vocabulary" / "hello.md").is_file()
    assert not (lesson_root / "grammar" / "be-verb.md").exists()
    assert not (lesson_root / "sources" / "page-001.jpg").exists()
    assert preserved_file.read_text(encoding="utf-8") == "keep this user note"
    assert repo.get_lesson(draft.lesson_id) == replacement


def test_obsolete_cleanup_failure_rolls_back_old_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)
    replacement = draft.model_copy(
        update={
            "content_items": [draft.content_items[0]],
            "source_images": [],
            "operation_id": "op-lesson-002",
        }
    )
    monkeypatch.setattr(
        repo,
        "_delete_obsolete_file",
        lambda _path: (_ for _ in ()).throw(OSError("simulated obsolete cleanup failure")),
    )

    with pytest.raises(RepositoryError, match="could not write"):
        repo.save_lesson_draft(replacement)

    assert repo.get_lesson(draft.lesson_id) == draft
    lesson_root = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
    )
    assert (lesson_root / "grammar" / "be-verb.md").is_file()
    assert (lesson_root / "sources" / "page-001.jpg").is_file()
    assert not list(repo.root.glob(".talkpath-stage-*"))


def test_duplicate_content_identity_is_rejected_before_creating_curricula(
    tmp_path: Path,
) -> None:
    draft = load_draft()
    duplicate = draft.model_copy(
        update={"content_items": [draft.content_items[0], draft.content_items[0]]}
    )
    repo = make_repository(tmp_path)

    with pytest.raises(RepositoryError, match="duplicate content"):
        repo.save_lesson_draft(duplicate)

    assert not (tmp_path / "lessonlens" / "curricula").exists()


def test_duplicate_source_image_id_is_rejected_before_creating_curricula(
    tmp_path: Path,
) -> None:
    draft = load_draft().model_copy(
        update={"source_images": ["page-001.jpg", "page-001.jpg"]}
    )
    repo = make_repository(tmp_path)

    with pytest.raises(RepositoryError, match="duplicate source"):
        repo.save_lesson_draft(draft)

    assert not (tmp_path / "lessonlens" / "curricula").exists()


def test_reusing_operation_id_for_different_content_is_rejected(
    tmp_path: Path,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)
    changed = draft.model_copy(update={"title": "A different lesson"})

    with pytest.raises(RepositoryError, match="operation_id"):
        repo.save_lesson_draft(changed)


@pytest.mark.parametrize(
    "lesson_id",
    ["../escape", "junior-high/grade-1/english/lesson-01", "C:\\escape", "/absolute", "."],
)
def test_invalid_lesson_id_cannot_escape_vault(
    tmp_path: Path,
    lesson_id: str,
) -> None:
    repo = LessonLensMarkdownRepository(tmp_path / "lessonlens")

    with pytest.raises(InvalidLessonIdError):
        repo.get_lesson(lesson_id)


def test_lesson_with_textbook_suffix_round_trips_and_is_listed(tmp_path: Path) -> None:
    base = load_draft()
    scope = base.scope.model_copy(update={"textbook": "康軒", "lesson_id": ""})
    scope = type(scope).model_validate(
        {**scope.model_dump(), "lesson_id": ""}
    )
    draft = base.model_copy(update={"scope": scope, "lesson_id": scope.lesson_id})
    repo = make_repository(tmp_path)

    repo.save_lesson_draft(draft)

    lesson_root = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01--u5eb7-u8ed2"
    )
    assert (lesson_root / "lesson.md").is_file()
    assert scope.lesson_id.endswith("lesson-01--u5eb7-u8ed2")
    assert repo.get_lesson(scope.lesson_id) == draft
    assert repo.list_lessons() == [draft]


def test_textbook_lessons_and_legacy_lessons_can_coexist(tmp_path: Path) -> None:
    legacy = load_draft()
    scope = type(legacy.scope).model_validate(
        {**legacy.scope.model_dump(), "textbook": "翰林", "lesson_id": ""}
    )
    other = legacy.model_copy(
        update={
            "scope": scope,
            "lesson_id": scope.lesson_id,
            "operation_id": "op-lesson-002",
        }
    )
    repo = make_repository(tmp_path)

    repo.save_lesson_draft(legacy)
    repo.save_lesson_draft(other)

    assert {lesson.lesson_id for lesson in repo.list_lessons()} == {
        legacy.lesson_id,
        other.lesson_id,
    }
    assert legacy.lesson_id != other.lesson_id


def make_incoming(draft: LessonDraft) -> LessonDraft:
    scope = type(draft.scope).model_validate(
        {**draft.scope.model_dump(), "pages": ["14"]}
    )
    return draft.model_copy(
        update={
            "scope": scope,
            "content_items": [
                ContentItem(
                    content_id="goodbye",
                    type="vocabulary",
                    content={"word": "goodbye", "meaning": "a farewell"},
                    source_page="14",
                )
            ],
            "source_images": ["page-002.jpg"],
            "operation_id": "op-lesson-002",
            "passage": "Goodbye, Amy.",
        }
    )


def lesson_root_of(tmp_path: Path, draft: LessonDraft) -> Path:
    return (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
    )


def test_merged_lesson_keeps_old_sources_and_writes_only_the_new_one(
    tmp_path: Path,
) -> None:
    first = load_draft()
    make_repository(tmp_path).save_lesson_draft(first)
    merged = merge_lesson(first, make_incoming(first))
    # A fresh repository (as after a restart) only knows the new upload.
    repo = LessonLensMarkdownRepository(
        tmp_path / "lessonlens",
        approved_sources=[approve_image(tmp_path, "page-002.jpg")],
    )

    repo.save_lesson_draft(
        merged.lesson,
        import_batches=[legacy_batch(first), merged.batch],
    )

    sources = lesson_root_of(tmp_path, first) / "sources"
    assert (sources / "page-001.jpg").read_bytes() == b"fixture image bytes"
    assert (sources / "page-002.jpg").read_bytes() == b"fixture image bytes"
    assert (lesson_root_of(tmp_path, first) / "vocabulary" / "hello.md").is_file()
    assert (lesson_root_of(tmp_path, first) / "vocabulary" / "goodbye.md").is_file()
    assert repo.get_lesson(first.lesson_id) == merged.lesson
    assert repo.list_lessons() == [merged.lesson]


def test_import_batches_round_trip_and_legacy_lessons_get_an_implied_batch(
    tmp_path: Path,
) -> None:
    first = load_draft()
    make_repository(tmp_path).save_lesson_draft(first)
    repo = LessonLensMarkdownRepository(
        tmp_path / "lessonlens",
        approved_sources=[approve_image(tmp_path, "page-002.jpg")],
    )

    assert repo.get_import_batches(first.lesson_id) == [legacy_batch(first)]

    merged = merge_lesson(first, make_incoming(first))
    batches = [legacy_batch(first), merged.batch]
    repo.save_lesson_draft(merged.lesson, import_batches=batches)

    restored = repo.get_import_batches(first.lesson_id)
    assert restored == batches
    assert restored[1].pages == ["14"]
    assert restored[1].content_ids == ["goodbye"]
    assert restored[1].imported_at is not None
    assert repo.get_import_batches("junior-high-grade-9-english-lesson-09") == []


def test_source_image_path_only_serves_images_of_that_lesson(tmp_path: Path) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)

    path = repo.source_image_path(draft.lesson_id, "page-001.jpg")

    assert path is not None
    assert path.read_bytes() == b"fixture image bytes"
    assert repo.source_image_path(draft.lesson_id, "page-999.jpg") is None
    assert repo.source_image_path("junior-high-grade-9-english-lesson-09", "page-001.jpg") is None
    # Unsafe identifiers simply do not name an image of any lesson.
    assert repo.source_image_path(draft.lesson_id, "../lesson.md") is None
    assert repo.source_image_path("../escape", "page-001.jpg") is None


def test_replacing_a_lesson_still_requires_approval_for_new_sources(
    tmp_path: Path,
) -> None:
    first = load_draft()
    make_repository(tmp_path).save_lesson_draft(first)
    repo = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    replacement = make_incoming(first)

    with pytest.raises(SourceImageNotApprovedError):
        repo.save_lesson_draft(replacement)


def test_missing_lesson_returns_none(tmp_path: Path) -> None:
    repo = LessonLensMarkdownRepository(tmp_path / "lessonlens")

    assert repo.get_lesson("junior-high-grade-1-english-lesson-01") is None


def test_malformed_markdown_is_not_silently_treated_as_missing(
    tmp_path: Path,
) -> None:
    repo = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson_root = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
    )
    lesson_root.mkdir(parents=True)
    (lesson_root / "lesson.md").write_text("---\n: invalid: yaml: [\n", encoding="utf-8")

    with pytest.raises(RepositoryError):
        repo.get_lesson("junior-high-grade-1-english-lesson-01")


def test_invalid_utf8_is_reported_as_a_lessonlens_parse_error(
    tmp_path: Path,
) -> None:
    repo = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    lesson_root = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
    )
    lesson_root.mkdir(parents=True)
    (lesson_root / "lesson.md").write_bytes(b"---\nkind: lesson\n---\n\xff")

    with pytest.raises(LessonLensParseError):
        repo.get_lesson("junior-high-grade-1-english-lesson-01")


def test_missing_content_document_is_reported_instead_of_being_swallowed(
    tmp_path: Path,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)
    content_path = (
        tmp_path
        / "lessonlens"
        / "curricula"
        / "junior-high"
        / "grade-1"
        / "english"
        / "lesson-01"
        / "vocabulary"
        / "hello.md"
    )
    content_path.unlink()

    with pytest.raises(RepositoryError, match="could not read LessonLens document"):
        repo.get_lesson(draft.lesson_id)


def test_vault_symlink_escape_is_rejected_for_save_and_delete(
    tmp_path: Path,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    curricula_link = repo.root / "curricula"
    try:
        curricula_link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(RepositoryError, match="symlink|outside"):
        repo.save_lesson_draft(draft)
    with pytest.raises(RepositoryError, match="symlink|outside"):
        repo.delete_lesson(draft.lesson_id)

    assert not (outside / "junior-high" / "grade-1" / "english" / "lesson-01").exists()


def test_source_images_must_be_approved_image_references(tmp_path: Path) -> None:
    draft = load_draft()
    repo = LessonLensMarkdownRepository(tmp_path / "lessonlens")

    with pytest.raises(SourceImageNotApprovedError):
        repo.save_lesson_draft(draft)


def test_invalid_content_id_is_rejected_before_writing(tmp_path: Path) -> None:
    draft = load_draft()
    draft = draft.model_copy(
        update={
            "content_items": [
                draft.content_items[0].model_copy(update={"content_id": "../escape"})
            ]
        }
    )
    repo = make_repository(tmp_path)

    with pytest.raises(RepositoryError):
        repo.save_lesson_draft(draft)

    assert not (tmp_path / "lessonlens" / "curricula").exists()


def test_publish_failure_rolls_back_replaced_files_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = load_draft()
    repo = make_repository(tmp_path)
    repo.save_lesson_draft(draft)
    changed = draft.model_copy(
        update={"title": "Updated lesson", "operation_id": "op-lesson-002"}
    )
    publish_count = 0
    original_publish = repo._publish_staged_file

    def fail_on_second_publish(staged: Path, formal: Path) -> None:
        nonlocal publish_count
        publish_count += 1
        if publish_count == 2:
            raise OSError("simulated publish failure")
        original_publish(staged, formal)

    monkeypatch.setattr(repo, "_publish_staged_file", fail_on_second_publish)

    with pytest.raises(RepositoryError, match="could not write"):
        repo.save_lesson_draft(changed)

    assert repo.get_lesson(draft.lesson_id) == draft
    assert not list(repo.root.glob(".talkpath-stage-*"))
