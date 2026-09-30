# TalkPath Agent Instructions

本文件維持 200 行以內，只放規則與連結。詳細內容一律寫在 `docs/` 並以連結引用。

## 必須遵守

**所有 coding agent 必須確實遵守 @docs/CONSTITUTION.md**，並在工作過程中動態調整相關文件。開始任何工作前，先讀取憲章與 @docs/PROGRESS.md。

## 專案位置

正式位置為 `D:\python\TalkPath`。若目前工作目錄不同，須在回覆中明確標示實際路徑與限制，不得默默當成正式位置。

## 文件索引

- @docs/CONSTITUTION.md：專案憲章（最高規則）
- @docs/STRUCTURE.md：專案與文件結構
- @docs/TECHSTACKS.md：技術棧
- @docs/IDEAS.md：破碎想法
- @docs/PLANS.md：有完整想法、非目前工作項目
- @docs/PROGRESS.md：進行中工作與交接資訊
- @docs/HISTORY.md：已完成工作記錄
- @docs/INSIGHT.md：關鍵洞察
- `docs/talkpath-progress.md`：產品定位與需求背景
- `docs/superpowers/specs/`、`docs/superpowers/plans/`：設計規格與實作計畫書

## 工作規則摘要（細節見憲章）

1. 所有文件放在 `docs/`，以正體中文書寫。
2. 文件流轉：`IDEAS` → `PLANS` → 實作計畫書 → `PROGRESS` → `HISTORY`；同一項目只存在於一處。
3. `PROGRESS` 只記進行中，`HISTORY` 只記已完成。
4. 遵守 MVP 最小開發；延伸想法記入 `IDEAS`，不擅自實作。
5. 有疑慮就向使用者澄清，不自行決定。
6. 完成宣告前執行對應測試並記錄驗證結果；未完成部分須明確說明。
7. `AGENTS.md` 保持 200 行內；`CLAUDE.md` 僅含 `@AGENTS.md`。
