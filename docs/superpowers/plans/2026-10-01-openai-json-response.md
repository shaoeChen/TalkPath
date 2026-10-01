# OpenAI 相容模型 JSON 回應修正實作計畫

> 依已確認設計於目前工作階段執行，測試先行；本工作不需平行代理。

**目標：** 圖片辨識模型偶發輸出未跳脫引號時，自動重新請求一次有效 JSON。

**架構：** 只調整 `src/talkpath/adapters/openai_compatible_services.py` 的 JSON 提示及 `_chat`，保留 `_parse_content` 的嚴格解析。失敗重試限於內容 JSON 語法錯誤。

**技術：** Python、httpx、pytest。

## 工作 1：建立失敗測試

**檔案：** `tests/unit/test_openai_compatible_services.py`

- [x] 以 `httpx.MockTransport` 依序回傳未跳脫引號的 `content` 與有效的課程 JSON；呼叫 `extract_lesson` 後斷言有兩次請求，第二次訊息帶有前次無效內容與跳脫提醒，結果為有效課程。
- [x] 回傳兩次無效 JSON 時，斷言 `ProviderResponseInvalid` 且只有兩次請求。
- [x] 正常 JSON 僅一次請求；缺少 `choices` 或 schema 無效不重試。
- [x] 執行 `.venv/Scripts/python.exe -m pytest tests/unit/test_openai_compatible_services.py -q`，確認新測試因目前無重試而失敗。

## 工作 2：最小修正

**檔案：** `src/talkpath/adapters/openai_compatible_services.py`

- [x] 在 `_JSON_OUTPUT_INSTRUCTION` 加上字串內雙引號及反斜線的 JSON 跳脫指示。
- [x] `_chat` 只在 `_parse_content` 引發的 JSON 語法錯誤時重新送出請求一次；第二次帶上前次無效內容與修正指示。
- [x] 執行單元測試並確認通過。

## 工作 3：驗證及文件流轉

**檔案：** `docs/PROGRESS.md`、`docs/HISTORY.md`

- [x] 執行相關測試與 `git diff --check`，讀取輸出確認結果。
- [x] 將完成工作與實際驗證結果移至 `HISTORY.md`，並從 `PROGRESS.md` 移除。
