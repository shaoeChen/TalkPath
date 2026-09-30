from inspect import signature

from talkpath.ports.model_services import ModelService
from talkpath.ports.progress_repository import ProgressRepository


def test_model_service_exposes_one_formal_name_for_each_streaming_operation() -> None:
    assert hasattr(ModelService, "stream_transcribe")
    assert hasattr(ModelService, "stream_synthesize")
    assert not hasattr(ModelService, "transcribe_stream")
    assert not hasattr(ModelService, "synthesize_stream")


def test_record_attempt_can_resolve_lesson_from_a_bound_session() -> None:
    lesson_id = signature(ProgressRepository.record_attempt).parameters["lesson_id"]

    assert lesson_id.default is None
    assert "session" in (ProgressRepository.record_attempt.__doc__ or "").lower()
