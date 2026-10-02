# TalkPath

TalkPath 是供小朋友使用的英文互動學習 Web 應用。使用者可匯入課本照片、確認課程範圍、檢視保存的課程，並依課程內容進行詞彙、文法、聽力與閱讀練習。後端以 FastAPI 提供 API，課程內容儲存在本機 Markdown，學習紀錄儲存在本機 SQLite。

目前是單機使用的 MVP，預設只監聽 `127.0.0.1`。專案沒有使用者帳號與公開網路部署所需的存取控制。

## 快速開始

需要 Python 3.12 以上及 [uv](https://docs.astral.sh/uv/)；若要使用本機 TTS／STT，還需要 Docker Desktop。以下指令在專案根目錄執行：

```powershell
uv sync
Copy-Item .env.example .env
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

若要啟用本機語音，將 `.env` 中對應欄位改成以下設定，並以剛產生的 64 字元密鑰取代 `TALKPATH_STT_API_KEY` 的佔位文字：

```dotenv
TALKPATH_TTS_BACKEND=local_http
TALKPATH_TTS_BASE_URL=http://127.0.0.1:8880
TALKPATH_TTS_MODEL=kokoro
TALKPATH_TTS_PROTOCOL=openai_speech
TALKPATH_TTS_SPEECH_PATH=/v1/audio/speech

TALKPATH_STT_BACKEND=local_http
TALKPATH_STT_BASE_URL=http://127.0.0.1:8765
TALKPATH_STT_API_KEY=<上一步產生的密鑰>
TALKPATH_STT_MODEL=qwen3-asr-0.6b
TALKPATH_STT_PROTOCOL=openai_transcription
TALKPATH_STT_TRANSCRIBE_PATH=/compat/openai/v1/audio/transcriptions
```

接著啟動 TTS／STT；`ps` 顯示兩個服務都為 `healthy` 後，再啟動 TalkPath：

```powershell
docker compose --env-file .env -f docker/compose.speech.yml up -d
docker compose --env-file .env -f docker/compose.speech.yml ps
uv run uvicorn talkpath.api.app:create_app --factory --host 127.0.0.1 --port 8001
```

在瀏覽器開啟 `http://127.0.0.1:8001`。首次啟動 STT 可能需要下載模型，步驟與檢查方式見 [本機語音服務](docs/SPEECH_SERVICES.md)。若只想先體驗不需語音模型的流程，可保留 `.env.example` 的 fake STT／TTS 設定，略過密鑰與 Docker Compose 步驟；Vision／Text 也預設為 fake providers，產生的是示範內容，並非真實課本辨識結果。

### 用手機在區網操作

完成上述安裝及語音服務設定後，以區網 HTTPS 模式啟動 TalkPath：

```powershell
uv run python -m talkpath.main --lan
```

啟動時會顯示 `https://<主機區網 IP>:8000` 及此安裝環境的 CA 憑證檔案位置。TalkPath 會自動建立並重用憑證；手機安裝及信任 CA、手機與主機位於同一區網，以及必要的主機防火牆設定，均由使用者自行處理。多網卡主機若漏掉需要的 IP，可加 `--lan-ip <區網 IP>`。詳見 [區網 HTTPS 說明](docs/LAN_HTTPS.md)。

## 使用真實模型

在未納入版本控制的 `.env` 設定 Vision、Text、STT、TTS provider。可用欄位及範例見 [.env.example](.env.example)。Vision／Text 可接 OpenAI 相容的 API；本機語音服務的進一步設定與管理方式見 [本機語音服務](docs/SPEECH_SERVICES.md)。

不要將 API 金鑰、語音密鑰、課本照片或小朋友的錄音提交到 Git。`.env`、上傳檔、課程資料、學習資料庫與日誌已列入 [.gitignore](.gitignore)。

## 目前功能

- 上傳課本照片，確認學程、年級、科目、課次與頁碼，再匯入課程。
- 在 **My lessons** 檢視已保存課程與每次匯入的來源頁面；同一課程可分次附加內容，重複頁碼會先提示。
- 從已保存課程進入詞彙、文法、聽力及閱讀活動；練習頁一次呈現一題。
- 詞彙練習可搭配 TTS 播放與 STT 跟讀；未設定語音服務時，部分互動會使用文字替代流程。
- 以 LessonLens 相容的 Markdown 保存課程，以 SQLite 保存作答與複習紀錄。

Vision／Text／STT／TTS 由可替換的 provider adapter 提供。Direct API 是預設路徑；Pi RPC 僅作為實驗性的明確選用模式。

## 驗證

```powershell
uv run pytest -q
node --test frontend/test/screen-flow.test.cjs
```

整合測試預設使用測試替身，不會呼叫外部模型。`tests/live/` 的真實服務測試須明確設定 `TALKPATH_LIVE_TESTS=1` 與對應的 provider；本機語音服務的設定見 [語音服務文件](docs/SPEECH_SERVICES.md)。

## 文件與授權

產品背景見 [產品進度與定位](docs/talkpath-progress.md)，專案規則及目前工作分別見 [AGENTS.md](AGENTS.md)與 [PROGRESS.md](docs/PROGRESS.md)。程式碼以 [MIT License](LICENSE) 授權。第三方模型、容器映像與課本內容各自適用其原有授權或使用條款。
