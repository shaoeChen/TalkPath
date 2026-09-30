# TalkPath Direct API Agent Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make direct Vision/Text API calls the default TalkPath lesson path while retaining Pi as an explicit experimental backend, adding safe failure logs, and making failed imports retry through a fresh session.

**Architecture:** `Settings.agent_backend` selects `direct` or `pi`. `SessionService` branches only at the lesson-import boundary: direct mode calls `VisionService`, while Pi mode preserves the existing Pi-first path; the existing `ActivityService` continues to call `TextService` directly. FastAPI constructs Pi only for Pi mode, structured safe logs expose failure location without payloads or secrets, and the browser retry flow replays upload and scope confirmation into a new session.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, asyncio, pytest, JavaScript, Vitest/TypeScript for retained Pi extension regression.

**Design reference:** `docs/superpowers/specs/2026-08-12-direct-api-agent-backend-design.md`

**Workspace constraint:** Provider and speech integration files already contain uncommitted work required by this feature. Work in `D:/python/TalkPath`; before each commit inspect the index and stage only the direct-API hunks. Do not stage unrelated provider, speech, documentation, or generated WAV changes.

---

## File Map

- Modify `src/talkpath/config.py`: validate and expose the agent backend setting.
- Modify `src/talkpath/application/session_service.py`: make Pi optional, select direct/Pi import, and emit safe operation logs.
- Modify `src/talkpath/api/app.py`: construct Pi only in Pi mode and manage internally created service lifecycle.
- Modify `src/talkpath/api/provider_health.py`: report the selected agent backend without command or credential data.
- Modify `frontend/app.js`: retain the selected file and scope payload long enough to retry through a new session.
- Modify `tests/test_config.py`: settings default, override, and validation coverage.
- Modify `tests/unit/test_session_service.py`: direct mode and safe logging tests.
- Modify `tests/api/test_import_flow.py`: direct API default and Pi compatibility coverage.
- Modify `tests/api/test_health.py`: internally created service lifecycle coverage.
- Modify `tests/api/test_provider_health.py`: safe agent backend health metadata.
- Modify `tests/api/test_static_ui.py`: fresh-session retry contract.
- Modify `.env.example` and `README.md`: direct startup documentation.
- Modify `docs/PROGRESS.md`: implementation evidence and remaining live-provider limits.

### Task 1: Add validated backend selection and health metadata

**Files:**
- Modify: `src/talkpath/config.py`
- Modify: `src/talkpath/api/provider_health.py`
- Test: `tests/test_config.py`
- Test: `tests/api/test_provider_health.py`

- [ ] **Step 1: Write failing settings tests**

Add these assertions/tests to `tests/test_config.py`:

```python
def test_settings_default_to_direct_agent_backend(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    assert Settings(_env_file=None).agent_backend == "direct"


def test_settings_accept_pi_agent_backend(monkeypatch):
    _clear_talkpath_environment(monkeypatch)
    monkeypatch.setenv("TALKPATH_AGENT_BACKEND", "pi")
    assert Settings(_env_file=None).agent_backend == "pi"


def test_settings_reject_unknown_agent_backend():
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_backend="unknown")
```

- [ ] **Step 2: Run the settings tests and verify RED**

Run:

```powershell
uv run pytest tests/test_config.py -k agent_backend -q
```

Expected: failures because `Settings` has no `agent_backend` field or ignores/rejects it incorrectly.

- [ ] **Step 3: Implement the minimal validated setting**

Update imports and fields in `src/talkpath/config.py`:

```python
from typing import Literal


class Settings(BaseSettings):
    agent_backend: Literal["direct", "pi"] = "direct"
    pi_command: str = "pi"
```

Keep Pi command and extension fields unchanged for compatibility.

- [ ] **Step 4: Add a failing safe health-report test**

Add to `tests/api/test_provider_health.py`:

```python
def test_provider_health_reports_agent_backend_without_pi_command(tmp_path):
    settings = _settings(
        tmp_path,
        agent_backend="direct",
        pi_command="pi --api-key secret-value",
    )

    response = TestClient(
        create_app(settings=settings, services=object(), testing=True)
    ).get("/health/providers")

    assert response.status_code == 200
    assert response.json()["agent"] == {"backend": "direct"}
    assert "pi --api-key" not in response.text
    assert "secret-value" not in response.text
```

- [ ] **Step 5: Run the health test and verify RED**

Run:

```powershell
uv run pytest tests/api/test_provider_health.py -k agent_backend -q
```

Expected: failure because `agent` is absent.

- [ ] **Step 6: Add safe agent metadata**

Update the return value in `src/talkpath/api/provider_health.py`:

```python
return {
    "status": "ok" if healthy else "degraded",
    "agent": {"backend": settings.agent_backend},
    "providers": providers,
}
```

- [ ] **Step 7: Run targeted tests and verify GREEN**

Run:

```powershell
uv run pytest tests/test_config.py tests/api/test_provider_health.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit only Task 1 hunks**

Inspect and stage only the new agent-backend hunks because these files already contain unrelated work:

```powershell
git -c safe.directory=D:/python/TalkPath diff -- src/talkpath/config.py src/talkpath/api/provider_health.py tests/test_config.py tests/api/test_provider_health.py
git -c safe.directory=D:/python/TalkPath diff --cached --check
git -c safe.directory=D:/python/TalkPath commit -m "feat: add direct agent backend setting"
```

Before committing, verify `git diff --cached --name-only` lists only the four Task 1 files and the staged diff contains only agent-backend additions.

### Task 2: Route lesson import directly to Vision by default

**Files:**
- Modify: `src/talkpath/application/session_service.py`
- Modify: `tests/unit/test_session_service.py`
- Modify: `tests/api/test_import_flow.py`

- [ ] **Step 1: Add a Pi spy and failing direct-mode test**

Add to `tests/unit/test_session_service.py`:

```python
class PiMustNotRun:
    def __init__(self) -> None:
        self.started = 0
        self.prompted = 0

    @property
    def is_running(self) -> bool:
        return False

    async def start(self) -> None:
        self.started += 1

    async def prompt(self, message: str, **kwargs: object) -> object:
        self.prompted += 1
        raise AssertionError("Pi must not run in direct mode")


@pytest.mark.asyncio
async def test_direct_import_calls_vision_without_starting_pi(tmp_path: Path) -> None:
    pi = PiMustNotRun()
    vision = FakeVisionService()
    service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=LessonLensMarkdownRepository(tmp_path / "lessonlens"),
        vision_service=vision,
        text_service=FakeTextService(),
        speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(),
        agent_backend="direct",
        pi_client=pi,
        upload_root=tmp_path / "uploads",
    )
    session_id = service.create_session().session_id
    service.upload_image(session_id, b"book page", mime_type="image/png")
    service.confirm_scope(
        session_id,
        CourseScope(program="junior high", grade="7", subject="English", lesson="1", pages=["1"]),
    )

    result = await service.import_lesson(session_id, operation_id="direct-import")

    assert result.lesson.operation_id == "direct-import"
    assert pi.started == 0
    assert pi.prompted == 0
```

Import `CourseScope` in the test file.

- [ ] **Step 2: Run the direct test and verify RED**

Run:

```powershell
uv run pytest tests/unit/test_session_service.py::test_direct_import_calls_vision_without_starting_pi -q
```

Expected: failure because `agent_backend` is not accepted or Pi is still called.

- [ ] **Step 3: Make Pi optional and add one explicit branch**

Change `SessionService.__init__` and the import section in `src/talkpath/application/session_service.py`:

```python
def __init__(
    self,
    *,
    # existing repositories and provider arguments
    agent_backend: str = "direct",
    pi_client: PiBoundary | None = None,
    # existing upload arguments
) -> None:
    if agent_backend not in {"direct", "pi"}:
        raise ValueError(f"unsupported agent backend: {agent_backend}")
    if agent_backend == "pi" and pi_client is None:
        raise ValueError("pi_client is required when agent_backend='pi'")
    self.agent_backend = agent_backend
    self.pi_client = pi_client
```

Replace the unconditional Pi-first block in `import_lesson()` with:

```python
if self.agent_backend == "direct":
    draft = await self.vision_service.extract_lesson(
        trusted_images,
        scope,
        operation_id=operation_id,
    )
else:
    await self._start_pi_if_needed()
    assert self.pi_client is not None
    pi_result = await self.pi_client.prompt(
        self._import_prompt(scope, trusted_images),
        operation_id=operation_id,
        write_type=True,
        write_tool="extract_lesson",
        write_payload={
            "session_id": session_id,
            "operation_id": operation_id,
            "scope": scope.model_dump(mode="json"),
            "images": [image.model_dump(mode="json") for image in trusted_images],
        },
    )
    self._publish_agent_events(session, pi_result)
    draft = self._draft_from_pi_result(pi_result)
    if draft is None:
        draft = await self.vision_service.extract_lesson(
            trusted_images,
            scope,
            operation_id=operation_id,
        )
```

Guard `aclose()` and `_start_pi_if_needed()` with `if self.pi_client is None: return` before accessing Pi.

- [ ] **Step 4: Update import-flow fixtures to declare intent**

In `tests/api/test_import_flow.py`, make the existing Pi-event fixture explicit:

```python
service = SessionService(
    # existing arguments
    agent_backend="pi",
    pi_client=pi,
)
```

Add a production-shape direct test using a Pi spy and assert `pi.prompts == []`; retain the existing Pi-mode event test so both branches remain covered.

- [ ] **Step 5: Run import and session tests and verify GREEN**

Run:

```powershell
uv run pytest tests/unit/test_session_service.py tests/api/test_import_flow.py -q
```

Expected: direct tests pass without Pi calls and existing Pi-mode event tests pass.

- [ ] **Step 6: Confirm activities remain direct**

Run:

```powershell
uv run pytest tests/api/test_activity_flow.py tests/integration/test_textbook_to_activity.py -q
```

Expected: all pass. No implementation change is required because `ActivityService` already depends on `TextService`, not Pi.

- [ ] **Step 7: Commit only Task 2 hunks**

```powershell
git -c safe.directory=D:/python/TalkPath diff -- src/talkpath/application/session_service.py tests/unit/test_session_service.py tests/api/test_import_flow.py
git -c safe.directory=D:/python/TalkPath diff --cached --check
git -c safe.directory=D:/python/TalkPath commit -m "feat: use direct vision import by default"
```

Verify the staged diff does not include unrelated provider or speech changes.

### Task 3: Construct and close Pi only in Pi mode

**Files:**
- Modify: `src/talkpath/api/app.py`
- Modify: `tests/api/test_health.py`
- Modify: `tests/api/test_import_flow.py`

- [ ] **Step 1: Write a failing construction test**

Add a monkeypatch test to `tests/api/test_health.py`:

```python
def test_direct_app_does_not_construct_pi(monkeypatch, tmp_path):
    def fail_from_settings(*args, **kwargs):
        raise AssertionError("direct mode must not construct Pi")

    monkeypatch.setattr(PiRpcClient, "from_settings", fail_from_settings)
    settings = Settings(
        _env_file=None,
        agent_backend="direct",
        sqlite_path=tmp_path / "progress.sqlite",
        lessonlens_root=tmp_path / "lessonlens",
        upload_root=tmp_path / "uploads",
    )

    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/health").status_code == 200
```

Import `PiRpcClient` and `Settings` in the test module.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
uv run pytest tests/api/test_health.py::test_direct_app_does_not_construct_pi -q
```

Expected: `AssertionError` from `PiRpcClient.from_settings`.

- [ ] **Step 3: Construct Pi conditionally**

In `src/talkpath/api/app.py`, create the boundary before `SessionService`:

```python
pi_client = (
    PiRpcClient.from_settings(settings)
    if settings.agent_backend == "pi"
    else None
)
configured_service = SessionService(
    # existing repositories and providers
    agent_backend=settings.agent_backend,
    pi_client=pi_client,
    # existing upload settings
)
```

Track whether the service was internally created:

```python
owns_service = configured_service is None
```

For internally created services, register one shutdown handler for `configured_service.aclose`. Do not also register `providers.aclose`, because `SessionService.aclose()` already closes the four provider services:

```python
if owns_service:
    app.router.add_event_handler("shutdown", configured_service.aclose)
```

- [ ] **Step 4: Add Pi-mode construction coverage**

Add to `tests/api/test_health.py`:

```python
def test_pi_app_constructs_pi_once(monkeypatch, tmp_path):
    calls = []
    fake_pi = object()

    def from_settings(settings):
        calls.append(settings.agent_backend)
        return fake_pi

    monkeypatch.setattr(PiRpcClient, "from_settings", from_settings)
    settings = Settings(
        _env_file=None,
        agent_backend="pi",
        sqlite_path=tmp_path / "progress.sqlite",
        lessonlens_root=tmp_path / "lessonlens",
        upload_root=tmp_path / "uploads",
    )
    app = create_app(settings=settings)

    assert calls == ["pi"]
    assert app.state.session_service.pi_client is fake_pi
```

- [ ] **Step 5: Run API lifecycle tests and verify GREEN**

Run:

```powershell
uv run pytest tests/api/test_health.py tests/api/test_import_flow.py -q
```

Expected: all pass; direct construction never touches Pi and Pi mode constructs it once.

- [ ] **Step 6: Commit only Task 3 hunks**

```powershell
git -c safe.directory=D:/python/TalkPath diff -- src/talkpath/api/app.py tests/api/test_health.py tests/api/test_import_flow.py
git -c safe.directory=D:/python/TalkPath diff --cached --check
git -c safe.directory=D:/python/TalkPath commit -m "feat: isolate pi application lifecycle"
```

### Task 4: Add safe operation logs and preserve provider errors

**Files:**
- Modify: `src/talkpath/application/session_service.py`
- Modify: `tests/unit/test_session_service.py`
- Modify: `tests/integration/test_failure_recovery.py`

- [ ] **Step 1: Write failing safe-log tests**

Add a provider that raises a secret-bearing unknown exception and a test to `tests/unit/test_session_service.py`:

```python
class ExplodingVision(FakeVisionService):
    async def extract_lesson(self, *args, **kwargs):
        raise RuntimeError("secret-token full-provider-body")


@pytest.mark.asyncio
async def test_import_logs_safe_failure_context_without_exception_message(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = make_service(tmp_path, vision_service=ExplodingVision())
    session_id = service.create_session().session_id
    service.upload_image(session_id, b"private-image-bytes", mime_type="image/png")
    service.confirm_scope(
        session_id,
        CourseScope(program="junior high", grade="7", subject="English", lesson="1", pages=["1"]),
    )

    with caplog.at_level("ERROR", logger="talkpath.operations"):
        with pytest.raises(RepositoryError):
            await service.import_lesson(session_id, operation_id="safe-log-op")

    text = caplog.text
    assert "lesson_import_failed" in text
    assert session_id in text
    assert "safe-log-op" in text
    assert "RuntimeError" in text
    assert "session_service.py" in text
    assert "secret-token" not in text
    assert "full-provider-body" not in text
    assert "private-image-bytes" not in text
```

Extend the local `make_service` helper to accept `vision_service` and use direct mode.

- [ ] **Step 2: Run the safe-log test and verify RED**

Run:

```powershell
uv run pytest tests/unit/test_session_service.py::test_import_logs_safe_failure_context_without_exception_message -q
```

Expected: failure because no operation log exists.

- [ ] **Step 3: Implement safe traceback logging**

Add imports and a dedicated logger in `src/talkpath/application/session_service.py`:

```python
import logging
import time
import traceback

operation_logger = logging.getLogger("talkpath.operations")
```

Add a helper that excludes `str(error)` and all request/provider payloads:

```python
def _log_operation_failure(
    *,
    event: str,
    session_id: str,
    operation_id: str,
    agent_backend: str,
    stage: str,
    started_at: float,
    error: Exception,
) -> None:
    stack = "".join(traceback.format_tb(error.__traceback__))
    operation_logger.error(
        "%s session_id=%s operation_id=%s agent_backend=%s stage=%s "
        "elapsed_ms=%d error_type=%s\n%s",
        event,
        session_id,
        operation_id,
        agent_backend,
        stage,
        round((time.perf_counter() - started_at) * 1000),
        type(error).__name__,
        stack,
    )
```

At import entry set `started_at = time.perf_counter()` and update a local `stage` immediately before validation, Pi, Vision, identity validation, and save operations. In the existing `except Exception as exc` block call `_log_operation_failure(...)` before `_mark_failed`. Continue to re-raise `DomainError` unchanged; wrap only unknown exceptions in `RepositoryError("lesson import failed")`.

- [ ] **Step 4: Add provider-error mapping regression**

In `tests/integration/test_failure_recovery.py`, create the service with `agent_backend="direct"` and add/assert the existing Vision timeout/unavailable/invalid cases return their existing 504/503/502 codes rather than 500. The assertion remains:

```python
error(response, expected_status, expected_code, retryable=True)
```

- [ ] **Step 5: Run failure tests and verify GREEN**

Run:

```powershell
uv run pytest tests/unit/test_session_service.py tests/integration/test_failure_recovery.py -q
```

Expected: all pass; unknown errors produce safe stack locations and provider domain errors retain 502/503/504 mappings.

- [ ] **Step 6: Commit only Task 4 hunks**

```powershell
git -c safe.directory=D:/python/TalkPath diff -- src/talkpath/application/session_service.py tests/unit/test_session_service.py tests/integration/test_failure_recovery.py
git -c safe.directory=D:/python/TalkPath diff --cached --check
git -c safe.directory=D:/python/TalkPath commit -m "feat: log safe import failure context"
```

### Task 5: Retry failed imports through a fresh browser session

**Files:**
- Modify: `frontend/app.js`
- Modify: `tests/api/test_static_ui.py`

- [ ] **Step 1: Write a failing static contract test**

Add to `tests/api/test_static_ui.py`:

```python
def test_child_ui_failed_import_retry_creates_a_fresh_session() -> None:
    script = TestClient(create_app(testing=True)).get("/app.js").text
    retry_helper = _source_between(
        script,
        "  async function retryFailedImport() {",
        "  async function runImport() {",
    )

    assert "state.uploadFile" in retry_helper
    assert "state.confirmedScope" in retry_helper
    _assert_source_order(
        retry_helper,
        "createSessionAndUpload",
        "/scope",
        "connectWebSocket()",
        "runImport()",
    )
    assert 'setRetry("Try the lesson again", () => retryFailedImport())' in script
    assert 'setRetry("Try the lesson again", () => runImport())' not in script
```

- [ ] **Step 2: Run the static test and verify RED**

Run:

```powershell
uv run pytest tests/api/test_static_ui.py::test_child_ui_failed_import_retry_creates_a_fresh_session -q
```

Expected: failure because the retry helper and retained values do not exist.

- [ ] **Step 3: Retain only the required browser values**

Extend the frontend state in `frontend/app.js`:

```javascript
const state = {
  // existing fields
  uploadFile: null,
  confirmedScope: null,
};
```

In the course form submit handler, set `state.uploadFile = file` before upload. In the scope submit handler, calculate once and retain the payload:

```javascript
const confirmedScope = scopePayload(event.currentTarget);
const session = await api(`/api/sessions/${state.sessionId}/scope`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(confirmedScope),
});
state.confirmedScope = confirmedScope;
```

Clear both values in `resetForNewCourse()`.

- [ ] **Step 4: Implement fresh-session retry**

Place this helper before `runImport()`:

```javascript
async function retryFailedImport() {
  if (!state.uploadFile || !state.confirmedScope) {
    resetForNewCourse();
    showScreen("new-course");
    showError("#upload-error", "Choose the textbook image again to retry the lesson.");
    return;
  }
  try {
    showError("#processing-error", "");
    setRetry("Try again", null);
    await createSessionAndUpload(state.uploadFile);
    const session = await api(`/api/sessions/${state.sessionId}/scope`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.confirmedScope),
    });
    updateFromSession(session);
    connectWebSocket();
    await runImport();
  } catch (error) {
    updateStatus("FAILED");
    showError("#processing-error", error.message || "I could not restart that lesson yet.");
    setRetry("Try the lesson again", () => retryFailedImport());
  }
}
```

Replace both failure retry callbacks (HTTP catch and WebSocket processing failure) with:

```javascript
setRetry("Try the lesson again", () => retryFailedImport());
```

Wrap the retry helper's network path in `try/catch` so a retry setup failure stays on the processing screen, displays its message, and re-enables the same retry action.

- [ ] **Step 5: Run frontend contract and syntax checks**

Run:

```powershell
uv run pytest tests/api/test_static_ui.py -q
node --check frontend/app.js
```

Expected: all tests pass and Node exits 0.

- [ ] **Step 6: Commit Task 5**

```powershell
git -c safe.directory=D:/python/TalkPath add -- frontend/app.js tests/api/test_static_ui.py
git -c safe.directory=D:/python/TalkPath diff --cached --check
git -c safe.directory=D:/python/TalkPath commit -m "fix: retry imports with a fresh session"
```

### Task 6: Document direct startup and run full verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/PROGRESS.md`

- [ ] **Step 1: Document the default backend**

Add to `.env.example` near application settings:

```dotenv
# Default production path. Set to pi only for experimental Pi RPC mode.
TALKPATH_AGENT_BACKEND=direct
```

Update `README.md` startup instructions to use:

```powershell
cd D:\python\TalkPath
uv run uvicorn talkpath.api.app:create_app --factory --reload --host 127.0.0.1 --port 8001
```

State that direct mode does not require Pi CLI/login variables. Keep a separate opt-in Pi example; do not place API keys in command lines or documentation.

- [ ] **Step 2: Run focused Python regression**

Run:

```powershell
uv run pytest tests/test_config.py tests/unit/test_session_service.py tests/api/test_health.py tests/api/test_provider_health.py tests/api/test_import_flow.py tests/api/test_static_ui.py tests/integration/test_failure_recovery.py tests/integration/test_textbook_to_activity.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run full Python verification**

Run:

```powershell
uv run pytest -q
uv run python -m compileall -q src
```

Expected: pytest exits 0 with only documented live-test skips; compileall exits 0.

- [ ] **Step 4: Verify retained Pi compatibility and frontend syntax**

Run:

```powershell
npm test --prefix pi-extension
npm run typecheck --prefix pi-extension
node --check frontend/app.js
```

Expected: Pi extension tests, TypeScript typecheck, and JavaScript syntax checks all exit 0.

- [ ] **Step 5: Run a direct-mode local smoke without user images**

Start a temporary server process with `TALKPATH_AGENT_BACKEND=direct` on an unused local port, then request `/health` and `/health/providers`. Verify:

```text
/health -> 200 {"status":"ok"}
/health/providers -> 200 with "agent":{"backend":"direct"}
no pi-coding-agent child process exists for the temporary server
```

Do not call `/import` with a user textbook image. Live Vision verification remains behind `TALKPATH_LIVE_TESTS=1` and may still report the documented Z.ai HTTP 429.

- [ ] **Step 6: Update the sole progress handoff**

Append a dated section to `docs/PROGRESS.md` containing:

```markdown
## 16. 2026-08-12 direct API agent backend

- Implementation status and exact files changed.
- Targeted and full verification command results with pass/skip counts.
- Direct-mode local health smoke result and proof that no Pi child started.
- Remaining live limitations, including current Vision provider availability.
- Next development start point.
```

Only mark the feature complete if the code and verification evidence exist.

- [ ] **Step 7: Check scope and commit documentation hunks only**

Run:

```powershell
git -c safe.directory=D:/python/TalkPath diff --check
git -c safe.directory=D:/python/TalkPath status --short
```

Because README, `.env.example`, and `docs/PROGRESS.md` already contain other work, inspect the staged patch and include only direct-backend documentation hunks:

```powershell
git -c safe.directory=D:/python/TalkPath diff --cached --check
git -c safe.directory=D:/python/TalkPath commit -m "docs: document direct API runtime"
```

Expected: no whitespace errors; unrelated provider, speech, WAV, or user-owned changes remain unstaged.
