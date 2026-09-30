# TalkPath Direct API Agent Backend Design

Date: 2026-08-12
Status: Approved for planning

## Objective

Make direct provider API calls the default TalkPath execution path. Pi Agent remains available as an explicitly selected experimental backend, but the production lesson flow must not start or depend on Pi by default.

This change removes Pi CLI startup, RPC, authentication, and extension-tool bridging from the normal runtime path while preserving the existing Vision, Text, STT, and TTS service interfaces.

## Scope

The change covers lesson import, activity generation, application lifecycle, provider health reporting, failure logging, frontend retry behavior, configuration, and tests.

It does not remove the Pi RPC implementation or Pi extension. It does not change provider API credentials, provider response schemas, STT/TTS protocols, or the session state model except where retry behavior creates a fresh session.

## Backend Selection

Add `TALKPATH_AGENT_BACKEND` with two accepted values:

- `direct`: default; application services call provider APIs directly and never start Pi.
- `pi`: opt-in compatibility mode retaining the existing Pi-mediated behavior.

Invalid values fail during settings validation. Pi-specific settings remain accepted but are not required or accessed in direct mode.

The selected backend is exposed through provider health output without exposing credentials or command arguments.

## Architecture

### Direct lesson import

1. Validate session state, confirmed course scope, operation ID, and image references.
2. Transition the session to `EXTRACTING`.
3. Call `VisionService.extract_lesson()` with trusted image references, confirmed scope, and operation ID.
4. Validate that the resulting `LessonDraft` identity matches the confirmed scope and operation.
5. Preserve the existing preview, save, and ready-to-generate state transitions.

No Pi process is started, no Pi prompt is sent, and no Pi extension tool is called in direct mode.

### Direct activity and learning operations

Activity generation calls the existing `TextService.generate_activity()` implementation directly. Grammar explanation and answer evaluation continue through the existing Text service. STT and TTS continue through their existing service interfaces.

### Pi compatibility mode

When `TALKPATH_AGENT_BACKEND=pi`, lesson import retains the existing Pi-first behavior, including Pi events and the existing Vision fallback when Pi does not return a valid lesson draft. Existing Pi RPC and extension tests remain supported.

## Application Lifecycle

The application constructs and manages a Pi client only when the selected backend is `pi`. In direct mode, startup and shutdown do not launch, inspect, or close a Pi child process.

`SessionService` receives the backend selection explicitly. A Pi client may be optional in direct mode, preventing accidental calls and making tests able to prove that Pi is not touched.

## Observability and Error Handling

Use structured application logs around external operations. Each operation records:

- event or stage name;
- `session_id` where applicable;
- `operation_id`;
- selected agent backend;
- provider capability or backend name;
- elapsed time;
- exception type and traceback on failure.

Logs must not contain API keys, authorization headers, image or audio bytes, full prompts, or complete provider response bodies.

Expected provider exceptions preserve their existing public mappings:

- timeout: HTTP 504;
- unavailable or rate limited: HTTP 503;
- malformed or invalid provider response: HTTP 502.

Unknown exceptions return HTTP 500 and are logged with a traceback. Domain errors are not replaced by generic repository errors.

## Frontend Retry Behavior

A failed session is terminal under the current state machine. The frontend therefore must not retry import against the same `FAILED` session.

The retry action creates a new lesson session and repeats the normal upload and scope-confirmation flow using the files and form values still held by the browser. If those files are no longer available, the UI returns the user to the upload step with an explicit message.

## Compatibility

Existing public HTTP routes and successful response payloads remain unchanged. WebSocket lifecycle events remain available in direct mode, but Pi-specific agent events are emitted only in Pi mode.

Existing Pi settings remain recognized. Normal direct startup requires only the configured Vision, Text, STT, and TTS providers; it does not require `TALKPATH_PI_COMMAND`, Pi login state, or additional shell environment variables.

## Test Strategy

### Unit and application tests

- Settings default to `direct` and reject invalid backend values.
- Direct import calls Vision exactly once and never starts or prompts Pi.
- Direct activity generation calls Text directly.
- Pi mode preserves the existing Pi-mediated behavior.
- Provider errors keep their public HTTP status and error code.
- Unknown failures produce safe structured logs with traceback metadata.
- Log records do not include configured secrets, image bytes, audio bytes, or full prompts.

### API and frontend tests

- Provider health reports the selected agent backend.
- Direct-mode import reaches the existing success response without Pi.
- Failed-import retry creates a new session instead of reusing a failed session.
- Frontend JavaScript syntax validation passes.

### Regression verification

- Run the full Python test suite.
- Run Pi extension tests and TypeScript typecheck.
- Run Python bytecode compilation and JavaScript syntax checks.
- Run diff/whitespace checks.
- Start TalkPath on port 8001 in direct mode and verify health endpoints.
- Perform live provider calls only through the existing explicit live-test gate. Do not resend user textbook images as an automated diagnostic action.

## Acceptance Criteria

1. A default TalkPath process can import and generate activities without installing, authenticating, or starting Pi.
2. Direct mode contains no Pi process or RPC call during lesson and activity flows.
3. Pi remains usable only when explicitly selected.
4. A backend failure produces a useful server-side traceback and a correctly classified public API error without leaking sensitive data.
5. Retry after import failure starts a fresh session.
6. All relevant automated verification passes, with live provider limitations reported separately rather than hidden by fallback behavior.
