# TalkPath

TalkPath 是供小朋友使用的英文互動學習 Web 應用。使用者可匯入課本照片、確認課程範圍、檢視保存的課程，並依課程內容進行詞彙、文法、聽力與閱讀練習。後端以 FastAPI 提供 API，課程內容儲存在本機 Markdown，學習紀錄儲存在本機 SQLite。

目前是單機使用的 MVP，預設只監聽 `127.0.0.1`。專案沒有使用者帳號與公開網路部署所需的存取控制。

## 快速開始

需要 Python 3.12 以上及 [uv](https://docs.astral.sh/uv/)。以下指令在專案根目錄執行：

```powershell
uv sync
Copy-Item .env.example .env
uv run uvicorn talkpath.api.app:create_app --factory --host 127.0.0.1 --port 8001
```

在瀏覽器開啟 `http://127.0.0.1:8001`。`.env.example` 預設使用 fake providers，可在沒有模型帳號的情況下體驗流程與執行測試；產生的內容是示範資料，不能當成真實課本辨識結果。

## 使用真實模型

在未納入版本控制的 `.env` 設定 Vision、Text、STT、TTS provider。可用欄位及範例見 [.env.example](.env.example)。Vision／Text 可接 OpenAI 相容的 API；本機語音服務的 Docker Compose 設定與啟動方式見 [本機語音服務](docs/SPEECH_SERVICES.md)。

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
