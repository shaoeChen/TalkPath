# TalkPath 第二期：可替換模型 Backend 與本地語音服務設計

日期：2026-08-11  
狀態：設計已批准，第二期 implementation plan 已建立；尚未開始正式開發

## 1. 目標

第二期只處理 provider 與真實服務接入，不改變第一期已完成的兒童學習流程：

1. Vision 與 Text backend 不綁定特定供應商。
2. 透過環境變數切換 GLM、ClinePass、OpenAI-compatible 或其他 HTTP backend。
3. STT 與 TTS 以本地 HTTP service 為主要部署方式。
4. 保留 fake provider，讓既有測試不依賴外部服務。
5. 增加可控的實際 provider smoke test，完成後才能進行真實端到端測試。

## 2. Backend 抽象

目前的 domain service interface 保持不變：

- Vision：extract_lesson
- Text：explain_grammar、generate_activity、evaluate_answer
- STT：transcribe
- TTS：synthesize

Provider registry 負責依設定建立 adapter；UI、SessionService、ActivityService 與 Pi extension 不直接建立供應商 client。

每個能力有獨立設定：

    TALKPATH_VISION_BACKEND
    TALKPATH_VISION_BASE_URL
    TALKPATH_VISION_API_KEY
    TALKPATH_VISION_MODEL

    TALKPATH_TEXT_BACKEND
    TALKPATH_TEXT_BASE_URL
    TALKPATH_TEXT_API_KEY
    TALKPATH_TEXT_MODEL

    TALKPATH_STT_BACKEND
    TALKPATH_STT_BASE_URL
    TALKPATH_STT_MODEL

    TALKPATH_TTS_BACKEND
    TALKPATH_TTS_BASE_URL
    TALKPATH_TTS_MODEL

    TALKPATH_PROVIDER_TIMEOUT_SECONDS

API key 只能從環境變數或本機 .env 讀取，不進入 LessonLens、SQLite、UI event、Pi prompt 或一般 log。

## 3. Backend 類型

### 3.1 fake

僅供測試與沒有真實服務時的本機開發，維持第一期行為。

### 3.2 talkpath_http

使用目前既有的 TalkPath provider contract，例如：

- /extract
- /grammar
- /activity
- /evaluate
- /transcribe
- /synthesize

用於自建模型 gateway 或已有固定 contract 的服務。

### 3.3 openai_compatible

使用可由設定指定的 chat／vision HTTP API。GLM、ClinePass 或其他服務若提供相容介面，應只需要更換：

- BASE_URL
- API_KEY
- MODEL
- 必要的 request／response profile

供應商名稱不寫死在 application layer。

## 4. 本地 STT／TTS

STT 與 TTS 預設使用 local_http backend。

### STT contract

    POST {base_url}/transcribe
    Content-Type: multipart/form-data

    audio: binary
    mime_type: audio/wav
    operation_id: string
    language: optional string

回應為 TalkPath Transcript JSON，且必須帶回相同 operation_id。

### TTS contract

    POST {base_url}/synthesize
    Content-Type: application/json

    {
      "text": "...",
      "voice": "...",
      "operation_id": "...",
      "model": "..."
    }

回應可為 audio/* binary，或包含 base64 audio 的 JSON；兩者都需轉成 TalkPath AudioArtifact。

TalkPath 不負責管理本地語音模型的程序生命週期。語音服務由本機服務管理，TalkPath 只負責 HTTP timeout、錯誤分類、operation ID 與 fallback。未來若某個模型只有 CLI，再另外增加 local_process adapter，不讓 CLI 細節污染既有 service interface。

## 5. 錯誤與安全

- timeout → ProviderTimeout
- 連線失敗或 5xx → ProviderUnavailable
- schema、JSON、audio 格式錯誤 → ProviderResponseInvalid
- 可重試錯誤在公開 API 回傳 retryable: true
- 錯誤訊息不得包含 API key、Authorization header、完整音訊內容或完整圖片 base64
- provider health check 只回報 backend、model、configured 與可用性，不回報秘密值
- 預設不把兒童原始音訊永久保存

## 6. 測試策略

1. Settings tests：確認四個能力可各自切換 backend、base URL、model 與 timeout。
2. Adapter contract tests：使用 httpx.MockTransport，不連外部網路。
3. Provider registry tests：確認 fake、TalkPath HTTP、OpenAI-compatible、local HTTP 建立正確 adapter。
4. Error tests：確認 timeout、連線錯誤、非 2xx、無效 JSON、無效音訊與 operation identity mismatch。
5. Live smoke tests：只有 TALKPATH_LIVE_TESTS=1 且設定完整時執行；未設定時明確 skip。
6. End-to-end test：實際 Vision／Text backend 加上本地 STT／TTS service，驗證圖片到活動、語音轉錄與語音合成。

## 7. 非本期範圍

- 不在 application layer 寫死 GLM、ClinePass 或任何供應商名稱。
- 不在本期實作本地語音模型本身。
- 不加入多使用者帳號、付費、正式雲端部署或長期音訊保存。
- 不因接入真實 provider 而移除 fake provider。

## 8. 完成條件

第二期完成時，必須能：

1. 只透過環境變數切換 Vision／Text backend。
2. 使用本地 HTTP service 完成 STT 與 TTS contract。
3. 保持第一期全部 Python、Pi TypeScript 與 JavaScript 驗證通過。
4. 在設定 live test 環境後，完成至少一次真實 provider smoke test。
5. 完整流程中不洩漏 API key、答案 key 或兒童原始音訊。