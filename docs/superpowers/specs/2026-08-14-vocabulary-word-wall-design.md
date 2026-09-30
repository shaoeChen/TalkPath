# TalkPath 詞彙練習：單字卡牆＋自選練習 設計規格

| 項目 | 內容 |
| --- | --- |
| 狀態 | 設計確認（2026-08-14；用戶以互動預覽確認「完美，完全就是我想要的感覺」） |
| 關聯文件 | [第三期進度](../../PROGRESS.md)、[聽音＋跟讀＋STT 比對設計](./2026-08-13-vocabulary-practice-speaking-design.md)、[練習頁改版設計](./2026-08-13-one-question-practice-design.md) |
| 使用情境 | 既然是練習，就要讓小孩自己選要練哪一個單字：章節所有單字以字卡牆呈現（上方搜尋框），點卡直接聽或進入該字練習；也可整批隨機練習 |

## 1. 需求背景

用戶指出目前的練習是「系統餵什麼就練什麼」；練習應該像市面熱門 App（Memrise／Quizlet／Anki／Duolingo）的概念：字庫可見＋搜尋、點擊即聽、自選練習、狀態可視、短回合＋即時回饋。用戶以 NTU 頁面為參考（上方查找、下方章節所有單字的字卡、點卡進入練習），並以互動預覽確認最終版面：

1. 單字卡牆：上方搜尋框，下方該課全部單字字卡（英文大字＋中文＋狀態標籤＋喇叭）。
2. 點喇叭＝直接聽發音；點卡片＝進入該字練習（Listen＋Record＋STT 比對）。
3. 右上 Practice all＝整批隨機練習（沿用現有洗牌＋錯題排回）。
4. 練完單字＝回卡牆自己挑下一個；Practice all 才自動接續。

## 2. 現況與問題（已核對證據）

- Overview 的 Vocabulary practice 卡片目前直接 `generateActivity`（約 18 秒等待）才進練習；練習頁只有逐題流程，沒有「選字」。
- 課程單字已存在 LessonLens：`state.lesson.content_items` 中 `type == "vocabulary"`，欄位可能為 `{english, chinese}` 或 `{word, meaning}`。
- TTS（`/speech/synthesize`）與 STT（`/speech/transcribe`）已可用（`af_bella` 發音已修正）；本機文字比對已有 `_evaluate_standard_answer` 模式。
- `SQLiteProgressRepository.record_attempt` 支援 `operation_id` 冪等與任意 `activity_id` → 單字作答可直接記錄 attempt／review item，不需建立活動檔。

## 3. 設計決策

### 3.1 畫面流程

```text
Overview「Vocabulary practice」卡片
  → 單字卡牆頁（words screen）
      ├─ 搜尋框：依英文／中文即時過濾
      ├─ 字卡：英文＋中文＋狀態標籤＋喇叭（點喇叭＝TTS 直接播發音）
      ├─ 點卡片 → 練習頁（單字模式）：Listen＋Record＋STT 比對
      │     ├─ 答對：標記 practised、回卡牆
      │     └─ 答錯：Try again（可重錄）、標記 again
      └─ Practice all → 沿用現有 generateActivity 流程（洗牌＋錯題排回＋結果頁）
```

### 3.2 單字資料來源

- 字卡牆讀 `state.lesson.content_items` 的 vocabulary 項目，不生成活動、不需等待。
- 英文＝`content.english || content.word`；中文＝`content.chinese || content.meaning || ""`。

### 3.3 狀態標籤（MVP：session 內記憶體）

- `state.wordStatus[content_id]`：`new`（預設）、`done`（本 session 練對過）、`again`（本 session 答錯過）。
- `resetForNewCourse` 重置；不持久化（未來再接入錯題本）。

### 3.4 單字作答 API（後端）

新端點：`POST /api/sessions/{session_id}/vocabulary/{content_id}/answer`

- Request：`{operation_id, answer}`（answer＝前端 STT 轉錄文字）。
- 驗證：session 存在、content item 屬於 session 的 lesson 且 `type == "vocabulary"`。
- 評分：本機 `strip().casefold()` 比對答案與單字 → `{passed, score, feedback}`（「Great job!」／「Try again.」），不呼叫 AI。
- 記錄：以 `activity_id = "{lesson_id}-word-{content_id}"` 寫 attempt 與 review item；沿用 `record_attempt` 的 `operation_id` 冪等。
- 回饋安全：沿用 `_safe_child_feedback` 概念，不在回應中回顯答案。

### 3.5 Practice all 不變

- 卡牆的 Practice all 呼叫既有 `generateActivity(vocabulary_practice)`；洗牌、錯題排回、500ms 自動跳題、results 頁全部沿用。

### 3.6 不變更範圍

- 其他七種活動、測驗（vocabulary_quiz）行為、results／overview 既有內容、SQLite schema、LessonLens 格式、internal tools。
- 既有「練習頁一次一題」與「單字練習洗牌＋錯題排回」機制不拆。

## 4. 測試與驗證（TDD）

1. 後端 unit：`answer_vocabulary_word` 正確／錯誤、`operation_id` 冪等重送、content 不存在、非 vocabulary 內容拒絕、activity_id 穩定。
2. API：新端點 200 passed、attempt 寫入、公開回應不含答案。
3. static UI 契約：
   - words screen 元素（搜尋框、字卡格、Practice all、喇叭）。
   - app.js：字卡由 `lesson.content_items` 渲染、搜尋過濾、點卡進練習、新端點呼叫、`wordStatus` 標籤、`resetForNewCourse` 重置。
   - CSS：字卡牆樣式。
4. 全量 `uv run pytest -q`、`compileall`、`node --check`、`node --test`、`git diff --check`。
5. 瀏覽器手動驗證仍受限（in-app Browser sandbox），以 static UI 契約、API 測試與 node 測試為準，並在 PROGRESS.md 記錄。

## 5. 未來（非本次範圍）

- 每字狀態持久化（錯題本／複習區接單字層級）。
- 發音品質評分、MiniCPM-o-4_5 統一模型（下一期工程）。
