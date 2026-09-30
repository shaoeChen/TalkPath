# TalkPath 詞彙測驗：聽寫＋中翻英＋辨識題 設計規格

| 項目 | 內容 |
| --- | --- |
| 狀態 | 設計草稿（2026-08-14；用戶於對話確認題型方向，待審閱本文件） |
| 關聯文件 | [第三期進度](../../PROGRESS.md)、[詞彙練習聽音跟讀設計](./2026-08-13-vocabulary-practice-speaking-design.md)、[單字卡牆設計](./2026-08-14-vocabulary-word-wall-design.md) |
| 使用情境 | 詞彙測驗是老師式的評量：保留目前 TOEIC 型「聽音選義」選擇題，新增「聽寫」與「中翻英」提取題；一次作答、答錯看訂正、結束給結果與錯題複習 |

## 1. 需求背景

用戶確認（2026-08-14）：

- 詞彙練習已定版（單字卡牆＋自選練習＋聽音跟讀）。
- 詞彙測驗採用老師常見的「筆試＋聽力」：核心是「老師唸 fruit、學生寫 fruit」的聽寫，以及看中文拼出英文單字的中翻英。
- 目前「聽音選義」的多益類型測驗保留。

因此詞彙測驗從「看／聽再選答案」升級為「辨識＋提取」混合測驗：選擇題測「認得」，聽寫／中翻英測「寫得出」。

## 2. 現況與問題（已核對證據）

- `vocabulary_quiz` 與 `vocabulary_practice` 共用 `renderPracticeQuestion`（frontend/app.js）；目前 quiz 是 MC 出題作答，沒有洗牌、沒有錯題排回（練習才有）。
- `ActivityService.answer()`：`item.choices` 有值或 `activity.type == "vocabulary_practice"` 才走本機比對；無選項的其他題目會呼叫 text provider AI 評分。測驗若新增打字題，必須改為本機比對，避免 AI 延遲與安全回顯風險。
- `PublicActivityItem` 在 API 邊界隱藏 `answer` 與 `explanation`；`ActivityAnswerResponse.evaluation` 只有 passed/score/feedback，且 `_safe_child_feedback` 防止回饋回顯答案。→「答錯看訂正」需要新的契約欄位。
- TTS 逐字發音已存在（`playPracticeWord` → `/speech/synthesize`）；文字輸入（`.answer-input`）與選擇題（`.choice-list`）都已存在。
- `record_attempt` 已自動維護 review_items（答對刪除、答錯 upsert mistake_count），錯題持久化不需改 schema。
- 產生器契約（`_ACTIVITY_OUTPUT_INSTRUCTION`）目前只有 `vocabulary_practice` 的特殊形狀；`vocabulary_quiz` 與其他活動共用一般 MC 形狀。Fake provider 的 quiz 分支也走一般 MC。

## 3. 設計決策

### 3.1 題型組合（MVP：4 種）

| question_type | 情境 | 刺激 | 作答 | 測驗目標 |
| --- | --- | --- | --- | --- |
| `dictation`（聽寫） | 唸 fruit → 輸入 fruit | 音檔（TTS） | 打字拼字 | 聽音辨字＋拼字 |
| `meaning_to_word`（中翻英） | 顯示「水果」→ 輸入 fruit | 中文義 | 打字拼字 | 主動提取＋拼字 |
| `word_to_meaning`（英翻中） | 顯示 fruit → 選「水果」 | 英文單字 | 選擇題 | 認得字義（辨識） |
| `listen_to_meaning`（聽選中，保留） | 唸 fruit → 選「水果」 | 音檔（TTS） | 選擇題 | 聽力辨識（TOEIC 型） |

生成原則：每課 vocabulary 單字一題；題型混出並隨機洗牌；整份測驗至少一半是提取題（dictation／meaning_to_word），另一半為辨識題。

### 3.2 題目形狀與契約（後端）

`Activity`／`PublicActivityItem` 新增公開欄位 `question_type: str | None = None`（缺省時沿用現有 render 行為，舊活動不壞）：

- `dictation`：`prompt`＝英文單字（僅供 TTS，不顯示）、`choices=[]`、`answer`＝英文單字。
- `meaning_to_word`：`prompt`＝中文義（顯示）、`choices=[]`、`answer`＝英文單字。
- `word_to_meaning`：`prompt`＝英文單字（顯示）、`choices`＝4 個中文選項（含正確義）、`answer`＝正確中文義。
- `listen_to_meaning`：`prompt`＝英文單字（僅供 TTS）、`choices`＝4 個中文選項、`answer`＝正確中文義。

`_ACTIVITY_OUTPUT_INSTRUCTION` 增加 `vocabulary_quiz` 專屬指引（單字來源＝lesson 的 vocabulary items、每字一題、question_type 分配、choices/answer 規則、隨機順序）。`FakeTextService.generate_activity` 對 `vocabulary_quiz` 產生含三種題型的 fixture（dictation＋meaning_to_word＋word_to_meaning 各一，同一單字）。

### 3.3 評分（後端）

`ActivityService.answer()` 本機比對條件改為 `item.choices or activity.type in {"vocabulary_practice", "vocabulary_quiz"}`；`_evaluate_standard_answer` 不變（`strip().casefold()` 完全一致，忽略大小寫、不寬容拼字變體）。

訂正契約：`ActivityAnswerResponse` 新增 `correction: str | None = None`，僅當 `activity.type == "vocabulary_quiz"` 且作答後才回傳 `item.answer`（答對答錯都回，供訂正顯示）；其他活動一律不回。`PublicActivityItem` 仍不含 answer；`_safe_child_feedback` 不變。

### 3.4 前端互動（vocabulary_quiz 分支）

`renderPracticeQuestion` 依 `item.question_type` 渲染：

- `dictation`：題幹「Listen and write the word.」＋ Listen 按鈕（`playPracticeWord(item.prompt)`）＋ 文字輸入；不顯示單字。
- `meaning_to_word`：顯示中文 prompt ＋ 文字輸入。
- `word_to_meaning`：顯示英文 prompt ＋ 選擇題。
- `listen_to_meaning`：Listen 按鈕（進題自動播一次）＋ 選擇題。
- 缺省：沿用現有行為（有 choices 顯示選項、否則文字輸入）。

測驗作答策略（與練習區隔）：

- 一次作答；答對答錯都顯示回饋；答錯同時顯示 `correction`（訂正）。
- 不自動跳題（練習的 500ms auto-advance 不套用到 quiz）；由「Next question／Finish」按鈕前進。
- 不把答錯題排回佇列（quiz 一次作答）；改用 `state.quizResults` 收集每題 `{prompt, question_type, passed, correction}`。

洗牌：`generateActivity` 的 shuffle 條件從 `vocabulary_practice` 擴展為同時含 `vocabulary_quiz`（沿用 Fisher–Yates）。

TTS fallback：`dictation`／`listen_to_meaning` 合成失敗時，顯示既有「Audio is taking a break」友善訊息；`dictation` 提供「Show the word」按鈕，顯示單字後該題仍以打字作答與計分（降級為看字拼寫，不跳題）。

### 3.5 結果頁與錯題

`showAnswerResult` 對 `vocabulary_quiz` 顯示：

- 分數：X of Y correct。
- 答錯清單：單字＋正確拼字（或正確中文義）。
- 按鈕：「Practice these words」（回到單字牆 `openWordWall()`，用現有 Listen＋Record 複習）與「Back to overview」。
- 錯題持久化自動完成：`record_attempt` 對答錯的 `activity_id` 已寫入 review_items；結果頁錯題清單用前端 `state.quizResults`（MVP 不讀 /progress 重算）。

### 3.6 不變更範圍

- `vocabulary_practice` 與其他七種活動、單字牆、results 既有內容、SQLite schema、LessonLens 格式、`_safe_child_feedback`、screen-flow 不變。
- 不引入發音品質評分、手寫辨識、AI 評分（quiz 全本機比對）、每字兩題、聽＋義複合題、克漏字。

## 4. 測試與驗證（TDD）

1. 後端 service：
   - `vocabulary_quiz` 題目 shape：dictation／meaning_to_word 為 `choices=[]` 且 prompt／answer 符合規則；word_to_meaning／listen_to_meaning 有 4 個 choices。
   - 作答 dictation `fruit` → passed、`frut` → 未過，且 `evaluate_calls == 0`（本機比對）。
   - answer 回應含 correction（僅 quiz 且作答後）。
2. API：
   - 公開 items 含 `question_type`、不含 `answer`。
   - quiz answer 200、attempt 寫入、correction 只出現在 quiz 回應；其他活動（如 vocabulary_practice）無 correction。
3. static UI 契約（tests/api/test_static_ui.py）：
   - `activityDefinitions` quiz 描述更新。
   - render 分支：dictation 有 Listen＋文字輸入且不顯示 prompt 文字；meaning_to_word 顯示中文＋文字輸入；word_to_meaning／listen_to_meaning 有 choices；quiz 無 auto-advance、無錯題排回、有 correction 顯示。
   - shuffle 條件含 vocabulary_quiz；`state.quizResults` init／reset。
   - 結果頁 quiz 分支（分數、錯題清單、Practice these words）。
4. `uv run pytest -q`（不允許 regression）、`uv run python -m compileall -q src tests`、`node --check frontend/app.js frontend/screen-flow.js`、`node --test frontend/test/screen-flow.test.cjs`、`git diff --check`。
5. 瀏覽器手動驗證仍受限（in-app Browser sandbox），以 static UI 契約、API 測試與 node 測試為準，並在 PROGRESS.md 記錄。

## 5. 未來（非本次範圍）

- 錯題專屬複習測驗（重新出錯題卷，而非回單字牆）。
- 每字兩題（辨識＋提取）或分節測驗（辨識節→提取節）。
- 聽＋義複合題（拼字＋選中文一次測）、句子克漏字（測「會用」）。
- 手寫輸入／筆順評分。
- 測驗成績持久化與報表（給老師／家長）。
