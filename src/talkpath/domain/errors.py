"""Domain-level exceptions shared by application services and adapters."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for expected TalkPath domain failures."""


class InvalidStateTransition(DomainError):
    """Raised when a session attempts a transition outside the workflow."""

    def __init__(self, current: Any, target: Any) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid session transition: {current} -> {target}")


class ScopeNotConfirmed(InvalidStateTransition):
    """Raised when extraction starts before the child confirms the scope."""

    def __init__(self, current: Any, target: Any) -> None:
        super().__init__(current, target)
        self.args = (
            "course scope must be confirmed before extraction "
            f"({current} -> {target})",
        )


class UnsupportedOperation(DomainError):
    """Raised by a provider adapter for a deliberately unsupported capability."""


class ProviderError(DomainError):
    """Base class for expected model or speech provider failures."""


class ProviderUnavailable(ProviderError):
    """Raised when a provider cannot be reached or returns a non-success status."""


class ProviderTimeout(ProviderError):
    """Raised when a provider does not answer within the configured timeout."""


class ProviderResponseInvalid(ProviderError):
    """Raised when a provider response is not valid for the requested contract."""


class OperationFailed(DomainError):
    """Raised when an internal/external operation fails unexpectedly."""


class RepositoryError(DomainError):
    """Raised when a repository cannot complete a requested operation."""
