# TalkPath 專案結構

```text
AGENTS.md            coding agent 指令（<= 200 行，僅放規則與連結）
CLAUDE.md            內容固定為 @AGENTS.md
src/talkpath/        後端（api/、adapters/、service 等）
frontend/            前端（index.html、app.js、screen-flow.js、styles.css、test/）
pi-extension/        Pi agent 的 TypeScript 工具
tests/               Python 測試（api/、unit/、integration/）
data/                執行期資料
docker/              本機語音服務的 Docker Compose 設定
docs/                所有文件（見下）
```

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
| `docs/talkpath-progress.md` | 產品定位、需求背景、架構決策 |
| `docs/superpowers/specs/` | 設計規格 |
| `docs/superpowers/plans/` | 實作計畫書 |
| `docs/PROGRESS-phase*.md` | 前二期進度封存（歷史） |
