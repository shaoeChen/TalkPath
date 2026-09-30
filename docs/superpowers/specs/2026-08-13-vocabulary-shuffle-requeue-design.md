# TalkPath 單字練習：隨機出題 + 錯題再出現 設計規格

| 項目 | 內容 |
| --- | --- |
| 狀態 | 設計確認（2026-08-13；依用戶三點回饋定稿：隨機出題、只套用單字練習、錯題不設次數上限） |
| 關聯文件 | [第三期進度](../../PROGRESS.md)、[練習頁改版設計](./2026-08-13-one-question-practice-design.md) |
| 使用情境 | 小孩反覆做單字練習時，不能靠「記住順序」來答對；答錯的單字必須在後面再次出現，達到加強記憶的效果 |

## 1. 需求背景

現行 practice 流程一次一題、依活動原始題目順序（`activity.items`）呈現；每題只出現一次。用戶觀察到：固定順序下，小孩練習多次後會背「順序」而不是「單字」；且答錯的題目錯過就過了，沒有再次練習的機會。用戶要求：

1. 單字練習的題目順序必須隨機（每次進入都重新打散），避免背順序。
2. 答錯的題目要在後面再次出現（錯題加強）。
3. 此功能先只套用於 Vocabulary practice（`vocabulary_practice`）；Grammar / Listening / Speaking 尚未實測，維持現狀，待用戶測試後再討論是否套用。
4. 錯題「就是再出現」——不設「最多出現幾次」的上限，也不預設小孩會故意無限答錯；答對才能前進是既有保證，機制自然收斂。

## 2. 現況與問題（已核對證據）

- `frontend/app.js`：`generateActivity` 收到活動後 `renderActivity` → `renderPracticeProgress` + `renderPracticeQuestion`；題目順序為 `activity.items` 原始順序（`state.currentQuestionIndex` 逐題 +1）。
- 答錯：該選項加入 `state.practiceWrongChoices` 並 disabled，小孩必須答對才能繼續（選擇題）；答對後 500ms 自動進下一題（`PRACTICE_AUTO_ADVANCE_MS`），或點 Next / Finish。
- 進度：點狀進度 +「Question X」（刻意不顯示總數）。
- 評分：`POST .../answer` 用 `item.activity_id` 逐題評分（`ActivityService._normalize_item_ids` 已保證 id 唯一），題目順序完全不影響評分 → 前端洗牌安全。
- 後端不需變更。

## 3. 設計決策

### 3.1 只套用 Vocabulary practice

- 以 `activity.type === "vocabulary_practice"` 為啟用條件；其他 type 維持現狀（原始順序、不重排錯題）。
- 未來若要在其他類型啟用，只需放寬條件（機制本身與 type 無關）。

### 3.2 隨機出題（佇列洗牌）

- `state` 新增 `practiceQueue: []`（題目索引佇列）。
- `generateActivity` 成功取得活動後：
  - 若 type 為 `vocabulary_practice`：以 Fisher–Yates 洗牌（`Math.random()`）建立 `practiceQueue = shuffle([0..items.length-1])`；每次進入活動都重新洗牌。
  - 其他 type：`practiceQueue = [0..items.length-1]`（原始順序）。
- `currentQuestionIndex` 語意改為「佇列內位置」；`renderPracticeQuestion` 取 `activity.items[state.practiceQueue[state.currentQuestionIndex]]`。
- `renderPracticeProgress`、`isLastPracticeQuestion`、`advancePracticeQuestion` 全部改以 `practiceQueue` 為準。
- `generateActivity` 開始時與 `resetForNewCourse` 都重置 `practiceQueue`。

### 3.3 錯題再出現

- 答對時（`evaluation.passed`）若該次出現曾答錯（`state.practiceWrongChoices.length > 0`），立即把目前題目索引 `push` 到 `practiceQueue` 尾端（在判斷是否最後一題 / 自動跳題之前，因此最後一題答錯過也會正確排回）。
- 錯題再次出現時從全新狀態開始（`practiceWrongChoices` 等已重置）；若又答錯，再一次 `push` 到尾端——**不設上限**。
- 收斂保證：每次出現都必須答對才能前進（既有機制），錯題最終會在「某次出現一次答對」時結束；不預設小孩會故意無限答錯。
- 任何一次出現若完全沒答錯就答對，不會被排回。

### 3.4 進度顯示

- 點狀進度以 `practiceQueue.length` 渲染（錯題被排回時多一顆點，小孩可直觀看到「這題會再回來」）；「Question X」以佇列位置計。
- 維持「不顯示共 N 題」的既有決策。
- 最後一題（佇列走完）才顯示 Finish → 既有 results 頁（不變）。

### 3.5 不變更範圍

- 後端 API、評分邏輯完全不動。
- results screen、overview、lessons 頁、screen-flow.js 不動。
- 自動跳題（500ms）、答錯選項 disable、audio / 口說流程不動。

## 4. 測試與驗證（TDD）

1. `tests/api/test_static_ui.py` 更新來源契約：
   - `state` 新增 `practiceQueue: []`；`generateActivity` 中 `vocabulary_practice` 分支洗牌（shuffle helper + `Math.random`）、其他 type 不洗牌。
   - `renderPracticeQuestion` / `renderPracticeProgress` / `isLastPracticeQuestion` / `advancePracticeQuestion` 使用 `practiceQueue`。
   - 答對且有錯過才 `practiceQueue.push`（在自動跳題判斷之前）；不新增「最多一次」上限邏輯。
   - `resetForNewCourse` 重置 `practiceQueue`。
2. `node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs`。
3. 全量 `uv run pytest -q`（現基準 302 passed、9 skipped、1 warning，不允許 regression）；`compileall`；`git diff --check` 乾淨。
4. 瀏覽器手動驗證仍受限（in-app Browser sandbox），以 static 契約與 node 測試為準，並在 PROGRESS.md 記錄。

## 5. 未來（非本次範圍）

- Grammar / Listening / Speaking 是否套用隨機 + 錯題機制：待用戶實測後再討論。
- 錯題統計 / 複習記錄（如錯題本）：未要求，YAGNI。
