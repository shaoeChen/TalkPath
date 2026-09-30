from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from talkpath.adapters.fake_services import (
    FakeSpeechToTextService,
    FakeTextService,
    FakeTextToSpeechService,
    FakeVisionService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.api.app import create_app
from talkpath.application.session_service import SessionService
from talkpath.domain.models import Activity


class DuplicateItemIdTextService(FakeTextService):
    """Simulate real text providers that copy the activity ID into every item."""

    async def generate_activity(self, lesson, activity_type, *, operation_id):
        draft = await super().generate_activity(
            lesson, activity_type, operation_id=operation_id
        )
        items = [
            Activity(
                activity_id=draft.activity_id,
                lesson_id=lesson.lesson_id,
                type="multiple_choice",
                prompt=f"What does word {index} mean?",
                choices=[f"meaning-{index}", "other"],
                answer=f"meaning-{index}",
                source_content_ids=draft.items[0].source_content_ids,
            )
            for index in range(1, 4)
        ]
        return draft.model_copy(update={"items": items})


class FixedActivityIdTextService(FakeTextService):
    """Simulate real providers that derive the activity ID from the lesson."""

    async def generate_activity(self, lesson, activity_type, *, operation_id):
        draft = await super().generate_activity(
            lesson, activity_type, operation_id=operation_id
        )
        return draft.model_copy(update={"activity_id": f"fixed-{activity_type}"})


class NoopPi:
    async def prompt(self, message: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(response=SimpleNamespace(payload={}), events=())


def make_client(tmp_path: Path) -> tuple[TestClient, SessionService]:
    service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=FakeVisionService(),
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=NoopPi(),
        upload_root=tmp_path / "uploads",
    )
    return TestClient(create_app(services=service, testing=True)), service


def prepare_activity(client: TestClient) -> tuple[str, dict[str, object]]:
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json={
            "program": "junior high",
            "grade": "7",
            "subject": "English",
            "lesson": "1",
        },
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-activity-flow"},
    ).status_code == 200
    response = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={
            "operation_id": "generate-activity-flow",
            "activity_type": "vocabulary_quiz",
        },
    )
    assert response.status_code == 200
    return session_id, response.json()["activity"]


def test_vocabulary_practice_uses_word_cards_and_spoken_transcript_answer(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json={
            "program": "junior high",
            "grade": "7",
            "subject": "English",
            "lesson": "1",
        },
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-speaking-flow"},
    ).status_code == 200
    generated = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={
            "operation_id": "generate-speaking-flow",
            "activity_type": "vocabulary_practice",
        },
    )
    assert generated.status_code == 200
    activity = generated.json()["activity"]
    item = activity["items"][0]

    assert "answer" not in item
    assert item["choices"] == []
    assert item["prompt"] == "school"

    answered = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "public-speaking-answer-1",
            "item_id": item["activity_id"],
            "answer": "school",
        },
    )
    assert answered.status_code == 200
    payload = answered.json()
    assert payload["evaluation"]["passed"] is True
    assert payload["evaluation"]["feedback"] == "Great job!"


def test_new_session_regenerating_saved_activity_returns_200_with_fresh_id(
    tmp_path: Path,
) -> None:
    service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=FakeVisionService(),
        text_service=FixedActivityIdTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        pi_client=NoopPi(),
        upload_root=tmp_path / "uploads",
    )
    client = TestClient(create_app(services=service, testing=True))
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json={
            "program": "junior high",
            "grade": "7",
            "subject": "English",
            "lesson": "1",
        },
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-regenerate-flow"},
    ).status_code == 200

    first = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={
            "operation_id": "regenerate-api-1",
            "activity_type": "vocabulary_practice",
        },
    )
    assert first.status_code == 200

    second_session = client.post(
        "/api/sessions",
        json={"lesson_id": "junior-high-grade-7-english-lesson-01"},
    )
    assert second_session.status_code == 200
    second_session_id = second_session.json()["session_id"]
    second = client.post(
        f"/api/sessions/{second_session_id}/activities/generate",
        json={
            "operation_id": "regenerate-api-2",
            "activity_type": "vocabulary_practice",
        },
    )

    assert second.status_code == 200
    assert (
        second.json()["activity"]["activity_id"]
        != first.json()["activity"]["activity_id"]
    )


def test_same_session_can_generate_a_different_activity_type_after_ready(
    tmp_path: Path,
) -> None:
    client, _service = make_client(tmp_path)
    session_id, _ = prepare_activity(client)

    second = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={
            "operation_id": "generate-second-activity",
            "activity_type": "grammar_practice",
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["activity"]["type"] == "grammar_practice"
    assert body["session"]["state"] == "READY_FOR_PRACTICE"


def test_same_session_rejects_regenerating_the_same_activity_type(
    tmp_path: Path,
) -> None:
    client, _service = make_client(tmp_path)
    session_id, _ = prepare_activity(client)

    rejected = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={
            "operation_id": "generate-same-activity-again",
            "activity_type": "vocabulary_quiz",
        },
    )

    assert rejected.status_code == 409
    assert rejected.json()["code"] == "activity_operation_conflict"


def test_public_answer_uses_saved_activity_hides_answers_and_is_idempotent(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id, activity = prepare_activity(client)
    item = activity["items"][0]

    assert "answer" not in item
    assert "expected_answer" not in item

    answered = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "public-answer-1",
            "item_id": item["activity_id"],
            "answer": "not the word",
        },
    )

    assert answered.status_code == 200
    payload = answered.json()
    assert payload["evaluation"]["passed"] is False
    assert payload["evaluation"]["feedback"] == "Try again."
    assert "answer" not in payload
    assert "expected_answer" not in payload
    assert "answer" not in payload["evaluation"]
    assert "expected_answer" not in payload["evaluation"]

    retried = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "public-answer-1",
            "item_id": item["activity_id"],
            "answer": "not the word",
        },
    )
    assert retried.status_code == 200
    assert retried.json() == payload


def test_vocabulary_word_answer_endpoint_compares_and_hides_answer(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json={
            "program": "junior high",
            "grade": "7",
            "subject": "English",
            "lesson": "1",
        },
    ).status_code == 200
    imported = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-word-flow"},
    )
    assert imported.status_code == 200
    word_item = next(
        item
        for item in imported.json()["lesson"]["content_items"]
        if item["type"] == "vocabulary"
    )

    answered = client.post(
        f"/api/sessions/{session_id}/vocabulary/{word_item['content_id']}/answer",
        json={"operation_id": "word-answer-1", "answer": "school"},
    )
    assert answered.status_code == 200
    payload = answered.json()
    assert payload["passed"] is True
    assert payload["feedback"] == "Great job!"
    assert payload["attempt"]["activity_id"].endswith(
        f"-word-{word_item['content_id']}"
    )
    assert "answer" not in payload
    assert "expected_answer" not in payload

    missed = client.post(
        f"/api/sessions/{session_id}/vocabulary/{word_item['content_id']}/answer",
        json={"operation_id": "word-answer-2", "answer": "teacher"},
    )
    assert missed.status_code == 200
    assert missed.json()["passed"] is False
    assert missed.json()["feedback"] == "Try again."
    attempts = service.progress_repository.list_attempts(session_id)
    assert {attempt.correct for attempt in attempts} == {True, False}


def test_vocabulary_word_answer_accepts_punctuated_asr_transcript(
    tmp_path: Path,
) -> None:
    client, _ = make_client(tmp_path)
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json={
            "program": "junior high",
            "grade": "7",
            "subject": "English",
            "lesson": "1",
        },
    ).status_code == 200
    imported = client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-word-punct"},
    )
    assert imported.status_code == 200
    word_item = next(
        item
        for item in imported.json()["lesson"]["content_items"]
        if item["type"] == "vocabulary"
    )

    answered = client.post(
        f"/api/sessions/{session_id}/vocabulary/{word_item['content_id']}/answer",
        json={"operation_id": "word-answer-punct", "answer": "School."},
    )
    assert answered.status_code == 200
    assert answered.json()["passed"] is True
    assert answered.json()["feedback"] == "Great job!"


def test_public_activity_retrieval_rejects_unknown_activity_and_never_returns_answer(
    tmp_path: Path,
) -> None:
    client, _ = make_client(tmp_path)
    session_id, activity = prepare_activity(client)

    stored = LessonLensMarkdownRepository(tmp_path / "lessonlens").get_activity_draft(
        activity["activity_id"]
    )
    assert stored is not None
    assert stored.items[0].question_type == "dictation"
    assert stored.items[0].answer == "school"

    retrieved = client.get(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}"
    )
    assert retrieved.status_code == 200
    assert all("answer" not in item for item in retrieved.json()["activity"]["items"])
    assert "expected_answer" not in retrieved.text

    unknown = client.get(f"/api/sessions/{session_id}/activities/unknown-activity")
    assert unknown.status_code == 404

    forged_payload = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "forged-answer",
            "item_id": activity["items"][0]["activity_id"],
            "answer": "anything",
            "expected_answer": "anything",
        },
    )
    assert forged_payload.status_code == 422


def test_public_speech_endpoints_use_session_scoped_stt_and_tts(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    session_id = client.post("/api/sessions").json()["session_id"]

    transcript = client.post(
        f"/api/sessions/{session_id}/speech/transcribe",
        data={"operation_id": "public-stt-1"},
        files={"audio": ("recording.wav", b"audio bytes", "audio/wav")},
    )
    assert transcript.status_code == 200
    assert transcript.json()["transcript"]["text"] == "Hello, TalkPath!"

    synthesized = client.post(
        f"/api/sessions/{session_id}/speech/synthesize",
        json={"operation_id": "public-tts-1", "text": "Hello", "voice": "child"},
    )
    assert synthesized.status_code == 200
    body = synthesized.json()
    assert body["mime_type"] == "audio/mpeg"
    assert base64.b64decode(body["audio_base64"])
    assert body["audio_data_url"].startswith("data:audio/mpeg;base64,")


def test_public_answer_is_correct_for_second_question_when_item_ids_repeated(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    service.activity_service.text_service = DuplicateItemIdTextService()
    session_id, activity = prepare_activity(client)
    assert len(activity["items"]) == 3

    for index, item in enumerate(activity["items"], start=1):
        answered = client.post(
            f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
            json={
                "operation_id": f"public-answer-{index}",
                "item_id": item["activity_id"],
                "answer": f"meaning-{index}",
            },
        )
        assert answered.status_code == 200
        payload = answered.json()
        assert payload["evaluation"]["passed"] is True
        assert payload["item_id"] == item["activity_id"]
        assert payload["attempt"]["activity_id"] == item["activity_id"]


def test_vocabulary_quiz_public_items_include_question_type_and_hide_answer(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id, activity = prepare_activity(client)

    for item in activity["items"]:
        assert item["question_type"] in {
            "dictation",
            "meaning_to_word",
            "word_to_meaning",
        }
        assert "answer" not in item
        assert "expected_answer" not in item


def test_vocabulary_quiz_answer_returns_correction_and_records_attempt(
    tmp_path: Path,
) -> None:
    client, service = make_client(tmp_path)
    session_id, activity = prepare_activity(client)
    item = activity["items"][0]
    assert item["question_type"] == "dictation"

    answered = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "quiz-answer-correction",
            "item_id": item["activity_id"],
            "answer": "scool",
        },
    )

    assert answered.status_code == 200
    payload = answered.json()
    assert payload["evaluation"]["passed"] is False
    assert payload["correction"] == "school"
    assert "answer" not in payload
    assert "expected_answer" not in payload
    assert "expected_answer" not in payload["evaluation"]
    assert len(service.progress_repository.list_attempts(session_id)) == 1


def test_non_quiz_answer_has_no_correction(tmp_path: Path) -> None:
    client, service = make_client(tmp_path)
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.post(
        f"/api/sessions/{session_id}/images",
        files={"file": ("book.png", b"book page", "image/png")},
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/scope",
        json={
            "program": "junior high",
            "grade": "7",
            "subject": "English",
            "lesson": "1",
        },
    ).status_code == 200
    assert client.post(
        f"/api/sessions/{session_id}/import",
        json={"operation_id": "import-no-correction"},
    ).status_code == 200
    generated = client.post(
        f"/api/sessions/{session_id}/activities/generate",
        json={
            "operation_id": "generate-no-correction",
            "activity_type": "vocabulary_practice",
        },
    )
    assert generated.status_code == 200
    activity = generated.json()["activity"]
    item = activity["items"][0]

    answered = client.post(
        f"/api/sessions/{session_id}/activities/{activity['activity_id']}/answer",
        json={
            "operation_id": "practice-answer-no-correction",
            "item_id": item["activity_id"],
            "answer": "school",
        },
    )

    assert answered.status_code == 200
    assert answered.json()["correction"] is None
