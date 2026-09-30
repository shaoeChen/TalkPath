"""Async JSONL client for the official Pi RPC process.

The Python service owns this process boundary.  Pi is deliberately started
without its persistent session and built-in filesystem/shell tools; the
TypeScript extension is the only tool surface exposed to the agent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from talkpath.config import PROJECT_ROOT
from talkpath.domain.errors import DomainError


DEFAULT_PI_EXTENSION = PROJECT_ROOT / "pi-extension" / "talkpath-tools.ts"


class PiRpcError(DomainError):
    """Base class for expected Pi process and protocol failures."""


class PiProtocolError(PiRpcError):
    """Raised when Pi emits malformed or structurally invalid JSONL."""


class PiProcessExited(PiRpcError):
    """Raised when the Pi child exits while work is still pending."""

    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        super().__init__(f"Pi RPC process exited unexpectedly (returncode={returncode})")


class PiCommandFailed(PiRpcError):
    """Raised when Pi rejects a command or the request is aborted."""

    def __init__(self, command: str, message: str, *, request_id: str | None = None) -> None:
        self.command = command
        self.request_id = request_id
        super().__init__(f"Pi RPC command {command!r} failed: {message}")


class PiClientClosed(PiRpcError):
    """Raised for pending work cancelled while the client is closing."""


@dataclass(frozen=True, slots=True)
class PiEvent:
    """A typed view over one JSONL event, retaining the original payload."""

    type: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PiResponseEvent(PiEvent):
    request_id: str | None
    command: str
    success: bool


@dataclass(frozen=True, slots=True)
class MessageUpdateEvent(PiEvent):
    delta: str
    assistant_event_type: str | None


@dataclass(frozen=True, slots=True)
class ToolExecutionEvent(PiEvent):
    event_type: str
    tool_call_id: str | None
    tool_name: str | None
    is_error: bool | None


@dataclass(frozen=True, slots=True)
class AgentSettledEvent(PiEvent):
    pass


@dataclass(frozen=True, slots=True)
class ExtensionErrorEvent(PiEvent):
    message: str


@dataclass(frozen=True, slots=True)
class UnknownPiEvent(PiEvent):
    pass


# A short, stable name for callers that only need to type a response.
PiResponse = PiResponseEvent


@dataclass(frozen=True, slots=True)
class PromptResult:
    response: PiResponseEvent
    events: tuple[PiEvent, ...] = ()
    operation_id: str | None = None


def _payload_dict(payload: Mapping[str, Any]) -> dict[str, Any]:
    return dict(payload)


def parse_jsonl_event(raw_line: bytes | str) -> PiEvent | None:
    """Parse exactly one LF/CRLF-delimited JSONL record.

    ``StreamReader.readline`` is intentionally used by ``read_jsonl_events``;
    unlike ``str.splitlines`` it does not treat U+2028 or U+2029 inside a JSON
    string as record delimiters.
    """

    if isinstance(raw_line, bytes):
        line = raw_line
        if line.endswith(b"\n"):
            line = line[:-1]
        if line.endswith(b"\r"):
            line = line[:-1]
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PiProtocolError("Pi RPC emitted invalid UTF-8") from exc
    else:
        text = raw_line
        if text.endswith("\n"):
            text = text[:-1]
        if text.endswith("\r"):
            text = text[:-1]

    if not text.strip():
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PiProtocolError(f"Pi RPC emitted invalid JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise PiProtocolError("Pi RPC event must be a JSON object")
    return _event_from_payload(decoded)


def _event_from_payload(payload: dict[str, Any]) -> PiEvent:
    event_type = payload.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise PiProtocolError("Pi RPC event is missing a string type")
    event_payload = _payload_dict(payload)

    if event_type == "response":
        request_id = payload.get("id")
        command = payload.get("command")
        success = payload.get("success")
        if request_id is not None and not isinstance(request_id, str):
            raise PiProtocolError("Pi RPC response id must be a string")
        if not isinstance(command, str) or not isinstance(success, bool):
            raise PiProtocolError("Pi RPC response requires command and success")
        return PiResponseEvent(event_type, event_payload, request_id, command, success)

    if event_type == "message_update":
        assistant_event = payload.get("assistantMessageEvent")
        if not isinstance(assistant_event, dict):
            raise PiProtocolError("message_update requires assistantMessageEvent")
        delta = assistant_event.get("delta", "")
        if not isinstance(delta, str):
            raise PiProtocolError("message_update delta must be a string")
        assistant_event_type = assistant_event.get("type")
        if assistant_event_type is not None and not isinstance(assistant_event_type, str):
            raise PiProtocolError("message_update event type must be a string")
        return MessageUpdateEvent(event_type, event_payload, delta, assistant_event_type)

    if event_type.startswith("tool_execution_"):
        tool_call_id = payload.get("toolCallId")
        tool_name = payload.get("toolName")
        is_error = payload.get("isError")
        if tool_call_id is not None and not isinstance(tool_call_id, str):
            raise PiProtocolError("tool execution call id must be a string")
        if tool_name is not None and not isinstance(tool_name, str):
            raise PiProtocolError("tool execution name must be a string")
        if is_error is not None and not isinstance(is_error, bool):
            raise PiProtocolError("tool execution isError must be a boolean")
        return ToolExecutionEvent(event_type, event_payload, event_type, tool_call_id, tool_name, is_error)

    if event_type == "agent_settled":
        return AgentSettledEvent(event_type, event_payload)

    if event_type == "extension_error":
        message = payload.get("message", "Pi extension error")
        if not isinstance(message, str):
            message = json.dumps(message, ensure_ascii=False)
        return ExtensionErrorEvent(event_type, event_payload, message)

    return UnknownPiEvent(event_type, event_payload)


async def read_jsonl_events(stream: Any) -> AsyncIterator[PiEvent]:
    """Read JSONL records using the stream's LF-aware ``readline`` method."""

    while True:
        raw_line = await stream.readline()
        if raw_line in (b"", ""):
            return
        event = parse_jsonl_event(raw_line)
        if event is not None:
            yield event


@dataclass(slots=True)
class _PromptContext:
    request_id: str
    response: asyncio.Future[PiResponseEvent]
    events: list[PiEvent] = field(default_factory=list)
    settled: asyncio.Future[None] | None = None
    abort_task: asyncio.Task[bool] | None = None
    abort_confirmed: bool = False


class PiRpcClient:
    """Manage one Pi RPC subprocess and correlate its JSONL responses."""

    def __init__(
        self,
        command: str | Sequence[str] = "pi",
        *,
        extension: str | Path | None = None,
        timeout: float = 60.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self._base_command = self._normalize_command(command)
        self.extension = Path(extension) if extension is not None else DEFAULT_PI_EXTENSION
        self.timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._prompt_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[PiResponseEvent]] = {}
        self._pending_commands: dict[str, str] = {}
        self._active_prompt: _PromptContext | None = None
        self._write_operations: dict[str, tuple[str, asyncio.Task[PromptResult]]] = {}
        self._completed_write_operations: dict[str, tuple[str, PromptResult]] = {}
        self._events: asyncio.Queue[PiEvent] = asyncio.Queue()
        self._process_error: PiRpcError | None = None
        self._closing = False
        self._closed = False

    @classmethod
    def from_settings(cls, settings: Any, *, timeout: float = 60.0) -> "PiRpcClient":
        """Build a client from the existing TalkPath settings object."""

        return cls(
            command=settings.pi_command,
            extension=settings.pi_extension,
            timeout=timeout,
        )

    @staticmethod
    def _normalize_command(command: str | Sequence[str]) -> tuple[str, ...]:
        if isinstance(command, str):
            parts = tuple(shlex.split(command))
        else:
            parts = tuple(str(part) for part in command)
        if not parts:
            raise ValueError("Pi command cannot be empty")
        return parts

    @property
    def command(self) -> tuple[str, ...]:
        args = [*self._base_command, "--mode", "rpc", "--no-session", "--no-builtin-tools"]
        if self.extension is not None:
            args.extend(("--extension", str(self.extension)))
        return tuple(args)

    @property
    def is_running(self) -> bool:
        return (
            self._process is not None
            and self._process.returncode is None
            and self._process_error is None
        )

    @property
    def events(self) -> asyncio.Queue[PiEvent]:
        return self._events

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self.is_running:
                return
            self._closed = False
            self._closing = False
            self._process_error = None
            create_task = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    *self.command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                name="talkpath-pi-rpc-create-process",
            )
            try:
                process = await asyncio.shield(create_task)
            except asyncio.CancelledError:
                try:
                    process = await asyncio.wait_for(asyncio.shield(create_task), timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    create_task.cancel()
                    await asyncio.gather(create_task, return_exceptions=True)
                    raise
                await self._terminate_process(process)
                raise
            if self._closed or self._closing:
                await self._terminate_process(process)
                return
            self._process = process
            assert process.stdout is not None
            self._reader_task = asyncio.create_task(
                self._read_events(process.stdout, process),
                name="talkpath-pi-rpc-reader",
            )
            if process.stderr is not None:
                self._stderr_task = asyncio.create_task(
                    self._drain_stderr(process.stderr),
                    name="talkpath-pi-rpc-stderr",
                )

    async def _drain_stderr(self, stream: Any) -> None:
        while await stream.readline():
            pass

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.returncode is not None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), timeout=0.25)
            return
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), timeout=0.5)
            return
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()

    async def _read_events(self, stream: Any, process: asyncio.subprocess.Process) -> None:
        error: PiRpcError | None = None
        try:
            async for event in read_jsonl_events(stream):
                await self._events.put(event)
                if isinstance(event, PiResponseEvent):
                    await self._handle_response(event)
                else:
                    self._handle_non_response(event)
        except PiProtocolError as exc:
            error = exc
        except (ConnectionError, OSError, asyncio.IncompleteReadError) as exc:
            error = PiProcessExited(process.returncode)
            error.__cause__ = exc
        finally:
            if self._closing:
                return
            if error is None:
                error = PiProcessExited(process.returncode)
            if self._process is process:
                self._process_error = error
                if process.stdin is not None:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
                if process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                self._fail_pending(error)
            await self._terminate_process(process)

    async def _handle_response(self, event: PiResponseEvent) -> None:
        future: asyncio.Future[PiResponseEvent] | None = None
        if event.request_id is not None:
            future = self._pending.get(event.request_id)
            if future is not None:
                expected_command = self._pending_commands.get(event.request_id)
                if expected_command is not None and event.command != expected_command:
                    raise PiProtocolError(
                        "Pi RPC response command mismatch for "
                        f"request {event.request_id!r}: expected {expected_command!r}, "
                        f"got {event.command!r}"
                    )
        if future is None and event.request_id is None:
            matching_ids = [
                request_id
                for request_id, command in self._pending_commands.items()
                if command == event.command
            ]
            if len(matching_ids) == 1:
                future = self._pending.get(matching_ids[0])
        if future is None:
            if self._active_prompt is not None:
                self._active_prompt.events.append(event)
            return
        if future.done():
            return
        if event.success:
            future.set_result(event)
        else:
            message = event.payload.get("error") or event.payload.get("message") or "unknown error"
            future.set_exception(
                PiCommandFailed(event.command, str(message), request_id=event.request_id)
            )

    def _handle_non_response(self, event: PiEvent) -> None:
        active = self._active_prompt
        if active is None:
            return
        active.events.append(event)
        if isinstance(event, AgentSettledEvent) and active.settled is not None:
            if not active.settled.done():
                active.settled.set_result(None)

    def _fail_pending(self, error: PiRpcError) -> None:
        active = self._active_prompt
        active_response = self._pending.get(active.request_id) if active is not None else None
        active_response_pending = active_response is not None and not active_response.done()
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)
            if not future.cancelled():
                future.exception()
        if active is not None and active.settled is not None and not active.settled.done():
            if active_response_pending:
                # The prompt is waiting on the response future and will leave
                # before it can observe a second exception from ``settled``.
                active.settled.cancel()
            else:
                active.settled.set_exception(error)
                active.settled.exception()

    def _ensure_available(self, *, allow_closing: bool = False) -> None:
        if self._closed:
            raise PiClientClosed("Pi RPC client is closed")
        if self._closing and not allow_closing:
            raise PiClientClosed("Pi RPC client is closing")
        if not self.is_running:
            if self._process_error is not None:
                raise self._process_error
            raise PiProcessExited(self._process.returncode if self._process else None)

    async def _write_command(
        self, payload: Mapping[str, Any], *, allow_closing: bool = False
    ) -> None:
        encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        async with self._write_lock:
            self._ensure_available(allow_closing=allow_closing)
            process = self._process
            assert process is not None and process.stdin is not None
            try:
                process.stdin.write(encoded)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionError, OSError) as exc:
                error = PiProcessExited(process.returncode)
                self._process_error = error
                raise error from exc

    async def _send_and_wait(self, command: str, payload: Mapping[str, Any]) -> PiResponseEvent:
        request_id = str(uuid4())
        future: asyncio.Future[PiResponseEvent] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._pending_commands[request_id] = command
        try:
            await self._write_command({"type": command, "id": request_id, **payload})
            return await asyncio.wait_for(asyncio.shield(future), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise PiCommandFailed(command, "timed out", request_id=request_id) from exc
        finally:
            self._pending.pop(request_id, None)
            self._pending_commands.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def _prompt_once(
        self,
        message: str,
        *,
        operation_id: str | None,
        write_tool: str | None = None,
        write_payload: Any = None,
    ) -> PromptResult:
        async with self._prompt_lock:
            self._ensure_available()
            request_id = str(uuid4())
            response_future: asyncio.Future[PiResponseEvent] = asyncio.get_running_loop().create_future()
            settled_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            context = _PromptContext(
                request_id=request_id,
                response=response_future,
                settled=settled_future,
            )
            self._active_prompt = context
            self._pending[request_id] = response_future
            self._pending_commands[request_id] = "prompt"
            try:
                prompt_payload: dict[str, Any] = {
                    "type": "prompt",
                    "id": request_id,
                    "message": message,
                }
                if write_payload is not None:
                    prompt_payload["write_payload"] = write_payload
                await self._write_command(prompt_payload)
                response = await asyncio.wait_for(
                    asyncio.shield(response_future), timeout=self.timeout
                )
                await asyncio.wait_for(asyncio.shield(settled_future), timeout=self.timeout)
                return PromptResult(response=response, events=tuple(context.events), operation_id=operation_id)
            except asyncio.TimeoutError as exc:
                await self._abort_context(context)
                raise PiCommandFailed("prompt", "timed out", request_id=request_id) from exc
            except asyncio.CancelledError:
                abort_task = asyncio.create_task(self._abort_context(context), name="talkpath-pi-abort")
                try:
                    await asyncio.shield(abort_task)
                except asyncio.CancelledError:
                    try:
                        await asyncio.shield(abort_task)
                    except BaseException:
                        pass
                raise
            finally:
                self._pending.pop(request_id, None)
                self._pending_commands.pop(request_id, None)
                if self._active_prompt is context:
                    self._active_prompt = None

    async def prompt(
        self,
        message: str,
        *,
        operation_id: str | None = None,
        write_type: bool = False,
        write_tool: str | None = None,
        write_payload: Any = None,
    ) -> PromptResult:
        """Send a prompt and wait for its response plus ``agent_settled``.

        When a prompt represents a write-type tool operation, callers provide
        its operation ID. Concurrent or repeated retries then share one Pi
        request and one result, preventing duplicate writes.
        """

        self._ensure_available()
        if not write_type or not operation_id:
            return await self._prompt_once(
                message,
                operation_id=operation_id,
                write_tool=write_tool,
                write_payload=write_payload,
            )
        fingerprint = self._write_fingerprint(write_tool, message, write_payload)
        completed = self._completed_write_operations.get(operation_id)
        if completed is not None:
            completed_fingerprint, result = completed
            if completed_fingerprint != fingerprint:
                raise PiCommandFailed("prompt", "operation_id reused for a different write request")
            return result
        existing = self._write_operations.get(operation_id)
        if existing is not None:
            existing_fingerprint, existing_task = existing
            if existing_fingerprint != fingerprint:
                raise PiCommandFailed("prompt", "operation_id reused for a different write request")
            return await asyncio.shield(existing_task)
        task = asyncio.create_task(
            self._prompt_once(
                message,
                operation_id=operation_id,
                write_tool=write_tool,
                write_payload=write_payload,
            ),
            name=f"talkpath-pi-write-{operation_id}",
        )
        self._write_operations[operation_id] = (fingerprint, task)
        task.add_done_callback(
            lambda completed_task, op_id=operation_id, op_fingerprint=fingerprint: self._finish_write_operation(
                op_id, op_fingerprint, completed_task
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            active = self._active_prompt
            if active is not None:
                abort_task = asyncio.create_task(
                    self._abort_context(active),
                    name=f"talkpath-pi-abort-{active.request_id}",
                )
                try:
                    await asyncio.shield(abort_task)
                except asyncio.CancelledError:
                    try:
                        await asyncio.shield(abort_task)
                    except BaseException:
                        pass
            raise

    @staticmethod
    def _write_fingerprint(write_tool: str | None, message: str, payload: Any) -> str:
        try:
            encoded = json.dumps(
                {"tool": write_tool or "", "message": message, "payload": payload},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=repr,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("write payload must be fingerprintable") from exc
        return hashlib.sha256(encoded).hexdigest()

    def _finish_write_operation(
        self,
        operation_id: str,
        fingerprint: str,
        task: asyncio.Task[PromptResult],
    ) -> None:
        current = self._write_operations.get(operation_id)
        if current is not None and current[0] == fingerprint and current[1] is task:
            self._write_operations.pop(operation_id, None)
        if task.cancelled():
            return
        try:
            result = task.result()
        except BaseException:
            return
        if not self._closed:
            self._completed_write_operations[operation_id] = (fingerprint, result)

    async def _confirm_abort(self) -> bool:
        try:
            response = await asyncio.wait_for(
                self._send_and_wait("abort", {}),
                timeout=min(0.5, self.timeout),
            )
        except (PiRpcError, asyncio.TimeoutError):
            return False
        return response.success

    async def _abort_context(self, context: _PromptContext, *, fail_wait: bool = False) -> bool:
        if context.abort_task is None:
            context.abort_task = asyncio.create_task(
                self._confirm_abort(),
                name=f"talkpath-pi-abort-{context.request_id}",
            )
        try:
            confirmed = await asyncio.shield(context.abort_task)
        except BaseException:
            confirmed = False
        context.abort_confirmed = confirmed
        if not confirmed:
            process = self._process
            if process is not None:
                self._process_error = PiProcessExited(process.returncode)
                self._fail_pending(self._process_error)
                await self._terminate_process(process)
        if fail_wait:
            failure = PiCommandFailed("prompt", "aborted", request_id=context.request_id)
            if not context.response.done():
                context.response.set_exception(failure)
                if context.settled is not None and not context.settled.done():
                    context.settled.cancel()
            elif context.settled is not None and not context.settled.done():
                context.settled.set_exception(failure)
        else:
            if not context.response.done():
                context.response.cancel()
            elif not context.response.cancelled():
                context.response.exception()
            if context.settled is not None and not context.settled.done():
                context.settled.cancel()
            elif context.settled is not None and not context.settled.cancelled():
                context.settled.exception()
        return confirmed

    async def abort(self) -> None:
        """Cancel the active prompt locally, then notify Pi best-effort."""

        self._ensure_available()
        active = self._active_prompt
        if active is not None:
            await self._abort_context(active, fail_wait=True)
            return
        await self._send_and_wait("abort", {})

    async def new_session(self) -> PiResponseEvent:
        """Ask Pi to clear its current agent session."""

        return await self._send_and_wait("new_session", {})

    async def next_event(self) -> PiEvent:
        """Wait for the next raw-but-typed Pi event."""

        return await self._events.get()

    async def close(self) -> None:
        """Stop the child process and fail all pending work deterministically."""

        async with self._lifecycle_lock:
            if self._closed and self._process is None:
                return
            self._closing = True
            process = self._process
            if process is not None and process.returncode is None:
                try:
                    # Send graceful close while _closed is still false; the
                    # regular write path can therefore enforce availability.
                    await self._write_command(
                        {"type": "close", "id": str(uuid4())},
                        allow_closing=True,
                    )
                except PiRpcError:
                    pass
            self._closed = True
            self._fail_pending(PiClientClosed("Pi RPC client is closing"))
            if process is not None:
                await self._terminate_process(process)
            tasks = [task for task in (self._reader_task, self._stderr_task) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._reader_task = None
            self._stderr_task = None
            self._process = None
            self._active_prompt = None
            self._pending.clear()
            self._pending_commands.clear()
            self._write_operations.clear()
            self._completed_write_operations.clear()
