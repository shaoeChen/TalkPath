# MY LESSONS 課程管理：課程詳情、附加匯入與頁碼警示 Implementation Plan

> **For agentic workers:** 依 Task 順序執行，每個 Task 先寫失敗測試，確認失敗後再做最小實作，並跑指定的回歸測試。每完成一個 Task，立即在 `docs/PROGRESS.md` 記錄驗證結果。

**Goal:** 讓 MY LESSONS 可檢視每課的照片與內容；課程以 program、grade、subject、lesson、textbook（出版社版本）分群；同課程再匯入時以附加方式保留舊內容；頁碼重複時警示。

**Architecture:** 抽取流程完全不動。合併只放在 `SessionService._save_lesson_draft` 這個唯一插入點，由 domain 純函式 `merge_lesson` 處理。批次資訊存在 lesson.md 的 frontmatter `import_batches`，`LessonDraft` 欄位不變。新增三個唯讀或檢查用的 API，前端新增 scope 警示與課程詳情畫面。

**Spec:** `docs/superpowers/specs/2026-09-30-lesson-library-append-import-design.md`

---

## 禁止修改（違反即停下回報）

- `src/talkpath/adapters/openai_compatible_services.py`
- vision／text 抽取與活動生成的實作、提示詞
- `src/talkpath/api/internal_tools.py`、`pi-extension/`
- `LessonDraft`、`ContentItem` 欄位

若某個 Task 看起來非改上述檔案不可，先停下來向使用者說明。

## 前置確認

- 工作目錄：`D:\python\TalkPath`；開新分支 `feat/lesson-library-append`。
- 基準：`uv run pytest -q` → 336 passed、9 skipped、1 warning。
- 讀 spec 第 2、7 節（上一輪失敗原因與 scope 同步）。

### Task 1：TEXTBOOK 納入 lesson_id

**Files:** `src/talkpath/domain/models.py`、`src/talkpath/adapters/lessonlens_markdown.py`（`_LESSON_ID`）、`tests/unit/test_models*.py`、`tests/unit/test_lessonlens_markdown.py`

- [ ] 失敗測試：textbook 為 None 或空白時，ID 與現行相同；textbook="康軒" 時 ID 以 `--u5eb7-u8ed2` 結尾；兩個不同 textbook 產生不同 ID；帶後綴的 ID 可存取並由目錄反推回原 ID；既有 `data/` 格式的課程仍可解析。
- [ ] 實作：`validate_lesson_id` 在 textbook 有值時附加 `--<_slug(textbook)>`；`_LESSON_ID` 的 lesson 群組改為 `lesson-[0-9]+(?:--[a-z0-9]+(?:-[a-z0-9]+)*)?`。
- [ ] 回歸：`uv run pytest tests/unit -q`

### Task 2：`merge_lesson` 與頁碼正規化（純函式）

**Files:** Add `src/talkpath/domain/lesson_merge.py`、`tests/unit/test_lesson_merge.py`

- [ ] 失敗測試，逐條對應 spec 第 5 節：舊項目不變、衝突 ID 改為 `-2`／`-3`、pages 有序聯集、title 和 textbook 保留、passage 串接（空的略過）、source_images 合併、provider／model／operation_id 取新值；去重（vocabulary 比對 english／word 的 casefold、其他類型比對 content 完全相同；捨棄新項目、保留舊 ID；批次 content_ids 只含新增項目；回傳捨棄數量）；`normalize_pages(["12-13","5"])` → {"12","13","5"}；`overlapping_pages`。
- [ ] 實作：`ImportBatch` 模型（operation_id、pages、source_images、content_ids、imported_at）、`merge_lesson(existing, incoming) -> MergeResult`（lesson、batch、skipped_duplicates）、`normalize_pages`、`overlapping_pages`、`legacy_batch(lesson)`。
- [ ] 回歸：`uv run pytest tests/unit/test_lesson_merge.py -q`

### Task 3：Repository 支援附加儲存、批次、讀取照片

**Files:** `src/talkpath/adapters/lessonlens_markdown.py`、`src/talkpath/ports/lesson_repository.py`、`tests/unit/test_lessonlens_markdown.py`

- [ ] 失敗測試：
  - 舊課程加上新照片後儲存：舊照片檔保留且不需重新核准，新照片寫入，frontmatter 有 `import_batches`。
  - `get_import_batches` 對舊課程回傳一個隱含批次。
  - 重新讀回的 `LessonDraft` 與合併結果相同。
  - `source_image_path(lesson_id, image_id)`：不屬於該課程的 image_id 拒絕，路徑逃逸拒絕。
- [ ] 實作：`save_lesson_draft(..., import_batches=None)`；`_find_obsolete_managed_files` 與 source payload 對既有照片改為保留原檔；`_render_lesson` 在有批次時寫入 `import_batches`；新增 `get_import_batches`、`source_image_path`。
- [ ] 回歸：`uv run pytest tests/unit/test_lessonlens_markdown.py -q`

### Task 4：Service 合併插入點與 scope 同步

**Files:** `src/talkpath/application/session_service.py`、`tests/unit/test_session_service.py`、`tests/integration/`（新檔 `test_append_lesson_import.py`）

- [ ] 失敗測試（fake provider）：
  - 兩個 session 先後匯入同一 scope 的 p.3、p.4：`ImportResult.lesson` 與 `get_lesson` 都含兩頁內容，舊 content_id 不變。
  - **附加後在同一 session 生成活動成功**（direct backend）。
  - **附加後在同一 session 生成活動成功**（fake Pi backend，會經過 internal `save_lesson_draft` 與 `import_lesson` 兩次儲存，驗證冪等不重複）。
  - 另開 session 進入該課程後生成活動成功。
  - 相同 operation_id 重送不會重複附加。
  - `check_import(scope)`：回傳 exists、existing_pages、overlapping_pages。
- [ ] 實作：`_save_lesson_draft` 先讀既有課程；存在且 operation_id 尚未在批次中時，呼叫 `merge_lesson`，並帶 `import_batches` 儲存；已在批次中則略過。儲存後把 `_scopes[session_id]` 更新成合併後的 scope。`import_lesson` 的 `ImportResult.lesson` 改成重新讀取的完整課程。新增 `check_import`、`get_import_batches`、`lesson_image_path`。
- [ ] 回歸：`uv run pytest tests/unit tests/integration -q`

### Task 5：API 端點

**Files:** `src/talkpath/api/routes.py`、`tests/api/test_lesson_list.py`

- [ ] 失敗測試：`POST /api/lessons/import-check`（不存在、存在、頁碼重疊）；`GET /api/lessons/{id}/batches`；`GET /api/lessons/{id}/images/{image_id}` 回傳 200 且 content-type 正確，其他課程的 image_id 回 404。
- [ ] 實作三個路由；照片以 `FileResponse` 回傳，MIME 依 magic bytes（jpeg、png、webp）判斷。
- [ ] 回歸：`uv run pytest tests/api -q`

### Task 6：前端 scope 警示與課程詳情畫面

**Files:** `frontend/index.html`、`frontend/app.js`、`frontend/styles.css`、`tests/api/test_static_ui.py`

- [ ] 失敗測試（來源契約）：`#lesson-detail-screen` 存在；卡片點擊改開詳情頁；詳情頁有「Start practice」並呼叫 `enterSavedLesson`；scope 送出前呼叫 `/api/lessons/import-check`；有 `#scope-notice` 與 Cancel／Add anyway 按鈕。
- [ ] 實作：
  - Textbook 欄位 placeholder 改為 `Publisher, e.g. 康軒`。
  - scope 表單：在送出流程最前面做 import-check；已存在就顯示提示；頁碼重疊時暫停，等使用者選擇；Cancel 回到表單；Add anyway 繼續原流程（原本的 `/scope` 與 `runImport` 不改）。
  - 詳情頁：取得 lesson 與 batches，依批次呈現頁碼、縮圖（`<img>` 指向 images 端點，點擊開新分頁）、內容摘要。
  - `resetForNewCourse` 重置新增的 state。
- [ ] 回歸：`uv run pytest tests/api/test_static_ui.py -q`、`node --test frontend/test`

### Task 7：整體驗證與交接

- [ ] `uv run pytest -q` 全綠，數量不少於基準加新增數。
- [ ] `git diff --stat main`：確認「禁止修改」清單中的檔案沒有出現。
- [ ] 請使用者用真實模型實測：新課程匯入 p.3 → 附加 p.4 → 詳情頁看到兩批，重複單字沒有重複出現 → 生成各類活動正常 → 重複匯入 p.4 時出現警示。
- [ ] 通過後更新 `HISTORY.md`、刪除 `PROGRESS.md` 項目；延伸想法寫入 `IDEAS.md`。
