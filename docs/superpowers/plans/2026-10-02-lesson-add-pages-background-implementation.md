# 既有課程多頁匯入與背景提取實作計畫書

> 使用者後續授權開始實作並選擇協作方式；實際採主代理整合、儲存／前端模組子代理與獨立審查。原計畫中的程式片段為示意，實際名稱與調整見驗證記錄。

**目標：** 既有課程可一次新增多頁，後端獨立提取、保存成功頁、通知前端，失敗或中斷頁於課程詳情單獨 Retry。

**架構：** SQLite 保存工作與逐頁狀態，單一應用程式管理的非同步 worker 逐頁呼叫現有匯入。保留模型與 Pi 契約；同步儲存移交 thread，匯入鎖縮至每 session，LessonLens 合併與發布以同一可重入鎖保護。

**技術：** Python 3.12、FastAPI、asyncio、SQLite、Pydantic、原生 HTML／CSS／JavaScript、pytest／pytest-asyncio、Node 內建測試。無新增外部工作佇列依賴。

**規格：** [既有課程多頁匯入與背景提取](../specs/2026-10-02-lesson-add-pages-background-design.md)。

**狀態：** 程式及自動化驗證完成，人工瀏覽器驗收待補。實際結果與需求覆蓋見 [驗證記錄](../../diagnostics/2026-10-02-page-import-validation.md)；未執行的人工步驟維持未勾選。

## 0. 執行界線與檔案配置

- 正式專案 `D:\python\TalkPath`。開始實作先讀憲章、PROGRESS、最新工作樹差異，保留使用者既有修改；依 `using-git-worktrees` 建立隔離工作樹。
- 有 `.codegraph/` 時，先 `codegraph explore` 再搜尋程式；本計畫已按目前 source 確認入口，實作時仍須確認行號變動。
- 不改抽取提示詞、OpenAI JSON 修復、Pi TypeScript/internal tool 契約、content 去重規則、新建課程一頁限制或 ID 格式。
- 依使用者後續授權可分配獨立模組代理；不把本功能與教材 ID migration、課本資料模型重做或模型替換混合。
- 測試全部使用臨時 SQLite、LessonLens、upload_root 與明確注入的 fake provider；禁止以正式 `.env` 建立測試服務。

| 建立／修改 | 責任 |
|---|---|
| 新增 `src/talkpath/domain/page_import.py` | 工作模型、狀態、計數與 PageUpload 值物件 |
| 新增 `src/talkpath/ports/page_import_repository.py` | 工作資料庫契約 |
| 新增 `src/talkpath/adapters/sqlite_page_import.py` | 新表、交易、領取、冪等及 Retry CAS |
| 新增 `src/talkpath/application/page_import_service.py` | 原圖、提交、worker、恢復及訂閱 |
| 修改 `src/talkpath/application/session_service.py` | 每 session 匯入鎖、儲存 offload，維持唯一合併入口 |
| 修改 `src/talkpath/ports/lesson_repository.py`、`src/talkpath/adapters/lessonlens_markdown.py` | 可重入鎖、完整讀－合併－發布隔離 |
| 新增 `src/talkpath/api/page_import_routes.py` | HTTP／WebSocket 契約及公開模型 |
| 修改 `src/talkpath/api/app.py` | 組裝、啟動恢復及 shutdown 順序 |
| 新增 `frontend/lesson-page-import.js` | 提交控制、工作快照及通知去重，可由 Node 測試 |
| 修改 `frontend/index.html`、`frontend/app.js`、`frontend/styles.css` | Add pages、狀態、Retry、MESSAGE 與導覽 |
| 新增 `tests/unit/test_page_import.py`、`tests/unit/test_sqlite_page_import.py` | 領域及持久化測試 |
| 新增 `tests/unit/test_page_import_service.py`、`tests/integration/test_page_import_recovery.py` | worker、保存與恢復行為 |
| 新增 `tests/api/test_page_imports.py`、`frontend/test/lesson-page-import.test.cjs` | API 與前端行為 |
| 修改 `tests/conftest.py` | 本計畫的 job／imports／lesson_id 測試 fixture |
| 修改既有 session／LessonLens／匯入／static UI 測試 | 相容與回歸 |
| 修改 `docs/PROGRESS.md`、`docs/HISTORY.md`、`docs/STRUCTURE.md`、`docs/TECHSTACKS.md`、`README.md` | 執行交接與實際完成後的操作說明 |

## 1. 共用契約

以下名稱為新程式的固定介面，各工作依此保持一致；內部同步 repository 由 service 使用 `asyncio.to_thread` 呼叫。

| 介面 | 參數／回傳及語意 |
|---|---|
| `PageUpload` | `page_label: str, content: bytes, mime_type: str`；frozen dataclass |
| `ImportPage` | 規格第 4 節全部頁面欄位，status 使用 `PageStatus` |
| `ImportJob` | 規格第 4 節全部 job 欄位，另有 `pages: list[ImportPage]`、status 與 counts 計算屬性 |
| `SQLitePageImportRepository(database_path)` | 與 progress 使用相同檔案，獨立連線／新表 |
| `create_job(job)` | 原子建立 job/pages；相同 operation_id＋fingerprint 回原 job，不同內容衝突 |
| `get_job(job_id)`、`list_jobs(lesson_id=None)` | 回 domain 快照，無資料的單筆回 None |
| `claim(page_id)` | CAS queued → running；成功回 True，其他狀態 False |
| `finish(page_id, status, error_code=None, error_message=None)` | 原子更新頁面與 job revision／完成版本，回最新 job |
| `retry(page_id, operation_id)` | CAS failed/interrupted → queued，或冪等重送；回最新 job |
| `PageImportService(session_service, repository, source_root)` | source_root 為 upload_root 下 page-imports；只由 backend 管理 |
| `start()`、`stop()`、`join()` | async；啟動前恢復、關閉 worker、測試等待佇列完成 |
| `submit(lesson_id, operation_id, uploads, allow_overlap=False)` | async，回 ImportJob；成功持久化才入隊 |
| `retry_page(job_id, page_id, operation_id)` | async，先檢查批次證據再 CAS／排入一頁 |
| `recover_pending()` | async，核對存檔證據；未完成工作中斷，不排入 queue |
| `subscribe()`、`unsubscribe(queue)` | 非阻塞事件訂閱；disconnect 不控制 worker |
| `get_source_path(job_id, page_id)` | 從 server metadata 安全解析，驗證歸屬、regular file、摘要與大小 |
| `_process_page(job_id, page_id)` | async，穩定 import_operation_id、新 session、fresh upload、原課程 scope |
| `_has_saved_batch(lesson_id, import_operation_id)` | 同步讀取受鎖保護的 batches；讀取失敗向上拋錯 |
| `_persist_lesson_draft(draft, source_references)` | 同步、唯一合併核心，回 LessonDraft，不碰 async queues/session cache |

所有時間存 UTC。job/page ID 由 server UUID 產生，不能採用檔名；頁面 processing 狀態為 queued 或 running。公開投影排除 source_key、sha256、scope_json、fingerprint、內部實體路徑，保留 page_label、狀態、計數、revision、completion_revision 及安全錯誤訊息。

領域模型使用以下欄位定義，搭配工作 1 的 PageStatus／page_counts／job_status。兩個狀態計算函式位於相同模組：

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import Field
from talkpath.domain.models import DomainModel

@dataclass(frozen=True)
class PageUpload:
    page_label: str
    content: bytes
    mime_type: str

class ImportPage(DomainModel):
    page_id: str = Field(default_factory=lambda: uuid4().hex)
    ordinal: int = Field(ge=0)
    page_label: str = Field(min_length=1)
    status: PageStatus = PageStatus.QUEUED
    source_key: str
    sha256: str
    mime_type: str
    size_bytes: int = Field(ge=1)
    import_operation_id: str
    attempt_count: int = Field(default=0, ge=0)
    retry_operation_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None

class ImportJob(DomainModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    operation_id: str
    lesson_id: str
    scope_json: str
    fingerprint: str
    pages: list[ImportPage] = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    completion_revision: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def counts(self):
        return page_counts(self.pages)

    @property
    def status(self):
        return job_status(self.pages)
```

## 工作 1：工作模型與 SQLite 持久化

**檔案：** 新增 domain、port、adapter，以及 `tests/unit/test_page_import.py`、`tests/unit/test_sqlite_page_import.py`。

- [x] 寫狀態／計數、重開 database、相同提交 ID 冪等、不同 fingerprint 衝突、claim CAS、雙擊 Retry 的失敗測試。

模型的狀態及計數核心：

```python
from enum import StrEnum

class PageStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

def page_counts(pages):
    counts = {status.value: 0 for status in PageStatus}
    for page in pages:
        counts[page.status.value] += 1
    return {"total": len(pages), **counts}

def job_status(pages):
    return "processing" if any(
        page.status in {PageStatus.QUEUED, PageStatus.RUNNING}
        for page in pages
    ) else "completed"
```

測試使用真 SQLite，不用記憶體 dict 模擬交易。fixture `job` 使用 `ImportJob` 建立完整兩頁 queued 記錄，固定 operation_id、fingerprint 與合法 source_key。測試內容：

在 `tests/conftest.py` 建立：

```python
import hashlib
import pytest
from talkpath.domain.page_import import ImportJob, ImportPage

@pytest.fixture
def lesson_id():
    return "junior-high-grade-7-english-lesson-01"

@pytest.fixture
def job(lesson_id):
    pages = [
        ImportPage(
            page_id=f"page-{number}", ordinal=index, page_label=str(number),
            source_key=f"job-1/page-{number}",
            sha256=hashlib.sha256(f"page{number}".encode()).hexdigest(),
            mime_type="image/png", size_bytes=len(f"page{number}".encode()),
            import_operation_id=f"page-import:page-{number}",
        )
        for index, number in enumerate([12, 13])
    ]
    return ImportJob(
        job_id="job-1", operation_id="submit-1", lesson_id=lesson_id,
        scope_json='{"program":"junior high","grade":"7","subject":"English","lesson":"1"}',
        fingerprint="fingerprint-1", pages=pages,
    )
```

```python
def test_claim_is_atomic_and_survives_reopen(tmp_path, job):
    from talkpath.adapters.sqlite_page_import import SQLitePageImportRepository
    path = tmp_path / "progress.sqlite"
    repo = SQLitePageImportRepository(path)
    repo.create_job(job)
    page_id = job.pages[0].page_id
    assert repo.claim(page_id) is True
    assert SQLitePageImportRepository(path).claim(page_id) is False
    assert repo.get_job(job.job_id).pages[0].status.value == "running"

def test_same_request_does_not_create_another_job(tmp_path, job):
    from talkpath.adapters.sqlite_page_import import SQLitePageImportRepository
    repo = SQLitePageImportRepository(tmp_path / "progress.sqlite")
    first = repo.create_job(job)
    second = repo.create_job(job)
    assert second.job_id == first.job_id
    assert len(repo.list_jobs()) == 1
```

- [x] 執行 `uv run pytest tests/unit/test_page_import.py tests/unit/test_sqlite_page_import.py -q`，確認先因新增契約未實作失敗。
- [x] 實作 Pydantic 模型及 port。job status/counts 由 pages 計算，不另存容易失真的計數。
- [x] 實作 schema，新表名稱為 `lesson_page_import_jobs`／`lesson_page_import_pages`。job 表 operation_id UNIQUE；pages 的 import_operation_id UNIQUE、job_id 外鍵、status CHECK；建立 active partial unique index：`(lesson_id, page_label, sha256) WHERE status IN ('queued','running')`。
- [x] 另建 `lesson_page_import_retries`：operation_id PRIMARY KEY、page_id 外鍵。接受 Retry 與 receipt insert 同交易；舊重試 ID 延遲重送不再提取（重複 queue delivery 由 claim CAS 拒絕），重試 ID 用於別頁回 409。加入接受兩次不同 Retry 後重送第一次 ID 的測試。
- [x] SQLite 沿用 connection-per-transaction、`PRAGMA foreign_keys=ON`、`BEGIN IMMEDIATE`，讀取驗證 JSON／enum，所有值用參數綁定。任一頁 insert 衝突回滾整個 job。
- [x] claim 使用 `UPDATE ... SET status='running' WHERE page_id=? AND status='queued'` 的 rowcount。Retry 的狀態判定、retry ID 比對與更新在同一交易；成功 retry 令 attempt_count 在下次 claim 增加，不在 duplicate request 增加。
- [x] pages 的完整 SQL schema 依上述 model 欄位建立；另存 lesson_id 供 active unique index 使用，插入值必須來自父 job，不能由客戶端頁面覆寫。資料庫公開 `database_path: Path`，供重開及故障注入測試。
- [x] 每次 finish/retry/claim 更新 job revision。只有本輪從 processing → completed 才設定 completion_revision；重複 finish 不產生完成版本。
- [x] 執行同一測試及 `uv run pytest tests/unit/test_sqlite_progress.py -q`；預期全數通過、原 progress 表仍可讀寫。只提交本工作檔案，建議訊息 `feat: persist lesson page import jobs`。

## 工作 2：原圖保留與持久化提交

**檔案：** 新增 `application/page_import_service.py` 的提交／原圖方法；新增 `tests/unit/test_page_import_service.py`。

- [x] 寫以下行為測試：每張照片與頁碼正確對應；job/files 重開後可讀；錯 MIME、空檔、超過上限、空頁碼先拒絕且無 job；DB 建立失敗清理未引用檔案；相同 ID 重送不覆寫原圖；不同 ID 的相同 active 頁衝突。
- [x] 測試先紅：`uv run pytest tests/unit/test_page_import_service.py -q`。
- [x] 提交從 repository 讀選定的 saved lesson，不從 client 接收 course scope；完整建立身分快照。fingerprint 使用 canonical JSON 加 SHA-256，不用 Python 的隨機 hash。

```python
import hashlib
import json

def submission_fingerprint(lesson_id, uploads):
    payload = {
        "lesson_id": lesson_id,
        "pages": [
            {
                "page_label": upload.page_label.strip(),
                "mime_type": upload.mime_type,
                "sha256": hashlib.sha256(upload.content).hexdigest(),
            }
            for upload in uploads
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

- [x] 原圖先寫同目錄 temporary file，再 `os.replace` 發布；metadata commit 完成才 queue。SQLite conflict 時先找原 operation_id：相同 fingerprint 返回既有 job，僅刪除此請求新產生而未引用的候選目錄。
- [x] `get_source_path` 查 job/page 關係，限制 source_key 在 source_root，下層拒絕 symlink／junction 逃逸及任意用戶路徑；核對大小及 SHA-256。測試照片遺失或被更換的行為為安全錯誤，可保留原頁狀態供處理。
- [x] 實作已儲存頁碼重疊的 server 檢查；未 allow_overlap 回 409；已確認後的 Retry 不受新加入其他成功頁的重疊檢查阻擋。active 相同照片防重不受 allow_overlap 影響。
- [x] 再跑工作 1、2 測試；全部通過才提交，建議訊息 `feat: retain sources for retryable page imports`。

## 工作 3：縮小匯入鎖並隔離同步發布

**檔案：** `session_service.py`、`lesson_repository.py`、`lessonlens_markdown.py`；修改 `tests/unit/test_session_service.py`、`tests/unit/test_lessonlens_markdown.py`、`tests/unit/test_ports.py`、`tests/integration/test_append_lesson_import.py`。

- [x] 加入閘門 vision 測試：一個 import 等待時，另一 session 的活動生成可完成；同一 session 重送相同匯入仍只呼叫模型一次。
- [x] 加入兩個不同 session 同課程 append 競爭測試，最後 pages／content／batch 皆保留；讀取與發布交錯時不得讀到無法解析的 lesson。
- [x] 新增 `test_import_concurrency.py` 先觀察鎖介面及活動被阻擋的失敗，再修正；執行 session／LessonLens／append 回歸。
- [x] 在 SessionService 初始化新增 `_import_locks = {}`；只替換 `import_lesson` 的外層鎖，不改活動鎖：

```python
lock = self._import_locks.setdefault(session_id, asyncio.Lock())
async with lock:
    existing = self._imports.get((session_id, operation_id))
    if existing is not None:
        return existing
```

- [x] 在 LessonRepository 新增 `locked()` context manager；Markdown adapter 使用 instance `threading.RLock`。get/list/batches/source path/save 的完整操作都進此鎖；讀－合併－save 外層進同一鎖，nested calls 依 RLock 重入。不得在模型等待時持鎖。
- [x] 將既有 `_save_lesson_draft` 的讀－合併－save 核心抽成 `_persist_lesson_draft`，核心維持：

```python
def _persist_lesson_draft(self, draft, source_references):
    repository = self.lesson_repository
    with repository.locked():
        if source_references:
            approve = getattr(repository, "approve_source_image", None)
            if approve is not None:
                for reference in source_references:
                    approve(reference)
        existing = repository.get_lesson(draft.lesson_id)
        if existing is None:
            saved, batches = draft, [initial_batch(draft)]
        else:
            batches = repository.get_import_batches(draft.lesson_id)
            if any(batch.operation_id == draft.operation_id for batch in batches):
                return existing
            merged = merge_lesson(existing, draft)
            saved, batches = merged.lesson, [*batches, merged.batch]
        repository.save_lesson_draft(saved, source_references=source_references, import_batches=batches)
        return saved

def _save_lesson_draft(self, draft, source_references, *, session_id=None):
    saved = self._persist_lesson_draft(draft, source_references)
    self._follow_saved_scope(session_id, saved)
    return saved
```

- [x] async `import_lesson` 用 `asyncio.to_thread(self._persist_lesson_draft, draft, trusted_images)`，得到結果後在原事件迴圈呼叫 `_follow_saved_scope`。保留同步 `_save_lesson_draft` 給既有 Pi tool 路徑，兩者必須共用核心。
- [x] offload 的 task 用強參照追蹤並 shield；取消 worker 時先等待已開始的發布結束，再依 batch 判定 succeeded／interrupted。SQLite session transition／照片 I/O 亦 offload；不可從 thread 發送 asyncio.Queue 事件。worker upload helper 僅操作 fresh、未曝光且無 subscriber 的 session，粗粒度 thread 執行已經獨立審查；一般 session 狀態事件維持原 loop。
- [x] 確認 `ProviderRegistry` 的 AsyncClient、Pi client 仍在同一事件迴圈。既有同 session 活動狀態守衛保留。
- [x] 重跑上述測試及 `uv run pytest tests/api/test_internal_tools.py tests/integration/test_failure_recovery.py -q`；Pi 同批次兩次 save 仍只追加一次。提交訊息建議 `fix: isolate import locks and lesson publication`。

## 工作 4：逐頁 worker、重試及重啟恢復

**檔案：** `page_import_service.py`、`tests/unit/test_page_import_service.py`、新增 `tests/integration/test_page_import_recovery.py`。

- [x] 在 `tests/unit/test_page_import_service.py` 建立 async fixture `imports`：臨時 SQLite／LessonLens／uploads，SessionService 注入 FakeVision／FakeText／FakeSTT／FakeTTS，先儲存一門既有課程，PageImportService.start 後 yield，finally stop。以 service.lesson_id 保存原課程，並提供可替換 vision 的引用。

將以下 fixture 放在 `tests/conftest.py`，供 unit／API／integration 共用；不同測試可替換 `imports.session_service.vision_service` 為有閘門或單頁失敗的 fake：

```python
import pytest_asyncio
from talkpath.adapters.fake_services import (
    FakeVisionService, FakeTextService, FakeSpeechToTextService, FakeTextToSpeechService,
)
from talkpath.adapters.lessonlens_markdown import LessonLensMarkdownRepository
from talkpath.adapters.sqlite_progress import SQLiteProgressRepository
from talkpath.adapters.sqlite_page_import import SQLitePageImportRepository
from talkpath.application.session_service import SessionService
from talkpath.application.page_import_service import PageImportService
from talkpath.domain.models import CourseScope

@pytest_asyncio.fixture
async def imports(tmp_path, lesson_id):
    lessons = LessonLensMarkdownRepository(tmp_path / "lessonlens")
    session_service = SessionService(
        progress_repository=SQLiteProgressRepository(tmp_path / "progress.sqlite"),
        lesson_repository=lessons, vision_service=FakeVisionService(),
        text_service=FakeTextService(), speech_to_text_service=FakeSpeechToTextService(),
        text_to_speech_service=FakeTextToSpeechService(), upload_root=tmp_path / "uploads",
    )
    scope = CourseScope(program="junior high", grade="7", subject="English", lesson="1", lesson_id=lesson_id)
    seed = await session_service.vision_service.extract_lesson([], scope, operation_id="seed")
    lessons.save_lesson_draft(seed)
    service = PageImportService(
        session_service, SQLitePageImportRepository(tmp_path / "progress.sqlite"),
        tmp_path / "uploads" / "page-imports",
    )
    await service.start()
    try:
        yield service
    finally:
        await service.stop()
        await session_service.aclose()
```
- [x] 寫兩頁中一頁失敗、後續頁繼續、Retry 只呼叫失敗頁、超過一小時後仍可 Retry、重啟 queued/running 中斷而非自動提取的測試。

```python
import pytest
from talkpath.domain.page_import import PageUpload

@pytest.mark.asyncio
async def test_closed_frontend_does_not_stop_backend(imports, lesson_id):
    subscriber = imports.subscribe()
    job = await imports.submit(
        lesson_id, "submit-close", [PageUpload("12", b"page12", "image/png")]
    )
    imports.unsubscribe(subscriber)
    await imports.join()
    completed = imports.repository.get_job(job.job_id)
    assert completed.pages[0].status.value == "succeeded"

@pytest.mark.asyncio
async def test_already_saved_batch_is_not_imported_again(imports, lesson_id):
    job = await imports.submit(
        lesson_id, "submit-window", [PageUpload("12", b"page12", "image/png")]
    )
    await imports.join()
    page = imports.repository.get_job(job.job_id).pages[0]
    before = imports.session_service.lesson_repository.get_import_batches(lesson_id)
    import sqlite3
    with sqlite3.connect(imports.repository.database_path) as connection:
        connection.execute(
            "UPDATE lesson_page_import_pages SET status='interrupted' WHERE page_id=?",
            (page.page_id,),
        )
    await imports.retry_page(job.job_id, page.page_id, "retry-window")
    await imports.join()
    after = imports.session_service.lesson_repository.get_import_batches(lesson_id)
    assert [batch.operation_id for batch in after] == [batch.operation_id for batch in before]
    assert imports.repository.get_job(job.job_id).pages[0].status.value == "succeeded"
```

第二個測試以直接 SQL 模擬工作狀態落後於教材存檔；正式 `finish` 狀態守衛不允許 succeeded 倒退。此測試須另外斷言 vision 呼叫數未增加，不能只看最後 batch 數。

- [x] worker 實作前執行新增 service 測試先紅；完成後補 `test_page_import_recovery.py` 故障注入並一起執行驗證，不將後補案例宣稱全部曾先紅。
- [x] worker 以 queue 逐頁 claim；scope 建構固定使用後端 saved scope：

```python
scope = CourseScope.model_validate({
    **lesson.scope.model_dump(),
    "lesson_id": lesson.lesson_id,
    "pages": [page.page_label],
})
session = self.session_service.create_session()
self.session_service.upload_image(session.session_id, content, mime_type=page.mime_type)
self.session_service.confirm_scope(session.session_id, scope)
result = await self.session_service.import_lesson(
    session.session_id, operation_id=page.import_operation_id
)
```

上段為資料流；同步方法的 I/O offload 及 publish 分界按工作 3 執行。PageImportService 不自行呼叫 merge 或修改模型回覆；每次 Retry 新 session／upload，固定 page import operation ID 不變。

- [x] `_process_page` 在開始、例外及完成後核對 batch marker；存在標為 succeeded，否則以安全錯誤標 failed；一頁失敗繼續 next。`CancelledError` 不吞成一般 failed，停機時按恢復規則處理。
- [x] `recover_pending` 啟動時掃全部 job：有固定 batch 的未成功頁校正為 succeeded，剩餘 queued/running 標 interrupted，不 enqueue。若 SQLite／LessonLens 不可讀，啟動失敗而非假設未儲存並重跑。
- [x] Retry 先核對 batch，再 repository CAS，成功才 enqueue 該 page。worker 例外不得悄悄退出留下 processing；unexpected storage failure 對外呈現服務錯誤並停收新工作。
- [x] 以 fault injection 測試：Pi 已 save 後拋錯、Markdown 完成後 SQLite finish 失敗、批次證據讀取失敗、發布期間取消；驗證成功內容不遺失、不重複，未完成可手動重試。
- [x] 使用 fake gate 延遲 vision，以 events 控制，不用固定 sleep 掩飾競態；direct／SavingPi 都測。重跑工作 1–4，提交訊息建議 `feat: process and recover page imports independently`。

## 工作 5：API、後端生命週期與跨畫面通知

**檔案：** 新增 `api/page_import_routes.py`、修改 `api/app.py`、新增 `tests/api/test_page_imports.py`。

- [x] 寫 API 測試：202 早於 vision 解鎖；course identity 不能由 form 修改；404／422／409；列表與圖片不洩漏路徑；學習活動、health 與 list lessons 在提取中仍回應。
- [x] 寫 WebSocket 連線快照、狀態更新、disconnect 後完成、重連快照與 startup recovery 測試。TestClient 必須以 context manager 使用，才能執行 startup/shutdown。
- [x] 執行 `uv run pytest tests/api/test_page_imports.py -q`，確認新測試先紅。
- [x] 實作規格第 6 節各端點。multipart 解析 `pages` 為 JSON string array，對 `files` 使用 `await file.read(max_upload_bytes + 1)` 並拒絕超限；只接受指定表單 key，禁止默默忽略課程身分欄位。
- [x] 公開輸出使用明確 Pydantic `ImportJobResponse`／`ImportPageResponse`，不直接序列化內部 domain。映射：page_import_not_found → 404、invalid_page_import → 422、page_import_conflict → 409、repository failure → 500；提交模型錯誤不是同步 HTTP 失敗，而是工作頁面 failed。
- [x] create_app 組裝 SQLitePageImportRepository(settings.sqlite_path)、PageImportService(configured_service, ..., configured_service.upload_root / 'page-imports')；測試接受明確注入的 page_import_service，不從 `.env` 取得 provider。
- [x] 啟動 hook 先 `start()` 完成恢復後接收 API；shutdown 先 `stop()`，再既有 SessionService.aclose；create_app injected service 既有擁有權語意保留。不新增另一個與原 service 不共用狀態的 SessionService。
- [x] WebSocket 先 subscribe，再以 thread 取 snapshot；每個變動只在資料庫更新成功後發送。snapshot／update 都帶 revision，慢 subscriber 滿載時解除訂閱並讓用戶端重連查快照，不阻塞 worker、不取消工作。
- [x] `allow_overlap=False` 時重疊回 409＋overlapping_pages；check 以實際 ID 查原課程，涵蓋 textbook 舊 ID 案例。頁碼通過但寫入時已有別人新增，提交處再檢查。
- [x] 完整重跑 `uv run pytest tests/api/test_page_imports.py tests/api/test_import_flow.py tests/api/test_lesson_list.py tests/api/test_internal_tools.py -q`；提交訊息建議 `feat: expose durable page import APIs and events`。

## 工作 6：可測試的前端工作協調

**檔案：** 新增 `frontend/lesson-page-import.js`、`frontend/test/lesson-page-import.test.cjs`。

- [x] 模組沿用 `screen-flow.js` 的 UMD pattern，Node 可 `require`。輸出 `createPageImportController`、`retryAllowed`、`completionMessage`；controller 注入 api、onUpdate、onComplete、seenStore，不耦合 DOM。
- [x] 寫 revision 去舊、初始快照終止工作、完成一次提示、Retry 下一輪提示、localStorage 例外、submit 回 202 才導覽、重送保持 operation_id 的行為測試。

```javascript
const test = require("node:test");
const assert = require("node:assert/strict");
const { retryAllowed, completionMessage } = require("../lesson-page-import.js");

test("only failed or interrupted pages allow Retry", () => {
  assert.equal(retryAllowed({ status: "failed" }), true);
  assert.equal(retryAllowed({ status: "interrupted" }), true);
  for (const status of ["queued", "running", "succeeded"]) {
    assert.equal(retryAllowed({ status }), false);
  }
});

test("completion reports interrupted pages among unsuccessful pages", () => {
  assert.equal(completionMessage({ counts: { succeeded: 4, failed: 0, interrupted: 1 } }),
    "Added 4 pages. 1 page needs retry.");
});
```

- [x] 先跑 `node --test frontend/test/lesson-page-import.test.cjs` 確認紅，再實作純函式：

```javascript
function retryAllowed(page) {
  return page.status === "failed" || page.status === "interrupted";
}

function completionMessage(job) {
  const success = job.counts.succeeded;
  const failed = job.counts.failed + job.counts.interrupted;
  return `Added ${success} ${success === 1 ? "page" : "pages"}. `
    + `${failed} ${failed === 1 ? "page needs" : "pages need"} retry.`;
}
```

- [x] controller 保存每個 job 的最高 revision；接受 update 時先比版本再覆蓋。completed 且 completion_revision 高於 seenStore 時 onComplete 並保存版本；processing 不標已讀完成版本。
- [x] WS 重連及 window focus 重新 GET 全部工作，照相同 merge 流程處理；retry／submit 後用回傳 snapshot 校正，API 失敗不提前更改成功頁或清空表單。
- [x] 不在導航切換時取消後端、不重用學習 session WebSocket；釋放前端 socket 只影響訂閱。網路事件加入捕獲、重連取消與關閉頁面清理，避免重複 listener／重連計時器。
- [x] 跑 `node --test frontend/test/lesson-page-import.test.cjs`、`node --check frontend/lesson-page-import.js`；提交訊息建議 `feat: coordinate page import state in the frontend`。

## 工作 7：Add pages、詳情 Retry 與 MESSAGE

**檔案：** `frontend/index.html`、`frontend/app.js`、`frontend/styles.css`；修改 `tests/api/test_static_ui.py`，擴充前端行為測試。

- [x] Add pages 按鈕連到新 `data-screen="add-pages"`，使用 state.detailLesson.lesson_id。新建 upload 的 file input 不加 multiple；只有新 Add pages input 加 multiple。
- [x] 新畫面以文字呈現唯讀課程欄位，照片縮圖逐張頁碼輸入；submit 僅傳 files/pages/operation_id/allow_overlap。新模組 script 放在 app.js 前，screen controller 自動納入新 screen。
- [x] 加入真 DOM 邊界行為測試或 fake DOM 注入，驗證選定課程 ID、逐張頁碼配對、提交停用／恢復、202 導覽、不同課程遲到回應隔離；不能只斷言程式字串。
- [x] 接 existing Cancel／Add anyway 語意，但使用新 lesson-specific check；重疊 cancel 保留表單，Add anyway 重新送同內容＋確認旗標。allow_overlap 是接受確認，不納入 payload fingerprint；未接受前沒有 durable job。
- [x] My Lessons 顯示進行中的 job；詳情追加非 succeeded 頁面列，顯示照片、頁碼、安全錯誤或中斷文案。Retry button 呼叫 retry_page endpoint，request 中停用；409 校正最新狀態，不丟失成功內容。
- [x] 跨畫面 MESSAGE 使用 `textContent` 組文案及安全 DOM link；連結導航至該 job.lesson_id。保持目前活動畫面，只有用戶點連結才導覽。
- [x] 選照片或移除時管理 object URLs；離開畫面清理預覽。沿用 navigationEpoch 避免舊詳情請求覆蓋新課，global controller 不因 screen reset 被清空。
- [x] 跑 `node --test frontend/test/*.test.cjs`、`node --check frontend/app.js`、`uv run pytest tests/api/test_static_ui.py -q`。
- [ ] fake provider 真實瀏覽器驗證：建立一門課→Add pages 12/13/14→13 首次失敗→202 回 My Lessons→操作其他課程→完成 MESSAGE→詳情只 Retry 13→刷新→確認不重複。另測頁碼重疊 Cancel/Add anyway、舊 textbook ID、關閉前端後完成。測試 server 手動組裝 fake 服務、臨時目錄及 localhost，不能讀正式 `.env`。
- [ ] 人工觀察記錄畫面與 API 結果；瀏覽器只見新畫面但後端未重啟時，先確認 `/openapi.json` 新路由。提交訊息建議 `feat: add lesson pages and retry failures from details`。

## 工作 8：整體回歸、文件與交接

**檔案：** README、STRUCTURE、TECHSTACKS、PROGRESS、HISTORY、此計畫核取方塊。

- [x] 建立需求覆蓋表，AC01–AC13 對應已執行測試／人工驗收。每個失敗修復後只重跑受影響範圍；最後統一執行一次完整回歸。
- [x] 執行以下命令，實際讀取輸出並記錄 passed/skipped/warnings，不能沿用舊數量：

```powershell
uv run pytest -q
node --test frontend/test/*.test.cjs
node --check frontend/app.js
node --check frontend/lesson-page-import.js
uv lock --check
git diff --check
```

- [x] Pi TypeScript 未變更亦確認既有測試；執行命令先查 `pi-extension/package.json` 的實際 scripts，不猜測 script 名稱。direct／Pi append 整合須包含在 Python 回歸。
- [ ] 手動測試 backend restart：閘門暫停多頁，其中一頁已成功，停止並重啟 fake server；成功頁仍在、剩餘中斷，未點擊 Retry 前無新模型呼叫。另注入教材已存／狀態未存窗口，確認校正成功且不重複。
- [x] 更新 README：Add pages、一頁新建、完成通知、失敗 Retry、前端關閉不取消、後端重啟需手動 Retry。STRUCTURE／TECHSTACKS 寫實際已加入的 worker、工作表與原圖位置，不把計畫設計當作已部署功能。
- [x] 全部驗證通過後，HISTORY 記錄實際功能、命令及人工結果／限制，PROGRESS 移除完成項；沒有真實模型驗證則明確記 fake 與人工範圍。保留本計畫作已執行紀錄，不將未完成核取方塊勾選。
- [x] 依 `verification-before-completion` 核對修改範圍及輸出，再提交本工作檔案；不得 `git add .` 混入使用者先前診斷／文件修改。

## 需求覆蓋與任務依賴

| 規格驗收 | 工作 |
|---|---|
| AC01、AC02 | 2、4、5、7 |
| AC03 | 3、5、7 |
| AC04、AC05 | 1、4、7 |
| AC06、AC11 | 4、5、6、7 |
| AC07、AC08 | 3、4、8 |
| AC09、AC10 | 1、2、4、5 |
| AC12、AC13 | 3、7、8 |

原規劃為工作 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8；實際依使用者後續授權將獨立儲存與前端模組平行處理，主代理順序整合。功能與缺陷修正使用先紅後綠；後補恢復案例明確記為驗證。分段提交訊息保留作原建議，實際合併為一次功能提交，未完成的人工驗收不勾選。
