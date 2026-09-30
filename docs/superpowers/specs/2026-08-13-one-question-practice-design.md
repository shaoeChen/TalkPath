# TalkPath 練習頁改版（獨立頁面 + 一次一題）設計規格

| 項目 | 內容 |
| --- | --- |
| 狀態 | 已確認（2026-08-13；版面以視覺伴侶確認，用戶選擇 Option A「單卡完成」） |
| 關聯文件 | [第三期進度](../../PROGRESS.md)、[入口改版設計](./2026-08-13-saved-lessons-nav-entry-design.md) |
| 使用情境 | 小孩進入活動練習時，不應看到「像考卷一樣一次列出全部題目」的頁面，也不應在 overview 同頁下方堆疊活動內容 |

## 1. 需求背景

現行 overview 頁（Pick a practice）在同一頁下方直接渲染活動面板（`#activity-panel`），生成活動後需捲動才能看到內容；且 `renderActivity` 一次列出活動內全部題目，像傳統考卷，容易讓小孩覺得負擔大而關掉 App。用戶要求：活動內容改為獨立頁面，並「一次一題」呈現。

已與兒童教育心理學觀點（學習科學）討論並納入設計：一次一題 + 即時回饋；以點狀進度代替「共 N 題」的考試框架；答錯不懲罰、可再試一次；不直接揭曉正確答案（同時符合既有兒童安全契約）；讚美努力而非能力。

## 2. 現況與問題（已核對證據）

- `#overview-screen` 同時包含 `#activity-list`、`#activity-panel`、`#activity-error`；`generateActivity` 把活動渲染進 overview 頁下方的 panel，需捲動。
- `renderActivity` 一次 `items.forEach` 渲染全部題目，每個題目有自己的「Check my answer」；作答後 `submitActivityAnswer` 直接 `showAnswerResult` 切到 results 頁。
- child-facing answer endpoint 刻意不回傳 `expected_answer`（`PublicAnswerEvaluation` 只有 passed/score/feedback），避免答案外洩與作弊——本設計沿用此安全契約。
- 後端已具備所需能力：`POST /api/sessions/{id}/activities/generate` 回傳 `PublicActivityDraft.items`（題目清單）；`POST .../answer` 逐題評分並記錄 attempt / review item。本次不改後端。

## 3. 設計決策

### 3.1 獨立 practice screen（版面：Option A 單卡完成）

- 新增 `<section id="practice-screen" data-screen="practice">`。
- 版面（單卡完成，用戶已確認）：
  - 頂部：`← Back to practice list`（回 overview）+ 活動標題。
  - 標題下方：點狀進度（● ○ ○ ○）+「第 X 題」文字。
  - 中間一張卡片：題目（prompt）、選項按鈕或文字輸入、聽力/口說題的音訊播放或錄音。
  - 卡片內：作答回饋區 + 操作按鈕（見 3.3）。
- 桌面單卡 max-width 約 720px 置中；手機全寬單欄；一次只顯示一題，無需捲動找題目。

### 3.2 一次一題狀態

- `state.currentQuestionIndex` 追蹤目前題號；`renderActivity` 改為只渲染一題。
- 進度顯示：點狀進度條（每個題目一個點，已完成填滿）+「第 X 題」；**不顯示「共 N 題」**，避免考卷框架壓力。
- 點卡片進入 practice 頁後顯示載入中（「Making your activity…」），載入完成渲染第 1 題；失敗在 practice 頁顯示錯誤，不切走。

### 3.3 作答與回饋流程

1. 小孩作答後按「Check my answer」→ `POST .../answer`（沿用現有 `submitActivityAnswer` 的請求所有權與防呆）。
2. 回饋立即顯示在卡片內（不跳頁）：
   - 答對：溫和正向訊息（如「That was a strong try!」/「Nice work」）+「Next question」。
   - 答錯：溫和訊息（如「Good try! Check the word again.」），**不顯示正確答案**；按鈕為「Try again」與「Next question」（跳過）。
3. 答錯題目由既有後端寫入 review corner；「Try again」答對後由既有後端移除該 review item。
4. 最後一題完成後按鈕變「Finish」→ 進入既有 results 頁（不變）。

### 3.4 overview 頁簡化

- `#overview-screen` 移除 `#activity-panel` 與 `#activity-error`，只保留標題、課程上下文與活動卡片。
- 點活動卡片 → `showScreen("practice")` 並開始 `generateActivity`。

### 3.5 音訊與口說題

- 每題保留音訊播放（`appendAudioPlayer`）、音訊 provider 不可用時的 fallback、口說錄音與文字替代（沿用現有 `audioFallbackMessage` / `showAudioFallback` / `transcribeSpeaking` 邏輯），全部移到 practice 頁內逐題呈現。

### 3.6 樣式

- 沿用既有視覺語言（白卡、圓角、`--blue` / `--mint` / `--coral`、`--shadow`）。
- 答對回饋用薄荷色系、答錯用奶油色系溫和呈現（不大紅叉、不懲罰音效）。
- 按鈕：primary 藍色「Check / Next / Finish」，secondary「Try again / Back」；手機單欄、按鈕可觸控。
- `@media (prefers-reduced-motion: reduce)` 區塊如更動需同步更新 static 契約測試（目前有逐字元比對）。

## 4. 測試與驗證

1. `tests/api/test_static_ui.py` 更新來源契約：
   - 存在 `id="practice-screen"` / `data-screen="practice"`；overview 不再包含 `id="activity-panel"` / `id="activity-error"`。
   - `app.js`：點卡片 → `showScreen("practice")` → generate → 渲染單題；`currentQuestionIndex`、點狀進度、Check / Next / Try again / Finish 流程順序契約；`submitActivityAnswer` 不再直接 `showScreen("results")`。
   - 既有 overview 卡片、results 頁契約維持（如需調整 `_source_between` 切片同步更新）。
2. `node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs`。
3. 全量 `uv run pytest -q`（現基準 291 passed、9 skipped、1 warning，不允許 regression）。
4. `git diff --check` 乾淨。
5. 瀏覽器手動驗證仍受限（in-app Browser sandbox），以 static 契約與 node 測試為準，並在 PROGRESS.md 記錄。

## 5. 不變更範圍

- 後端 API 完全不動。
- results screen 結構與內容不動。
- lessons 頁（My lessons）不動。
- screen-flow.js 的 screen controller 不動（僅新增一個 screen）。
