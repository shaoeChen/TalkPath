# 本機語音服務

TalkPath 的 TTS 與 STT 由 `docker/compose.speech.yml` 一起管理。TTS 使用 Kokoro-FastAPI CPU；STT 使用 qwen3-asr-service CPU OpenVINO 0.6B。兩個 API 僅綁定主機 `127.0.0.1`，TalkPath 應用仍在主機執行。

## 設定

在未納入版本控制的根目錄 `.env` 設定：

```dotenv
TALKPATH_TTS_BACKEND=local_http
TALKPATH_TTS_BASE_URL=http://127.0.0.1:8880
TALKPATH_TTS_MODEL=kokoro
TALKPATH_TTS_PROTOCOL=openai_speech
TALKPATH_TTS_SPEECH_PATH=/v1/audio/speech

TALKPATH_STT_BACKEND=local_http
TALKPATH_STT_BASE_URL=http://127.0.0.1:8765
TALKPATH_STT_API_KEY=<自行產生的固定私有密鑰>
TALKPATH_STT_MODEL=qwen3-asr-0.6b
TALKPATH_STT_PROTOCOL=openai_transcription
TALKPATH_STT_TRANSCRIBE_PATH=/compat/openai/v1/audio/transcriptions
```

Compose 直接讀取同一個 `TALKPATH_STT_API_KEY` 作為 STT 服務的 Bearer 密鑰；無須複製動態 Token。STT 啟動時使用 `--no-config`：上游自動產生的 `config.yaml` 帶有空白 `api_key`，會覆蓋環境變數並意外關閉驗證。其他必需的 STT 選項已由 Compose 明確指定。不要把 `.env`、密鑰或含密鑰的 `docker compose config` 完整輸出提交到版本控制。TTS 的聲音、速度與輸出格式仍使用現有 `TALKPATH_TTS_VOICE`、`TALKPATH_TTS_SPEED`、`TALKPATH_TTS_RESPONSE_FORMAT` 設定。

## 啟動與檢查

在專案根目錄執行：

```powershell
docker compose --env-file .env -f docker/compose.speech.yml up -d
docker compose --env-file .env -f docker/compose.speech.yml ps
```

兩個服務都顯示 `healthy` 後，可檢查健康端點：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/v2/health
Invoke-RestMethod http://127.0.0.1:8880/health
```

STT 的 ASR／VAD 模型保存在 Compose volume `talkpath-speech_asr_models`；第一次在新電腦啟動且 volume 為空時，服務會下載模型。此機目前已將先前驗證的 WebView 0.6B 模型與 VAD 複製進 volume，不再依賴 WebView 安裝目錄。Compose 的兩個映像均固定到此次驗證過的 digest，升級時需明確更新設定並重測。

Compose 使用 `restart: unless-stopped`；若希望 Windows 開機後自動運行，Docker Desktop 本身也須隨登入啟動。修改 `.env` 的 TalkPath provider 設定後，需重啟 TalkPath API 行程；若修改密鑰，還需重新執行上述 `docker compose up -d`，讓 STT 容器套用新密鑰。

## 管理

```powershell
docker compose --env-file .env -f docker/compose.speech.yml logs --tail 50 stt tts
docker compose --env-file .env -f docker/compose.speech.yml restart
docker compose --env-file .env -f docker/compose.speech.yml down
```

`down` 會停止容器但保留 ASR 模型 volume。舊的獨立 `kokoro-fastapi` 與 `talkpath-qwen3-asr-test` 容器目前已停止，並未刪除；日常啟停應以本文件的 Compose 指令為準。
