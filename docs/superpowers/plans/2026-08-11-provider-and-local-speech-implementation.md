# TalkPath 第二期 Provider 與本地語音整合 Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan task by task, with verification after every task.

**Goal:** 在不改動 TalkPath domain service 介面的前提下，完成可由環境變數切換的 Vision/Text backend，接入以本地 HTTP service 為主的 STT/TTS，保留 fake provider，並建立可控的真實服務 smoke test 與端到端驗證。

**Architecture:** 以 capability-specific ProviderProfile 統一讀取設定；由 ProviderRegistry 建立 fake、TalkPath HTTP、OpenAI-compatible 與 local HTTP adapter。Vision/Text 的 OpenAI-compatible adapter 使用 chat completions 風格的 HTTP contract；STT/TTS 使用本地服務專用的 multipart、JSON 與 audio response contract。API 層只依賴既有 VisionService、TextService、SpeechToTextService、TextToSpeechService 介面，不直接知道供應商名稱。

**Tech Stack:** Python 3.12、Pydantic Settings、httpx、pytest、FastAPI、既有 TypeScript/Node 測試工具；不新增供應商專用 SDK，所有遠端能力先經由 HTTP adapter。

---

## 執行順序與不變條件

1. 每個 Task 先寫失敗測試，再寫最小實作，再執行該 Task 的驗證命令。
2. 每完成一個 Task，立即更新 docs/PROGRESS.md，記錄檔案證據、測試結果、已知限制與下一個起點。
3. 不得把 fake、adapter skeleton、設定可讀取或 provider registry 建立成功宣稱為真實模型已接通。
4. production/default 測試不得要求外部模型、本地語音服務、瀏覽器或實體音訊設備；真實服務測試必須由 TALKPATH_LIVE_TESTS=1 明確啟用。
5. 不把 API key、音訊內容、圖片 base64、完整 prompt 或完整 provider response 寫入 log、錯誤訊息、health response 或 UI。
6. 所有 HTTP adapter 以 capability-specific response model 驗證結果，timeout、連線失敗、5xx、格式錯誤要維持可辨識的錯誤身份。

## Task 1：建立 capability-specific provider 設定模型

**Files**

- Modify: src/talkpath/config.py
- Create: src/talkpath/adapters/provider_profiles.py
- Modify: tests/test_config.py
- Create: tests/unit/test_provider_profiles.py

**Step 1: 先寫設定與正規化測試**

新增測試覆蓋以下行為：

    monkeypatch.setenv("TALKPATH_VISION_BACKEND", "openai_compatible")
    monkeypatch.setenv("TALKPATH_VISION_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("TALKPATH_VISION_API_KEY", "vision-secret")
    monkeypatch.setenv("TALKPATH_VISION_MODEL", "glm-4v")
    settings = Settings()
    profile = settings.provider_profile("vision")
    assert profile.backend == "openai_compatible"
    assert profile.base_url == "https://vision.example/v1"
    assert profile.model == "glm-4v"

測試同時確認：

- backend 只接受 fake、talkpath_http、openai_compatible、local_http。
- timeout 使用 TALKPATH_PROVIDER_TIMEOUT_SECONDS，且必須大於零。
- local STT/TTS 可以沒有 API key。
- 現有 TALKPATH_VISION_ENDPOINT、TALKPATH_TEXT_ENDPOINT 等舊設定仍可正規化到 talkpath_http，避免第一期 fake/demo 啟動方式立即失效。
- SecretStr 的字串表示不會暴露 secret。
- 未設定必要的 base URL 時，只有選用非 fake backend 才在建立服務時產生可讀的設定錯誤。

**Step 2: 執行失敗測試**

    uv run pytest tests/test_config.py tests/unit/test_provider_profiles.py -q

預期：新測試因 provider_profile、BackendKind 或正規化欄位尚未存在而失敗。

**Step 3: 實作最小設定模型**

在 provider_profiles.py 定義 capability、backend kind 與不可變 ProviderProfile。Profile 至少包含 capability、backend、base_url、api_key、model、timeout、chat_path、request_headers；敏感欄位使用 SecretStr。Settings 提供 provider_profile(capability) 與四個 capability 的 canonical environment mapping。canonical 變數固定為 TALKPATH_{CAPABILITY}_BACKEND、BASE_URL、API_KEY、MODEL，並明確列出 TALKPATH_VISION_BACKEND、TALKPATH_TEXT_BACKEND、TALKPATH_STT_BACKEND、TALKPATH_TTS_BACKEND 及其對應欄位；同時保留第一期 endpoint 欄位的相容正規化。

**Step 4: 執行 Task 1 驗證**

    uv run pytest tests/test_config.py tests/unit/test_provider_profiles.py -q

預期：設定與正規化測試全部通過，且尚未發送任何網路請求。

## Task 2：建立 ProviderRegistry 與 adapter 建構邊界

**Files**

- Create: src/talkpath/adapters/provider_registry.py
- Modify: src/talkpath/adapters/http_model_services.py
- Modify: src/talkpath/adapters/fake_services.py
- Modify: src/talkpath/api/app.py
- Create: tests/unit/test_provider_registry.py
- Modify: tests/api/test_activity_flow.py

**Step 1: 先寫 registry contract 測試**

測試 registry 能依 capability 與 backend 建立對應介面：

- fake 產生現有 fake service。
- talkpath_http 產生現有 HTTP model service。
- openai_compatible 產生新的 Vision/Text adapter。
- local_http 只允許 STT/TTS，套用 local speech adapter。
- Vision/Text 選 local_http、STT/TTS 選 openai_compatible、或缺少必要 URL 時，錯誤訊息指出 capability/backend，不含 API key。
- app startup 使用 registry，既有 API route 的 fake 行為保持不變。

**Step 2: 執行失敗測試**

    uv run pytest tests/unit/test_provider_registry.py tests/api/test_activity_flow.py -q

預期：registry construction tests 失敗，既有 activity flow 測試仍能提供未回歸基準。

**Step 3: 實作 registry**

把 provider 選擇集中在一個建構入口；domain service 與 route 不可自行讀取環境變數或判斷供應商名稱。保留既有建構函式的測試注入能力，讓測試可以直接傳入 fake 或 MockTransport。所有 HTTP client 的 timeout、headers 與 base URL 在 adapter 邊界建立。

**Step 4: 執行 Task 2 驗證**

    uv run pytest tests/unit/test_provider_registry.py tests/api/test_activity_flow.py -q

預期：registry、API flow 與既有 fake provider 行為通過。

## Task 3：實作可替換的 OpenAI-compatible Vision/Text backend

**Files**

- Create: src/talkpath/adapters/openai_compatible_services.py
- Modify: src/talkpath/adapters/provider_registry.py
- Create: tests/unit/test_openai_compatible_services.py
- Modify: tests/unit/test_http_model_services.py

**Step 1: 先寫 MockTransport contract tests**

使用 httpx.MockTransport，不連線真實服務，固定驗證：

- Vision 呼叫 {base_url}/chat/completions，送出 model、messages、response_format，圖片以 data URL 放在 user message 的 image_url，並包含既有 lesson scope。
- Text 的 grammar、activity、evaluate 都呼叫同一 chat completions contract，將 lesson、activity、answer 放進結構化 user message。
- 回應 choices[0].message.content 可以是 JSON 字串，也可以包在單層 json fenced text；解析後必須通過 LessonDraft、ActivityDraft 或 AnswerEvaluation model。
- 非 JSON、缺少 choices/message/content、schema 不符時統一為 ProviderResponseInvalid。
- timeout、ConnectError、HTTP 5xx 分別映射為 ProviderTimeout 或 ProviderUnavailable。
- Authorization header 使用設定的 API key，但測試錯誤與 log 不可包含該 key。
- request body 不得包含未經要求的音訊或圖片以外敏感資料。

**Step 2: 執行失敗測試**

    uv run pytest tests/unit/test_openai_compatible_services.py tests/unit/test_http_model_services.py -q

預期：新 adapter 與解析器尚未存在而失敗。

**Step 3: 實作 adapter**

建立共用的 OpenAI-compatible chat completion transport 與 capability-specific parser。base_url 統一移除尾端斜線，chat_path 預設為 /chat/completions；profile 可覆寫 path，但不以 GLM、ClinePass 或其他 vendor 名稱作分支。Vision 與 Text service 只負責組織既有 domain input、呼叫 transport、驗證 domain output；不改動 domain service 介面。

**Step 4: 執行 Task 3 驗證**

    uv run pytest tests/unit/test_openai_compatible_services.py tests/unit/test_http_model_services.py -q

預期：所有 MockTransport、錯誤身份、API key redaction 與既有 HTTP adapter 測試通過。

## Task 4：實作本地 HTTP STT/TTS adapter

**Files**

- Create: src/talkpath/adapters/local_speech_services.py
- Modify: src/talkpath/adapters/provider_registry.py
- Create: tests/unit/test_local_speech_services.py
- Modify: tests/api/test_activity_flow.py

**Step 1: 先寫本地 HTTP contract tests**

STT 測試固定驗證：

- POST {base_url}/transcribe。
- multipart 欄位包含 audio、mime_type、operation_id；若 domain input 有 language 才送 language。
- 回應 JSON 需包含 operation_id、text，可選 segments；解析為既有 Transcript。
- operation_id 缺失、text 非字串或 JSON 無法解析時為 ProviderResponseInvalid。

TTS 測試固定驗證：

- POST {base_url}/synthesize。
- JSON 欄位包含 text、voice、operation_id、model；未設定欄位不送空值。
- 支援 audio/* raw bytes 與 JSON base64 兩種回應，皆解析為既有 AudioArtifact。
- 不接受空音訊、錯誤 base64 或不支援的 content type。
- audio bytes 不進入錯誤文字、health response 或一般 log。

同時測試 timeout、連線失敗、5xx 與 content-type/schema 錯誤的錯誤身份。

**Step 2: 執行失敗測試**

    uv run pytest tests/unit/test_local_speech_services.py -q

預期：local HTTP adapter 尚未存在而失敗。

**Step 3: 實作 local_http adapter**

只管理 HTTP request/response 與 domain model 轉換，不啟動、停止或重啟本地 process。若未來需要 process lifecycle，另立 local_process backend，不在本期混入 local_http。audio bytes 只存在於 request/response 生命週期內，測試以 bytes/hash/metadata 驗證，不輸出完整內容。

**Step 4: 執行 Task 4 驗證**

    uv run pytest tests/unit/test_local_speech_services.py tests/api/test_activity_flow.py -q

預期：本地 HTTP contract、錯誤映射與既有 activity flow 通過。

## Task 5：加入 provider health 與安全診斷資訊

**Files**

- Create: src/talkpath/api/provider_health.py
- Modify: src/talkpath/api/app.py
- Create: tests/api/test_provider_health.py
- Modify: tests/test_cli.py

**Step 1: 先寫 health response tests**

新增 GET /health/providers，驗證每個 capability 回報 backend、model、configured 與 availability 欄位；沒有設定或無法建立 adapter 時回報狀態，不把 secret、完整 URL query、audio、image 或 prompt 放入 response。預設 health 檢查只做設定與 adapter readiness，不對外部模型或本地語音服務發出探測請求；真實可用性由 gated smoke tests 驗證。

**Step 2: 執行失敗測試**

    uv run pytest tests/api/test_provider_health.py tests/test_cli.py -q

預期：health route 與欄位尚未存在而失敗。

**Step 3: 實作診斷邊界**

Provider health 只讀 registry 的安全 metadata；API key 僅保留在 adapter transport header。錯誤分類與 health status 分開，避免把供應商原始 response 直接返回給 UI 或 API client。

**Step 4: 執行 Task 5 驗證**

    uv run pytest tests/api/test_provider_health.py tests/test_cli.py -q

預期：health response、redaction 與既有 CLI/API 測試通過。

## Task 6：建立明確開關的 live smoke tests

**Files**

- Create: tests/live/conftest.py
- Create: tests/live/test_provider_smoke.py
- Create: tests/live/test_local_speech_smoke.py
- Modify: .gitignore
- Create: .env.example

**Step 1: 先寫 skip/guard tests**

預設執行時，live tests 必須在 TALKPATH_LIVE_TESTS 不等於 1 時 skip，不能因缺少 API key 或本地服務而使 CI 失敗。啟用後依 capability 檢查對應 backend、base URL、model 與 API key；local STT/TTS 不要求 API key。測試輸出只顯示 backend、model、status，不顯示 secret、prompt、圖片或音訊內容。

**Step 2: 執行失敗測試**

    uv run pytest tests/live -q

預期：未設定 TALKPATH_LIVE_TESTS=1 時全部受控 skip，測試收集成功。

**Step 3: 實作最小真實 smoke case**

Vision smoke 使用固定小型 image fixture，檢查回傳可解析為 LessonDraft；Text smoke 檢查 grammar/activity/evaluate 的結構欄位；STT smoke 使用固定短音訊 fixture，檢查 operation_id 與非空文字；TTS smoke 檢查 audio content type、非空 bytes 與可辨識 mime type。禁止依賴精確自然語言內容。

**Step 4: 執行 Task 6 驗證**

    uv run pytest tests/live -q

預期：未啟用時只出現受控 skip，無外部請求。

若要實際驗證服務，使用明確環境變數執行：

    $env:TALKPATH_LIVE_TESTS = "1"
    uv run pytest tests/live -q -rs

預期：實際服務可用時通過；服務未啟動或 contract 不符時，以 ProviderUnavailable 或 ProviderResponseInvalid 清楚失敗，不洩露敏感資料。

## Task 7：建立真實 provider 到 speech 的端到端測試

**Files**

- Create: tests/integration/test_real_provider_to_speech.py
- Modify: tests/integration/conftest.py
- Modify: docs/talkpath-progress.md

**Step 1: 先寫 gated integration test**

測試串接既有 application flow：輸入圖片或文字 lesson material，經 Vision 產出 lesson，經 Text 產生 activity，使用 STT 轉成 answer，再交給 Text evaluate，最後用 TTS 產生可播放音訊。只驗證 domain schema、operation_id 關聯、錯誤邊界與資料不外洩，不對模型文案做 exact match。

**Step 2: 執行預設測試**

    uv run pytest tests/integration/test_real_provider_to_speech.py -q

預期：沒有 TALKPATH_LIVE_TESTS=1 時受控 skip，不需要任何真實服務。

**Step 3: 啟用真實服務驗證**

    $env:TALKPATH_LIVE_TESTS = "1"
    uv run pytest tests/integration/test_real_provider_to_speech.py -q -rs

預期：Vision、Text、local STT、local TTS 都能完成最小閉環；任何失敗指出 capability、backend、operation_id 與錯誤類別，但不輸出內容或 secret。

## Task 8：同步使用文件與第二期交接

**Files**

- Modify: README.md
- Modify: docs/talkpath-progress.md
- Modify: docs/PROGRESS.md
- Modify: .env.example

**Step 1: 文件測試與靜態檢查**

確認 README 與 .env.example 說明：

- Vision/Text 使用 capability-specific backend 設定，可切換 fake、TalkPath HTTP、OpenAI-compatible。
- GLM、ClinePass 等僅是 OpenAI-compatible endpoint 的設定例，不在程式碼中硬編碼 vendor 分支。
- STT/TTS 本期以本地 HTTP service 為主，列出 /transcribe 與 /synthesize contract。
- 真實測試需 TALKPATH_LIVE_TESTS=1，並提醒不要把 API key 寫入版本控制。
- local HTTP 不負責啟動本地 process。

**Step 2: 執行文件與全量驗證**

    uv run pytest
    npm test --prefix pi
    npm run typecheck --prefix pi
    node --check pi/src/index.js

預期：Python 全量測試、Pi TypeScript tests、typecheck 與 JavaScript syntax check 全部通過；live/integration tests 在未啟用時只受控 skip。

**Step 3: 更新 PROGRESS.md**

記錄每個 Task 的完成證據、實際測試結果、是否完成真實服務 smoke/e2e、已知 provider contract 限制、目前工作路徑 D:/python/TalkPath，以及下一個交接起點。只有在真實服務測試有證據時，才把「實際模型與本地語音服務已接入」標記完成。

## 最終驗收清單

- [ ] Vision/Text backend 可用環境變數切換，且 domain service 不綁定 vendor 名稱。
- [ ] fake provider 與第一期測試仍通過。
- [ ] OpenAI-compatible Vision/Text adapter 有 MockTransport contract、錯誤映射與 API key redaction 測試。
- [ ] local HTTP STT/TTS adapter 有 multipart、JSON、raw audio/base64 contract 測試。
- [ ] health response 不含 secrets、prompt、圖片或音訊內容。
- [ ] live smoke tests 預設不連線，明確啟用後可檢查真實服務。
- [ ] real provider-to-speech integration test 已建立，並清楚區分受控 skip 與實際通過。
- [ ] README、.env.example、docs/talkpath-progress.md 與 docs/PROGRESS.md 已同步。
- [ ] 全量 Python、Pi tests、typecheck 與 syntax check 有可核對結果。
- [ ] 文件明確保留未完成項目，不把 skeleton、fake 或 adapter construction 說成真實服務已完成。