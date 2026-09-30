# MY LESSONS 課程管理：課程詳情、附加匯入與頁碼警示 設計規格

- 日期：2026-09-30
- 狀態：已實作（2026-09-30，分支 `feat/lesson-library-append`），待使用者以真實模型實測
- 實作計畫：`docs/superpowers/plans/2026-09-30-lesson-library-append-import-implementation.md`

## 1. 目標

1. MY LESSONS 可檢視每一課的內容：已上傳的照片，以及從各照片抽取出的內容。
2. 課程群組鍵為 PROGRAM、GRADE、SUBJECT、LESSON，再加上 TEXTBOOK（出版社版本，例如康軒、翰林）。
3. 在 NEW LESSON 上傳時，若同一課程已存在，新內容以附加方式加入，不刪除舊內容。
4. 頁碼與已匯入頁碼重複時提示警示，由使用者選「取消」或「仍要加入」。

## 2. 最高約束：不碰已完善的生成邏輯

上一輪「同課程分次匯入」（分支 `feat/incremental-lesson-import`，已重設）改了 35 個檔案、約 4,000 行，並動到抽取與提示詞路徑，導致課程內容生成全面異常，最後整個取消。本次必須遵守：

1. **不得修改**：`adapters/openai_compatible_services.py`（提示詞與 provider）、vision／text 抽取及活動生成的實作、`api/internal_tools.py`、Pi extension。
2. 抽取流程完全照舊：新照片走原本的抽取，產生一份獨立的 `LessonDraft`；**合併只在儲存前進行**，唯一插入點為 `SessionService._save_lesson_draft`。direct 與 Pi 兩條後端路徑都經過這一點。
3. `LessonDraft`、`ContentItem` 的欄位不變（它們是抽取輸出的契約）；批次資訊另存。
4. 不引入新套件、檔案鎖、fingerprint 或 receipt 機制。本機單人使用，沿用既有的 `_operation_lock`。

## 3. 課程識別（加入 TEXTBOOK）

欄位定義（2026-09-30 與使用者確認）：

| 欄位 | 定義 | 納入識別 |
|---|---|---|
| PROGRAM | 學程，例如國中（junior high） | 是 |
| GRADE | 年級，例如 7 | 是 |
| SUBJECT | 科目，例如英語 | 是 |
| LESSON | 課次，只取數字，例如 lesson-01 | 是 |
| TEXTBOOK | 出版社版本，例如康軒、翰林、南一、何嘉仁 | 是（本次新增） |
| EDITION | 描述用，不定義特定含義 | 否 |
| PAGES | 本次上傳的頁碼 | 否（用於重複警示） |

已知限制（使用者確認接受）：冊次（上、下學期）不納入識別，因此 7 上 L1 與 7 下 L1 會視為同一課並互相附加。非數字課次（Review 1、Starter）的撞號問題，本期也不處理。兩者都記入 `IDEAS.md`。

- TEXTBOOK 為空：`lesson_id` 維持現行格式 `<program>-grade-N-<subject>-lesson-NN`，既有課程與 SQLite 進度的 key 完全不變，不需要 migration。
- TEXTBOOK 有值：`lesson_id` = 現行格式 + `--` + textbook slug，例如 `junior-high-grade-7-english-lesson-01--u5eb7-u8ed2`（康軒）。
- 目錄：`curricula/<program>/<grade>/<subject>/lesson-01--<textbook>/`。`_lesson_id_from_dir` 取最後四層的邏輯不變。
- 修改點：`CourseScope.validate_lesson_id`、`_LESSON_ID` 正規式（lesson 群組允許 `--<slug>` 後綴）。
- EDITION 不納入識別，只作為描述資訊。
- 相容：已存檔且填過 textbook、但 `lesson_id` 沒有後綴的舊課程，`CourseScope` 仍接受該舊 ID（否則讀取時驗證失敗）；新建課程一律帶後綴。因此舊課程再用同一 textbook 匯入時，會被視為另一門課程（不會附加到舊課程）。
- 前端 Textbook 欄位的 placeholder 改為提示填寫出版社版本（例如 `Publisher, e.g. 康軒`）。

## 4. 匯入批次（import batch）

課程文件 frontmatter 新增 `import_batches`：

```yaml
import_batches:
  - operation_id: import-...
    pages: ['3']
    source_images: [image-...]
    content_ids: [pronoun-table, contractions]
    skipped_duplicates: 0
    imported_at: 2026-09-30T10:00:00+08:00
```

- 舊課程沒有這個欄位：讀取時推導出一個隱含批次（operation_id、scope.pages、全部 source_images、全部 content_ids），下一次附加時才寫入檔案。
- `content_ids` 只含該批實際新增的項目；`skipped_duplicates` 記錄被略過的重複數。Pi 路徑第二次儲存時會靠它讀回略過數。
- 由 repository 的新方法 `get_import_batches(lesson_id)` 讀取。`_parse_lesson` 忽略此欄位，`LessonDraft` 不變。

## 5. 附加合併規則（domain 純函式 `merge_lesson(existing, incoming)`）

1. 舊的 `content_items` 內容、ID、順序全部保留，不重新抽取、不改寫。
2. 新項目接在後面。若 `(type, content_id)` 與既有項目衝突，新項目的 ID 加上 `-2`、`-3`…後綴。舊 ID 不變，所以既有活動與學習紀錄仍然有效。
3. `title`、scope 的課程欄位（textbook、edition）保留舊值。`scope.pages` 取有序聯集。
4. `passage`：舊課文 + 空行 + 新課文（新課文為空則略過）。
5. `source_images`：舊 + 新。`provider`、`model`、`operation_id` 記錄最新一批。
6. 冪等：`import_batches` 已有相同 operation_id 時直接略過。Pi 路徑會存兩次（internal tool 一次，`import_lesson` 一次），因此這條規則必須成立。
7. 去重（新項目與既有項目重複時，捨棄新項目、保留舊項目與舊 ID）：
   - vocabulary：取 `content` 的 `english`（或 `word`；若 `content` 為字串則取字串本身），`strip().casefold()` 後比對。
   - 其他類型：同類型且 `content` 完全相同才算重複。
   - 批次的 `content_ids` 只記錄實際新增的項目；被捨棄的數量回傳給前端顯示（例如「3 duplicates skipped」）。

## 6. 儲存（repository）

`save_lesson_draft` 新增選填參數 `import_batches`。另外調整：來源照片若已在課程 `sources/` 且屬於既有課程，則保留原檔，不要求本次核准、也不重寫；只寫入新照片。其他行為（staging、原子發布、失敗還原）不變。

## 7. Session scope 同步（上一輪的地雷）

Pi 路徑的 `save_lesson_draft`、`generate_activity_for_lesson` 會比對 `lesson.scope == session scope`。附加後 pages 變成聯集，兩邊會不一致。處理方式：合併儲存成功後，把 `self._scopes[session_id]` 更新成合併後課程的 scope，比照既有的「進入已存課程」做法（`session_service.py:233`）。`ImportResult.lesson` 回傳合併後的完整課程。

## 8. API

| 端點 | 用途 |
|---|---|
| `POST /api/lessons/import-check`（body：CourseScope） | 純讀取，回傳 `lesson_id`、`exists`、`title`、`existing_pages`、`overlapping_pages`、`content_item_count` |
| `GET /api/lessons/{lesson_id}/batches` | 回傳批次清單（頁碼、照片 ID、content_ids、時間） |
| `GET /api/lessons/{lesson_id}/images/{image_id}` | 回傳來源照片；image_id 必須屬於該課程，不安全或不屬於該課的 ID 回 404；依檔頭判斷 MIME（jpeg、png、gif、webp），判斷不出來回 `application/octet-stream`，一律加 `X-Content-Type-Options: nosniff` |

`POST /api/sessions/{id}/import` 的回應新增 `skipped_duplicates`。import-check 的 scope 不完整（缺欄位或空白）回 422。

頁碼比對：`"12-13"` 展開成 {12, 13}；逗號分隔；非數字的值以字串比對。

## 9. 前端

1. **確認 scope（Step 2）**：送出前先呼叫 import-check。
   - 課程不存在，或已存在且頁碼沒有重疊：不打斷流程，直接匯入；匯入完成後預覽頁顯示「Added to your existing lesson. N repeated items were skipped.」。
   - 頁碼重疊：顯示警示「Page 3 was already added to this lesson…」，按鈕「Cancel」／「Add anyway」；修改任何欄位會收起警示。
   - 課程已存在但未填頁碼：同樣以警示提示無法檢查重複，可選 Add anyway。
2. **MY LESSONS**：每張課程卡有兩個按鈕：「View lesson」進入新的課程詳情畫面 `lesson-detail`；「Continue →」沿用既有行為，直接進入練習（保留原本的快速路徑）。卡片與詳情頁的 scope 摘要會顯示 textbook。
   - 標題、scope（含 textbook）。
   - 每個批次一區：頁碼、照片縮圖（點擊在新分頁開原圖），以及該批的內容項目（類型＋摘要）。
   - 「Start practice」按鈕，沿用既有 `enterSavedLesson`。
3. UI 文字沿用既有英文風格。

## 10. 不在本期（記入 IDEAS）

同頁取代或刪除、一次多選照片、冊次納入識別、非數字課次、既有課程的 textbook 補填或改名。

## 11. 驗收

- 既有測試全部通過（基準：336 passed、9 skipped）。
- 附加時重複的單字與完全相同的內容不會重複出現。
- 附加後，同一 session 內可以生成活動（direct 與 fake Pi 兩條路徑都要測）；另開 session 進入該課程也可以生成活動。
- 舊課程（沒有 `import_batches`、沒有 textbook）的讀取、進入、練習行為不變。
- 以真實模型實測：第一次匯入 p.3，再附加 p.4，兩頁內容都在、活動可生成。由使用者確認；未實測前不宣告完成。

### 已完成的驗證（2026-09-30）

- `uv run pytest -q` → 385 passed、9 skipped、1 warning；`node --test frontend/test/screen-flow.test.cjs` → 3 passed。
- 瀏覽器（Chrome，僅 fake provider、暫存資料夾）走完：首次匯入、附加並回報略過數、頁碼重複警示（Cancel／改欄位收起／Add anyway）、不同 textbook 不警示、課程詳情（每批頁碼、縮圖載入、內容項目）、從詳情頁與卡片進入練習並生成活動、手機寬度無橫向捲動。
- 禁止修改清單（提示詞、internal_tools、pi-extension）的 diff 為空。
