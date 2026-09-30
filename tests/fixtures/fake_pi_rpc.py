"""Small stdin/stdout JSONL process used by Pi RPC tests."""

from __future__ import annotations

import json
import os
import sys
import time


def emit(payload: dict[str, object], *, crlf: bool = True) -> None:
    separator = "\r\n" if crlf else "\n"
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + separator)
    sys.stdout.flush()


def log_command(command: dict[str, object]) -> None:
    path = os.environ.get("FAKE_PI_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(command, ensure_ascii=False) + "\n")


def handle(command: dict[str, object]) -> None:
    log_command(command)
    command_type = command.get("type")
    request_id = command.get("id")
    if command_type == "prompt":
        message = str(command.get("message", ""))
        if message == "die":
            raise SystemExit(17)
        if message == "invalid":
            sys.stdout.write("not-json\n")
            sys.stdout.flush()
            raise SystemExit(17)
        if message == "invalid_live":
            sys.stdout.write("not-json\n")
            sys.stdout.flush()
            time.sleep(30)
            return
        if message == "eof_live":
            sys.stdout.flush()
            try:
                os.close(sys.stdout.fileno())
            except OSError:
                pass
            time.sleep(30)
            return
        if message == "mismatch":
            emit(
                {
                    "type": "response",
                    "id": "not-the-request",
                    "command": "prompt",
                    "success": True,
                }
            )
        if message == "command_mismatch":
            emit(
                {
                    "type": "response",
                    "id": request_id,
                    "command": "new_session",
                    "success": True,
                }
            )
            time.sleep(30)
            return
        emit(
            {
                "type": "response",
                "id": request_id,
                "command": "prompt",
                "success": True,
            }
        )
        if message == "wait":
            return
        if message == "unknown":
            emit({"type": "future_event", "value": 7})
        if message in {"events", "unicode"}:
            delta = "A\u2028B" if message == "unicode" else "Hello"
            emit(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": delta},
                }
            )
            emit(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "tool-1",
                    "toolName": "extract_lesson",
                }
            )
            emit(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "tool-1",
                    "toolName": "extract_lesson",
                    "isError": False,
                }
            )
            emit({"type": "extension_error", "message": "non-fatal test error"})
        emit({"type": "agent_settled"})
    elif command_type == "abort":
        emit(
            {
                "type": "response",
                "id": request_id,
                "command": "abort",
                "success": True,
            }
        )
    elif command_type == "new_session":
        emit(
            {
                "type": "response",
                "id": request_id,
                "command": "new_session",
                "success": True,
            }
        )
    elif command_type == "close":
        return


def main() -> None:
    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        command = json.loads(raw_line)
        handle(command)
        if command.get("type") == "close":
            break


if __name__ == "__main__":
    main()
