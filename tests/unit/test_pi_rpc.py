from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from talkpath.config import PROJECT_ROOT, Settings
from talkpath.agent.pi_rpc import (
    AgentSettledEvent,
    ExtensionErrorEvent,
    MessageUpdateEvent,
    PiClientClosed,
    PiCommandFailed,
    PiProcessExited,
    PiProtocolError,
    PiRpcClient,
    ToolExecutionEvent,
    UnknownPiEvent,
    parse_jsonl_event,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "fake_pi_rpc.py"


class AsyncLines:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = iter(lines)

    async def readline(self) -> bytes:
        try:
            return next(self.lines)
        except StopIteration:
            return b""


class BlockingStream:
    async def readline(self) -> bytes:
        await asyncio.Future()
        return b""


class StubStdin:
    def __init__(self) -> None:
        self.closed = False
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class BlockingDrainStdin(StubStdin):
    def __init__(self) -> None:
        super().__init__()
        self.drain_started = asyncio.Event()
        self.release_drain = asyncio.Event()
        self._block_next_drain = True

    async def drain(self) -> None:
        if self._block_next_drain:
            self._block_next_drain = False
            self.drain_started.set()
            await self.release_drain.wait()


class StubProcess:
    def __init__(self, stdin: StubStdin | None = None) -> None:
        self.stdin = stdin or StubStdin()
        self.stdout = BlockingStream()
        self.stderr = BlockingStream()
        self.returncode: int | None = None
        self.terminated = 0
        self.killed = 0
        self._exited = asyncio.Event()

    async def wait(self) -> int | None:
        await self._exited.wait()
        return self.returncode

    def terminate(self) -> None:
        self.terminated += 1
        self.returncode = -15
        self._exited.set()

    def kill(self) -> None:
        self.killed += 1
        self.returncode = -9
        self._exited.set()


def test_jsonl_parser_uses_only_lf_or_crlf_and_keeps_unicode_line_separators() -> None:
    event = parse_jsonl_event(
        b'{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"A\xe2\x80\xa8B"}}\r\n'
    )

    assert isinstance(event, MessageUpdateEvent)
    assert event.delta == "A\u2028B"


def test_jsonl_parser_ignores_blank_lines_and_exposes_unknown_events() -> None:
    assert parse_jsonl_event(b"\r\n") is None
    event = parse_jsonl_event(b'{"type":"future_event","value":7}\n')

    assert isinstance(event, UnknownPiEvent)
    assert event.payload["value"] == 7


def test_jsonl_parser_rejects_invalid_json() -> None:
    with pytest.raises(PiProtocolError, match="invalid JSON"):
        parse_jsonl_event(b"not-json\n")


@pytest.mark.asyncio
async def test_jsonl_reader_handles_eof_after_final_line() -> None:
    from talkpath.agent.pi_rpc import read_jsonl_events

    events = [event async for event in read_jsonl_events(AsyncLines([b'{"type":"agent_settled"}']))]

    assert len(events) == 1
    assert isinstance(events[0], AgentSettledEvent)


def client_for(tmp_path: Path, **kwargs: object) -> PiRpcClient:
    return PiRpcClient(
        command=(sys.executable, str(FIXTURE)),
        extension=tmp_path / "talkpath-tools.ts",
        timeout=2.0,
        **kwargs,
    )


def test_client_can_be_built_from_talkpath_settings(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        pi_command="pi-test",
        pi_extension=tmp_path / "talkpath-tools.ts",
    )

    client = PiRpcClient.from_settings(settings, timeout=3.0)

    assert client.command == (
        "pi-test",
        "--mode",
        "rpc",
        "--no-session",
        "--no-builtin-tools",
        "--extension",
        str(tmp_path / "talkpath-tools.ts"),
    )


def test_client_uses_project_extension_by_default() -> None:
    client = PiRpcClient()
    expected_extension = PROJECT_ROOT / "pi-extension" / "talkpath-tools.ts"

    assert client.extension == expected_extension
    assert client.command[-2:] == ("--extension", str(expected_extension))


@pytest.mark.asyncio
async def test_start_and_close_are_lifecycle_serialized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = StubProcess()
    create_started = asyncio.Event()
    release_create = asyncio.Event()

    async def delayed_create(*args: object, **kwargs: object) -> StubProcess:
        create_started.set()
        await release_create.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_create)
    client = PiRpcClient(command=("fake-pi",), extension=tmp_path / "talkpath-tools.ts")
    start_task = asyncio.create_task(client.start())
    await create_started.wait()
    close_task = asyncio.create_task(client.close())
    await asyncio.sleep(0)
    release_create.set()

    try:
        await start_task
        await close_task
        assert process.terminated == 1
        assert client.is_running is False
        assert client._reader_task is None
    finally:
        if not close_task.done():
            await client.close()
        if not start_task.done():
            start_task.cancel()
            await asyncio.gather(start_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_close_wins_write_lock_and_blocks_queued_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = StubProcess()

    async def create_process(*args: object, **kwargs: object) -> StubProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    client = PiRpcClient(command=("fake-pi",), extension=tmp_path / "talkpath-tools.ts")
    await client.start()
    await client._write_lock.acquire()
    close_task = asyncio.create_task(client.close())
    try:
        for _ in range(20):
            if client._closing:
                break
            await asyncio.sleep(0)
        assert client._closing is True
        prompt_task = asyncio.create_task(client.prompt("events"))
        await asyncio.sleep(0)
        client._write_lock.release()

        await close_task
        with pytest.raises(PiClientClosed):
            await prompt_task
        writes = [json.loads(data) for data in process.stdin.writes]
        assert [write["type"] for write in writes] == ["close"]
    finally:
        if client._write_lock.locked():
            client._write_lock.release()
        if not close_task.done():
            await client.close()
        if not prompt_task.done():
            prompt_task.cancel()
            await asyncio.gather(prompt_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_prompt_write_finishes_before_close_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stdin = BlockingDrainStdin()
    process = StubProcess(stdin)

    async def create_process(*args: object, **kwargs: object) -> StubProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    client = PiRpcClient(command=("fake-pi",), extension=tmp_path / "talkpath-tools.ts")
    await client.start()
    prompt_task = asyncio.create_task(client.prompt("events"))
    close_task: asyncio.Task[None] | None = None
    try:
        await stdin.drain_started.wait()
        close_task = asyncio.create_task(client.close())
        for _ in range(20):
            if client._closing:
                break
            await asyncio.sleep(0)
        assert client._closing is True
        stdin.release_drain.set()

        await close_task
        with pytest.raises(PiClientClosed):
            await prompt_task
        writes = [json.loads(data) for data in process.stdin.writes]
        assert [write["type"] for write in writes] == ["prompt", "close"]
    finally:
        if close_task is not None and not close_task.done():
            await client.close()
        if not prompt_task.done():
            prompt_task.cancel()
            await asyncio.gather(prompt_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_start_uses_rpc_command_and_prompt_waits_for_settled(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.jsonl"
    old_log = os.environ.get("FAKE_PI_LOG")
    os.environ["FAKE_PI_LOG"] = str(log_path)
    client = client_for(tmp_path)
    try:
        await client.start()
        result = await client.prompt("events")

        assert result.response.success is True
        assert any(isinstance(event, MessageUpdateEvent) for event in result.events)
        assert any(isinstance(event, ToolExecutionEvent) for event in result.events)
        assert any(isinstance(event, ExtensionErrorEvent) for event in result.events)
        command = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
        assert command["type"] == "prompt"
        assert client.command[-6:] == (
            "--mode",
            "rpc",
            "--no-session",
            "--no-builtin-tools",
            "--extension",
            str(tmp_path / "talkpath-tools.ts"),
        )
    finally:
        await client.close()
        if old_log is None:
            os.environ.pop("FAKE_PI_LOG", None)
        else:
            os.environ["FAKE_PI_LOG"] = old_log


@pytest.mark.asyncio
async def test_prompt_correlates_matching_response_and_keeps_unknown_event(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    await client.start()
    try:
        result = await client.prompt("mismatch")

        assert result.response.command == "prompt"
        assert any(isinstance(event, UnknownPiEvent) is False for event in result.events)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["invalid_live", "eof_live"])
async def test_reader_failure_immediately_fails_and_stops_live_process(
    message: str, tmp_path: Path
) -> None:
    client = client_for(tmp_path)
    await client.start()
    try:
        with pytest.raises((PiProtocolError, PiProcessExited)):
            await asyncio.wait_for(client.prompt(message), timeout=1.0)
        assert client.is_running is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_new_session_waits_for_correlated_response(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    await client.start()
    try:
        response = await client.new_session()

        assert response.command == "new_session"
        assert response.success is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_abort_stops_a_waiting_prompt(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    await client.start()
    prompt_task = asyncio.create_task(client.prompt("wait"))
    await asyncio.sleep(0.05)
    try:
        await client.abort()
        with pytest.raises(PiCommandFailed, match="aborted"):
            await prompt_task
    finally:
        if not prompt_task.done():
            prompt_task.cancel()
        await client.close()


@pytest.mark.asyncio
async def test_prompt_timeout_confirms_abort_before_write_retry(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.jsonl"
    old_log = os.environ.get("FAKE_PI_LOG")
    os.environ["FAKE_PI_LOG"] = str(log_path)
    client = PiRpcClient(
        command=(sys.executable, str(FIXTURE)),
        extension=tmp_path / "talkpath-tools.ts",
        timeout=0.2,
    )
    await client.start()
    try:
        with pytest.raises(PiCommandFailed, match="timed out"):
            await client.prompt("wait", operation_id="retry-1", write_type=True)
        await client.prompt("events", operation_id="retry-1", write_type=True)
        commands = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert [command["type"] for command in commands[:2]] == ["prompt", "abort"]
    finally:
        await client.close()
        if old_log is None:
            os.environ.pop("FAKE_PI_LOG", None)
        else:
            os.environ["FAKE_PI_LOG"] = old_log


@pytest.mark.asyncio
async def test_prompt_cancellation_confirms_abort(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.jsonl"
    old_log = os.environ.get("FAKE_PI_LOG")
    os.environ["FAKE_PI_LOG"] = str(log_path)
    client = PiRpcClient(
        command=(sys.executable, str(FIXTURE)),
        extension=tmp_path / "talkpath-tools.ts",
        timeout=1.0,
    )
    await client.start()
    prompt_task = asyncio.create_task(client.prompt("wait", operation_id="cancel-1", write_type=True))
    await asyncio.sleep(0.05)
    prompt_task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await prompt_task
        commands = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert [command["type"] for command in commands[:2]] == ["prompt", "abort"]
    finally:
        await client.close()
        if old_log is None:
            os.environ.pop("FAKE_PI_LOG", None)
        else:
            os.environ["FAKE_PI_LOG"] = old_log


@pytest.mark.asyncio
async def test_process_exit_is_translated_to_domain_error(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    await client.start()
    try:
        with pytest.raises(PiProcessExited):
            await client.prompt("die")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_protocol_is_translated_to_clear_error(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    await client.start()
    try:
        with pytest.raises(PiProtocolError, match="invalid JSON"):
            await client.prompt("invalid")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_response_command_mismatch_fails_protocol_and_pending_work(
    tmp_path: Path,
) -> None:
    client = client_for(tmp_path)
    await client.start()
    try:
        with pytest.raises(PiProtocolError, match="command mismatch"):
            await client.prompt("command_mismatch")
        assert client.is_running is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_same_write_operation_id_is_sent_once(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.jsonl"
    old_log = os.environ.get("FAKE_PI_LOG")
    os.environ["FAKE_PI_LOG"] = str(log_path)
    client = client_for(tmp_path)
    await client.start()
    try:
        first, second = await asyncio.gather(
            client.prompt("events", operation_id="write-1", write_type=True),
            client.prompt("events", operation_id="write-1", write_type=True),
        )
        assert first.response.request_id == second.response.request_id
        commands = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert len([command for command in commands if command["type"] == "prompt"]) == 1
    finally:
        await client.close()
        if old_log is None:
            os.environ.pop("FAKE_PI_LOG", None)
        else:
            os.environ["FAKE_PI_LOG"] = old_log


@pytest.mark.asyncio
async def test_pi_prompt_log_contains_structured_write_payload(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.jsonl"
    old_log = os.environ.get("FAKE_PI_LOG")
    os.environ["FAKE_PI_LOG"] = str(log_path)
    client = client_for(tmp_path)
    payload = {
        "session_id": "session-1",
        "operation_id": "operation-1",
        "scope": {"lesson_id": "junior-high-grade-7-english-lesson-01"},
        "images": [
            {
                "image_id": "image-1",
                "path": "uploads/session-1/image-1.png",
                "mime_type": "image/png",
                "size_bytes": 12,
                "expires_at": "2099-01-01T00:00:00Z",
            }
        ],
    }
    try:
        await client.start()
        await client.prompt(
            "events",
            operation_id="operation-1",
            write_type=True,
            write_tool="extract_lesson",
            write_payload=payload,
        )
        commands = [
            json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
        ]
        prompt = next(command for command in commands if command["type"] == "prompt")
        assert prompt["write_payload"] == payload
    finally:
        await client.close()
        if old_log is None:
            os.environ.pop("FAKE_PI_LOG", None)
        else:
            os.environ["FAKE_PI_LOG"] = old_log


@pytest.mark.asyncio
async def test_write_dedup_rejects_same_operation_with_different_fingerprint(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    await client.start()
    try:
        await client.prompt(
            "events",
            operation_id="fingerprint-1",
            write_type=True,
            write_tool="save_lesson_draft",
            write_payload={"lesson_id": "lesson-1"},
        )
        with pytest.raises(PiCommandFailed, match="different write request"):
            await client.prompt(
                "events",
                operation_id="fingerprint-1",
                write_type=True,
                write_tool="save_learning_result",
                write_payload={"lesson_id": "lesson-1"},
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_close_terminates_process_and_cleans_pending_prompt(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    await client.start()
    prompt_task = asyncio.create_task(client.prompt("wait"))
    await asyncio.sleep(0.05)

    await client.close()

    with pytest.raises((PiClientClosed, PiProcessExited, PiCommandFailed)):
        await prompt_task
    assert client.is_running is False


@pytest.mark.asyncio
async def test_close_sends_graceful_command_before_terminating_and_is_idempotent(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.jsonl"
    old_log = os.environ.get("FAKE_PI_LOG")
    os.environ["FAKE_PI_LOG"] = str(log_path)
    client = client_for(tmp_path)
    try:
        await client.start()
        await client.close()
        await client.close()

        commands = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert [command["type"] for command in commands] == ["close"]
    finally:
        if old_log is None:
            os.environ.pop("FAKE_PI_LOG", None)
        else:
            os.environ["FAKE_PI_LOG"] = old_log
