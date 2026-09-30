# TalkPath Implementation Plan

> 實作計畫的目前執行狀態與交接資訊，請以 [`docs/PROGRESS.md`](../../PROGRESS.md) 為準。本文件保留原始的任務拆解、驗收條件與開發順序。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (required) to implement this plan task-by-task. Steps use the checkbox syntax `- [x]` for tracking.

**Goal:** 建立 TalkPath 第一版可運作的兒童英文學習垂直流程：圖片上傳、課程範圍確認、Pi agent 協調視覺萃取、LessonLens 保存、題目生成與基本 UI 回饋。

**Architecture:** Python 3.12 的 FastAPI 主服務負責 session、資料、模型 adapter 與 Web UI API；Python 啟動 Pi 官方 RPC 子程序，Pi 只透過 TalkPath TypeScript extension 使用白名單學習工具。LessonLens 使用本機 Obsidian Markdown，學習進度使用 SQLite，STT／TTS 以 provider adapter 隔離。

**Tech Stack:** Python 3.12、uv、FastAPI、Pydantic v2、SQLite、pytest、httpx、原生 HTML/CSS/JavaScript、Pi RPC、TypeScript extension、Node test runner。

> **執行進度交接：** 本計畫的實際執行狀態請以 [`docs/PROGRESS.md`](../../PROGRESS.md) 為準。此計畫保留原始的拆解、驗收條件與開發順序。

> **目前狀態（2026-08-11）：** Task 1～Task 10 已依 docs/PROGRESS.md 完成；本計畫的勾選範圍是 fake provider、測試替身、FastAPI TestClient 與本機回歸驗證。真實模型、真實 Pi agent、瀏覽器自動化、實體音訊設備與 production endpoint 仍屬後續整合，不包含在本計畫的完成宣告內。
---

## 執行原則

- 先寫測試，再寫最小實作；每個任務都要有獨立的測試命令。
- 先完成文字與課程內容閉環，再接入實際音訊模型。
- 外部模型使用 fake provider 或 HTTP contract mock 測試，不讓測試依賴外部服務。
- Pi agent 不取得 read、bash、edit、write、grep、find、ls 等內建工具。
- 所有寫入 LessonLens、SQLite 或活動資料的操作都要有 operation ID 並具備冪等性。
- 目前工作區沒有 Git repository；計畫中的 commit 是執行階段的檢查點，需在 Git 初始化後執行。

## 檔案結構與責任

### Python 主服務

- pyproject.toml：Python 套件、測試與啟動設定。
- src/talkpath/config.py：環境變數與設定模型。
- src/talkpath/domain/models.py：CourseScope、LessonDraft、Activity、Session 等領域模型。
- src/talkpath/domain/errors.py：可預期的領域錯誤與錯誤碼。
- src/talkpath/ports/lesson_repository.py：LessonLens 資料存取接口。
- src/talkpath/ports/progress_repository.py：學習進度存取接口。
- src/talkpath/ports/model_services.py：Vision、Text、STT、TTS provider 接口。
- src/talkpath/adapters/lessonlens_markdown.py：Obsidian Markdown adapter。
- src/talkpath/adapters/sqlite_progress.py：SQLite progress adapter。
- src/talkpath/adapters/http_model_services.py：地端／雲端模型 HTTP adapter。
- src/talkpath/adapters/fake_services.py：測試用 fake provider。
- src/talkpath/agent/pi_rpc.py：Pi 子程序生命週期、JSONL reader/writer 與事件轉換。
- src/talkpath/application/session_service.py：課程匯入與學習 session 狀態機。
- src/talkpath/application/activity_service.py：活動生成、作答評估與結果保存。
- src/talkpath/api/app.py：FastAPI app factory、middleware、靜態檔案。
- src/talkpath/api/routes.py：兒童 UI 使用的公開 API。
- src/talkpath/api/internal_tools.py：Pi extension 使用的本機內部工具 API。
- src/talkpath/main.py：本機啟動入口。

### Pi extension 與 UI

- pi-extension/package.json：TypeScript extension 的依賴與檢查命令。
- pi-extension/tsconfig.json：TypeScript 編譯設定。
- pi-extension/talkpath-tools.ts：Pi 白名單工具與 Python 內部 API client。
- frontend/index.html：兒童學習介面骨架。
- frontend/app.js：上傳、課程確認、事件串流與活動互動。
- frontend/styles.css：簡單、可讀、適合兒童操作的版面。

### 測試與測試資料

- tests/unit/：領域模型、repository、provider、RPC parser。
- tests/api/：FastAPI endpoint 與 session flow。
- tests/integration/：fake Vision/Text/Speech/Pi 的端到端流程。
- tests/fixtures/：固定課程範圍、LessonDraft、Activity 與圖片 metadata。
- pi-extension/test/：TypeScript 工具 schema 與 bridge 行為。
- data/lessonlens/.gitkeep：本機 LessonLens Vault 根目錄提示，不提交兒童資料。
- data/talkpath.sqlite：執行時 SQLite，加入 .gitignore。

## Task 1: 建立 Python 專案骨架與測試入口

**Files:**
- Create: pyproject.toml
- Create: src/talkpath/__init__.py
- Create: src/talkpath/config.py
- Create: src/talkpath/api/app.py
- Create: tests/conftest.py
- Create: tests/api/test_health.py
- Create: .gitignore
- Create: README.md

- [x] **Step 1: 寫健康檢查的失敗測試**

建立 FastAPI TestClient 測試：

```python
from fastapi.testclient import TestClient
from talkpath.api.app import create_app

def test_health_returns_ok():
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [x] **Step 2: 執行測試確認目前失敗**

Run: uv run pytest tests/api/test_health.py -q

Expected: FAIL，因為 talkpath 套件與 create_app 尚未存在。

- [x] **Step 3: 建立最小 app 與設定模型**

在 pyproject.toml 加入 FastAPI、uvicorn、pydantic-settings、pytest、pytest-asyncio、httpx；create_app 建立 /health。config.py 提供以下設定欄位：

```python
class Settings:
    app_host: str
    app_port: int
    lessonlens_root: Path
    sqlite_path: Path
    pi_command: str
    pi_extension: Path
```

預設值使用本專案內的 data/lessonlens 與 data/talkpath.sqlite，模型 endpoint 與憑證只從環境變數讀取。

- [x] **Step 4: 執行測試確認通過**

Run: uv run pytest tests/api/test_health.py -q

Expected: 1 passed。

- [x] **Step 5: 建立執行與忽略檔規則**

README 說明：

```text
uv sync
uv run uvicorn talkpath.api.app:create_app --factory --reload
uv run pytest
```

.gitignore 忽略 .venv/、__pycache__/、.pytest_cache/、data/talkpath.sqlite、上傳暫存檔與模型憑證。

## Task 2: 建立領域模型、狀態機與服務接口

**Files:**
- Create: src/talkpath/domain/models.py
- Create: src/talkpath/domain/errors.py
- Create: src/talkpath/ports/lesson_repository.py
- Create: src/talkpath/ports/progress_repository.py
- Create: src/talkpath/ports/model_services.py
- Create: tests/unit/test_domain_models.py
- Create: tests/unit/test_session_states.py

- [x] **Step 1: 寫 CourseScope 與內容模型測試**

測試 CourseScope 產生穩定 lesson_id：

```python
scope = CourseScope(
    program="國中",
    grade="一年級",
    subject="英文",
    lesson="第一課",
)
assert scope.lesson_id == "junior-high-grade-1-english-lesson-01"
```

同時測試 CourseScope 缺少 grade 或 lesson 時拒絕建立；ContentItem 需要 content_id、type、content、source_page、confidence、status。

- [x] **Step 2: 寫流程狀態轉移測試**

只允許以下轉移：

```text
UPLOAD_IMAGE -> CONFIRM_COURSE_SCOPE
CONFIRM_COURSE_SCOPE -> EXTRACTING
EXTRACTING -> PREVIEW_DRAFT
PREVIEW_DRAFT -> SAVE_LESSON
SAVE_LESSON -> ASK_GENERATE_ACTIVITY
ASK_GENERATE_ACTIVITY -> GENERATING_ACTIVITY
GENERATING_ACTIVITY -> READY_FOR_PRACTICE
任何狀態 -> FAILED
```

測試範圍未確認時不能進入 EXTRACTING，且 FAILED 可以進入 RETRY。

- [x] **Step 3: 建立 Pydantic 模型與 Protocol 接口**

固定以下資料契約：

```python
class CourseScope(BaseModel):
    program: str
    grade: str
    subject: str
    textbook: str | None = None
    edition: str | None = None
    lesson: str
    pages: list[str] = []
    lesson_id: str

class ImageReference(BaseModel):
    image_id: str
    path: str
    mime_type: str
    size_bytes: int
    expires_at: datetime

class LessonDraft(BaseModel):
    lesson_id: str
    scope: CourseScope
    title: str
    passage: str
    content_items: list[ContentItem]
    source_images: list[str]
    extraction_status: Literal["draft", "reviewed", "published"]
    provider: str
    model: str
    operation_id: str
```

Model service Protocol 必須提供 extract_lesson、explain_grammar、generate_activity、evaluate_answer、transcribe、synthesize；串流方法使用 async iterator，第一版可由 adapter 回傳未支援錯誤。

- [x] **Step 4: 執行領域測試**

Run: uv run pytest tests/unit/test_domain_models.py tests/unit/test_session_states.py -q

Expected: all tests pass。

## Task 3: 實作 LessonLens Markdown repository

**Files:**
- Create: src/talkpath/adapters/lessonlens_markdown.py
- Create: tests/unit/test_lessonlens_markdown.py
- Create: tests/fixtures/lesson_draft.json
- Create: data/lessonlens/.gitkeep

- [x] **Step 1: 寫 repository round-trip 測試**

測試 save_lesson_draft 寫出：

```text
<root>/curricula/junior-high/grade-1/english/lesson-01/lesson.md
<root>/curricula/junior-high/grade-1/english/lesson-01/vocabulary/<content_id>.md
<root>/curricula/junior-high/grade-1/english/lesson-01/grammar/<content_id>.md
<root>/curricula/junior-high/grade-1/english/lesson-01/sources/<image_id>
```

再用 get_lesson 讀回，確認 scope、content_items、source_images 與 operation_id 相同。

- [x] **Step 2: 執行測試確認失敗**

Run: uv run pytest tests/unit/test_lessonlens_markdown.py -q

Expected: FAIL，因為 Markdown repository 尚未存在。

- [x] **Step 3: 實作安全且可重試的 Markdown adapter**

實作：

- 以 lesson_id 產生固定目錄，拒絕 ..、絕對路徑與非法字元。
- Properties 使用 YAML frontmatter，內容使用 Markdown headings。
- 先寫入暫存檔，再以 atomic replace 更新正式檔案。
- 以 operation_id 判斷相同操作是否已完成，重試不得重複追加內容。
- source image 只接受 ImageReference 已核准的來源。
- get_lesson 找不到資料時回傳 None，不把解析錯誤吞掉。

- [x] **Step 4: 執行 repository 測試**

Run: uv run pytest tests/unit/test_lessonlens_markdown.py -q

Expected: all tests pass。

## Task 4: 實作 SQLite 學習進度 repository

**Files:**
- Create: src/talkpath/adapters/sqlite_progress.py
- Create: tests/unit/test_sqlite_progress.py
- Modify: src/talkpath/config.py

- [x] **Step 1: 寫建立 session、記錄作答與錯題查詢測試**

測試以下行為：

```python
session = repo.create_session("local-child", lesson_id)
repo.record_attempt(session.id, activity_id, correct=False, score=0.0)
items = repo.list_review_items(session.id, lesson_id)
assert items[0].activity_id == activity_id
```

同一個 operation_id 重複記錄時只能產生一筆結果。

- [x] **Step 2: 執行測試確認失敗**

Run: uv run pytest tests/unit/test_sqlite_progress.py -q

Expected: FAIL，因為 repository 尚未存在。

- [x] **Step 3: 建立 SQLite schema 與 transaction**

建立三張表：

```sql
learning_sessions(
  id TEXT PRIMARY KEY,
  learner_key TEXT NOT NULL,
  lesson_id TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)

attempts(
  operation_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  activity_id TEXT NOT NULL,
  correct INTEGER NOT NULL,
  score REAL NOT NULL,
  feedback TEXT NOT NULL,
  created_at TEXT NOT NULL
)

review_items(
  session_id TEXT NOT NULL,
  lesson_id TEXT NOT NULL,
  activity_id TEXT NOT NULL,
  mistake_count INTEGER NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(session_id, activity_id)
)
```

所有寫入使用 transaction；資料庫首次使用時自動建立 schema。

- [x] **Step 4: 執行 SQLite 測試**

Run: uv run pytest tests/unit/test_sqlite_progress.py -q

Expected: all tests pass。

## Task 5: 實作模型與語音 provider adapters

**Files:**
- Create: src/talkpath/adapters/http_model_services.py
- Create: src/talkpath/adapters/fake_services.py
- Create: tests/unit/test_fake_services.py
- Create: tests/unit/test_http_model_services.py
- Modify: src/talkpath/config.py

- [x] **Step 1: 寫 fake provider 測試**

Fake VisionService 回傳固定 LessonDraft；Fake TextService 回傳一題 vocabulary_quiz；Fake STT 回傳 Transcript；Fake TTS 回傳固定音訊 bytes。測試所有輸出符合 Task 2 的資料模型。

- [x] **Step 2: 寫 HTTP adapter contract 測試**

使用 httpx MockTransport 測試：

- POST /extract 回傳 LessonDraft。
- POST /activity 回傳 ActivityDraft。
- POST /transcribe 回傳 Transcript。
- POST /synthesize 回傳 audio bytes。
- 非 2xx、逾時與無效 JSON 轉成 ProviderUnavailable、ProviderTimeout、ProviderResponseInvalid。

- [x] **Step 3: 實作 provider registry**

設定檔提供：

```yaml
vision_provider: fake
text_provider: fake
stt_provider: fake
tts_provider: fake
vision_endpoint: null
text_endpoint: null
stt_endpoint: null
tts_endpoint: null
```

provider registry 根據設定建立 fake 或 HTTP adapter；UI 與 Pi 不直接建立 provider。

- [x] **Step 4: 執行 provider 測試**

Run: uv run pytest tests/unit/test_fake_services.py tests/unit/test_http_model_services.py -q

Expected: all tests pass。

## Task 6: 實作 Pi RPC client 與白名單 extension

**Files:**
- Create: src/talkpath/agent/pi_rpc.py
- Create: tests/unit/test_pi_rpc.py
- Create: tests/fixtures/fake_pi_rpc.py
- Create: pi-extension/package.json
- Create: pi-extension/tsconfig.json
- Create: pi-extension/talkpath-tools.ts
- Create: pi-extension/test/tool_bridge.test.ts
- Modify: src/talkpath/config.py

- [x] **Step 1: 寫 Pi JSONL parser 與 request correlation 測試**

測試 fake Pi 輸出以下訊息時，Python 可以正確解析並分派：

```json
{"type":"response","id":"r1","command":"prompt","success":true}
{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Hello"}}
{"type":"agent_settled"}
```

測試 CRLF 輸入、空白行、無效 JSON、未知事件與 process EOF。

- [x] **Step 2: 寫 PiRpcClient 生命週期測試**

使用 tests/fixtures/fake_pi_rpc.py 模擬：

- start 後可送 prompt。
- prompt 會等待 agent_settled。
- abort 會停止等待。
- 子程序退出時回傳 PiProcessExited。
- 同一 operation_id 不重複送出寫入型工具請求。

- [x] **Step 3: 實作 PiRpcClient**

PiRpcClient 必須：

- 使用 asyncio.create_subprocess_exec 啟動 Pi。
- 使用 stdin 傳送一行一個 JSON command。
- 使用自訂 LF reader，不用會把 U+2028/U+2029 當換行的通用 reader。
- 以 request ID 管理 pending futures。
- 將 message_update、tool_execution_*、agent_settled、extension_error 轉成 Python event。
- 提供 prompt、abort、new_session、close。
- 啟動命令由 config 組成：pi、--mode、rpc、--no-session、--no-builtin-tools、--extension。
- 不把模型 API key 寫入 prompt 或 UI event。

- [x] **Step 4: 寫 TypeScript extension tool schema 測試**

確認 extension 只註冊：

```text
extract_lesson
save_lesson_draft
generate_activity
evaluate_answer
evaluate_pronunciation
transcribe_audio
synthesize_speech
save_learning_result
```

工具參數必須驗證 image reference、course scope、operation ID 與 payload size；未知工具不得被註冊。

- [x] **Step 5: 實作 TypeScript extension**

extension 使用 Pi registerTool 註冊工具；每個工具將請求送到 Python 內部工具 endpoint，取得結果後轉成 Pi tool result。不得呼叫 shell、任意檔案路徑或外部網路。

- [x] **Step 6: 執行 Python 與 TypeScript 測試**

Run: uv run pytest tests/unit/test_pi_rpc.py -q

Expected: all Python RPC tests pass。

Run: npm install --prefix pi-extension

Expected: dependencies install without errors。

Run: npm run typecheck --prefix pi-extension

Expected: TypeScript typecheck exits 0。

## Task 7: 建立 session service 與課本匯入 API

**Files:**
- Create: src/talkpath/application/session_service.py
- Create: src/talkpath/api/routes.py
- Create: src/talkpath/api/internal_tools.py
- Create: tests/api/test_import_flow.py
- Create: tests/api/test_internal_tools.py
- Modify: src/talkpath/api/app.py

- [x] **Step 1: 寫課本匯入 API 的失敗測試**

建立以下 API contract：

```text
POST /api/sessions
POST /api/sessions/{session_id}/images
POST /api/sessions/{session_id}/scope
POST /api/sessions/{session_id}/import
POST /api/sessions/{session_id}/activities/generate
GET  /api/sessions/{session_id}
GET  /api/lessons/{lesson_id}
WS   /ws/sessions/{session_id}
```

測試順序：

1. 建立 session。
2. 上傳圖片取得 image reference。
3. 未確認 scope 直接呼叫 import，回傳 409。
4. 確認國中一年級、英文、第一課。
5. 使用 fake Pi 完成 import，回傳 draft lesson。
6. 呼叫 generate，保存一個 activity。

- [x] **Step 2: 執行 API 測試確認失敗**

Run: uv run pytest tests/api/test_import_flow.py -q

Expected: FAIL，因為 routes 與 SessionService 尚未存在。

- [x] **Step 3: 實作 session service**

SessionService 負責：

- 建立單一小朋友 learning session。
- 驗證圖片格式、大小與暫存期限。
- 強制 scope confirmation gate。
- 將 import operation 交給 PiRpcClient。
- 接收 Pi 事件並更新 session state。
- 將 draft 保存到 LessonRepository。
- 產生題目後保存 ActivityDocument。
- 服務錯誤時保留 FAILED state 與 retryable 錯誤碼。

- [x] **Step 4: 實作公開 API 與內部工具 API**

公開 API 只處理小朋友 UI 所需資料；internal_tools 只允許由本機 Pi extension 使用，至少包含：

```text
POST /internal/tools/extract_lesson
POST /internal/tools/save_lesson_draft
POST /internal/tools/generate_activity
POST /internal/tools/evaluate_answer
POST /internal/tools/transcribe_audio
POST /internal/tools/synthesize_speech
POST /internal/tools/save_learning_result
```

internal endpoint 必須檢查 loopback、內部 token、operation ID 與 Pydantic schema；不把它們列入公開 OpenAPI 使用流程。

- [x] **Step 5: 執行 API 與內部工具測試**

Run: uv run pytest tests/api/test_import_flow.py tests/api/test_internal_tools.py -q

Expected: all tests pass。

## Task 8: 建立兒童 Web UI 垂直流程

**Files:**
- Create: frontend/index.html
- Create: frontend/app.js
- Create: frontend/styles.css
- Modify: src/talkpath/api/app.py
- Create: tests/api/test_static_ui.py

- [x] **Step 1: 寫 UI smoke test**

使用 FastAPI TestClient 確認：

- GET / 回傳 index.html。
- index.html 包含首頁、新增課程、課程範圍確認、課程總覽與結果區塊。
- frontend/app.js 與 frontend/styles.css 都可被取得。

- [x] **Step 2: 實作靜態 UI 骨架**

畫面只保留小朋友使用流程：

```text
首頁
新增課程
課程範圍確認
萃取處理狀態
課程預覽
課程總覽
結果與錯題複習
學習進度
```

所有活動使用同一個 ActivityPanel，不為每種題型複製一套頁面。

- [x] **Step 3: 實作圖片上傳與範圍確認**

app.js 使用 FormData 上傳圖片，呼叫 session API；未確認 scope 前停留在確認畫面；確認後顯示狀態與 Pi agent 回覆。

- [x] **Step 4: 實作 WebSocket 事件處理**

將 message_update 顯示在 agent message 區；將 extracting、generating、ready、failed 映射為可讀狀態；斷線後顯示重試按鈕，不清除已上傳的 session。

- [x] **Step 5: 實作課程總覽與活動卡片**

顯示詞彙練習、詞彙測驗、文法說明與練習、文法測驗、聽力練習、聽力測驗、閱讀／朗讀、口說練習。尚未設定音訊 provider 時，音訊活動顯示可重試訊息與文字替代，不讓整個頁面失效。

- [x] **Step 6: 執行 UI smoke test**

Run: uv run pytest tests/api/test_static_ui.py -q

Expected: all UI static tests pass。

## Task 9: 接上活動、作答回饋與語音接口

**Files:**
- Create: src/talkpath/application/activity_service.py
- Create: tests/unit/test_activity_service.py
- Create: tests/api/test_activity_flow.py
- Modify: src/talkpath/api/routes.py
- Modify: frontend/app.js

- [x] **Step 1: 寫活動生成與作答測試**

測試 fake TextService 產生 vocabulary_quiz 與 grammar_practice；作答後由 evaluate_answer 回傳：

```json
{
  "correct": false,
  "score": 0.0,
  "feedback": "Try again.",
  "review_item": true
}
```

確認錯題會寫入 ProgressRepository，且相同 operation ID 不會重複計算。

- [x] **Step 2: 實作 ActivityService**

ActivityService 負責：

- 只從已保存 LessonDocument 生成題目。
- 將 source_content_ids 寫入 ActivityDocument。
- 驗證 activity type 與 lesson_id 一致。
- 將答案交給 TextService。
- 寫入 attempt 與 review item。
- 回傳適合 UI 顯示的提示與下一步。

- [x] **Step 3: 加入語音 API**

提供：

```text
POST /api/sessions/{session_id}/speech/transcribe
POST /api/sessions/{session_id}/speech/synthesize
```

API 只依賴 SpeechToTextProvider 與 TextToSpeechProvider；第一版用 fake provider 跑 contract test，真實地端 provider 由 endpoint 設定切換。

- [x] **Step 4: 接上活動互動 UI**

ActivityPanel 根據 activity type 顯示文字、播放、錄音、提示、重新作答與結果；沒有 provider 時使用文字 fallback。

- [x] **Step 5: 執行 activity 與 speech 測試**

Run: uv run pytest tests/unit/test_activity_service.py tests/api/test_activity_flow.py -q

Expected: all tests pass。

## Task 10: 完成端到端驗證與交付文件

**Files:**
- Create: tests/integration/test_textbook_to_activity.py
- Create: tests/integration/test_failure_recovery.py
- Modify: README.md
- Modify: docs/talkpath-progress.md
- Modify: docs/superpowers/specs/2026-08-10-talkpath-design.md

- [x] **Step 1: 寫完整文字垂直流程測試**

使用 fake Pi、fake Vision、fake Text、fake STT/TTS 與 temporary LessonLens：

1. 建立 session。
2. 上傳一張 fixture image metadata。
3. 確認國中一年級、英文、第一課。
4. 完成 Pi import。
5. 驗證 LessonLens lesson.md 與 vocabulary/grammar 檔案。
6. 生成一組 vocabulary_quiz。
7. 完成一次錯誤作答。
8. 驗證 SQLite review item。
9. 驗證 UI 可取得 lesson、activity、progress。

- [x] **Step 2: 寫失敗恢復測試**

測試圖片不完整、scope 未確認、Vision timeout、Pi process exit、Obsidian write failure、TTS unavailable；每個情境都要確認錯誤碼、retryable 狀態與資料不被半寫入。

- [x] **Step 3: 執行完整測試**

Run: uv run pytest -q

Expected: all Python tests pass with zero failures。

Run: npm run typecheck --prefix pi-extension

Expected: TypeScript typecheck exits 0。

- [x] **Step 4: 更新 README 與進度**

README 必須說明：

```text
uv sync
uv run uvicorn talkpath.api.app:create_app --factory --reload
uv run pytest
pi --mode rpc --no-session --no-builtin-tools --extension pi-extension/talkpath-tools.ts
```

進度文件標記第一版垂直流程已完成或列出實際尚未完成項目，不宣稱尚未驗證的模型整合已完成。

- [x] **Step 5: 建立交付檢查點**

確認以下結果後，才進入下一個功能週期：

- 課本圖片到 LessonLens 的文字流程可在 fake provider 下完整運作。
- 課程範圍確認 gate 有測試保護。
- Pi 只使用白名單工具。
- 音訊 provider 可替換，沒有綁死雲端服務。
- 失敗與重試不會重複寫入課程或作答紀錄。

## 設計規格覆蓋檢查

- 兒童單一使用者與 UI 導覽：Tasks 7–9。
- 課程範圍確認與圖片萃取：Tasks 2、5、7、10。
- LessonLens Obsidian 資料：Task 3、Task 10。
- Python／Pi RPC、extension、白名單工具：Task 6、Task 7。
- TextService、VisionService、STT、TTS provider：Task 5、Task 9。
- SQLite 進度、錯題與冪等寫入：Task 4、Task 9、Task 10。
- 錯誤處理、取消、逾時與重試：Task 6、Task 7、Task 10。
- Web UI 與事件串流：Task 8、Task 9。
- 隱私與資料保存：Tasks 1、3、4、6、7、10。

## 計畫自我檢查

- 未留下未定義的佔位符或空泛的後續步驟。
- 每個實作區塊都有明確檔案路徑與測試命令。
- Python 的 CourseScope、LessonDraft、Activity、Pi event 與 repository 方法在各任務中使用一致名稱。
- 計畫只建立一個 MVP 垂直流程；聽力與口說先完成接口、fake provider 與 UI fallback，再接入實際地端模型。
