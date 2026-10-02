# TalkPath 想法清單

> 較破碎、尚未成形的想法記錄於此。整理成完整想法並寫入 `PLANS.md` 後，需同步從本文件刪除。MVP 開發過程中衍生的延伸性想法也記錄於此。

## 待釐清：視覺模型輸出的課程身分不符

- 更新日期：2026-10-01。
- 在 JSON 回應錯誤修正的實際供應商驗證中，`glm-4.6v` 曾回傳語法有效的 JSON，但 `scope` 或 `operation_id` 與請求不符，遭現有身分檢查拒絕。需先確認原始請求與模型輸出的差異，再決定是否調整提示詞或身分欄位處理；未在此次 JSON 修正中實作。

## 想法：轉用全模態模型 MiniCPM-o-4_5 取代雙模型

- 更新日期：2026-08-14（僅記錄想法，未實作、未技術評估）。
- 背景：目前語音管線為「雙模型」分工——TTS 用 Kokoro（`http://127.0.0.1:8880`，`openai_speech`，voice `af_bella`），STT 用區網上的轉錄服務（`<LAN-IP>:11435`）。優點是各司其職，缺點是要維護兩個本地服務、兩組設定與 adapter。
- 想法：改以單一全模態模型 [MiniCPM-o-4_5](https://huggingface.co/openbmb/MiniCPM-o-4_5)（openbmb，text＋vision＋audio in/out，可本地部署）取代上述兩個模型——一個模型同時處理語音理解（STT／跟讀比對）與語音生成（TTS／發音播放），簡化本地依賴與對接面。
- 與既有進度的關聯：`docs/PROGRESS.md`（2026-08-13，第四期後續）已把「MiniCPM-o-4_5 統一模型」列為下一期工程、本期不引入；本筆即為該方向的前置想法記錄。
- 考慮事項（待確認）：
  1. 部署方式：本機推理（GPU／量化需求？）還是沿用 local server 模式包一層 API？
  2. 取代範圍：只取代 TTS＋STT 兩個語音模型，或連 text 模型（目前為外部 AI provider）一併評估？
  3. 音質與轉錄品質需與 Kokoro／現有 STT 實測對比。
  4. 既有 `local_speech_services.py` adapter、`/speech/synthesize` 與 STT 端點的契約是否可維持不變（只換底層實作）。
- 狀態：想法已記錄，尚未實作，尚未決定取代範圍與部署方式。

## 想法：課程管理延伸（MY LESSONS 附加匯入的後續）

- 更新日期：2026-09-30（從「MY LESSONS 課程管理」討論中延伸，本期不做）
- 同一頁重新拍照時，以「取代舊頁」代替附加（需處理被學習紀錄引用的內容）。
- 一次選取多張照片上傳。
- 冊次（上、下學期）納入課程識別：目前 7 上 L1 與 7 下 L1 會被視為同一課並互相附加。可選做法為重新定義 EDITION 為冊次，或新增 Volume 欄位；使用者 2026-09-30 決定本期不納入。
- 非數字課次：`_lesson_slug` 只取數字，「Review 1」與「Lesson 1」都會變成 `lesson-01` 而撞號；「Starter」這類無數字課次不符合 `lesson_id` 格式，無法存檔。
- 既有課程補填或修改 textbook（會改變 lesson_id，需要 migration）。

## 想法：課程詳情頁直接加頁（Add pages）

- 更新日期：2026-09-30（使用者實測附加匯入時提出，本期不做）
- 現況：要新增頁面必須走 New lesson，並手動把 Program、Grade、Subject、Lesson、Textbook 填得跟原課程一致；填錯（尤其 Textbook 空白與否）會被當成另一門課。
- 想法：課程詳情頁加「Add pages」按鈕，點下去帶入該課程的 Program、Grade、Subject、Lesson、Textbook（唯讀或預填），使用者只需選照片並填頁碼，避免填錯。
- 待確認：帶入後欄位是否唯讀；舊課程（textbook 已填但 ID 無後綴）如何處理。
