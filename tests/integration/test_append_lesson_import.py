"""Importing more pages into a saved lesson appends to it instead of replacing it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService,
    FakeTextService,
    FakeTextToSpeechService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.application.session_service import SessionService
from talkpath.domain.models import (
    ContentItem,
    CourseScope,
    ImageReference,
    LessonDraft,
    SessionState,
)

LESSON_ID = "junior-high-grade-7-english-lesson-01"

# page -> (content_id, English word) pairs the fake vision "reads" from that page
PAGE_WORDS = {
    "3": [("word-1", "school"), ("word-2", "teacher")],
    "4": [("word-1", "friend"), ("word-2", "School"), ("word-3", "happy")],
    "5": [("word-1", "book")],
}


class PagedVision:
    """Return page-specific vocabulary, deliberately reusing content IDs."""

    async def extract_lesson(
        self,
        images: list[ImageReference],
        scope: CourseScope,
        *,
        operation_id: str,
    ) -> LessonDraft:
        page = scope.pages[0]
        return LessonDraft(
            lesson_id=scope.lesson_id,
            scope=scope,
            title=f"Title from page {page}",
            passage=f"Text of page {page}.",
            content_items=[
                ContentItem(
                    content_id=content_id,
                    type="vocabulary",
                    content={"english": word, "chinese": "翻譯"},
                    source_page=page,
                )
                for content_id, word in PAGE_WORDS[page]
            ],
            source_images=[image.image_id for image in images],
            extraction_status="draft",
            provider="fake-vision",
            model="paged-vision",
            operation_id=operation_id,
        )


class SavingPi:
    """Behave like the real Pi agent: extract and save through the internal tools.

    The service then saves the same draft a second time when the import
    finishes, so the merge has to tolerate a repeated save.
    """

    def __init__(self) -> None:
        self.service: SessionService | None = None

    async def start(self) -> None:
        return None

    async def prompt(self, message: str, **kwargs: object) -> SimpleNamespace:
        service = self.service
        assert service is not None
        payload = kwargs["write_payload"]
        assert isinstance(payload, dict)
        images = [ImageReference.model_validate(image) for image in payload["images"]]
        scope = CourseScope.model_validate(payload["scope"])
        draft = await service.extract_lesson(
            session_id=payload["session_id"],
            images=images,
            scope=scope,
            operation_id=payload["operation_id"],
        )
        service.save_lesson_draft(
            draft,
            session_id=payload["session_id"],
            operation_id=payload["operation_id"],
            scope=scope,
            source_references=images,
        )
        return SimpleNamespace(
            response=SimpleNamespace(payload={"draft": draft}), events=()
        )


def make_service(root: Path, *, agent_backend: str = "direct") -> SessionService:
    pi = SavingPi()
    service = SessionService(
        progress_repository=SQLiteProgressRepository(root / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(root / "lessonlens"),
        vision_service=PagedVision(),
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=pi,
        agent_backend=agent_backend,
        upload_root=root / "uploads",
    )
    pi.service = service
    return service


def scope_for(page: str) -> CourseScope:
    return CourseScope(
        program="junior high",
        grade="7",
        subject="English",
        lesson="1",
        pages=[page],
    )


async def import_page(
    service: SessionService,
    page: str,
    *,
    operation_id: str,
) -> tuple[str, LessonDraft]:
    session_id = service.create_session().session_id
    service.upload_image(session_id, f"image of page {page}".encode(), mime_type="image/png")
    service.confirm_scope(session_id, scope_for(page))
    result = await service.import_lesson(session_id, operation_id=operation_id)
    return session_id, result.lesson


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_backend", ["direct", "pi"])
async def test_second_import_appends_to_the_saved_lesson(
    tmp_path: Path,
    agent_backend: str,
) -> None:
    service = make_service(tmp_path, agent_backend=agent_backend)

    _, first = await import_page(service, "3", operation_id="import-page-3")
    _, second = await import_page(service, "4", operation_id="import-page-4")

    ids = [(item.content_id, item.content.get("english")) for item in second.content_items]
    assert ids == [
        ("word-1", "school"),
        ("word-2", "teacher"),
        ("word-1-2", "friend"),
        ("word-3", "happy"),
    ]
    assert second.content_items[:2] == first.content_items
    assert second.title == "Title from page 3"
    assert second.scope.pages == ["3", "4"]
    assert second.passage == "Text of page 3.\n\nText of page 4."
    assert len(second.source_images) == 2
    assert second.operation_id == "import-page-4"
    assert service.get_lesson(LESSON_ID) == second

    lesson_dir = tmp_path / "lessonlens" / "curricula" / "junior-high" / "grade-7" / "english" / "lesson-01"
    for image_id in second.source_images:
        assert (lesson_dir / "sources" / image_id).is_file()
    assert (lesson_dir / "vocabulary" / "word-1-2.md").is_file()

    batches = service.lesson_repository.get_import_batches(LESSON_ID)
    assert [batch.operation_id for batch in batches] == ["import-page-3", "import-page-4"]
    assert [batch.pages for batch in batches] == [["3"], ["4"]]
    assert batches[1].content_ids == ["word-1-2", "word-3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_backend", ["direct", "pi"])
async def test_activities_can_be_generated_after_appending(
    tmp_path: Path,
    agent_backend: str,
) -> None:
    service = make_service(tmp_path, agent_backend=agent_backend)
    await import_page(service, "3", operation_id="import-page-3")
    session_id, lesson = await import_page(service, "4", operation_id="import-page-4")

    # The same session that appended can practise straight away.
    generated = await service.generate_activity(
        session_id,
        activity_type="vocabulary_practice",
        operation_id="activity-after-append",
    )
    assert generated.session.state is SessionState.READY_FOR_PRACTICE
    assert generated.activity.lesson_id == LESSON_ID

    # The session keeps a scope that still matches the merged lesson.
    assert service.get_snapshot(session_id).scope == lesson.scope
    activity = await service.generate_activity_for_lesson(
        lesson=service.get_lesson(LESSON_ID),
        activity_type="vocabulary_quiz",
        operation_id="internal-activity-after-append",
        scope=service.get_snapshot(session_id).scope,
    )
    assert activity.lesson_id == LESSON_ID

    # So can a brand-new session that opens the saved lesson.
    reopened = service.create_session(lesson_id=LESSON_ID)
    reopened_result = await service.generate_activity(
        reopened.session_id,
        activity_type="vocabulary_practice",
        operation_id="activity-on-reopened-lesson",
    )
    assert reopened_result.activity.lesson_id == LESSON_ID


@pytest.mark.asyncio
async def test_saving_the_same_import_twice_does_not_append_twice(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    session_id, merged = await import_page(service, "3", operation_id="import-page-3")
    await import_page(service, "4", operation_id="import-page-4")
    session_id, _ = await import_page(service, "5", operation_id="import-page-5")
    draft = await service.vision_service.extract_lesson(
        service.get_session(session_id).source_images,
        scope_for("5"),
        operation_id="import-page-5",
    )

    service.save_lesson_draft(
        draft,
        session_id=session_id,
        operation_id="import-page-5",
        scope=scope_for("5"),
    )

    lesson = service.get_lesson(LESSON_ID)
    batches = service.lesson_repository.get_import_batches(LESSON_ID)
    assert [batch.operation_id for batch in batches] == [
        "import-page-3",
        "import-page-4",
        "import-page-5",
    ]
    assert len(lesson.source_images) == 3
    assert [item.content_id for item in lesson.content_items].count("word-1-3") == 1
    assert merged.scope.pages == ["3"]


@pytest.mark.asyncio
async def test_a_lesson_saved_before_batches_existed_can_still_be_appended(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scope = scope_for("3")
    legacy = LessonDraft(
        lesson_id=scope.lesson_id,
        scope=scope,
        title="Old lesson",
        passage="Old text.",
        content_items=[
            ContentItem(
                content_id="old-word",
                type="vocabulary",
                content={"english": "school", "chinese": "學校"},
                source_page="3",
            )
        ],
        source_images=[],
        extraction_status="draft",
        provider="fake-vision",
        model="paged-vision",
        operation_id="legacy-op",
    )
    service.lesson_repository.save_lesson_draft(legacy)

    _, merged = await import_page(service, "4", operation_id="import-page-4")

    assert [item.content_id for item in merged.content_items] == [
        "old-word",
        "word-1",
        "word-3",
    ]
    batches = service.lesson_repository.get_import_batches(LESSON_ID)
    assert [batch.operation_id for batch in batches] == ["legacy-op", "import-page-4"]


@pytest.mark.asyncio
async def test_check_import_reports_existing_pages_and_overlap(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    fresh = service.check_import(scope_for("3"))
    assert fresh.lesson_id == LESSON_ID
    assert fresh.exists is False
    assert fresh.existing_pages == []
    assert fresh.overlapping_pages == []

    await import_page(service, "3", operation_id="import-page-3")

    other_page = service.check_import(scope_for("4"))
    assert other_page.exists is True
    assert other_page.title == "Title from page 3"
    assert other_page.existing_pages == ["3"]
    assert other_page.overlapping_pages == []
    assert other_page.content_item_count == 2

    repeated = service.check_import(scope_for("3"))
    assert repeated.overlapping_pages == ["3"]

    ranged = service.check_import(
        CourseScope(
            program="junior high",
            grade="7",
            subject="English",
            lesson="1",
            pages=["2-3"],
        )
    )
    assert ranged.overlapping_pages == ["3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_backend", ["direct", "pi"])
async def test_import_result_reports_how_many_duplicates_were_skipped(
    tmp_path: Path,
    agent_backend: str,
) -> None:
    service = make_service(tmp_path, agent_backend=agent_backend)
    first_session, _ = await import_page(service, "3", operation_id="import-page-3")
    assert service.get_snapshot(first_session).session.state is SessionState.ASK_GENERATE_ACTIVITY

    session_id = service.create_session().session_id
    service.upload_image(session_id, b"image of page 4", mime_type="image/png")
    service.confirm_scope(session_id, scope_for("4"))
    result = await service.import_lesson(session_id, operation_id="import-page-4")

    # "School" on page 4 repeats "school" from page 3.
    assert result.skipped_duplicates == 1
    assert len(result.lesson.content_items) == 4
