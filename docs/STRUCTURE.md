# TalkPath 專案結構

```text
AGENTS.md            coding agent 指令（<= 200 行，僅放規則與連結）
CLAUDE.md            內容固定為 @AGENTS.md
src/talkpath/        後端（api/、adapters/、service 等）
frontend/            前端（index.html、app.js、screen-flow.js、lesson-page-import.js、styles.css、test/）
pi-extension/        Pi agent 的 TypeScript 工具
tests/               Python 測試（api/、unit/、integration/）
data/                執行期資料
docker/              本機語音服務的 Docker Compose 設定
docs/                所有文件（見下）
```

背景新增頁面的責任分工：`domain/page_import.py` 定義工作模型，`ports/page_import_repository.py` 定義持久化契約，`adapters/sqlite_page_import.py` 保存逐頁工作與 Retry 收據，`application/page_import_service.py` 管理原圖、worker 及重啟恢復，`api/page_import_routes.py` 提供 HTTP／WebSocket。`frontend/lesson-page-import.js` 處理版本及通知去重，畫面入口位於 `app.js`。

## docs 文件

| 文件 | 用途 |
|---|---|
| `docs/CONSTITUTION.md` | 專案憲章（最高規則） |
| `docs/IDEAS.md` | 破碎的想法 |
| `docs/PLANS.md` | 有完整想法但非目前工作項目 |
| `docs/PROGRESS.md` | 進行中、未完成的工作進度（交接用） |
| `docs/HISTORY.md` | 已完成的工作記錄 |
| `docs/INSIGHT.md` | 討論中的關鍵洞察 |
| `docs/TECHSTACKS.md` | 技術棧 |
| `docs/STRUCTURE.md` | 本文件 |
| `docs/SPEECH_SERVICES.md` | 本機 TTS／STT Compose 啟停與設定 |
| `docs/LAN_HTTPS.md` | 區網 HTTPS 啟動與憑證保存 |
| `docs/talkpath-progress.md` | 產品定位、需求背景、架構決策 |
| `docs/superpowers/specs/` | 設計規格 |
| `docs/superpowers/plans/` | 實作計畫書 |
| [多頁匯入規格](superpowers/specs/2026-10-02-lesson-add-pages-background-design.md) | 已實作的既有課程 Add pages、背景提取及中斷重試設計 |
| [多頁匯入實作計畫](superpowers/plans/2026-10-02-lesson-add-pages-background-implementation.md) | 已執行工作與自動化驗證；人工瀏覽器驗收待補 |
| `docs/PROGRESS-phase*.md` | 前二期進度封存（歷史） |
