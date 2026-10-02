# 2026-10-01 Vision scope 不一致診斷

## 問題與重現

使用者提供教材照片，匯入錯誤為 `openai-compatible vision response scope does not match request`。本文件不保留原始照片檔名、session ID 或個人課程範圍。

從執行中的本機 API 取得失敗 session 的 scope，以現有設定與 `glm-4.6v` 重新請求原始照片。

三次修正前真實呼叫：

| 呼叫 | 耗時 | 結果 |
| --- | --- | --- |
| 1 | 50.2 秒 | 成功，9 個教材項目 |
| 2 | 32.0 秒 | 重現 scope 不一致；只漏掉 `scope.lesson_id` |
| 3 | 33.2 秒 | 成功，2 個教材項目 |

第二次回覆的 `program`、`grade`、`subject`、`lesson`、`pages`、`textbook`、`edition` 全部與請求相同；僅未回傳可由課程範圍推導的 `lesson_id`。

`CourseScope` 原有驗證器能從上述範圍推導同一個 lesson ID。舊 adapter 在呼叫這個驗證器前直接比較完整字典，將省略可推導欄位的等價 scope 誤判為不同課程。

## 修正與驗證

- 先以 `CourseScope.model_validate` 補齊預設欄位與推導 ID，再與使用者確認的範圍比較，最後使用可信任的 request scope 建立草稿。
- 真正不同的課次、年級、頁碼、教科書，以及無效或缺少必要欄位的 scope 仍拒絕；非空的 requested pages 不得省略。
- Vision 提示詞明確要求原樣回傳 scope 與身分欄位，不從圖片改寫課程資訊。
- 回歸測試先重現 3 個等價 scope 的預期失敗；修正後 OpenAI 相容服務、匯入 API、失敗恢復、同課追加與日誌測試共 67 passed，1 個既有 Starlette 棄用警告。
- 重播第二次保存的真實失敗回覆成功，11 個教材項目通過驗證。
- 修正後以原始照片與相同 scope 再呼叫一次真實 provider，42.6 秒完成，9 個教材項目、scope 一致。
- 本機 `127.0.0.1:8001` 服務已重啟載入修正，`/health` 回傳 `ok`。未將診斷草稿儲存成課程；未執行完整人工瀏覽器操作。

診斷完成後只保留此範圍差異與驗證摘要，移除暫存的完整模型教材回覆。
