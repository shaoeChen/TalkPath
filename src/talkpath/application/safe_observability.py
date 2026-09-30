"""Secret-safe structured observability for external operations."""

from __future__ import annotations

import json
import logging
import time
import traceback


operation_logger = logging.getLogger("talkpath.operations")


def _safe_log_value(value: object, *, max_length: int = 128) -> str:
    sanitized = "".join(
        character if character.isprintable() else "_" for character in str(value)
    )
    return json.dumps(sanitized[:max_length], ensure_ascii=True)


def log_operation_failure(
    *,
    event: str,
    session_id: str,
    operation_id: str,
    agent_backend: str,
    stage: str,
    started_at: float,
    error: Exception,
) -> None:
    """Log timing, exception type and traceback locations without error text."""

    formatted_stack = traceback.format_tb(error.__traceback__)
    stack = "\n".join(
        frame.splitlines()[0]
        for frame in formatted_stack
        if frame.splitlines()
    )
    operation_logger.error(
        "%s session_id=%s operation_id=%s agent_backend=%s stage=%s "
        "elapsed_ms=%d error_type=%s\n%s",
        _safe_log_value(event),
        _safe_log_value(session_id),
        _safe_log_value(operation_id),
        _safe_log_value(agent_backend),
        _safe_log_value(stage),
        round((time.perf_counter() - started_at) * 1000),
        _safe_log_value(type(error).__name__),
        stack,
    )
