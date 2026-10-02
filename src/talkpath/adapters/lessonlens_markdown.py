"""Obsidian-compatible Markdown persistence for the LessonLens vault."""

from __future__ import annotations

import os
import json
import re
import shutil
import tempfile
import threading
from functools import wraps
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml
from pydantic import ValidationError

from talkpath.domain.errors import RepositoryError
from talkpath.domain.lesson_merge import ImportBatch, legacy_batch
from talkpath.domain.models import (
    ActivityDraft,
    ContentItem,
    CourseScope,
    ImageReference,
    LessonDraft,
)


class InvalidLessonIdError(RepositoryError):
    """Raised when a lesson ID cannot be safely mapped into the vault."""


class InvalidDocumentComponentError(RepositoryError):
    """Raised when a content or source ID is unsafe as a file component."""


class SourceImageNotApprovedError(RepositoryError):
    """Raised when a draft references a source without approved metadata."""


class LessonLensParseError(RepositoryError):
    """Raised when an existing LessonLens document is malformed."""


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LESSON_ID = re.compile(
    r"^(?P<program>[a-z0-9]+(?:-[a-z0-9]+)*)-"
    r"(?P<grade>grade-[0-9]+)-"
    r"(?P<subject>[a-z0-9]+(?:-[a-z0-9]+)*)-"
    r"(?P<lesson>lesson-[0-9]+(?:--[a-z0-9]+(?:-[a-z0-9]+)*)?)$"
)


def _validate_component(value: str, label: str) -> str:
    """Allow only one conservative, platform-independent filename component."""

    if not isinstance(value, str) or not value:
        raise InvalidDocumentComponentError(f"{label} must be a non-empty string")
    if value in {".", ".."}:
        raise InvalidDocumentComponentError(f"{label} cannot be a traversal component")
    if (
        PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or "/" in value
        or "\\" in value
        or not _SAFE_COMPONENT.fullmatch(value)
    ):
        raise InvalidDocumentComponentError(
            f"unsafe {label}: {value!r}; expected one filename component"
        )
    return value


def _lesson_relative_path(lesson_id: str) -> Path:
    """Map the stable domain ID to the fixed LessonLens curriculum layout."""

    if (
        not isinstance(lesson_id, str)
        or "/" in lesson_id
        or "\\" in lesson_id
        or PurePosixPath(lesson_id).is_absolute()
        or PureWindowsPath(lesson_id).is_absolute()
    ):
        raise InvalidLessonIdError(f"unsafe lesson_id: {lesson_id!r}")

    match = _LESSON_ID.fullmatch(lesson_id)
    if match is None:
        raise InvalidLessonIdError(
            "lesson_id must match '<program>-grade-N-<subject>-lesson-NN'"
        )
    parts = match.groupdict()
    for label, value in parts.items():
        _validate_component(value, label)
    return Path("curricula", parts["program"], parts["grade"], parts["subject"], parts["lesson"])


def _frontmatter_document(metadata: Mapping[str, Any], body: str) -> bytes:
    frontmatter = yaml.safe_dump(
        dict(metadata),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{frontmatter}---\n{body}".encode("utf-8")


def _read_markdown_document(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise LessonLensParseError(f"invalid UTF-8 Markdown document: {path}") from exc
    except OSError as exc:
        raise RepositoryError(f"could not read LessonLens document: {path}") from exc

    match = re.match(
        r"\A---\r?\n(?P<frontmatter>.*?)(?:\r?\n)---(?:\r?\n|\Z)(?P<body>.*)\Z",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise LessonLensParseError(f"missing YAML frontmatter: {path}")

    try:
        metadata = yaml.safe_load(match.group("frontmatter"))
    except yaml.YAMLError as exc:
        raise LessonLensParseError(f"invalid YAML frontmatter: {path}") from exc
    if not isinstance(metadata, dict):
        raise LessonLensParseError(f"frontmatter must be a mapping: {path}")
    return metadata, match.group("body")


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._publication_lock:
            return method(self, *args, **kwargs)
    return call


class LessonLensMarkdownRepository:
    """Persist lessons as safe, human-readable files in an Obsidian vault.

    ``LessonDraft.source_images`` contains source IDs.  The repository accepts
    only IDs registered with an :class:`ImageReference`, then copies the
    approved local bytes into the lesson's ``sources`` directory.
    """

    def __init__(
        self,
        root: str | Path,
        approved_sources: Mapping[str, ImageReference] | Iterable[ImageReference] | None = None,
        *,
        approved_image_references: Mapping[str, ImageReference]
        | Iterable[ImageReference]
        | None = None,
    ) -> None:
        self._publication_lock = threading.RLock()
        self.root = Path(root).expanduser().resolve()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RepositoryError(f"could not create LessonLens root: {self.root}") from exc

        self._approved_sources: dict[str, ImageReference] = {}
        if approved_sources is not None:
            self._register_sources(approved_sources)
        if approved_image_references is not None:
            self._register_sources(approved_image_references)

    def locked(self):
        """Protect a complete read/merge/publication across nested calls."""
        return self._publication_lock

    @_serialized
    def approve_source_image(self, reference: ImageReference) -> None:
        """Register source metadata produced by the upload boundary."""

        if not isinstance(reference, ImageReference):
            raise SourceImageNotApprovedError("source must be an ImageReference")
        _validate_component(reference.image_id, "image_id")
        self._approved_sources[reference.image_id] = reference

    register_source_image = approve_source_image

    def _register_sources(
        self,
        references: Mapping[str, ImageReference] | Iterable[ImageReference],
    ) -> None:
        values = references.values() if isinstance(references, Mapping) else references
        for reference in values:
            self.approve_source_image(reference)

    def _lesson_dir(self, lesson_id: str) -> Path:
        return self._safe_vault_path(self.root / _lesson_relative_path(lesson_id))

    def _safe_vault_path(self, path: Path) -> Path:
        """Reject symlinks and resolved paths that could escape the vault root."""

        candidate = Path(path)
        try:
            relative_parts = candidate.relative_to(self.root).parts
        except ValueError as exc:
            raise RepositoryError(f"path is outside the LessonLens root: {candidate}") from exc

        current = self.root
        for component in relative_parts:
            current = current / component
            if current.is_symlink():
                raise RepositoryError(f"symlink is not allowed in LessonLens path: {current}")
            try:
                resolved = current.resolve(strict=False)
                resolved.relative_to(self.root)
            except (OSError, ValueError) as exc:
                raise RepositoryError(
                    f"LessonLens path resolves outside the vault: {current}"
                ) from exc
        return candidate

    @staticmethod
    def _content_path(lesson_dir: Path, item: ContentItem) -> Path:
        content_type = _validate_component(item.type, "content type")
        content_id = _validate_component(item.content_id, "content_id")
        return lesson_dir / content_type / f"{content_id}.md"

    @staticmethod
    def _source_path(lesson_dir: Path, image_id: str) -> Path:
        return lesson_dir / "sources" / _validate_component(image_id, "image_id")

    def _read_existing(self, lesson_id: str) -> LessonDraft | None:
        lesson_dir = self._lesson_dir(lesson_id)
        lesson_path = self._safe_vault_path(lesson_dir / "lesson.md")
        if not lesson_path.exists():
            return None
        if not lesson_path.is_file():
            raise RepositoryError(f"lesson path is not a file: {lesson_path}")
        return self._parse_lesson(lesson_dir, lesson_path)

    @_serialized
    def save_lesson_draft(
        self,
        draft: LessonDraft,
        source_references: Iterable[ImageReference] | None = None,
        import_batches: Sequence[ImportBatch] | None = None,
    ) -> None:
        """Save a draft through an in-vault staging bundle.

        The lesson document is published last as the completion marker.  Every
        formal file is replaced from the same staging directory, and a failed
        publish attempts to restore files already replaced in this operation.
        """

        if source_references is not None:
            self._register_sources(source_references)

        lesson_dir = self._lesson_dir(draft.lesson_id)
        if draft.scope.lesson_id != draft.lesson_id:
            raise RepositoryError("draft lesson_id does not match its scope")

        # Validate all output identities before creating a staging or curriculum directory.
        content_paths: list[Path] = []
        seen_content: set[tuple[str, str]] = set()
        for item in draft.content_items:
            identity = (item.type, item.content_id)
            if identity in seen_content:
                raise RepositoryError(
                    f"duplicate content identity: ({item.type}, {item.content_id})"
                )
            seen_content.add(identity)
            content_paths.append(
                self._safe_vault_path(self._content_path(lesson_dir, item))
            )

        source_ids = list(draft.source_images)
        if len(source_ids) != len(set(source_ids)):
            raise RepositoryError("duplicate source image ID in lesson draft")
        for image_id in source_ids:
            _validate_component(image_id, "image_id")
            self._safe_vault_path(self._source_path(lesson_dir, image_id))

        new_source_paths = [
            self._safe_vault_path(self._source_path(lesson_dir, image_id))
            for image_id in source_ids
        ]
        lesson_path = self._safe_vault_path(lesson_dir / "lesson.md")
        existing = self._read_existing(draft.lesson_id)
        if existing is not None:
            if existing.operation_id == draft.operation_id:
                if existing != draft:
                    raise RepositoryError(
                        "operation_id was already used for different lesson content"
                    )
                return

        desired_managed_paths = set(content_paths) | set(new_source_paths)
        obsolete_paths = self._find_obsolete_managed_files(
            lesson_dir,
            existing,
            desired_managed_paths,
        )

        # An image already stored with the lesson keeps its saved copy: its
        # upload approval is long gone when a later import appends to the lesson.
        stored_source_ids = set(existing.source_images) if existing is not None else set()
        source_payloads: list[tuple[Path, bytes]] = []
        for image_id, source_path in zip(source_ids, new_source_paths, strict=True):
            if image_id in stored_source_ids and source_path.is_file():
                continue
            reference = self._approved_sources.get(image_id)
            if reference is None:
                raise SourceImageNotApprovedError(
                    f"source image is not approved: {image_id}"
                )
            source_payloads.append(
                (
                    source_path,
                    self._approved_bytes(reference),
                )
            )

        lesson_bytes = self._render_lesson(draft, import_batches)
        payloads: list[tuple[Path, bytes]] = [
            (
                path,
                self._render_content(item),
            )
            for item, path in zip(draft.content_items, content_paths, strict=True)
        ]
        payloads.extend(source_payloads)
        payloads.append((lesson_path, lesson_bytes))

        self._write_bundle(lesson_dir, payloads, obsolete_paths, draft.lesson_id)

    def _find_obsolete_managed_files(
        self,
        lesson_dir: Path,
        existing: LessonDraft | None,
        desired_paths: set[Path],
    ) -> list[Path]:
        if existing is None:
            return []

        old_paths: list[Path] = []
        for item in existing.content_items:
            old_paths.append(self._content_path(lesson_dir, item))
        old_paths.extend(
            self._source_path(lesson_dir, image_id)
            for image_id in existing.source_images
        )

        obsolete: list[Path] = []
        seen: set[Path] = set()
        for path in old_paths:
            safe_path = self._safe_vault_path(path)
            if safe_path in desired_paths or safe_path in seen:
                continue
            seen.add(safe_path)
            if safe_path.is_symlink():
                raise RepositoryError(f"symlink is not allowed in LessonLens path: {safe_path}")
            if safe_path.exists() and not safe_path.is_file():
                raise RepositoryError(f"managed LessonLens path is not a file: {safe_path}")
            if safe_path.is_file():
                obsolete.append(safe_path)
        return obsolete

    def _write_bundle(
        self,
        lesson_dir: Path,
        payloads: list[tuple[Path, bytes]],
        obsolete_paths: list[Path],
        lesson_id: str,
    ) -> None:
        formal_payloads = [
            (self._safe_vault_path(path), payload) for path, payload in payloads
        ]
        touched_paths = list(dict.fromkeys(
            [path for path, _payload in formal_payloads]
            + [self._safe_vault_path(path) for path in obsolete_paths]
        ))
        previous = {path: self._read_previous_file(path) for path in touched_paths}
        staging_dir: Path | None = None
        staged_payloads: list[tuple[Path, Path]] = []
        try:
            try:
                staging_dir = Path(
                    tempfile.mkdtemp(prefix=".talkpath-stage-", dir=self.root)
                )
                self._safe_vault_path(staging_dir)
            except OSError as exc:
                raise RepositoryError(
                    "could not create LessonLens staging directory"
                ) from exc
            for formal_path, payload in formal_payloads:
                relative_path = formal_path.relative_to(lesson_dir)
                staged_path = self._safe_vault_path(staging_dir / relative_path)
                self._atomic_write(staged_path, payload)
                staged_payloads.append((staged_path, formal_path))
            self._publish_bundle(lesson_dir, staged_payloads, obsolete_paths, previous)
        except OSError as exc:
            raise RepositoryError(f"could not write LessonLens lesson: {lesson_id}") from exc
        finally:
            if staging_dir is not None:
                try:
                    shutil.rmtree(staging_dir)
                except OSError:
                    pass

    @staticmethod
    def _read_previous_file(path: Path) -> bytes | None:
        if path.is_symlink():
            raise RepositoryError(f"symlink is not allowed in LessonLens path: {path}")
        if not path.exists():
            return None
        if not path.is_file():
            raise RepositoryError(f"LessonLens output path is not a file: {path}")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise RepositoryError(f"could not read existing LessonLens file: {path}") from exc

    def _publish_bundle(
        self,
        lesson_dir: Path,
        staged_payloads: list[tuple[Path, Path]],
        obsolete_paths: list[Path],
        previous: dict[Path, bytes | None],
    ) -> None:
        changed_paths: list[Path] = []
        try:
            if not staged_payloads:
                raise RepositoryError("LessonLens bundle has no lesson marker")
            marker_staged, marker_formal = staged_payloads[-1]
            if marker_formal.name != "lesson.md":
                raise RepositoryError("LessonLens bundle must publish lesson.md last")

            for staged_path, formal_path in staged_payloads[:-1]:
                self._safe_vault_path(formal_path.parent)
                formal_path.parent.mkdir(parents=True, exist_ok=True)
                self._safe_vault_path(formal_path)
                self._publish_staged_file(staged_path, formal_path)
                changed_paths.append(formal_path)

            for obsolete_path in obsolete_paths:
                safe_obsolete_path = self._safe_vault_path(obsolete_path)
                if safe_obsolete_path.exists():
                    self._delete_obsolete_file(safe_obsolete_path)
                    changed_paths.append(safe_obsolete_path)

            self._safe_vault_path(marker_formal.parent)
            marker_formal.parent.mkdir(parents=True, exist_ok=True)
            self._safe_vault_path(marker_formal)
            self._publish_staged_file(marker_staged, marker_formal)
            changed_paths.append(marker_formal)
        except (OSError, RepositoryError):
            self._rollback_published_files(changed_paths, previous)
            self._cleanup_empty_directories(lesson_dir)
            raise

    @staticmethod
    def _publish_staged_file(staged_path: Path, formal_path: Path) -> None:
        os.replace(staged_path, formal_path)

    @staticmethod
    def _delete_obsolete_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise RepositoryError(f"managed LessonLens path is not a safe file: {path}")
        path.unlink()

    def _rollback_published_files(
        self,
        published: list[Path],
        previous: dict[Path, bytes | None],
    ) -> None:
        for formal_path in reversed(published):
            old_payload = previous[formal_path]
            try:
                self._safe_vault_path(formal_path)
                if old_payload is None:
                    if formal_path.exists() and not formal_path.is_symlink():
                        formal_path.unlink()
                else:
                    self._atomic_write(formal_path, old_payload)
            except (OSError, RepositoryError):
                # Rollback is deliberately best effort; the original write error remains primary.
                pass

    def _cleanup_empty_directories(self, start: Path) -> None:
        current = start
        while current != self.root and current.exists():
            if current.is_symlink() or not current.is_dir():
                return
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    @staticmethod
    def _approved_bytes(reference: ImageReference) -> bytes:
        expires_at = reference.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise SourceImageNotApprovedError(
                f"approved source image has expired: {reference.image_id}"
            )
        source_path = Path(reference.path).expanduser()
        try:
            source_path = source_path.resolve(strict=True)
            if not source_path.is_file():
                raise OSError("source path is not a regular file")
            payload = source_path.read_bytes()
        except OSError as exc:
            raise RepositoryError(
                f"could not read approved source image: {reference.image_id}"
            ) from exc
        if len(payload) != reference.size_bytes:
            raise RepositoryError(
                f"approved source size changed: {reference.image_id}"
            )
        return payload

    @staticmethod
    def _render_lesson(
        draft: LessonDraft,
        import_batches: Sequence[ImportBatch] | None = None,
    ) -> bytes:
        metadata: dict[str, Any] = {
            "kind": "lesson",
            "lesson_id": draft.lesson_id,
            "operation_id": draft.operation_id,
            "scope": draft.scope.model_dump(mode="json"),
            "title": draft.title,
            "extraction_status": draft.extraction_status,
            "provider": draft.provider,
            "model": draft.model,
            "source_images": list(draft.source_images),
            "content_items": [
                {"content_id": item.content_id, "type": item.type}
                for item in draft.content_items
            ],
        }
        if import_batches is not None:
            metadata["import_batches"] = [
                batch.model_dump(mode="json") for batch in import_batches
            ]
        body = f"# {draft.title}\n\n## Passage\n\n{draft.passage.rstrip()}\n"
        return _frontmatter_document(metadata, body)

    @staticmethod
    def _render_content(item: ContentItem) -> bytes:
        metadata = {
            "kind": "content_item",
            "content_id": item.content_id,
            "type": item.type,
            "source_page": item.source_page,
            "confidence": item.confidence,
            "status": item.status,
            "content": item.content,
        }
        body = f"# {item.content_id}\n\n## Content\n\n"
        if isinstance(item.content, str):
            body += f"{item.content.rstrip()}\n"
        else:
            body += f"```json\n{json.dumps(item.content, ensure_ascii=False, indent=2)}\n```\n"
        return _frontmatter_document(metadata, body)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        except OSError:
            raise
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @_serialized
    def get_lesson(self, lesson_id: str) -> LessonDraft | None:
        """Read one lesson, raising on malformed existing documents."""

        return self._read_existing(lesson_id)

    @_serialized
    def get_import_batches(self, lesson_id: str) -> list[ImportBatch]:
        """Return the imports that built a lesson, oldest first.

        A lesson saved before batches existed reads as one implied batch.
        """

        lesson = self._read_existing(lesson_id)
        if lesson is None:
            return []
        lesson_dir = self._lesson_dir(lesson_id)
        metadata, _body = _read_markdown_document(
            self._safe_vault_path(lesson_dir / "lesson.md")
        )
        stored = metadata.get("import_batches")
        if stored is None:
            return [legacy_batch(lesson)]
        try:
            return [ImportBatch.model_validate(batch) for batch in stored]
        except (TypeError, ValueError) as exc:
            raise LessonLensParseError(
                f"invalid import batch metadata: {lesson_dir}"
            ) from exc

    @_serialized
    def source_image_path(self, lesson_id: str, image_id: str) -> Path | None:
        """Return a stored source image of this lesson, or ``None`` if it has none."""

        try:
            image_id = _validate_component(image_id, "image_id")
            lesson = self._read_existing(lesson_id)
        except (InvalidLessonIdError, InvalidDocumentComponentError):
            return None
        if lesson is None or image_id not in lesson.source_images:
            return None
        path = self._safe_vault_path(self._source_path(self._lesson_dir(lesson_id), image_id))
        return path if path.is_file() else None

    def _parse_lesson(self, lesson_dir: Path, lesson_path: Path) -> LessonDraft:
        lesson_dir = self._safe_vault_path(lesson_dir)
        lesson_path = self._safe_vault_path(lesson_path)
        metadata, _body = _read_markdown_document(lesson_path)
        if metadata.get("kind") != "lesson":
            raise LessonLensParseError(f"unexpected document kind: {lesson_path}")
        try:
            stored_lesson_id = metadata["lesson_id"]
            if not stored_lesson_id:
                raise ValueError("missing lesson ID")
            if stored_lesson_id != _lesson_id_from_dir(lesson_dir):
                raise ValueError("lesson ID does not match its path")
            scope = CourseScope.model_validate(metadata["scope"])
            descriptors = metadata["content_items"]
            content_items = [
                self._parse_content_item(lesson_dir, descriptor)
                for descriptor in descriptors
            ]
            source_images = [
                _validate_component(image_id, "image_id")
                for image_id in metadata["source_images"]
            ]
            for image_id in source_images:
                source_path = self._safe_vault_path(
                    self._source_path(lesson_dir, image_id)
                )
                if not source_path.is_file():
                    raise RepositoryError(f"source image is missing: {source_path}")
            draft = LessonDraft(
                lesson_id=stored_lesson_id,
                scope=scope,
                title=metadata["title"],
                passage=_extract_passage(_body),
                content_items=content_items,
                source_images=source_images,
                extraction_status=metadata["extraction_status"],
                provider=metadata["provider"],
                model=metadata["model"],
                operation_id=metadata["operation_id"],
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise LessonLensParseError(f"invalid lesson metadata: {lesson_path}") from exc
        return draft

    def _parse_content_item(self, lesson_dir: Path, descriptor: Any) -> ContentItem:
        if not isinstance(descriptor, dict):
            raise LessonLensParseError(f"invalid content descriptor in {lesson_dir}")
        try:
            content_id = _validate_component(descriptor["content_id"], "content_id")
            content_type = _validate_component(descriptor["type"], "content type")
            path = self._safe_vault_path(
                lesson_dir / content_type / f"{content_id}.md"
            )
            metadata, _body = _read_markdown_document(path)
            if (
                metadata.get("kind") != "content_item"
                or metadata.get("content_id") != content_id
                or metadata.get("type") != content_type
            ):
                raise LessonLensParseError(f"content metadata does not match path: {path}")
            return ContentItem(
                content_id=content_id,
                type=content_type,
                content=metadata["content"],
                source_page=metadata.get("source_page"),
                confidence=metadata.get("confidence", 1.0),
                status=metadata.get("status", "draft"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LessonLensParseError(f"invalid content metadata: {lesson_dir}") from exc

    @_serialized
    def list_lessons(self, scope: CourseScope | None = None) -> list[LessonDraft]:
        curriculum_root = self.root / "curricula"
        if not curriculum_root.exists():
            return []
        lessons = [self._parse_lesson(path.parent, path) for path in curriculum_root.rglob("lesson.md")]
        if scope is not None:
            lessons = [lesson for lesson in lessons if lesson.scope == scope]
        return sorted(lessons, key=lambda lesson: lesson.lesson_id)

    @_serialized
    def delete_lesson(self, lesson_id: str) -> None:
        lesson_dir = self._lesson_dir(lesson_id)
        if not lesson_dir.exists():
            return
        try:
            shutil.rmtree(lesson_dir)
        except OSError as exc:
            raise RepositoryError(f"could not delete LessonLens lesson: {lesson_id}") from exc

    @_serialized
    def save_activity_draft(self, draft: ActivityDraft) -> None:
        """Persist one generated activity under its lesson's activities folder.

        Answers remain in this internal Markdown document so the evaluator can
        recover after a process restart.  Public routes always project an
        answer-free view before returning the activity to the child.
        """

        lesson = self.get_lesson(draft.lesson_id)
        if lesson is None:
            raise RepositoryError(f"lesson not found: {draft.lesson_id}")
        if draft.lesson_id != lesson.scope.lesson_id:
            raise RepositoryError("activity lesson_id does not match the saved lesson")

        activity_id = _validate_component(draft.activity_id, "activity_id")
        activity_type = _validate_component(draft.type, "activity type")
        source_content_ids = [
            _validate_component(content_id, "source_content_id")
            for content_id in draft.source_content_ids
        ]
        lesson_content_ids = {item.content_id for item in lesson.content_items}
        unknown_sources = set(source_content_ids) - lesson_content_ids
        if unknown_sources:
            raise RepositoryError(
                "activity source_content_ids are not present in the saved lesson"
            )
        for item in draft.items:
            if item.lesson_id != lesson.lesson_id:
                raise RepositoryError("activity item lesson_id does not match the saved lesson")
            for content_id in item.source_content_ids:
                _validate_component(content_id, "source_content_id")
                if content_id not in lesson_content_ids:
                    raise RepositoryError(
                        "activity item source_content_ids are not present in the saved lesson"
                    )

        activity_path = self._safe_vault_path(
            self._lesson_dir(draft.lesson_id) / "activities" / f"{activity_id}.md"
        )
        existing = self._read_activity_path(activity_path)
        if existing is not None:
            if existing == draft:
                return
            raise RepositoryError(
                "activity ID or operation_id was already used for different activity content"
            )

        metadata = {
            "kind": "activity",
            **draft.model_dump(mode="json"),
            "type": activity_type,
            "source_content_ids": source_content_ids,
        }
        body = (
            f"# {draft.title}\n\n"
            f"## Instructions\n\n{draft.instructions.rstrip()}\n"
        )
        try:
            self._atomic_write(activity_path, _frontmatter_document(metadata, body))
        except OSError as exc:
            raise RepositoryError(f"could not write LessonLens activity: {activity_id}") from exc

    @_serialized
    def get_activity_draft(self, activity_id: str) -> ActivityDraft | None:
        """Find and validate one generated activity by stable ID."""

        activity_id = _validate_component(activity_id, "activity_id")
        curriculum_root = self._safe_vault_path(self.root / "curricula")
        if not curriculum_root.exists():
            return None
        matches = [
            path
            for path in curriculum_root.rglob(f"{activity_id}.md")
            if path.parent.name == "activities"
        ]
        if not matches:
            return None
        if len(matches) > 1:
            raise RepositoryError(f"duplicate LessonLens activity ID: {activity_id}")
        path = self._safe_vault_path(matches[0])
        activity = self._read_activity_path(path)
        if activity is None:
            return None
        if activity.activity_id != activity_id:
            raise LessonLensParseError(f"activity ID does not match path: {path}")
        return activity

    def _read_activity_path(self, path: Path) -> ActivityDraft | None:
        path = self._safe_vault_path(path)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise RepositoryError(f"LessonLens activity path is not a file: {path}")
        metadata, _body = _read_markdown_document(path)
        if metadata.get("kind") != "activity":
            raise LessonLensParseError(f"unexpected activity document kind: {path}")
        try:
            activity_metadata = dict(metadata)
            activity_metadata.pop("kind", None)
            activity = ActivityDraft.model_validate(activity_metadata)
        except (TypeError, ValueError, ValidationError) as exc:
            raise LessonLensParseError(f"invalid activity metadata: {path}") from exc
        return activity


def _lesson_id_from_dir(lesson_dir: Path) -> str:
    parts = lesson_dir.parts
    if len(parts) < 4:
        raise ValueError("lesson directory is incomplete")
    return "-".join((parts[-4], parts[-3], parts[-2], parts[-1]))


def _extract_passage(body: str) -> str:
    match = re.search(r"(?ms)^## Passage\s*\n\n?(?P<passage>.*?)(?:\n\Z|\Z)", body)
    if match is None:
        raise LessonLensParseError("lesson document is missing the Passage heading")
    return match.group("passage").rstrip()


# Friendly alias for callers that use a shorter adapter name.
LessonLensRepository = LessonLensMarkdownRepository
