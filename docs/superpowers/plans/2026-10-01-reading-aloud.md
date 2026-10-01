# Reading / read aloud 跟讀 Implementation Plan

> **執行方式：** 本次使用目前工作階段逐項實作與驗證。工作樹已有其他未提交變更，只修改本計畫指定區塊並保留既有內容。

**Goal:** Reading / read aloud 播放當前題目、錄下孩子朗讀、轉錄後以題目文字做本機一致性判定。

**Architecture:** 維持現有 `ActivityDraft`、TTS、STT 與答題 API。文字 provider 將朗讀題定義為可朗讀句子；前端為 `reading_aloud` 顯示專屬錄音入口；`ActivityService` 對可信任的題目文字做本機比對。

**Tech Stack:** FastAPI、Python/Pydantic、原生 JavaScript、pytest、Node test。

---

## 檔案分工

- `src/talkpath/adapters/openai_compatible_services.py`：朗讀題生成指令。
- `src/talkpath/adapters/fake_services.py`：離線朗讀題形狀。
- `src/talkpath/application/activity_service.py`：朗讀文字正規化與本機判定。
- `frontend/app.js`：顯示題目與錄音入口，轉錄成功後送出作答。
- `tests/unit/test_activity_service.py`、`tests/unit/test_fake_services.py`、`tests/unit/test_openai_compatible_services.py`、`frontend/test/reading-aloud.test.cjs`：行為回歸測試。
- `docs/PROGRESS.md`、`docs/HISTORY.md`：工作交接與驗證結果。

## Task 1：後端依朗讀題目判定

- [ ] 在 `tests/unit/test_activity_service.py` 新增測試：生成 `reading_aloud` 後，以 `item.prompt` 的大小寫與標點變體作答通過；改變其中一字不通過；即使 `item.answer` 與 `prompt` 不同也只以 `prompt` 判定；`text_service.evaluate_calls == 0`。
- [ ] 執行該測試，確認因目前朗讀走文字 provider 判定而失敗。
- [ ] 在 `src/talkpath/application/activity_service.py` 的 `answer()` 讓 `reading_aloud` 優先進入本機判定。以 `item.prompt` 作標準答案，正規化時忽略大小寫、標點與多餘空白，保留單字順序；回傳現有 `AnswerEvaluation` 與進度紀錄。
- [ ] 重跑該測試，並跑 `tests/unit/test_activity_service.py`。

## Task 2：朗讀題目形狀

- [ ] 在 fake 與 OpenAI 相容 provider 測試加入 `reading_aloud` 斷言：每題 `prompt` 為英文朗讀文字、`choices=[]`、`answer=prompt`；模型生成指令須明確要求來自課文的句子或短段落，禁止聽寫與選擇題。
- [ ] 執行新測試，確認目前 fake 產生選擇題、真實 provider 缺乏朗讀指令而失敗。
- [ ] 在 `fake_services.py` 加入朗讀專屬分支；在 `_ACTIVITY_OUTPUT_INSTRUCTION` 加入朗讀題契約。既有 `vocabulary_quiz` 與其他型別保持原樣。
- [ ] 重跑相關 provider 測試。

## Task 3：前端錄音作答

- [ ] 在 `frontend/test/reading-aloud.test.cjs` 建立最小 DOM 與 API 模擬，驗證朗讀頁顯示當前 `prompt` 和錄音按鈕、沒有選項或輸入框；轉錄有文字時送到現有 answer API，空文字不送出；錯誤回饋仍可重錄。沿用 `activity-audio.test.cjs` 的換題音訊測試。
- [ ] 執行新測試，確認目前沒有朗讀錄音入口而失敗。
- [ ] 在 `renderPracticeQuestion()` 增加 `reading_aloud` 分支，沿用現有 `transcribeSpeaking()`，取得非空轉錄後呼叫 `submitActivityAnswer()`。播放器使用現有當前題目的 TTS 機制，不額外產生第二份音訊。
- [ ] 重跑 `frontend/test/*.test.cjs`、`node --check frontend/app.js`。

## Task 4：整合與文件

- [ ] 針對公用活動 API 驗證朗讀的正確／錯誤轉錄與進度持久化，確認答案不在生成回應中洩漏。
- [ ] 執行 `uv run pytest tests/unit/test_activity_service.py tests/unit/test_fake_services.py tests/unit/test_openai_compatible_services.py tests/api/test_activity_flow.py tests/api/test_static_ui.py -q`、`node --test frontend/test/*.test.cjs`、`node --check frontend/app.js`、`git diff --check`。如有具體回歸風險再擴大測試。
- [ ] 在 `docs/HISTORY.md` 記錄實際修正與驗證結果，並從 `docs/PROGRESS.md` 移除已完成項目；若尚有未完成工作，保留在 `PROGRESS`。
