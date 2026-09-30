# TalkPath 第二期前置交接進度

更新日期：2026-08-13
狀態：第二期預設程式與 Direct API agent backend 已完成並通過全量回歸；focused lesson flow 自動化契約與回歸已通過，但內建瀏覽器受 Windows sandbox helper 阻塞，桌面／手機互動驗證仍為部分完成；Text 與 Kokoro TTS live 已通過，Qwen STT 仍需 spoken WAV 驗證，Vision live 仍受 Z.ai HTTP 429 阻塞。

## 來源文件

第一期交接已封存於：

D:/python/TalkPath/docs/PROGRESS-phase1-2026-08-11.md

目前第二期 implementation plan：

D:/python/TalkPath/docs/superpowers/plans/2026-08-11-provider-and-local-speech-implementation.md

第二期設計規格：

D:/python/TalkPath/docs/superpowers/specs/2026-08-11-provider-and-local-speech-design.md

本文件是第二期唯一的實作進度與交接來源；實際完成狀態以本文件的驗證證據為準。

## 1. 第二期目標

- Vision backend 可透過環境變數切換 fake、TalkPath HTTP、OpenAI-compatible 或其他相容 HTTP provider。
- Text backend 可透過環境變數切換不同模型服務。
- STT 以本地 HTTP service 為主。
- TTS 以本地 HTTP service 為主。
- 保留 fake provider，讓第一期測試維持可重現。
- 建立 provider health、秘密遮罩、live smoke test 與真實端到端測試入口。

## 2. 已確認的設計決策

### 2.1 Vision／Text

Provider registry 集中處理 backend 建構；application 只依賴既有 VisionService 與 TextService interface。供應商名稱、base URL、API key、model、timeout 與 request profile 都由 capability-specific 環境變數管理。

預計支援 backend：

- fake
- talkpath_http
- openai_compatible

GLM、ClinePass 或其他服務只透過 OpenAI-compatible 設定接入，不在程式碼中硬編碼供應商分支。

### 2.2 STT／TTS

本地語音服務採 local_http backend。TalkPath 只負責 HTTP 呼叫、timeout、錯誤分類、operation ID 與 domain model 轉換，不管理語音模型程序生命週期。

若未來某個本地模型只有 CLI，再另增加 local_process adapter；目前不納入本期切片。

### 2.3 測試策略

- fake、MockTransport 與 contract tests 在預設測試中執行。
- 真實 provider 與本地語音服務測試只有在 TALKPATH_LIVE_TESTS=1 時執行。
- 真實測試只驗證 schema、operation ID、音訊可用性與錯誤邊界，不對模型自然語言內容做 exact match。

## 3. 第二期 Task 進度

| Task | 項目 | 狀態 | 驗證證據 |
|---|---|---|---|
| 1 | capability-specific provider 設定模型與環境變數正規化 | 已完成 | src/talkpath/adapters/provider_profiles.py、src/talkpath/config.py、tests/unit/test_provider_profiles.py、tests/test_config.py；Task 1 測試 18 passed |
| 2 | ProviderRegistry 與 adapter 建構邊界 | 已完成 | src/talkpath/adapters/provider_registry.py、src/talkpath/adapters/http_model_services.py、src/talkpath/api/app.py、tests/unit/test_provider_registry.py；受影響範圍 33 passed |
| 3 | OpenAI-compatible Vision／Text adapter | 已完成 | src/talkpath/adapters/openai_compatible_services.py、tests/unit/test_openai_compatible_services.py；contract 31 passed，registry integration 後範圍 38 passed |
| 4 | local HTTP STT／TTS adapter | 已完成 | src/talkpath/adapters/local_speech_services.py、tests/unit/test_local_speech_services.py；adapter 14 passed，registry/activity 範圍 25 passed |
| 5 | provider health 與安全診斷資訊 | 已完成 | src/talkpath/api/provider_health.py、src/talkpath/api/app.py、tests/api/test_provider_health.py；health tests 4 passed |
| 6 | gated live provider／speech smoke tests | 部分完成 | Text／DeepSeek V4 Flash 與 Kokoro TTS live smoke 已通過；Qwen STT 已到達真實 endpoint，但 silent WAV 回空文字，仍需 spoken WAV；Vision／Z.ai 回 HTTP 429 |
| 7 | 真實 provider 到 speech 的端到端測試 | 部分完成 | tests/integration/conftest.py、tests/integration/test_real_provider_to_speech.py；測試入口已建立，仍受 Vision 429 與 STT spoken-WAV 驗證未完成阻塞 |
| 8 | README、環境範例與最終交接同步 | 已完成（預設驗證） | README.md、.env.example、docs/talkpath-progress.md、docs/PROGRESS.md；全量與 Pi extension 預設驗證已通過 |

## 4. 本次前置工作的驗證結果

- 已建立第二期設計規格，並確認 Vision／Text 可替換 backend 與 local HTTP STT／TTS 的邊界。
- 已建立第二期 implementation plan，包含逐 Task 的檔案範圍、TDD 步驟、驗證命令、live test gate 與最終驗收條件。
- 已封存第一期 fake-provider 進度，未覆寫第一期交接紀錄。
- Task 1 已修改 provider profile 與 Settings；尚未宣稱已接入實際模型、真實 Pi agent、瀏覽器自動化或實體音訊設備。
- Task 1 驗證：uv run pytest tests/test_config.py tests/unit/test_provider_profiles.py -q → 18 passed；正式分支基線 uv run pytest -q → 175 passed, 4 skipped。
- Task 2 驗證：uv run pytest tests/unit/test_provider_registry.py tests/unit/test_fake_services.py tests/unit/test_http_model_services.py tests/api/test_activity_flow.py -q → 33 passed。
- Provider registry lifecycle 驗證：uv run pytest tests/api/test_health.py -q → 2 passed；production app shutdown 會關閉 registry-owned provider resources。
- Task 3 驗證：uv run pytest tests/unit/test_openai_compatible_services.py tests/unit/test_http_model_services.py -q → 31 passed；registry/openai integration 範圍 → 38 passed。
- Task 3 DeepSeek 相容性補強：JSON mode 加入明確輸出指示與 Vision／grammar／activity／evaluation schema；uv run pytest tests/unit/test_openai_compatible_services.py -q → 12 passed。
- Task 4 驗證：uv run pytest tests/unit/test_local_speech_services.py -q → 14 passed；local adapter + registry + activity flow 範圍 → 25 passed。
- Task 5 驗證：uv run pytest tests/api/test_provider_health.py tests/api/test_health.py -q → 4 passed。
- Task 6 驗證：uv run pytest tests/live -q -rs → 4 skipped（TALKPATH_LIVE_TESTS 未啟用）；尚未執行真實網路服務測試。
- Task 7 驗證：uv run pytest tests/integration/test_real_provider_to_speech.py -q -rs → 1 skipped（TALKPATH_LIVE_TESTS 未啟用）；real provider → STT → TTS 未執行。
- Text live 驗證（2026-08-12）：$env:TALKPATH_LIVE_TESTS=1; uv run pytest tests/live/test_provider_smoke.py -k text -q -rs → 1 passed、1 deselected；DeepSeek grammar／activity／evaluate schema 與 operation flow 通過。
- Vision live 驗證（2026-08-12）：$env:TALKPATH_LIVE_TESTS=1; uv run pytest tests/live/test_provider_smoke.py -k vision -q -rs → 1 failed、1 deselected；Z.ai endpoint 回 HTTP 429，adapter 分類為 ProviderUnavailable，未輸出 API key。
- 最新外部設定稽核（2026-08-12）：本地 .env 已有 Vision 的 Z.ai／glm-4.6v 與 Text 的 DeepSeek／deepseek-v4-flash 設定；Vision live 實際送達 Z.ai 但回 HTTP 429，Text live 已通過，STT／TTS 仍為 fake。
- Task 8／最終驗證：uv run pytest → 227 passed, 9 skipped, 1 warning；npm test --prefix pi-extension → 9 passed；Pi typecheck、frontend JavaScript syntax check、Python compileall、git diff --check 均通過。

## 5. 已知限制與路徑

- 正式工作目錄：D:/python/TalkPath。
- 真實 Vision／Text provider 的實際 base URL、model 與供應商 response 差異，須在各環境透過 profile 設定並由 live contract test 驗證。
- 本地 STT／TTS 需依本文件與設計規格提供 /transcribe、/synthesize HTTP contract；TalkPath 不負責啟動服務。
- API key、圖片 base64、音訊 bytes、完整 prompt 與完整 provider response 不得進入 log、health response 或 UI。

## 6. Subagent 執行阻塞

- 已建立隔離 worktree：D:/python/TalkPath/.worktrees/provider-speech 與 D:/python/TalkPath/worktrees/provider-speech。
- 多個 subagent 嘗試在兩個 worktree 執行 Task 1；均無法可靠讀取或寫入專案檔案，最後回報 Windows sandbox helper 檔案系統錯誤。
- 主代理在同一專案可正常讀取檔案，且隔離 worktree 的 Python 基線為 175 passed、4 skipped；Pi extension 的 npm test 與 typecheck 也通過。
- Task 1 已由主代理在正式工作目錄 inline 完成；apply_patch helper 仍有 Windows sandbox 問題，本次以 unified diff + git apply 完成精確修改。
- 本次變更尚未建立獨立 commit；目前變更保留在 codex/phase2-provider-speech 分支。程式與預設驗證已完成，僅待提供真實 provider／local speech 設定後執行 live 驗證。
## 7. 下一個開發起點

歷史交接起點（已被後續 Section 10～17 取代）：當時規劃先處理 Vision 429，再配置 local STT／TTS。現況以 Section 17 最後的 `Next development start` 為準。
## 8. 2026-08-12 STT QwenASRMiniTool integration

- Update date: 2026-08-12.
- External project cloned to `D:/python/QwenASRMiniTool`, commit `f2467aa`; the TalkPath workspace remains `D:/python/TalkPath`.
- CPU isolated environment created at `D:/python/QwenASRMiniTool/.venv`; `requirements.txt` installed successfully; imports for `api_server`, `app`, and `webview_backend` passed.
- Startup smoke: `app_webview.py` launched in a hidden process for 8 seconds with no stdout/stderr error, then the exact smoke-test PID was stopped. No model weights are present; `ov_models` contains only `mel_filters.npy`, so real inference is not yet verified. The GUI does not automatically provide a usable model/API endpoint without model download and endpoint enablement.
- Qwen API contract verified against its real `TranscribeServer` implementation using a fake engine only: `/health` returned `{"status":"ok","model_ready":true}`; TalkPath sent multipart `file` plus `model`/`response_format=verbose_json`, Bearer authorization was accepted, and `verbose_json` segments became a TalkPath `Transcript`.
- TalkPath changes: local STT now supports `protocol=openai_transcription` and configurable `TALKPATH_STT_TRANSCRIBE_PATH`; Qwen path is `/v1/audio/transcriptions`. The legacy `/transcribe` contract remains unchanged. `.env.example` documents the required settings; the real `.env` and endpoint token were not changed.
- Verification: targeted provider/config tests `41 passed`; cross-project Qwen API + TalkPath adapter contract smoke passed. Full regression and actual model inference remain pending.
- Historical limitation (superseded by Sections 10–11): this entry was written before the Qwen model and endpoint became ready. Current remaining STT evidence gap is a real spoken WAV that produces non-empty recognition.
- Historical next step (superseded by Sections 11–17): Qwen endpoint configuration and Kokoro TTS integration were completed later. Use the final Section 17 next development start.
## 9. 2026-08-12 STT verification update

- Full Python regression: `231 passed, 9 skipped, 1 warning`.
- Pi extension regression: `npm test` reported `9 passed`; `npm run typecheck` passed.
- Python bytecode compilation: `uv run python -m compileall -q src` passed.
- Historical Task 6 status (superseded by Sections 10–11): adapter/contract verification was complete at this point; the later live endpoint reached model-ready state, leaving spoken-audio recognition evidence outstanding.

## 16. 2026-08-12 direct API agent backend

- Task 1 completed: added validated `TALKPATH_AGENT_BACKEND=direct|pi` with `direct` as the default, and added safe agent backend metadata to `/health/providers`.
- Task 1 verification: `uv run pytest tests/test_config.py tests/api/test_provider_health.py -q` returned `22 passed, 1 warning`; specification and code-quality reviews both approved the incremental change.
- Task 2 completed: lesson import now routes directly to `VisionService` by default without starting or prompting Pi; explicit `pi` mode retains Pi prompts, agent events, write payloads, and Vision fallback when Pi returns no draft. Pi is optional and its start/close paths are `None`-safe in direct mode.
- Task 2 verification: `uv run pytest tests/unit/test_session_service.py tests/api/test_import_flow.py -q` returned `10 passed`; `uv run pytest tests/api/test_activity_flow.py tests/integration/test_textbook_to_activity.py -q` returned `4 passed`. Independent specification and code-quality reviews both approved the implementation with no open findings.
- No Task 1 commit was created because the same files contain pre-existing uncommitted provider/speech integration work; forcing a file-level commit would mix scopes. The verified changes remain in `D:/python/TalkPath`.
- Task 3 completed: `create_app` constructs Pi only for explicit `pi` mode, injects the backend/client into `SessionService`, and registers exactly one shutdown close only for an internally created service. Externally injected services, including falsey objects, remain caller-owned; duplicate provider registry close registration was removed.
- Task 3 verification: TDD tests first exposed direct Pi construction, missing backend injection, incorrect lifecycle ownership, and falsey-service identity handling; `uv run pytest tests/api/test_health.py tests/api/test_import_flow.py -q` now returns `11 passed, 1 warning`. Independent specification and code-quality reviews approved with no open findings.
- Task 4 completed: lesson import failures emit safe operation metadata and traceback locations without exception messages or request/provider payloads. Client error events use a fixed safe message; log metadata is control-character-cleaned, length-limited, and JSON quoted to prevent multiline and same-line field injection.
- Task 4 verification: TDD safe-log and regression coverage passed; provider mappings remain timeout 504/retryable, unavailable 503/retryable, and invalid response 502/non-retryable. `uv run pytest tests/unit/test_session_service.py tests/integration/test_failure_recovery.py -q` returned `15 passed, 1 warning`. Specification and code-quality review loops approved with no remaining findings.
- Task 5 completed: failed browser imports retry through a new session by replaying the retained upload and confirmed scope. WebSocket identity guards, immutable local session IDs, monotonic flow generations, and retry ownership prevent stale socket/HTTP continuations, reset races, and duplicate retries from reviving a failed session. Successful import clears the retained File, scope, and file input.
- Task 5 verification: `uv run pytest tests/api/test_static_ui.py -q` returned `10 passed, 1 warning`; `node --check frontend/app.js` and targeted diff checks passed. Specification and code-quality review loops approved with no Critical or Important findings. Known non-blocking test gap: retry behavior is protected by source-shape static contracts rather than an executable DOM/mock fetch-WebSocket harness.
- Task 6 documentation and direct smoke completed: `.env.example` documents `TALKPATH_AGENT_BACKEND=direct` as the default production path; `README.md` uses `D:\python\TalkPath` and the uvicorn factory on `127.0.0.1:8001`, states that direct mode requires no Pi CLI/login variables, and keeps Pi as a separate credential-free opt-in example. Task 6 finalization changed `.env.example`, `README.md`, `docs/PROGRESS.md`, and the database-isolation contract in `tests/unit/test_sqlite_progress.py`.
- Task 6 focused verification: `uv run pytest tests/test_config.py tests/unit/test_session_service.py tests/api/test_health.py tests/api/test_provider_health.py tests/api/test_import_flow.py tests/api/test_static_ui.py tests/integration/test_failure_recovery.py tests/integration/test_textbook_to_activity.py -q` returned `59 passed, 1 warning`.
- Task 6 database-isolation test correction and quality follow-up: the initial `uv run pytest -q` result was `250 passed, 9 skipped, 1 failed, 1 warning`; the failing test incorrectly assumed `data/talkpath.sqlite` must not pre-exist instead of verifying repository path isolation. Root-cause diagnostics performed before the final test rewrite observed unchanged project DB SHA256/mtime. The final test does not inspect, read, hash, stat, modify, or delete the project DB: it spies on the adapter module's `sqlite3.connect`, delegates to the saved real connector, asserts `repo.database_path == tmp_path / "progress.sqlite"`, confirms the temporary DB exists, and verifies every resolved connection path is that temporary DB. Targeted `uv run pytest tests/unit/test_sqlite_progress.py::test_repository_does_not_use_project_database -q` returned `1 passed`; the focused Task 6 command returned `59 passed, 1 warning`; final `uv run pytest -q` returned `251 passed, 9 skipped, 1 warning`. `uv run python -m compileall -q src` exited 0. The `.env.example` local TTS URL stray trailing `#` was removed, and README contains the corrected single `the` wording.
- Retained Pi/frontend verification: `npm test --prefix pi-extension` returned `10 passed`; `npm run typecheck --prefix pi-extension` exited 0; `node --check frontend/app.js` exited 0.
- Direct local smoke: a temporary server was started with `TALKPATH_AGENT_BACKEND=direct` on unused port `49405`. `GET /health` returned HTTP 200 with `status=ok`; `GET /health/providers` returned HTTP 200 with `agent.backend=direct`. Its process tree had `pi_child_count=0`. Cleanup stopped only the exact temporary launcher/descendant PID tree (`5` processes) and verified `survivor_count=0`. No import, user image, or live Vision call was made.
- Completion status: **DONE_WITH_CONCERNS**. Direct API implementation, startup documentation, direct smoke, targeted regression, and full regression are verified. No commit was created because the shared dirty branch contains mixed pre-existing hunks and this task explicitly forbids committing them. Remaining non-blocking concerns are the gated live-service limitations and the Task 5 retry coverage relying on static source-shape contracts rather than an executable DOM/fetch-WebSocket harness.
- Remaining live limitations: Z.ai Vision remains blocked by HTTP 429; Qwen STT reached the real endpoint but the repository silent WAV produced empty text, so a spoken WAV is still required; Kokoro TTS live smoke has passed, but the full real provider-to-speech E2E remains incomplete.
- Next development start: verify Qwen STT with a real spoken WAV and resume the live provider-to-speech gate; Vision requires Z.ai availability/quota recovery. A future UI-hardening task can add an executable DOM/fetch-WebSocket retry harness.
## 10. 2026-08-12 Qwen model readiness recheck

- User completed QwenASRMiniTool model download.
- `GET http://<LAN-IP>:11435/health` returned `{"status":"ok","model_ready":true}`.
- The previously supplied two candidate tokens both returned HTTP 401 through Qwen's `?k=` authentication; they are treated as stale/invalid after the QwenASR restart. No token was written to TalkPath `.env`.
- Next step: obtain the current token from QwenASR's Endpoint page, then run the real STT upload smoke and configure the local TalkPath STT profile.
## 11. 2026-08-12 Qwen live STT endpoint verification

- The newly supplied QwenASR endpoint token was verified successfully: authenticated endpoint page returned HTTP 200; unauthenticated transcription returned HTTP 401; `/health` returned `model_ready=true`.
- Local TalkPath `.env` was configured with the Qwen endpoint, `local_http` backend, `openai_transcription` protocol, `/v1/audio/transcriptions` path, and the user-supplied token. The token is not recorded in this progress file.
- Real TalkPath STT smoke reached QwenASR and parsed a valid `Transcript` with matching operation ID, but the test failed its non-empty-text assertion because the repository fixture is a minimal silent/empty WAV (`Transcript.text == ""`, no segments). This does not establish speech recognition accuracy.
- Next step: run the same live smoke path with a real WAV containing spoken audio, then verify returned text/segments before claiming real STT inference complete.
## 12. 2026-08-12 Kokoro-FastAPI TTS smoke verification

- User started Docker container `kokoro-fastapi`; container was running with `0.0.0.0:8880->8880/tcp`.
- `GET /v1/audio/voices` returned 68 voices, including 8 Mandarin voices (`zf_xiaobei`, `zf_xiaoni`, `zf_xiaoxiao`, `zf_xiaoyi`, `zm_yunjian`, `zm_yunxi`, `zm_yunxia`, `zm_yunyang`).
- Real English synthesis succeeded with `af_bella`: HTTP 200, WAV output 171,630 bytes, RIFF/WAVE header.
- Real Mandarin synthesis succeeded with `zf_xiaobei`: HTTP 200, WAV output 162,874 bytes, RIFF/WAVE header.
- The initial 422 was caused by PowerShell JSON escaping in the test command; sending a UTF-8 JSON file succeeded. This was a test-command issue, not a Kokoro service issue.
- TalkPath `.env` was not changed. TalkPath TTS still uses the existing `/synthesize` contract; Kokoro uses `/v1/audio/speech`, so a generic OpenAI speech protocol adapter remains to be implemented before claiming TalkPath TTS integration complete.
- Generated WAV evidence is retained at `D:/python/TalkPath/kokoro-smoke.wav` and `D:/python/TalkPath/kokoro-chinese-smoke.wav`.
## 13. 2026-08-12 Kokoro TTS TalkPath integration

- Design/spec and implementation plan: `docs/superpowers/specs/2026-08-12-kokoro-tts-design.md` and `docs/superpowers/plans/2026-08-12-kokoro-tts-implementation.md`; both completed before implementation.
- TalkPath now supports a generic TTS `openai_speech` protocol in the existing local HTTP adapter. Legacy `/synthesize` behavior remains covered and unchanged.
- New TTS settings: `TALKPATH_TTS_PROTOCOL`, `TALKPATH_TTS_SPEECH_PATH`, `TALKPATH_TTS_VOICE`, `TALKPATH_TTS_RESPONSE_FORMAT`, and `TALKPATH_TTS_SPEED`. Local `.env` currently points to the user's running Kokoro-FastAPI Docker service at `http://127.0.0.1:8880`; no TTS secret is configured.
- Real live verification: `$env:TALKPATH_LIVE_TESTS=1; uv run pytest tests/live/test_local_speech_smoke.py -k tts -q -rs` → `1 passed, 1 deselected`. The adapter sent OpenAI Speech JSON and received non-empty `audio/*` bytes from Kokoro.
- Targeted regression: `46 passed`. Full Python regression: `236 passed, 9 skipped, 1 warning`. Pi extension: `9 passed`; typecheck, compileall, and diff check passed.
- Current integrated TTS profile: backend `local_http`, model `kokoro`, protocol `openai_speech`, path `/v1/audio/speech`, voice `af_bella`, response format `wav`, speed `0.9`.
- Remaining project limitations: Qwen STT live smoke still needs a real spoken WAV rather than the repository's silent fixture; Vision live remains blocked by Z.ai HTTP 429; full real provider-to-speech E2E is therefore not yet complete.
## 14. 2026-08-12 import startup diagnosis

- User-reported browser flow reached session creation, image upload, scope confirmation, and WebSocket connection successfully; only `POST /api/sessions/{session_id}/import` returned HTTP 500.
- Root cause: the runtime environment has no `pi` command in PATH, while the repository-local Pi CLI is installed at `pi-extension/node_modules/@earendil-works/pi-coding-agent/dist/cli.js`. The failure occurred before the Vision provider call.
- Pi extension now reads `TALKPATH_API_BASE_URL` for its loopback API base URL; this is required when TalkPath runs on port 8001 because the previous default was port 8000.
- Verification: Pi RPC start/close smoke passed with the repository-local CLI; Pi extension targeted tests `10 passed`; TypeScript typecheck passed.
- Current safe startup requirement: start uvicorn with `TALKPATH_PI_COMMAND` pointing to the local CLI and `TALKPATH_API_BASE_URL=http://127.0.0.1:8001`. No fallback was added that would silently redirect textbook images to a different external Vision destination.

## 15. 2026-08-12 Pi provider authentication diagnosis

- A second real browser import still returned HTTP 500 after the local Pi CLI path was configured.
- Layered verification showed that Pi process startup and `new_session` succeed, but the first prompt fails with `PiCommandFailed: No API key found for the selected model` when Pi is started without provider credentials.
- Pi's local auth file is empty (`~/.pi/agent/auth.json` contains `{}`). TalkPath's `TALKPATH_TEXT_API_KEY` setting is loaded from `.env` by Pydantic but is not automatically exported to the Pi child process as `DEEPSEEK_API_KEY`.
- Pi's built-in catalog contains `deepseek/deepseek-v4-flash`, matching the configured TalkPath text model. A minimal no-image prompt returned a `PromptResult` after injecting the existing TalkPath text key as `DEEPSEEK_API_KEY` and starting Pi with `--provider deepseek --model deepseek-v4-flash`.
- Required startup addition: populate `DEEPSEEK_API_KEY` without printing it, and include the explicit DeepSeek provider/model flags in `TALKPATH_PI_COMMAND`. Restart uvicorn and create a new lesson because failed sessions cannot resume the import transition.
- Vision remains configured as Z.ai `glm-4.6v`; provider health reports it configured but does not perform a live availability check. The previously recorded Z.ai HTTP 429 may still block image extraction after Pi authentication is fixed.
## 17. 2026-08-12 direct backend observability review fixes

- Finding 1 completed: extracted secret-safe operation logging to `src/talkpath/application/safe_observability.py`. Session activity orchestration, direct Text generation/evaluation (including internal-tool paths), STT, and TTS now record safe event/session-or-lesson/operation/backend/stage/elapsed/error-type/traceback-location metadata without exception messages or provider/request payloads.
- Unknown Text/STT/TTS exceptions are wrapped with fixed-message `OperationFailed`, mapped to HTTP 500 with `code=operation_failed` and `retryable=false`; existing provider `DomainError` instances remain unchanged, preserving timeout 504, unavailable 503, invalid-response 502, and their retryability mappings. Session activity failure still emits the fixed subscriber message `activity generation failed` and transitions the session to `FAILED`.
- TDD evidence: `tests/unit/test_direct_observability.py` initially returned `5 failed` for the missing logging/wrapping behavior, then returned `5 passed` after the implementation. Focused observability, session, activity, API/internal-tool, and failure-recovery regression returned `36 passed, 1 warning`.
- Finding 2 completed: README Pi opt-in examples now set `TALKPATH_PI_COMMAND` to only the base executable/CLI tokens (`pi`, or the documented repo-local Node CLI). README states that `PiRpcClient` parses those tokens with `shlex` and automatically appends RPC/no-session/no-builtins/extension flags.
- Finding 3 completed: `docs/talkpath-progress.md` now defines direct Vision/Text calls as the production default, marks Pi RPC as experimental explicit opt-in compatibility, updates the normal/MVP flows, records the 2026-08-12 superseding decision, and synchronizes Kokoro/Qwen live limitations.
- Verification: the final main-agent gate returned full Python regression `262 passed, 9 skipped, 1 warning`; Pi extension `10 passed`; TypeScript typecheck, frontend JavaScript syntax check, Python compileall, and `git diff --check` exited 0.
- Path/branch limitation: work remains in the shared dirty `D:/python/TalkPath` worktree and no commit was created. The sandbox `apply_patch` helper repeatedly failed with `windows sandbox: helper_unknown_error`; scoped unified diffs were used, and the UTF-8 documentation candidate was copied back only after diff/stat and contradiction checks.
- Known concerns: live Z.ai Vision remains blocked by HTTP 429; Qwen STT still needs a real spoken WAV; browser retry still lacks an executable DOM/fetch-WebSocket harness. These are unchanged from the prior handoff and are outside this review-fix scope.
- Spec-gap follow-up: observability backend metadata now follows the configured `direct|pi` backend throughout SessionService and ActivityService. SessionService injects its backend into default ActivityService construction; direct ActivityService construction remains backward-compatible with `direct` default and validates both supported values. Public STT/TTS routes pass the real session ID to optional service context parameters; internal calls use the safe `internal` fallback.
- Spec-gap TDD evidence: the new backend/session-context cases initially produced `6 failed, 3 passed`; after implementation `tests/unit/test_direct_observability.py -q` returned `9 passed, 1 warning`. Final focused regression returned `40 passed, 1 warning`; Python compileall and `git diff --check` exited 0.
- Quality follow-up TDD evidence: the operation-mapping/error-type tests produced 7 failed, 3 passed before implementation and then passed. Final focused activity/speech/import/provider regression returned 46 passed, 1 warning. Unknown failures are 500/non-retryable while explicit provider unavailable remains 503/retryable. error_type is control-character-cleaned and JSON-quoted; the dynamic exception class-name injection regression passed.
- Vision-import follow-up: a non-domain Vision exception now remains secret-safe in logs and is wrapped as fixed-message `OperationFailed("lesson import failed")`, producing HTTP 500 / `operation_failed` / `retryable=false`; explicit Vision provider errors and repository `DomainError` instances remain unchanged. TDD evidence was `3 failed, 13 passed` before the fallback change and `16 passed, 1 warning` after correcting the expected non-retryable contract.
- Final review: the cross-task specification reviewer, code-quality reviewer, and final integrated code reviewer approved the Direct API backend with no remaining Critical or Important findings. Unknown Vision/Text/STT/TTS failures consistently return fixed-message HTTP 500 / `operation_failed` / `retryable=false`; classified provider and repository `DomainError` mappings remain unchanged.
- Final main-agent verification (2026-08-12): `uv run pytest -q` returned `262 passed, 9 skipped, 1 warning`; `uv run python -m compileall -q src`, `npm run typecheck --prefix pi-extension`, `node --check frontend/app.js`, and `git diff --check` exited 0; `npm test --prefix pi-extension` returned `10 passed`.
- Next development start: run the real spoken-WAV Qwen STT verification and resume the full provider-to-speech E2E gate when Vision availability permits.
## 18. 2026-08-13 focused lesson flow

- Completion status: **PARTIAL / DONE_WITH_CONCERNS**. The focused lesson-flow implementation and automated gates are verified, but the required desktop and mobile in-app Browser interaction pass could not run.
- Exact focused UI files present in the shared dirty worktree: `frontend/index.html`, `frontend/styles.css`, `frontend/app.js`, `frontend/screen-flow.js`, `frontend/test/screen-flow.test.cjs`, and `tests/api/test_static_ui.py`. The final review follow-up changed `frontend/app.js`, `frontend/index.html`, `frontend/styles.css`, `tests/api/test_static_ui.py`, and this Section 18 handoff; no backend/provider code and no lesson-editing behavior were changed.
- Final static regression: the new test enforces that `runImport` contains no overview transition and orders `state.lesson = result.lesson` before `renderLessonPreview(result.lesson)` before `showScreen("preview")`; the overview action must order the exact lesson guard before card rendering before `showScreen("overview")`. The first isolated run was coverage-first GREEN because the existing implementation already satisfied the contract: `1 passed, 1 warning`.
- Focused verification: `uv run pytest tests/api/test_static_ui.py tests/api/test_import_flow.py tests/integration/test_failure_recovery.py -q` returned `31 passed, 1 warning`; `node --test frontend/test/screen-flow.test.cjs` returned `3 passed, 0 failed`; `node --check frontend/app.js` and `node --check frontend/screen-flow.js` exited 0.
- Full verification: `uv run pytest -q` returned `269 passed, 9 skipped, 1 warning`; `uv run python -m compileall -q src` exited 0; `npm test --prefix pi-extension` returned `10 passed`; `npm run typecheck --prefix pi-extension` exited 0; full `git diff --check` exited 0.
- Browser attempt: port `8001` was already occupied by pre-existing PID `31828`, so a temporary direct/fake-only server was started on unused `127.0.0.1:49795` with Vision, Text, STT, and TTS explicitly forced to `fake`. Startup readiness reached HTTP 200. A harmless generated 1x1 PNG in the temporary run directory was reserved for upload; no live Vision or external image service was called.
- Browser limitation: the required Browser runtime failed during initial connection with `windows sandbox failed: helper_unknown_error: setup refresh had errors`, before a tab or page interaction became available. Per the Browser skill, no standalone/external Playwright substitution was used. Therefore desktop 1280x800 and mobile 390x844 visibility, upload/back/resubmit/import/preview/practice/return flow, console errors, horizontal overflow, one-column preview, card usability, below-fold screen leakage, and reduced-motion behavior remain unverified by an executable browser in this pass.
- Temporary server cleanup: stopped only the exact process tree rooted at launcher PID `38344` (`38344,29436,6816,31716,19412`); verification reported `SURVIVOR_COUNT=0` and `PORT_LISTENER_COUNT=0` for port `49795`. The validated temporary run directory and generated PNG/logs were deleted (`TEMP_DIR_EXISTS=False`); the unrelated pre-existing server on port `8001` was not touched.
- Known executable integration limitation: retry and success-path browser behavior still relies on static source-shape contracts rather than an executable DOM/fetch-WebSocket harness, and this pass could not close that gap because the in-app Browser runtime was unavailable.
- Important review follow-up A completed: `navigationEpoch` is independent of `flowGeneration`; explicit navigation invalidates scope/import/activity/answer/speech owners without clearing the retained upload/session on Step 2 Back. Scope confirmation guards every post-await mutation and its `finally`; import cannot replace an explicitly selected screen; activity and answer requests are latest-owner-wins; speech captures the originating session/epoch, stops an active recorder on navigation, and suppresses stale callback/error/finally mutations. Retry creates a fresh generation and navigation epoch while retaining its existing replay and WebSocket identity semantics.
- Important review follow-up B completed: Preview now renders semantic read-only scope and source-count summaries, and Practice Hub renders the current lesson title plus concise scope context. Values come only from the existing serialized `LessonDraft` (`title`, `scope`, and `source_images.length`); source identifiers, paths, bytes, provider/model metadata, and editing controls are not rendered. Wrapping/min-width styles cover long context on responsive layouts.
- TDD evidence for the follow-up: the new ownership/navigation and safe-context regressions initially returned `2 failed` because the owner helper and context renderer/DOM were absent; after implementation they returned `2 passed, 17 deselected, 1 warning`. Updated full static UI coverage returned `19 passed, 1 warning`.
- Follow-up focused verification: `uv run pytest tests/api/test_static_ui.py tests/api/test_import_flow.py tests/integration/test_failure_recovery.py tests/api/test_activity_flow.py tests/integration/test_textbook_to_activity.py -q` returned `37 passed, 1 warning`; `node --test frontend/test/screen-flow.test.cjs` returned `3 passed, 0 failed`; both JavaScript syntax checks exited 0.
- Follow-up full verification: `uv run pytest -q` returned `271 passed, 9 skipped, 1 warning`; Python compileall, Pi TypeScript typecheck, and full `git diff --check` exited 0; Pi tests returned `10 passed`.
- Cross-operation race follow-up completed: `generateActivity` calls `invalidatePracticeAttempt()` after validating lesson/session but before creating the new activity owner or changing visible request state. The helper nulls `answerOwner` and `speechOwner`, clears the shared recorder reference, and only then calls `stop()` on a recording recorder, so Activity B and Retry audio activity make Activity A answer/speech callbacks owner-stale before a synchronous or asynchronous stop callback can run.
- Cross-operation TDD evidence: the new source-order regression initially failed because `invalidatePracticeAttempt()` was absent; after the minimal production change the isolated ownership regression returned `1 passed, 1 warning`. The refreshed focused command remained `37 passed, 1 warning`; Node controller remained `3 passed`; both syntax checks and `git diff --check` exited 0.
- Cross-operation full verification: `uv run pytest -q` returned `271 passed, 9 skipped, 1 warning`; Python compileall and Pi TypeScript typecheck exited 0; Pi tests returned `10 passed`; final full `git diff --check` exited 0.
- Browser status remains **PARTIAL / DONE_WITH_CONCERNS**: no executable browser evidence was added because the in-app Browser runtime remains unavailable from the recorded Windows sandbox helper failure, and no external Playwright substitute was used. The static source-shape limitation therefore remains documented.
- Next development start: when the in-app Browser runtime is available, rerun the complete desktop and mobile fake-provider flow described above and record measured viewport/overflow/reduced-motion/console evidence here. After UI evidence is complete, resume the existing spoken-WAV Qwen STT and Vision/provider-to-speech live gates when their external prerequisites are available.
- Final quality review (2026-08-13): uv run pytest -> 271 passed, 9 skipped, 1 warning; node --test frontend/test/screen-flow.test.cjs -> 3 passed; npm test --prefix pi-extension -> 10 passed; npm run typecheck --prefix pi-extension -> exit 0; python -m compileall -q src tests -> exit 0; node --check frontend/app.js and frontend/screen-flow.js -> exit 0; git diff --check -> clean; git diff --stat -> 24 files, +2332/-339. Pending: browser manual verification (partial, sandbox blocked); remove or gitignore untracked kokoro-smoke.wav / kokoro-chinese-smoke.wav before commit.
## 19. 2026-08-13 openai-compatible vision schema mismatch fix (import 502)

- User report: `POST /api/sessions/{session_id}/import` returned HTTP 502; the detail was `openai-compatible vision response does not match schema` (`ProviderResponseInvalid` -> 502 / provider_response_invalid / retryable=false).
- Root cause reproduced against the real Z.ai endpoint (`https://api.z.ai/api/coding/paas/v4`, model `glm-4.6v`) using the actual textbook image retained from the failing session at `data/uploads/b8328605-0a25-4825-ab28-9c488b1ca95c/image-b654b86cf90e4c42a08276b8b119ed38.png`. The model JSON failed `LessonDraft.model_validate` for three reasons: `passage` was `null`; `extraction_status` was `"completed"` (allowed: draft/reviewed/published); `content_items` were flat vocabulary cards (`item_number`/`english`/`chinese`/`notes`) instead of `ContentItem` objects (`content_id`/`type`/`content`).
- Fix (TDD): `_VISION_OUTPUT_INSTRUCTION` in `src/talkpath/adapters/openai_compatible_services.py` now specifies the exact `content_items` entry shape, string requirements for `title`/`passage`, and the allowed `extraction_status` values. The adapter gained `_normalize_vision_payload`: explicit `passage: null` becomes `""`, unrecognized `extraction_status` becomes `"draft"`, and non-conforming word/translation cards (non-blank `english` plus optional `chinese`/`notes`) map into `ContentItem(type="vocabulary", content={english, chinese, notes})` with deterministic `content_id` (`content-N`). Entries that fit neither shape still raise `ProviderResponseInvalid`; no provider data is silently dropped.
- TDD evidence: the new tests (`test_vision_normalizes_common_provider_schema_variations`, `test_vision_rejects_content_item_that_cannot_be_mapped`, plus prompt-contract assertions in the existing vision test) initially failed and now pass. `tests/unit/test_openai_compatible_services.py` -> `14 passed`.
- Live end-to-end verification (2026-08-13): a real Z.ai call through `OpenAICompatibleVisionService` with the failed session's actual PNG parsed `LessonDraft` successfully (title `Lesson 1`, 30 vocabulary `content_items` with english/chinese, `extraction_status=draft`, `passage=""`). With the improved prompt the model returned conforming `content_id`/`type`/`content` items directly; the normalization remains as a fallback for non-conforming output.
- Regression: focused openai/import/session/observability/failure-recovery -> `45 passed, 1 warning`; full `uv run pytest -q` -> `273 passed, 9 skipped, 1 warning`; `uv run python -m compileall -q src tests` exited 0.
- Files changed: `src/talkpath/adapters/openai_compatible_services.py`, `tests/unit/test_openai_compatible_services.py`, `docs/PROGRESS.md`.
- Notes: the failing session `b8328605-...` remains in `FAILED` state in `data/talkpath.sqlite` with its upload retained; a failed import still requires a new session (unchanged behavior). The live Z.ai Vision call for this image now returns HTTP 200, so the previously recorded Z.ai HTTP 429 limitation no longer blocks this particular flow.
- Next development start: rerun the desktop/mobile browser lesson flow (previously blocked by the in-app Browser runtime) now that a real Vision import can succeed; then resume the spoken-WAV Qwen STT and provider-to-speech E2E gates when their external prerequisites are available.
## 20. 2026-08-13 import timeout + provider identity hardening (Z.ai)

- User report: after the schema fix, `POST /api/sessions/{session_id}/import` failed again, this time with a timeout (`ProviderTimeout` -> HTTP 504).
- Timeout root cause: the real Z.ai `glm-4.6v` vision call is slow and variable; measured 58s/72s/80s/65s across runs with one >120s spike. `data/talkpath.sqlite` shows the user's retry session `362ee87b-...` created at `01:02:41Z` and marked FAILED ~121s later, matching exactly `TALKPATH_PROVIDER_TIMEOUT_SECONDS=120`. The code/Settings default and `.env.example` were both 20s, far below the provider's real latency.
- Timeout fix: `TALKPATH_PROVIDER_TIMEOUT_SECONDS` raised 120 -> 300 in `.env` and `.env.example` (with a vision-latency comment); `Settings.provider_timeout_seconds` default 20 -> 120; adapter fallback constants (`DEFAULT_OPENAI_TIMEOUT`, `DEFAULT_PROVIDER_TIMEOUT`, `DEFAULT_LOCAL_SPEECH_TIMEOUT`) 20 -> 120; `tests/test_config.py` default assertion updated; README documents the timeout and the 60-120s+ vision latency budget.
- Second bug found during live verification (same family): one Z.ai run invented `source_images: ["lesson1_image"]`; the adapter only `setdefault`'d `source_images`, so the bogus ID reached the save step and failed with `SourceImageNotApprovedError` (HTTP 500 `repository_error`, `stage="save"`, `elapsed_ms=91097`). Fix: `OpenAICompatibleVisionService.extract_lesson` now forces `source_images` to the real uploaded image IDs and forces `extraction_status` to `"draft"` (an import-time draft is never published); `title: null` and `passage: null` coerce to `""` as defensive normalization. Provider-invented identity can no longer reach the repository.
- TDD evidence: new `test_vision_uses_real_upload_identity_and_draft_status` and extended `test_vision_normalizes_common_provider_schema_variations` (title/passage null + `completed` status + vocab cards) initially failed then passed; `tests/unit/test_openai_compatible_services.py` -> `15 passed`; focused config/adapter -> `33 passed`; full `uv run pytest -q` -> `274 passed, 9 skipped, 1 warning`; `compileall` and `git diff --check` exit 0.
- Live verification (2026-08-13): full API import through the running server with the real textbook PNG succeeded in 60-65s (HTTP 200, state `ASK_GENERATE_ACTIVITY`, 30 vocabulary `content_items`, `source_images` = real uploaded ID, `extraction_status=draft`). One earlier verification import correctly failed at save before the identity fix, confirming the repro.
- Server operations: `--reload` on this Windows setup does NOT actually restart the uvicorn worker (WatchFiles logs `Reloading...` but the worker process keeps serving stale code; confirmed twice). The server now runs WITHOUT `--reload`, launched hidden via `D:\python\TalkPath\.venv\Scripts\python.exe -m uvicorn talkpath.api.app:create_app --factory --host 127.0.0.1 --port 8001`, with logs at `data/uvicorn-8001.{out,err}.log`. Future code changes require a manual restart; do not rely on `--reload`.
- Current running server verified: `/health` returns 200; `/health/providers` shows vision `openai_compatible`/`glm-4.6v`, agent `direct`; `Settings` reads `provider_timeout_seconds=300.0` from `.env`.
- Server stopped on user request (2026-08-13): the background uvicorn started for verification was terminated; port 8001 has no listener and no uvicorn process remains. Logs from that run remain at `data/uvicorn-8001.{out,err}.log`. Manual start command if needed: `D:\python\TalkPath\.venv\Scripts\python.exe -m uvicorn talkpath.api.app:create_app --factory --host 127.0.0.1 --port 8001` (run from `D:\python\TalkPath`; no `--reload`).
- Notes: sessions `b8328605-...` and `362ee87b-...` remain FAILED (a failed import requires a new session). The last successful import also saved a real lesson under `data/lessonlens/curricula/...`.
- Plan finalization commit (2026-08-13): the accumulated phase2 provider/speech, direct API backend, focused lesson-flow, and vision/timeout work was committed on branch `codex/phase2-provider-speech` as `c61b0cd` (42 files, +5574/-342); working tree is clean. The temporary uvicorn log files and the Kokoro smoke WAV artifacts were removed before commit; `.env` remains untracked/ignored.
- Next development start: retry the real browser lesson flow with a new session — import should now succeed within ~60-120s; then resume the spoken-WAV Qwen STT and provider-to-speech E2E gates.
## 21. 2026-08-13 extracted-data persistence verification + flashcard preview

- 結論（Q1）：提取後的課程內容**有實際持久化**，但依規格分兩處存放，不是全部寫入 SQLite。`docs/talkpath-progress.md`（4.6）明確定義「學習進度：第一版使用 SQLite，與 LessonLens 課程資料分離」；課程內容由 `LessonRepository` 寫入 LessonLens Markdown（`data/lessonlens/curricula/...`），SQLite 只存 session 狀態、lesson_id、上傳圖片引用、作答 attempt 與 review item。
- Q1 實證（僅讀取、未修改資料）：`data/talkpath.sqlite` 的 `learning_sessions` 含成功匯入的 session（例如 `1b3902ca-...` state=READY_FOR_PRACTICE、`18ea0465-...` READY_FOR_PRACTICE）、`attempts` 2 筆、`review_items` 1 筆；`data/lessonlens/curricula/junior-high/grade-7/english/lesson-01/` 有 `lesson.md`、`vocabulary/1.md`…`vocabulary/30.md`、`sources/` 與 `activities/`，30 張單字的實際內容（english/chinese）都寫在 LessonLens 檔案中。
- Q2 實作：preview 由原本「type + JSON 字串」條列改為單字卡 deck。`frontend/index.html` 的 `#lesson-content-items` 清單換成 `#lesson-cards`（`#card-stage` + `#card-prev/#card-next/#card-counter`）；`frontend/app.js` 新增 `previewDeck` 與 `renderCardAt/buildVocabularyCard/buildGrammarCard/buildNoteCard`；`frontend/styles.css` 新增 3D 翻面單字卡、文法卡與導覽列樣式，並在 reduced-motion 停用翻面動畫。
- 單字卡：正面英文大字（Vocabulary + Tap to flip），點擊翻面顯示中文與 notes；一次一張、上/下張按鈕與「X / N」計數；button + `aria-pressed`，鍵盤可操作。
- 文法建議（目前 extraction 尚無 grammar item）：grammar 用「規則卡」呈現——pattern（句型公式）+ explanation（一句兒童友善說明）+ examples（2-3 組英文例句與中文翻譯）；renderer 已支援 `content = {pattern, explanation, examples}`（examples 為字串陣列或 `{en, zh}` 物件），待 Vision prompt 加入文法萃取後即可直接顯示。
- 驗證：`node --check frontend/app.js` 與 `node --check frontend/screen-flow.js` exit 0；`node --test frontend/test/screen-flow.test.cjs` 3 passed；新增 `test_child_ui_preview_uses_flashcard_deck_and_grammar_cards`（來源形狀契約），`uv run pytest tests/api/test_static_ui.py -q` 20 passed；全量 `uv run pytest -q` 275 passed、9 skipped、1 warning；`git diff --check` 乾淨。
- 變更檔案：`frontend/index.html`、`frontend/app.js`、`frontend/styles.css`、`tests/api/test_static_ui.py`、`docs/PROGRESS.md`。未 commit（沿用既有未提交工作樹狀態）。
- 待辦：Vision prompt 目前只產出 vocabulary；若要顯示文法卡，需在 `_VISION_OUTPUT_INSTRUCTION` 增加 grammar content shape（`{pattern, explanation, examples}`）並用真實課本圖片重跑 import 驗證。瀏覽器手動驗證仍待 in-app Browser 可用後執行。
- Next development start: 若採用文法卡建議，先更新 Vision prompt 允許 grammar item 並以真實課本圖片重跑 import；之後依 Section 18/19/20 續跑瀏覽器流程與 live STT/TTS gates。
