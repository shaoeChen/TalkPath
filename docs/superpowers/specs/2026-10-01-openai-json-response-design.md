# OpenAI 相容模型 JSON 回應修正設計

## 問題與證據

2026-09-30 的圖片匯入日誌顯示 `ProviderResponseInvalid`，位置為 `_parse_content`。使用當次保留的圖片重新請求 Z.ai `glm-4.6v`，HTTP 200 且 `finish_reason=stop`，但內容第 61 行把英文例句寫成 `"When "I" means "me"..."`，內層引號未跳脫，無法解析為 JSON。

## 修正範圍

在共用 JSON 輸出指示中明確要求字串內的雙引號及反斜線必須符合 JSON 跳脫規則。當模型回應的 `message.content` 因 JSON 語法錯誤而無法解析時，帶上該次無效文字並請模型修正 JSON 語法一次，同時保留原始任務訊息。第二次仍無效則維持 `ProviderResponseInvalid`。正常回應只請求一次；HTTP、逾時、回應封套、schema 與身分驗證錯誤維持原有處理。不嘗試猜補模型輸出的教材內容。

## 驗證

以 mock transport 重現未跳脫引號後重試成功、連續兩次無效後回報錯誤、正常回應不重試，以及非 JSON 語法錯誤不重試。執行 OpenAI 相容服務單元測試與相關測試。
