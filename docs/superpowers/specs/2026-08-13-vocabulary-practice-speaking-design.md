# TalkPath 詞彙練習改為「聽音＋跟讀＋STT 比對」設計規格

| 項目 | 內容 |
| --- | --- |
| 狀態 | 設計確認（2026-08-13；用戶指示：本期專注功能修正，MiniCPM-o-4_5 統一模型列為下一期工程） |
| 關聯文件 | [第三期進度](../../PROGRESS.md)、[練習頁改版設計](./2026-08-13-one-question-practice-design.md)、[隨機出題＋錯題再出現設計](./2026-08-13-vocabulary-shuffle-requeue-design.md) |
| 使用情境 | 「詞彙練習」必須是真的練習：點擊聽單字發音、小孩跟讀錄音、由 STT 轉文字後比對對錯；「詞彙測驗」維持出題作答 |

## 1. 需求背景

用戶指出目前「詞彙練習」與「詞彙測驗」幾乎相同：兩者都走同一個出題作答流程，差異只有名稱／描述，以及 `vocabulary_practice` 多出「隨機出題＋錯題再出現」。練習沒有「練習」的實質。

用戶要求：

1. 詞彙練習要能「點擊聽發音」，或「小孩發音後由模型判斷對錯」。
2. 評分第一版：STT 轉文字後比對（不引入發音品質評分，之後再調整）。
3. 測驗維持出題作答。
4. MiniCPM-o-4_5 統一模型列為下一期工程，本期不引入。

## 2. 現況與問題（已核對證據）

- `frontend/app.js` `activityDefinitions`：`vocabulary_practice` 與 `vocabulary_quiz` 共用同一 `renderPracticeQuestion`；唯一行為差異是 practice 的 Fisher–Yates 洗牌（`practiceQueue`）與答錯排回。
- `requestActivityAudio` 只合成第一題 `prompt` 的整份音檔（`activityDefinitions.audio` 活動用）；沒有「逐單字音檔」。
- `transcribeSpeaking` 只把 STT 轉錄結果顯示在回饋文字（「I heard: …」），不會自動當作答案送出。
- `ActivityService.answer()`：有 `choices` 的題目本機比對（`_evaluate_standard_answer`）；沒有選項的題目走 text provider AI 評分。
- `PublicActivityItem` 對兒童端隱藏 `answer`（既有 redaction 契約），前端不能取得標準答案。

## 3. 設計決策

### 3.1 型別識別字串不變，行為重新定義

維持 `vocabulary_practice`／`vocabulary_quiz` 兩個型別字串（不互換），把行為改為用戶要求的終態：

- `vocabulary_practice`（詞彙練習）＝聽音＋跟讀練習。
- `vocabulary_quiz`（詞彙測驗）＝出題作答（維持現狀）。

理由：型別字串是前後端契約 key，也寫進 LessonLens 活動檔與 SQLite attempts／review_items；互換會讓歷史資料語意翻轉，且剛完成的「洗牌＋錯題排回」是寫死在 `activity.type === "vocabulary_practice"`。互換對小孩看到的使用體驗沒有額外好處。

### 3.2 詞彙練習互動（vocabulary_practice）

- 每題＝一個單字：`prompt`＝英文單字（公開給前端顯示與 TTS）、`answer`＝同一個單字（僅後端比對）、`choices`＝空陣列。
- 練習卡片顯示單字、Listen 按鈕、Record 按鈕：
  - Listen：`POST /api/sessions/{id}/speech/synthesize`，`text=item.prompt`，播放回傳音檔。
  - Record：既有 MediaRecorder 錄音 → `POST .../speech/transcribe` → 拿到轉錄文字後**自動**送 `answer` 作答。
- 評分：後端本機 `strip().casefold()` 比對轉錄文字與 `item.answer`（零 AI 延遲；沿用「Great job!」／「Try again.」回饋）。
- 保留 `vocabulary_practice` 的洗牌＋答錯排回：單字順序每次進入隨機；答錯的單字會排回佇列尾端，直到某次出現答對。
- 答對後沿用 500ms 自動跳題／Next／Finish 既有流程。

### 3.3 評分變更（後端）

`ActivityService.answer()`：

- `item.choices` 有值 **或** `activity.type == "vocabulary_practice"` → `_evaluate_standard_answer`（本機比對）。
- 其他無選項題目（含 speaking_practice）維持 text provider AI 評分。

### 3.4 Provider 契約

- `_ACTIVITY_OUTPUT_INSTRUCTION` 增加 `vocabulary_practice` 專屬指引：每題一個單字，`prompt`＝英文單字、`answer`＝同一個英文單字、`choices`＝空陣列。
- `FakeTextService.generate_activity` 對 `vocabulary_practice` 產生練習形狀（單一單字卡），其餘型別維持現狀。

### 3.5 前端變更

- `state` 新增 `practiceTranscript: ""`（init、`generateActivity`、`advancePracticeQuestion`、`resetForNewCourse` 都重置）。
- `renderPracticeQuestion` 對 `vocabulary_practice` 產生單字卡分支（Listen＋Record）；其他型別維持既有選擇題／文字作答／speaking_practice 分支。
- 新增 `playPracticeWord`：合成並播放單字發音；TTS provider 不可用時顯示既有風格的友善訊息。
- `transcribeSpeaking` 增加可選 `onTranscript` callback；詞彙練習收到轉錄後自動 `submitActivityAnswer`。
- `activityDefinitions` 的 `vocabulary_practice` 描述改為「Listen to the word, then say it out loud.」。
- 樣式新增 `.practice-word`（大單字）與 `.practice-speech-actions`（Listen／Record 直排大按鈕）。

### 3.6 兒童安全（沿用既有契約）

- 前端不取得 `item.answer`；比對只在後端（`PublicActivityItem` redaction 不變）。
- 不揭曉正確答案（答錯顯示「Good try! Check the word again.」）；發音比對成功才能前進。

### 3.7 不變更範圍

- `vocabulary_quiz` 與其他七種活動的行為、results／overview／lessons 頁、`screen-flow.js`、SQLite schema、LessonLens 格式都不動。
- 不引入發音品質評分（用戶：之後再調整）。
- 不引入 MiniCPM-o-4_5（下一期工程）。

## 4. 測試與驗證（TDD）

1. 後端 service 測試：`vocabulary_practice` 的 item 為 `choices == []`、`prompt == answer == 單字`；作答 `school` → passed、`teacher` → 未過，且 `evaluate_calls == 0`（本機比對）。
2. API 測試：`vocabulary_practice` 產生活動後公開 items 不含 `answer`；以 STT 轉錄文字作答 → passed。
3. `tests/api/test_static_ui.py` 新增來源契約：
   - `activityDefinitions` 描述「Listen to the word, then say it out loud.」。
   - `renderPracticeQuestion` 的 `vocabulary_practice` 分支：Listen／Record／`/speech/synthesize`／`state.practiceTranscript`／自動送出。
   - `state` init／reset 含 `practiceTranscript: ""`；`transcribeSpeaking` 含 `onTranscript`。
   - CSS 含 `.practice-word`、`.practice-speech-actions`。
4. `node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs`。
5. 全量 `uv run pytest -q`（現基準 302 passed、9 skipped、1 warning，不允許 regression）；`uv run python -m compileall -q src tests`；`git diff --check` 乾淨。
6. 瀏覽器手動驗證仍受限（in-app Browser sandbox），以 static UI 契約與 node 測試為準，並在 `docs/PROGRESS.md` 記錄。

## 5. 未來（非本次範圍）

- 發音品質評分（例如以 MiniCPM-o-4_5 統一模型實作語音理解／評分）→ 下一期工程。
- `vocabulary_quiz` 是否也要洗牌／錯題排回：用戶未要求，YAGNI。
