# TalkPath Kokoro-FastAPI TTS Integration Design

日期：2026-08-12
狀態：已批准並進入實作

## 目標

將已啟動且已通過中英文實際輸出的 Kokoro-FastAPI 接入 TalkPath TTS，同時保留既有 TalkPath `/synthesize` 本地服務契約。TalkPath application/domain 層不直接知道 Kokoro 名稱，只依協定設定選擇請求格式。

## 邊界與資料流

`SessionService.synthesize_speech()` 維持原有介面。`ProviderRegistry` 依 TTS `ProviderProfile` 建立 `LocalHttpTextToSpeechService`；adapter 依 protocol 選擇：

- `talkpath`：POST `{base_url}/synthesize`，維持既有 operation_id 與 JSON/base64/raw audio 契約。
- `openai_speech`：POST `{base_url}/v1/audio/speech`，送出 `input`、`model`、`voice`、`response_format` 與 `speed`，接收 raw `audio/*`。

OpenAI Speech 回應沒有 operation_id；adapter 在 TalkPath domain boundary 補回呼叫端 operation_id。音訊 bytes 只存在 request/response 生命週期，不寫入 log 或 health response。

## 設定

新增 TTS 專用設定：

- `TALKPATH_TTS_PROTOCOL`，預設 `talkpath`
- `TALKPATH_TTS_SPEECH_PATH`，預設 `/synthesize`
- `TALKPATH_TTS_VOICE`，可選；若公開呼叫提供 voice，優先使用呼叫端 voice
- `TALKPATH_TTS_RESPONSE_FORMAT`，預設 `mp3`
- `TALKPATH_TTS_SPEED`，預設 `1.0`

Kokoro 範例：

```env
TALKPATH_TTS_BACKEND=local_http
TALKPATH_TTS_BASE_URL=http://127.0.0.1:8880
TALKPATH_TTS_MODEL=kokoro
TALKPATH_TTS_PROTOCOL=openai_speech
TALKPATH_TTS_SPEECH_PATH=/v1/audio/speech
TALKPATH_TTS_VOICE=af_bella
TALKPATH_TTS_RESPONSE_FORMAT=mp3
TALKPATH_TTS_SPEED=0.9
```

## 錯誤與相容性

- timeout → `ProviderTimeout`
- connection failure 或非 2xx → `ProviderUnavailable`
- empty/non-audio response、無效設定或不支援 protocol → `ProviderResponseInvalid` 或設定錯誤
- 不因 OpenAI Speech response 缺 operation_id 而拒絕，改由 adapter 保留 domain operation identity
- 舊 local TTS contract 的所有既有測試維持通過

## 驗證

- MockTransport 驗證 path、headers、JSON 欄位、voice precedence、response format/speed 與 raw audio parsing。
- Registry/config tests 驗證 TTS profile 透傳新欄位與 secret redaction。
- 以目前 Docker Kokoro-FastAPI 執行英文與中文真實 TTS smoke。
- 全量 Python、Pi tests、typecheck、compileall 與 diff check 通過後，更新 `docs/PROGRESS.md`。

## 非本次範圍

不加入 streaming domain interface、voice clone UI、audio cache、模型 lifecycle 管理或 Qwen3-TTS adapter；這些另立設計。