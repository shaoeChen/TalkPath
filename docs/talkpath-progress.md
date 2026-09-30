# TalkPath 專案目前進度

更新日期：2026-08-12
狀態：Direct API 是 production default；Vision/Text 由 Python application service 直接呼叫 provider。Pi RPC 僅保留為 experimental opt-in compatibility。fake-provider 垂直流程已完成，真實 provider 的限制以 [PROGRESS-phase2-2026-08-13.md](PROGRESS-phase2-2026-08-13.md) 為準。

本文件主要記錄 TalkPath 的產品背景、架構與需求脈絡。實作計畫的逐項執行狀態，請以 [PROGRESS-phase2-2026-08-13.md](PROGRESS-phase2-2026-08-13.md) 為準。

## 1. 專案定位

TalkPath 是一個給小朋友使用的英文互動學習系統。小朋友可以拍攝英文課本內容，系統透過視覺語言模型理解課文，再依課程範圍產生單字、文法、口說與其他互動練習。

目前的範例課程範圍是：

```text
國中一年級 → 英文 → 第一課
```

## 2. 名稱與責任分層

- **TalkPath**：整個兒童英文互動學習系統，以及小朋友使用的互動入口。
- **LessonLens**：課程內容資料庫的名稱。第一階段先使用 Obsidian Vault 保存資料，不另外建立獨立的 LLM Wiki 服務。
- **Direct API backend（正式預設）**：Python application service 直接協調 Vision/Text、LessonLens、STT/TTS 與學習進度。
- **Pi agent（實驗性 opt-in）**：只作為相容性路徑；不屬於正常啟動或 production default，必須明確設定 `TALKPATH_AGENT_BACKEND=pi` 才會建立。

## 3. 目前確認的使用場景

```text
小朋友進入 TalkPath
        ↓
提交英文課本圖片
        ↓
TalkPath UI 確認課本範圍
例如：國中一年級、英文第一課，對嗎？
        ↓
Python SessionService 直接呼叫 Vision provider 提取課文資料
        ↓
依課程結構寫入 LessonLens
        ↓
Python ActivityService 直接呼叫 Text provider 生成題目
        ↓
產生單字、文法、口說等互動活動
        ↓
TalkPath 開始學習練習
```

## 4. 初步模組

### 4.1 TalkPath

- 接收小朋友提交的圖片或語音。
- 顯示 TalkPath workflow 的範圍確認訊息、處理狀態與學習活動。
- 顯示題目、提示、答案回饋與學習結果。

### 4.2 Python application services（production default）與 Pi compatibility

正常流程由 `SessionService`／`ActivityService` 直接執行範圍確認後的 Vision 萃取、LessonLens 寫入、Text 活動生成與答案評估，不啟動 Pi，也不需要 Pi CLI 或 Pi provider 登入。Pi RPC 只在明確 opt-in 時使用相同白名單 internal tools，作為實驗性相容層。

Pi compatibility 只開放學習相關工具，例如：

- `get_lesson_context`
- `save_lesson_draft`
- `generate_activity`
- `evaluate_answer`
- `save_learning_result`

不直接開放檔案系統或命令列工具給兒童學習流程。

### 4.3 視覺語言模型服務

- 接收課本圖片。
- 辨識課文、單字、例句、文法與練習內容。
- 回傳結構化的課程資料。
- 保留原始圖片、來源頁碼與模型萃取狀態。

### 4.4 文字語言模型服務

- 產生適合小朋友理解的文法說明。
- 產生單字題、句型題與對話練習。
- 判斷答案並提供分級提示。

### 4.5 語音服務

- 語音轉文字：將小朋友的英文回答轉成文字。
- 文字轉語音：將系統的英文示範、提示與回饋播放給小朋友。

語音服務必須保留可替換的接口，地端模型與雲端服務都要能接入。TalkPath application services 與 UI 不直接依賴特定模型或供應商；實驗性 Pi compatibility 也沿用相同 provider 邊界。

建議抽象接口：

```text
SpeechToTextProvider
  transcribe(audio, options) -> Transcript
  transcribe_stream(audio_stream, options) -> TranscriptStream（預留）

TextToSpeechProvider
  synthesize(text, options) -> AudioResult
  synthesize_stream(text_stream, options) -> AudioStream（預留）
```

接口至少要能表達以下資訊：

- 語言與地區，例如 `en-US` 或 `en-GB`。
- 音訊格式、取樣率與聲道。
- 文字轉語音的聲音、速度與音調設定。
- 語音轉文字的時間戳、信心度與分段結果。
- 使用地端或雲端 provider 的選擇。

第一版可以先實作批次處理，但接口需預留串流方式，方便未來支援即時口說練習。provider、endpoint、模型名稱與 API 金鑰應由設定檔或環境變數控制，不寫死在 UI 或 Pi agent 中。

### 4.6 LessonLens Obsidian Vault

第一階段以 Markdown 筆記與 Properties 保存課程內容，並保留未來換成正式資料庫的可能。

建議的課程階層：

```text
學程
└── 年級
    └── 科目
        └── 課本或版本
            └── 課次
                ├── 課文
                ├── 單字
                ├── 文法
                ├── 例句
                ├── 互動活動
                └── 原始圖片與萃取紀錄
```

課程筆記可包含以下 Properties：

```yaml
program: 國中
grade: 一年級
subject: 英文
lesson: 第一課
source_type: textbook_image
extraction_status: draft
```

## 5. 第一版 MVP 範圍

先完成一條可以驗證整體概念的流程：

1. 上傳一張或多張英文課本圖片。
2. TalkPath UI 詢問並確認課程範圍。
3. `SessionService` 直接呼叫 Vision provider 萃取課文資料。
4. 將結果寫入 LessonLens 的 Obsidian Markdown 檔案。
5. TalkPath UI 詢問是否生成題目。
6. `ActivityService` 直接呼叫 Text provider 產生一組基本的單字或文法題目。

第一版暫不處理完整的個人化學習演算法、多使用者帳號與正式部署。

## 6. UI 功能與導覽

目前確認的學習活動包括：

- 詞彙練習（聽音＋跟讀＋STT 比對，含單字卡牆自選練習）
- 詞彙測驗
- 文法說明與練習
- 文法測驗
- 聽力練習
- 聽力測驗
- 閱讀／朗讀練習

> 2026-08-16 決策：原「口說練習（Speaking practice）」已取消。其無專屬題目形狀，只為通用題目加一顆不送出作答的錄音按鈕，與詞彙練習（真正的聽音＋跟讀＋STT 比對閉環）重覆；口說能力由詞彙練習與閱讀／朗讀涵蓋。

除了學習活動，完整 UI 還需要以下畫面：

### 6.1 兒童使用介面

- 首頁／學習地圖：顯示年級、課本、課次與目前進度。
- 新增課程：拍攝或上傳英文課本圖片。
- 課程範圍確認：確認學程、年級、科目與課次，例如「國中一年級、英文第一課」。
- 萃取處理狀態：顯示圖片分析、課文整理與題目生成進度。
- 課程總覽：集中顯示該課的詞彙、文法、聽力與閱讀活動。
- 學習活動頁：顯示題目、語音控制、錄音、提示與答案回饋。
- 結果頁：顯示完成狀態、分數、錯誤與建議複習項目。
- 錯題複習：重新練習孩子不熟悉的單字、文法或發音。
- 學習進度：顯示課次完成度與近期學習紀錄。

本版介面只提供給小朋友使用。

### 6.2 建議的 UI 導覽流程

```text
首頁
 ↓
選擇或新增課程
 ↓
拍攝課本
 ↓
確認課程範圍
 ↓
預覽萃取內容
 ↓
課程總覽
 ├─ 詞彙練習
 ├─ 詞彙測驗
 ├─ 文法說明與練習
 ├─ 文法測驗
 ├─ 聽力練習
 ├─ 聽力測驗
 └─ 閱讀／朗讀
 ↓
結果與錯題複習
 ↓
學習進度
```

學習活動與系統畫面要分開設計。六項核心活動是學習內容，而首頁、課程匯入、範圍確認、萃取預覽、結果複習與進度頁則負責把學習流程串成完整閉環。

## 7. 需要先固定的架構原則

- TalkPath 不直接依賴特定模型供應商，模型服務以介面隔離。
- 語音轉文字與文字轉語音必須以 provider adapter 隔離，地端服務是正式支援的部署選項，不是事後補做的替代方案。
- LessonLens 先使用 Obsidian，但 TalkPath 透過 `LessonRepository` 類似的資料存取介面讀寫，未來可以替換成資料庫。
- 原始圖片、萃取結果、人工修訂內容與生成活動要能追溯來源。
- 代理的工具必須採白名單，只提供學習流程需要的操作。
- 課程範圍必須在萃取前確認，避免把內容放到錯誤的年級或課次。
- 生成的題目應記錄它所依據的課文、單字或文法項目。
- 語音資料的保存方式要可設定，預設避免長期保存小朋友的原始錄音。

## 8. 設計決策狀態

除 Python／Pi 的整合細節外，其餘目前依建議採用：

- UI：第一版使用 Web UI。
- LessonLens：使用設定檔指定的本機 Obsidian Vault。
- 學習進度：第一版使用 SQLite，與 LessonLens 課程資料分離。
- STT／TTS：使用 provider adapter 隔離；第一版批次處理，接口預留串流。
- 使用者識別：第一版以單一小朋友學習 session 建模。
- 模型供應商：核心程式不寫死，透過 adapter 與設定切換。

2026-08-12 的 superseding 決策：production default 是 `TALKPATH_AGENT_BACKEND=direct`。Python 直接呼叫 Vision/Text provider 並協調 repository 與 speech ports；不建立 Pi 子程序。舊規格中把 Pi 描述成正常流程必要協調者的段落已被此決策取代。`TALKPATH_AGENT_BACKEND=pi` 僅保留為 experimental opt-in compatibility，才會啟動 Pi RPC 與受控 extension tools。

以下屬於實作設定，不再視為架構阻塞事項：

- 實際視覺模型、文字模型、STT 與 TTS 供應商。
- 地端 STT／TTS 的具體通訊協定與模型硬體需求。
- Obsidian Vault 的實際路徑與筆記模板細節。
- 課本圖片的暫存時間與學習資料保存期限。

## 9. 目前狀態

目前已完成需求、初步架構方向、UI 功能清單、STT／TTS 地端支援接口，以及 Python／Pi 整合方案的詳細設計，並已建立：

- 第一版設計規格 Draft：[2026-08-10-talkpath-design.md](superpowers/specs/2026-08-10-talkpath-design.md)
- 實作計畫書：[2026-08-10-talkpath-implementation.md](superpowers/plans/2026-08-10-talkpath-implementation.md)

TalkPath 程式碼、Obsidian Vault Markdown 結構、provider interfaces、direct Vision/Text backend 與測試替身已建立；Pi agent 不是 production 完成條件，只是尚未完成產品化驗證的 experimental opt-in compatibility。瀏覽器自動化與實體音訊設備仍未串接；真實模型與 speech live 狀態請以 `docs/PROGRESS-phase2-2026-08-13.md` 為準。

## 10. 參考資料

- [Pi Documentation](https://pi.dev/docs/latest)
- [Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)
- [Obsidian URI](https://help.obsidian.md/Extending%2BObsidian/Obsidian%2BURI)
# Task 9/10 verification update (2026-08-11)

Task 9 is implemented for the child-only flow: saved-lesson activity
generation, vocabulary/grammar/listening/reading/speaking activity contracts,
trusted answer evaluation, SQLite attempts and review items, public answer
redaction, and replaceable STT/TTS adapters with text fallback.

Task 10 adds the verified fake-provider vertical flow from textbook image to
LessonLens Markdown, activity generation, public answer submission, SQLite
progress, and recovery after a LessonLens repository restart. Integration tests
also cover invalid or incomplete images, missing scope confirmation, vision
timeout, Pi process exit, Markdown write failure, and unavailable TTS. A failed
import remains `FAILED` and is checked for absence of half-written lesson or
learning records.

Acceptance for the original Task 9/10 slice was deliberately limited to deterministic
fake providers and temporary storage. The superseding 2026-08-12 architecture uses
direct Vision/Text as the production default; Pi remains experimental opt-in compatibility.
DeepSeek Text and Kokoro TTS have live smoke evidence, Z.ai Vision is blocked by HTTP
429, and Qwen STT still needs a spoken-WAV recognition check. Browser automation,
physical audio devices, and the full provider-to-speech path remain incomplete.

The product remains a single child-facing experience; no parent or teacher role
is introduced by Task 9 or Task 10.
## 第二期 Provider 與本地語音整合（2026-08-12）

第二期目前已完成 fake、TalkPath HTTP、OpenAI-compatible Vision/Text，以及
local HTTP STT/TTS 的設定、registry、adapter contract 與安全 health 邊界。
真實 provider smoke tests 與 provider-to-speech E2E 已建立明確的
TALKPATH_LIVE_TESTS=1 gate；在未啟用時只會受控 skip，不會對外部模型或本地
語音服務發出請求。

截至本次交接，DeepSeek Text 已通過真實 live smoke；Z.ai Vision 實測回 HTTP 429，
Kokoro TTS 已通過 TalkPath live smoke；Qwen STT 已到達真實 endpoint，但仍需用含語音的 WAV 驗證辨識結果。Pi agent 不屬於 direct production flow 的必要接入項；瀏覽器自動化與實體音訊設備仍未接入，
因此不能把 Text 或 TTS 單項通過解讀為完整 provider-to-speech 已完成。API key、完整 URL query、prompt、圖片 base64
與音訊 bytes 不進入 health response 或 adapter 錯誤訊息。
