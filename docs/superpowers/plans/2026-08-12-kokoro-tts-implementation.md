# Kokoro-FastAPI TTS Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, with review checkpoints.

**Goal:** Add a protocol-configurable OpenAI Speech TTS path so TalkPath can use the running Kokoro-FastAPI service without breaking the existing local `/synthesize` contract.

**Architecture:** Extend the capability profile only with TTS speech settings. Keep `LocalHttpTextToSpeechService` as the boundary and branch by protocol: legacy TalkPath JSON or OpenAI Speech JSON/raw-audio. The registry passes normalized settings; domain/application interfaces remain unchanged.

**Tech Stack:** Python 3.12, Pydantic Settings, httpx MockTransport, pytest, existing Kokoro-FastAPI Docker service.

---

### Task 1: TTS profile and configuration

**Files:**
- Modify: `src/talkpath/adapters/provider_profiles.py`
- Modify: `src/talkpath/config.py`
- Test: `tests/test_config.py`
- Test: `tests/unit/test_provider_profiles.py`

- [x] Add a failing test that sets `TALKPATH_TTS_PROTOCOL=openai_speech`, `TALKPATH_TTS_SPEECH_PATH=/v1/audio/speech`, `TALKPATH_TTS_VOICE=af_bella`, `TALKPATH_TTS_RESPONSE_FORMAT=mp3`, and `TALKPATH_TTS_SPEED=0.9`, then asserts the normalized TTS profile contains those values.
- [x] Run the focused tests and confirm failure because the fields do not exist.
- [x] Add normalized `speech_path`, optional `voice`, `response_format`, and positive `speed` to `ProviderProfile`; add corresponding TTS Settings fields and pass them only for the TTS profile.
- [x] Run `uv run pytest tests/test_config.py tests/unit/test_provider_profiles.py -q` and confirm all pass.

### Task 2: OpenAI Speech adapter behavior

**Files:**
- Modify: `src/talkpath/adapters/local_speech_services.py`
- Test: `tests/unit/test_local_speech_services.py`

- [x] Add a failing MockTransport test for `protocol="openai_speech"` that expects `/v1/audio/speech`, `input`, `model`, configured voice, `response_format`, and `speed`, then parses raw `audio/wav` into `AudioArtifact` with the original operation ID.
- [x] Add failing tests for caller voice overriding configured voice and empty raw audio being rejected.
- [x] Run the focused tests and confirm the expected missing-protocol failure.
- [x] Implement the minimal TTS protocol branch and raw-audio parser while leaving the existing `/synthesize` branch unchanged.
- [x] Run `uv run pytest tests/unit/test_local_speech_services.py -q` and confirm all pass.

### Task 3: Registry, example configuration, and live wiring

**Files:**
- Modify: `src/talkpath/adapters/provider_registry.py`
- Modify: `.env.example`
- Test: `tests/unit/test_provider_registry.py`
- Modify: `tests/live/test_local_speech_smoke.py`

- [x] Add a failing registry test asserting the TTS adapter receives OpenAI Speech settings.
- [x] Run the registry test and confirm failure.
- [x] Pass the TTS profile's protocol, speech path, voice, response format, and speed into `LocalHttpTextToSpeechService`; document Kokoro settings in `.env.example` without secrets.
- [x] Update the gated TTS smoke to use configured voice when present and use a non-fake profile; keep it skipped unless `TALKPATH_LIVE_TESTS=1`.
- [x] Run focused registry/live collection tests with live tests gated and confirm pass/skip behavior.

### Task 4: Real Kokoro smoke and regression verification

**Files:**
- Modify: `docs/PROGRESS.md`

- [x] Set `TALKPATH_TTS_BACKEND=local_http`, base URL `http://127.0.0.1:8880`, model `kokoro`, protocol `openai_speech`, path `/v1/audio/speech`, voice `af_bella`, format `wav`, and speed `0.9` in the local `.env` only.
- [x] Run the real TTS smoke against the running Docker service and verify non-empty audio and `audio/*` MIME type.
- [x] Run `uv run pytest -q`, `npm test --prefix pi-extension`, `npm run typecheck --prefix pi-extension`, `uv run python -m compileall -q src`, and `git diff --check`.
- [x] Record exact results, the Kokoro Docker dependency, and remaining STT fixture limitation in `docs/PROGRESS.md`.