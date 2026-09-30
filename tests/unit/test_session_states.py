import pytest

from talkpath.domain.errors import InvalidStateTransition, ScopeNotConfirmed
from talkpath.domain.models import SessionState, SessionStateMachine


def test_happy_path_follows_the_import_and_activity_flow() -> None:
    machine = SessionStateMachine()
    machine.transition_to(SessionState.CONFIRM_COURSE_SCOPE)
    machine.confirm_scope()

    for state in (
        SessionState.EXTRACTING,
        SessionState.PREVIEW_DRAFT,
        SessionState.SAVE_LESSON,
        SessionState.ASK_GENERATE_ACTIVITY,
        SessionState.GENERATING_ACTIVITY,
        SessionState.READY_FOR_PRACTICE,
    ):
        machine.transition_to(state)

    assert machine.state is SessionState.READY_FOR_PRACTICE


def test_confirm_scope_is_only_allowed_in_scope_confirmation_state() -> None:
    machine = SessionStateMachine()

    with pytest.raises(InvalidStateTransition):
        machine.confirm_scope()


def test_scope_must_be_confirmed_before_extracting() -> None:
    machine = SessionStateMachine(state=SessionState.CONFIRM_COURSE_SCOPE)

    with pytest.raises(ScopeNotConfirmed):
        machine.transition_to(SessionState.EXTRACTING)


def test_any_state_can_fail_and_failed_can_retry() -> None:
    machine = SessionStateMachine(state=SessionState.EXTRACTING)

    machine.transition_to(SessionState.FAILED)
    machine.transition_to(SessionState.RETRY)

    assert machine.state is SessionState.RETRY


def test_invalid_transition_is_rejected() -> None:
    machine = SessionStateMachine()

    with pytest.raises(InvalidStateTransition):
        machine.transition_to(SessionState.READY_FOR_PRACTICE)


def test_ready_for_practice_can_generate_another_activity() -> None:
    machine = SessionStateMachine(
        state=SessionState.READY_FOR_PRACTICE,
        scope_confirmed=True,
    )

    machine.transition_to(SessionState.GENERATING_ACTIVITY)

    assert machine.state is SessionState.GENERATING_ACTIVITY


def test_retry_starts_a_new_upload_attempt() -> None:
    machine = SessionStateMachine(state=SessionState.FAILED)

    machine.transition_to(SessionState.RETRY)
    machine.transition_to(SessionState.UPLOAD_IMAGE)

    assert machine.state is SessionState.UPLOAD_IMAGE


def test_saved_lesson_can_enter_activity_generation_without_uploading() -> None:
    machine = SessionStateMachine(scope_confirmed=True)

    machine.transition_to(SessionState.ASK_GENERATE_ACTIVITY)

    assert machine.state is SessionState.ASK_GENERATE_ACTIVITY
    assert machine.scope_confirmed is True


def test_upload_flow_still_starts_through_scope_confirmation() -> None:
    machine = SessionStateMachine()

    machine.transition_to(SessionState.CONFIRM_COURSE_SCOPE)

    assert machine.state is SessionState.CONFIRM_COURSE_SCOPE


def test_saved_lesson_entry_requires_confirmed_scope() -> None:
    machine = SessionStateMachine()

    with pytest.raises(ScopeNotConfirmed):
        machine.transition_to(SessionState.ASK_GENERATE_ACTIVITY)
