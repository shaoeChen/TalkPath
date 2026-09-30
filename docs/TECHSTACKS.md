# TalkPath 技術棧

## 後端
- Python >= 3.12，套件管理與執行：`uv`
- FastAPI、uvicorn（含 WebSocket）、httpx、pydantic-settings、pyyaml、python-multipart
- 建置：hatchling

## 前端
- 原生 HTML / CSS / JavaScript（`frontend/`），由同一個 FastAPI 提供靜態檔（same-origin）
- 測試：Node 內建 `node --test`

## Agent 擴充
- `pi-extension/`：TypeScript（Pi agent 工具）

## 語音
- TTS：Kokoro（`openai_speech`，預設 `http://127.0.0.1:8880`）
- STT：qwen3-asr-service CPU OpenVINO 0.6B（`openai_transcription`，預設 `http://127.0.0.1:8765`）
- 本機語音服務：`docker/compose.speech.yml` 同時管理 Kokoro TTS 與 Qwen STT，模型由 Docker volume 保存；操作方式見 `docs/SPEECH_SERVICES.md`
- provider、endpoint、模型名稱與 API 金鑰一律由設定檔或環境變數控制

## 資料保存
- LessonLens：以 Obsidian Markdown 筆記與 Properties 保存課程，透過 repository 介面存取；進度使用 SQLite

## 測試
- Python：pytest、pytest-asyncio（`uv run pytest -q`）
- 前端：`node --check`、`node --test`
