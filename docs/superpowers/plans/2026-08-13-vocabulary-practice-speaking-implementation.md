# 詞彙練習改為「聽音＋跟讀＋STT 比對」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `vocabulary_practice`（詞彙練習）變成真的練習：卡片顯示單字 → Listen 聽發音（TTS）→ Record 跟讀（STT）→ 轉錄文字由後端本機比對 → 對才前進、錯的排回；`vocabulary_quiz`（詞彙測驗）維持出題作答。

**Architecture:** 前端 `frontend/app.js` 對 `vocabulary_practice` 走單字卡分支（Listen＋Record＋自動送轉錄作答），沿用既有 `practiceQueue` 洗牌／錯題排回與 500ms 自動跳題；後端 `ActivityService.answer()` 對 `vocabulary_practice` 一律本機比對（零 AI 延遲），provider 契約（`_ACTIVITY_OUTPUT_INSTRUCTION`）與 `FakeTextService` 改為產生「prompt=單字、answer=單字、choices=[]」的練習形狀。型別識別字串不變（不互換），避免歷史資料語意翻轉。

**Tech Stack:** Vanilla JS（`frontend/app.js`）、Python（FastAPI 服務＋pytest）、來源契約測試（`tests/api/test_static_ui.py`）、uv、node。

---

## File Structure

- Modify: `frontend/app.js` — `activityDefinitions` 描述；`state` 新增 `practiceTranscript`；`renderPracticeQuestion` 新增 vocabulary_practice 單字卡分支；新增 `playPracticeWord`；`transcribeSpeaking` 增加 `onTranscript` callback；`generateActivity`／`advancePracticeQuestion`／`resetForNewCourse` 重置 `practiceTranscript`。
- Modify: `frontend/styles.css` — 新增 `.practice-word`、`.practice-speech-actions`。
- Modify: `src/talkpath/application/activity_service.py` — `answer()` 對 `vocabulary_practice` 本機比對。
- Modify: `src/talkpath/adapters/openai_compatible_services.py` — `_ACTIVITY_OUTPUT_INSTRUCTION` 加 vocabulary_practice 指引。
- Modify: `src/talkpath/adapters/fake_services.py` — `generate_activity` 對 vocabulary_practice 產生練習形狀。
- Modify: `tests/unit/test_activity_service.py`、`tests/api/test_activity_flow.py`、`tests/api/test_static_ui.py` — TDD 新增契約。
- Add: `docs/superpowers/specs/2026-08-13-vocabulary-practice-speaking-design.md`（已建立）。
- Modify: `docs/PROGRESS.md` — 記錄實作結果與驗證（AGENTS.md 要求）。

不改：`vocabulary_quiz` 與其他活動行為、`frontend/index.html`、`frontend/screen-flow.js`、`frontend/test/screen-flow.test.cjs`、SQLite schema、LessonLens 格式、internal tools。

## 前置確認（執行者請先做）

- 讀 `docs/PROGRESS.md`（目前執行位置）與 `docs/superpowers/specs/2026-08-13-vocabulary-practice-speaking-design.md`（本計畫的規格來源）。
- 工作目錄必須是 `D:\python\TalkPath`；若不是，先確認路徑限制再動手。
- 基準測試數量：`uv run pytest -q` → 302 passed、9 skipped、1 warning。

### Task 1: 後端練習形狀與本機比對（TDD）

**Files:** `src/talkpath/adapters/fake_services.py`、`src/talkpath/application/activity_service.py`、`tests/unit/test_activity_service.py`、`tests/api/test_activity_flow.py`

- [ ] **Step 1: 寫失敗測試**
  - `tests/unit/test_activity_service.py` 新增：`vocabulary_practice` 產生後 item 為 `choices == []`、`prompt == answer == "school"`；作答 `school` → passed、`teacher` → 未過，且 `evaluate_calls == 0`（紅燈：目前 fake 產生 MC 形狀、無 choices 會走 AI）。
  - `tests/api/test_activity_flow.py` 新增：`vocabulary_practice` 公開 items 不含 `answer`、item 無 choices；以 `school` 作答 → `evaluation.passed is True`。
- [ ] **Step 2: 實作**
  - `fake_services.py`：`normalized_type == "vocabulary_practice"` 時產生單字卡 item（`prompt=word`、`answer=word`、`choices=[]`、`type="speaking"`），instructions 改為「Listen to the word, then say it out loud.」。
  - `openai_compatible_services.py`：`_ACTIVITY_OUTPUT_INSTRUCTION` 增加「For vocabulary_practice, every item is one vocabulary word: prompt is exactly the English word, answer is exactly the same English word, and choices must be an empty list.」。
  - `activity_service.py`：`answer()` 條件改為 `if item.choices or activity.type == "vocabulary_practice":` 走 `_evaluate_standard_answer`。
- [ ] **Step 3: 綠燈驗證**
  - `uv run pytest tests/unit/test_activity_service.py tests/api/test_activity_flow.py -q` 通過；無 regression。

### Task 2: 前端單字卡練習分支（TDD）

**Files:** `frontend/app.js`、`frontend/styles.css`、`tests/api/test_static_ui.py`

- [ ] **Step 1: 寫失敗測試（來源契約）**
  - `tests/api/test_static_ui.py` 新增 `test_child_ui_vocabulary_practice_is_speaking_drill`：
    - `activityDefinitions` 描述含「Listen to the word, then say it out loud.」。
    - `renderPracticeQuestion`（renderPracticeQuestion → renderPracticeResultActions 切片）含 `activity.type === "vocabulary_practice"`、`"Listen"`、`"Record your voice"`、`/speech/synthesize`、`text: item.prompt`、`state.practiceTranscript`、`submitActivityAnswer(activity, item, () => state.practiceTranscript`。
    - `state` init／reset 含 `practiceTranscript: ""`；`transcribeSpeaking` 含 `onTranscript`。
    - CSS 含 `.practice-word`、`.practice-speech-actions`。
- [ ] **Step 2: 實作**
  - `activityDefinitions`：`vocabulary_practice` 描述改為「Listen to the word, then say it out loud.」。
  - `state` 新增 `practiceTranscript: ""`；`generateActivity`／`advancePracticeQuestion`／`resetForNewCourse` 重置。
  - `renderPracticeQuestion`：`vocabulary_practice` 分支（單字 h3.practice-word + Listen + Record，包 `.practice-speech-actions`）；Record 完成轉錄後 `state.practiceTranscript = transcript` 並自動 `submitActivityAnswer(activity, item, () => state.practiceTranscript, feedback, record)`。
  - 新增 `playPracticeWord`（放在 `requestActivityAudio` 之後、`showAnswerResult` 之前，避免落入既有切片）：`POST /speech/synthesize` `text=item.prompt`、播放 `audio_data_url`；TTS 不可用顯示友善訊息。
  - `transcribeSpeaking(button, feedback, onTranscript = null)`：轉錄成功後若提供 callback 就呼叫。
  - `styles.css`：`.practice-word`（大字單字）、`.practice-speech-actions`（直排大按鈕）。
- [ ] **Step 3: 綠燈驗證**
  - `uv run pytest tests/api/test_static_ui.py -q` 通過；`node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs`。

### Task 3: 全量驗證與收尾

- [ ] `uv run pytest -q` 全量（基準 302 passed、9 skipped、1 warning，只允許新增數目）。
- [ ] `uv run python -m compileall -q src tests`。
- [ ] `node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs`。
- [ ] `git diff --check` 乾淨；commit（spec＋plan＋程式＋測試＋PROGRESS 更新）。
- [ ] 更新 `docs/PROGRESS.md`：新增「詞彙練習改為聽音＋跟讀＋STT 比對」執行紀錄（更新日期、TDD 紅燈→綠燈、全量驗證數字、已知限制、下一步）。
