# TalkPath 第一版系統設計規格

| 項目 | 內容 |
| --- | --- |
| 專案 | TalkPath |
| 文件狀態 | Draft，等待使用者審閱 |
| 更新日期 | 2026-08-10 |
| 關聯進度 | [talkpath-progress.md](../../talkpath-progress.md) |
| 目標 | 建立兒童英文互動學習系統的第一版產品與系統設計 |

本文件把目前已確認的需求整理成可實作的系統邊界。尚未決定的模型供應商、地端執行方式與部署細節會列在「待審閱決策」，不在本文件中假設成已完成的功能。

## 1. 產品概述

TalkPath 是一個給小朋友使用的英文互動學習系統。小朋友可以拍攝英文課本內容，系統由 Pi agent 協調視覺語言模型、文字語言模型與語音服務，將圖片內容整理成 LessonLens 課程資料，再產生適合該課程的互動學習活動。

主要範例課程範圍：

```text
國中一年級 → 英文 → 第一課
```

### 1.1 名稱與責任

- **TalkPath**：小朋友使用的互動學習產品，以及整體應用程式名稱。
- **LessonLens**：以 Obsidian Vault 實作的課程內容資料庫，保存課文、單字、文法、活動與來源資訊。
- **Pi agent**：學習流程的協調者，負責確認課程範圍、呼叫模型服務、讀寫 LessonLens 與安排互動活動。

## 2. 目標與非目標

### 2.1 第一版目標

1. 小朋友可以提交一張或多張英文課本圖片。
2. Pi agent 在萃取前確認課本的學程、年級、科目與課次。
3. 視覺語言模型可以將課本內容整理成結構化課程資料。
4. 結構化資料可以保存到 LessonLens Obsidian Vault。
5. Pi agent 可以詢問是否生成題目，並生成至少一組單字或文法活動。
6. TalkPath 具有完整的兒童學習導覽與基本結果回饋。
7. 語音轉文字與文字轉語音以可替換接口設計，支援地端或雲端 provider。

### 2.2 第一版非目標

- 完整的個人化學習演算法。
- 複雜的多人帳號、訂閱與付款功能。
- 多使用者帳號與外部管理功能。
- 一開始就支援所有模型供應商與所有地端硬體。
- 將 Obsidian 立即替換成正式的雲端資料庫。

## 3. 使用者與使用情境

### 3.1 小朋友

- 上傳或拍攝課本圖片。
- 確認課程範圍。
- 選擇詞彙、文法、聽力、閱讀或口說活動。
- 回答問題、錄音並取得提示與回饋。
- 查看結果並複習錯題。

### 3.2 主要使用情境

```text
小朋友進入 TalkPath
        ↓
提交英文課本圖片
        ↓
Pi agent 確認「國中一年級、英文第一課」
        ↓
視覺語言模型提取課文資料
        ↓
儲存為 LessonLens 課程草稿
        ↓
Pi agent 詢問是否生成相關題目
        ↓
生成互動活動
        ↓
小朋友開始學習與取得回饋
```

## 4. 核心流程與狀態

### 4.1 課本匯入流程

```text
UPLOAD_IMAGE
  → CONFIRM_COURSE_SCOPE
  → EXTRACTING
  → PREVIEW_DRAFT
  → SAVE_LESSON
  → ASK_GENERATE_ACTIVITY
  → GENERATING_ACTIVITY
  → READY_FOR_PRACTICE
```

每個流程狀態都必須有失敗與重試路徑。課程範圍未確認前，不得把萃取結果寫入正式課程位置。

### 4.2 學習流程

```text
選擇課程
  → 課程總覽
  → 選擇學習活動
  → 顯示題目或語音指示
  → 回答／錄音
  → 評估與回饋
  → 記錄學習結果
  → 錯題複習或返回課程總覽
```

## 5. UI 資訊架構

### 5.1 兒童使用介面

- **首頁／學習地圖**：顯示年級、課本、課次與目前進度。
- **新增課程**：拍攝或上傳英文課本圖片。
- **課程範圍確認**：確認學程、年級、科目、課本與課次。
- **萃取處理狀態**：顯示圖片分析、課文整理與題目生成進度。
- **課程預覽**：顯示本次萃取出的課文、單字與文法摘要。
- **課程總覽**：集中顯示該課的學習活動。
- **學習活動頁**：支援題目、提示、語音播放、錄音與答案回饋。
- **結果頁**：顯示完成狀態、分數、錯誤與建議複習項目。
- **錯題複習**：重新練習不熟悉的單字、文法或發音。
- **學習進度**：顯示課次完成度與近期學習紀錄。

### 5.2 學習活動

- 詞彙練習
- 詞彙測驗
- 文法說明與練習
- 文法測驗
- 聽力練習
- 聽力測驗
- 閱讀／朗讀練習
- 口說練習

本版介面只提供給小朋友使用。課程預覽、範圍確認與題目生成都在同一個兒童學習流程中完成。

### 5.3 UI 導覽

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
 ├─ 閱讀／朗讀
 └─ 口說練習
 ↓
結果與錯題複習
 ↓
學習進度
```

## 6. 系統架構

第一版採用 Python 作為 TalkPath 主服務，由 Python 直接啟動 Pi 官方 RPC 子程序。Pi 本身在 Node.js runtime 中執行，但第一版不另外建立 Node.js sidecar 服務；Python 與 Pi 之間以官方 RPC／JSONL 溝通。日後若需要改成 Node.js SDK sidecar，不應影響 UI、資料格式與模型服務接口。

```text
┌──────────────────────────────┐
│ TalkPath UI                  │
│ 兒童學習介面                │
└──────────────┬───────────────┘
               │ HTTP／WebSocket
┌──────────────▼───────────────┐
│ TalkPath API（Python）       │
│ session／UI API／流程狀態    │
└───────┬──────────┬───────────┘
        │ RPC      │ service interfaces
┌───────▼──────┐   ├───────────────┐
│ Pi agent     │   │ VisionService │
│ RPC process  │   │ TextService   │
│ + extension  │   │ STT／TTS      │
└───────┬──────┘   └───────┬───────┘
        │ internal tools   │
        ├──────────────────┤
        │                  │
┌───────▼────────┐  ┌──────▼─────────────┐
│ LessonLens     │  │ ProgressRepository │
│ Obsidian Vault │  │ 第一版可用 SQLite  │
└────────────────┘  └────────────────────┘
```

### 6.1 模組責任

| 模組 | 責任 |
| --- | --- |
| TalkPath UI | 顯示流程、接收圖片／語音、呈現題目與回饋 |
| TalkPath API | session、驗證、流程狀態與前端 API |
| Pi agent | 協調工具與學習流程，不直接暴露任意系統工具 |
| VisionService | 圖片理解與課程內容萃取 |
| TextService | 文法解釋、活動生成、答案評估 |
| SpeechToTextProvider | 語音轉文字，支援地端／雲端 adapter |
| TextToSpeechProvider | 文字轉語音，支援地端／雲端 adapter |
| LessonRepository | 讀寫 LessonLens 課程內容 |
| ProgressRepository | 儲存學習結果、錯題與進度 |

### 6.2 Python／Pi 整合詳細設計

#### 6.2.1 第一版採用方案

Python 主服務內建立 PiRpcClient，負責啟動與管理 Pi 子程序：

```text
TalkPath API（Python）
        │
        │ 啟動並管理 stdin/stdout
        ▼
pi --mode rpc --no-session --no-builtin-tools
        │
        │ 載入 TalkPath extension
        ▼
.pi/extensions/talkpath-tools.ts
        │
        │ 受控的內部服務呼叫
        ▼
Python 的 Vision／Text／Speech／Lesson／Progress 服務
```

啟動參數的目的：

- `--mode rpc`：讓 Pi 以無頭模式運作，透過 JSONL 接收命令與輸出事件。
- `--no-session`：第一版不讓 Pi 自動保存完整對話；必要的課程與學習資料由 TalkPath 自己保存。
- `--no-builtin-tools`：關閉 read、bash、edit、write、grep、find、ls 等 coding tools，只保留 TalkPath extension 提供的學習工具。
- `--extension`：明確載入 TalkPath 的 TypeScript extension，不依賴未確認的全域 extension。

這個方案保留 Python 專案的主導權，同時利用 Pi 已經提供的 agent loop、工具呼叫、模型切換與事件串流能力。第一版不需要額外維護一個常駐 Node API server。

#### 6.2.2 程序生命週期

1. TalkPath API 啟動時建立 PiRpcClient。
2. PiRpcClient 啟動一個 Pi RPC 子程序，等待啟動成功或錯誤輸出。
3. 小朋友開始一個課程匯入流程時，Python 建立一個 learning session ID。
4. MVP 只支援一個目前使用中的小朋友 session；Pi 使用記憶體 session，學習結果寫入 SQLite，課程內容寫入 LessonLens。
5. 流程結束、取消或服務關閉時，Python 發送 abort 或正常關閉子程序。
6. Pi 程序意外結束時，Python 將目前操作標記為失敗，清理未完成的暫存資料後才允許重試。

未來若需要同時服務多個小朋友，改為 Pi worker pool 或每個 session 一個受控 worker，不改變 TalkPath 對外接口。

#### 6.2.3 Python 與 Pi 的訊息邊界

Python 只透過 JSONL 與 Pi 溝通，每一行是一個 JSON 訊息。所有可等待的請求都必須帶有 request ID，以便對應回應與事件。

```text
Python → Pi
  prompt       傳送 agent 指令、課程範圍與圖片參照
  abort        取消目前處理
  new_session  清除目前 agent 對話狀態

Pi → Python
  response              命令成功或失敗
  message_update        文字串流更新
  tool_execution_start  工具開始
  tool_execution_update 工具進度
  tool_execution_end    工具完成
  agent_settled         本次 agent 操作完全結束
  extension_error       extension 錯誤
```

Python 的 JSONL reader 必須以 LF 作為記錄分隔，不能直接使用會把 Unicode 分隔字元當成換行的通用 reader。UI 若使用 WebSocket，Python 將 Pi 的 message_update 與狀態事件轉成前端事件。

#### 6.2.4 Pi extension 與工具邊界

TalkPath extension 只註冊學習流程需要的工具：

```text
extract_lesson
save_lesson_draft
generate_activity
evaluate_answer
evaluate_pronunciation
transcribe_audio
synthesize_speech
save_learning_result
```

工具的執行原則：

- Pi agent 不能直接讀寫 Obsidian；由 Python 的 LessonRepository 處理。
- Pi agent 不能直接執行 shell、讀取任意檔案或存取使用者憑證。
- 圖片先由 Python 驗證並建立短期 image reference，工具只能使用已核准的 reference。
- 工具參數要經過 schema 驗證，並限制課程 ID、檔案路徑與輸入大小。
- 會寫入資料的工具必須帶 operation ID，避免 Pi 重試造成重複課程或重複題目。
- 工具錯誤要回傳可理解的錯誤類型，讓 Pi agent 能向小朋友提出重試或補充資料的要求。

extension 可以透過本機 loopback API 或受控 IPC 呼叫 Python 服務。這個內部接口不對小朋友的 UI 直接公開，也不接受未經 Pi agent 流程授權的請求。

#### 6.2.5 圖片、文字與語音的資料流

1. UI 將圖片上傳給 Python。
2. Python 檢查格式、大小與暫存位置，產生 image reference。
3. Python 將課程範圍與 image reference 傳給 Pi。
4. Pi 呼叫 extract_lesson，extension 將請求交給 Python 的 VisionService。
5. VisionService 回傳 LessonDraft，Pi 再要求 Python 保存草稿。
6. 文字活動、STT、TTS 與進度保存都沿用相同的受控工具邊界。

Pi 的推理模型與 TextService 可以使用不同模型：Pi 負責決定下一個工具與學習流程，TextService 負責文法解釋、題目生成與答案評估。

#### 6.2.6 取消、逾時與重試

- UI 取消操作時，Python 發送 abort，並停止等待該 operation 的後續結果。
- Vision、Text、STT、TTS 與寫入操作各自有設定的逾時，不使用一個無限等待。
- 可重試的工具錯誤要標記 retryable；課程範圍錯誤則要求 Pi 重新詢問，不自動重試。
- 保存草稿與活動的 operation ID 必須具備冪等性。
- Pi 程序重啟後不自動重播上一個會寫入資料的工具，避免重複寫入。

#### 6.2.7 為何第一版不採 Node.js SDK sidecar

Pi SDK 適合直接嵌入 Node.js 應用，能以 AgentSession 與 customTools 控制狀態；但 TalkPath 的主服務是 Python，新增 Node sidecar 會多出程序部署、健康檢查與另一層 API。官方文件也將 RPC 定位為跨語言與程序隔離的整合方式，因此第一版先使用 Python 直接啟動 Pi RPC。

若未來需要 Node 端直接管理大量 AgentSession、複雜的自訂工具或高併發 worker，再將 PiRpcClient 替換成 Node SDK worker；Python 對外的 session、工具結果與資料接口不變。

## 7. 服務接口

服務接口必須以能力與資料契約為中心，不綁定特定模型供應商。

### 7.1 課程範圍

```text
CourseScope
  program: string
  grade: string
  subject: string
  textbook: string?
  edition: string?
  lesson: string
  pages: list[string]?
```

### 7.2 視覺語言模型

```text
VisionService
  extract_lesson(images, course_scope) -> LessonDraft
```

LessonDraft 必須包含課文、單字、文法、例句、來源頁碼、萃取狀態與模型資訊。圖片模糊或範圍不明時，服務應回傳可供 agent 追問的問題，而不是自行猜測後直接寫入正式資料。

### 7.3 文字語言模型

```text
TextService
  explain_grammar(content, learner_context) -> Explanation
  generate_activity(content, activity_type, options) -> ActivityDraft
  evaluate_answer(activity, answer, context) -> Evaluation
```

文字模型的輸入必須包含課程來源內容，避免生成與該課無關的題目。生成活動需記錄所依據的內容項目 ID。

### 7.4 語音轉文字

```text
SpeechToTextProvider
  transcribe(audio, options) -> Transcript
  transcribe_stream(audio_stream, options) -> TranscriptStream（預留）
```

接口至少要能表達語言／地區、音訊格式、取樣率、分段結果、時間戳與信心度。

### 7.5 文字轉語音

```text
TextToSpeechProvider
  synthesize(text, options) -> AudioResult
  synthesize_stream(text_stream, options) -> AudioStream（預留）
```

接口至少要能表達語言／地區、聲音、速度、音調、輸出格式與取樣率。

第一版可先使用批次接口，但必須保留串流接口，方便未來支援即時口說練習。

### 7.6 課程資料存取

```text
LessonRepository
  get_lesson(course_scope) -> LessonDocument?
  save_lesson_draft(lesson_draft) -> LessonDocument
  save_activity(activity_draft) -> ActivityDocument
  list_activities(lesson_id, filters) -> list[ActivityDocument]
```

TalkPath 不直接依賴 Obsidian 的 UI；第一版由 Markdown repository adapter 讀寫 Vault，未來可替換成資料庫 adapter。

### 7.7 學習進度

```text
ProgressRepository
  record_attempt(learner_id, activity_id, result) -> Attempt
  get_progress(learner_id, course_scope) -> Progress
  list_review_items(learner_id, course_scope) -> list[ReviewItem]
```

第一版可用 SQLite 保存進度，並與 LessonLens 課程資料分離。

## 8. Pi agent 設計

### 8.1 Agent 流程

1. 接收圖片與使用者描述。
2. 取得或詢問 CourseScope。
3. 在範圍確認前，不執行正式保存。
4. 呼叫 VisionService 取得 LessonDraft。
5. 呼叫 save_lesson_draft 寫入 LessonLens。
6. 詢問是否生成互動題目。
7. 依使用者選擇呼叫 TextService.generate_activity。
8. 將活動保存並交給 TalkPath UI 呈現。
9. 在練習過程中呼叫答案評估、語音服務與進度保存工具。

### 8.2 白名單工具

第一版只提供學習流程需要的工具：

- get_lesson_context
- save_lesson_draft
- generate_activity
- evaluate_answer
- evaluate_pronunciation
- save_learning_result
- list_review_items

Pi agent 不直接取得任意檔案系統、命令列、網路或憑證工具。LessonLens 的檔案讀寫由受控的 LessonRepository 負責。

## 9. LessonLens 資料設計

### 9.1 建議目錄

```text
LessonLens/
└── curricula/
    └── junior-high/
        └── grade-1/
            └── english/
                └── lesson-01/
                    ├── lesson.md
                    ├── vocabulary/
                    ├── grammar/
                    ├── activities/
                    └── sources/
```

### 9.2 課程筆記 Properties

```yaml
id: junior-high-grade-1-english-lesson-01
program: 國中
grade: 一年級
subject: 英文
textbook: null
edition: null
lesson: 第一課
status: draft
source_type: textbook_image
source_images: []
extraction:
  provider: null
  model: null
  created_at: null
  confidence: null
```

### 9.3 內容項目

每個單字、文法、例句與課文片段都應有穩定的 content_id，並包含：

- type：vocabulary、grammar、dialogue、sentence 或 reading。
- content：原始或整理後的內容。
- translation：必要時提供中文說明。
- source_page：來源頁碼或圖片索引。
- confidence：模型萃取可信度。
- status：draft、reviewed 或 published。

### 9.4 活動資料

活動必須與來源內容關聯：

```yaml
activity_id: activity-001
type: vocabulary_quiz
lesson_id: junior-high-grade-1-english-lesson-01
source_content_ids:
  - vocab-001
difficulty: beginner
status: draft
```

## 10. 地端語音支援

STT／TTS 的地端支援是正式架構需求。上層服務只依賴 provider interface，實際 provider 由設定檔或環境變數選擇。

```yaml
speech:
  stt:
    provider: local
    endpoint: http://localhost:0000
    model: local-stt-model
  tts:
    provider: local
    endpoint: http://localhost:0001
    model: local-tts-model
```

設定內容不可寫死在 UI 或 Pi agent。地端 provider 應提供健康檢查、能力資訊與清楚的錯誤回應；若語音服務不可用，TalkPath 至少要能退回文字互動，不應讓整個課程流程失效。

第一版可先驗證批次語音接口，串流語音保留為後續口說即時互動的擴充。

## 11. 錯誤處理

| 情境 | 系統行為 |
| --- | --- |
| 圖片模糊或頁面不完整 | 顯示原因，要求重新拍攝或補充頁面 |
| 課程範圍不明 | Pi agent 追問，不自行決定正式範圍 |
| 視覺模型萃取失敗 | 保留失敗狀態與原圖，提供重試 |
| 萃取結果可信度低 | 顯示問題，要求小朋友重新拍攝或確認後再繼續 |
| 文字模型暫時不可用 | 顯示可理解的錯誤，保留已保存課程 |
| 地端 STT／TTS 不可用 | 提供重試或切換 provider；必要時使用文字模式 |
| 題目生成失敗 | 不影響課程資料，允許稍後重新生成 |
| Obsidian 寫入失敗 | 不標記為完成，保留 draft 與可重試狀態 |

## 12. 隱私與安全

- 小朋友的圖片、錄音與學習紀錄要與課程內容分開管理。
- 原始錄音預設不長期保存，除非使用者明確啟用保存功能。
- 地端模式下，圖片與語音可留在本機或內網，不應被強制送往雲端。
- 模型輸入與生成內容都要保留必要的來源與版本資訊。
- Pi agent 只允許白名單工具，不直接使用任意檔案或命令工具。
- 已確認的課程內容要保留版本與來源，避免後續重新萃取時無聲覆蓋既有內容。

## 13. MVP 與驗收條件

### 13.1 MVP 階段

第一階段先完成文字與課程內容閉環：

1. 圖片上傳。
2. 課程範圍確認。
3. 視覺模型萃取。
4. LessonLens Markdown 保存。
5. 生成一組詞彙或文法活動。
6. UI 顯示活動與基本結果。

第二階段接入實際 STT／TTS，完成聽力與口說活動；接口與 provider adapter 在第一階段即保留。

### 13.2 驗收條件

- 使用者上傳課本圖片後，系統必須先要求確認課程範圍。
- 範圍未確認時，不得寫入正式課程資料。
- 成功萃取後，可以在 LessonLens 找到對應的課程 Markdown 與來源資訊。
- 生成的活動可以追溯到課文、單字或文法內容項目。
- 視覺模型、文字模型與語音 provider 可透過設定切換，不需修改 UI 流程。
- STT／TTS provider contract 可以用地端測試 provider 驗證。
- 任何主要服務失敗時，都有可理解的提示與重試方式。

## 14. 設計決策狀態

除 Python／Pi 的整合細節外，以下建議依目前需求採用。具體模型名稱、地端 endpoint 與套件版本屬於實作設定，不改變本架構。

| 決策 | 狀態與內容 |
| --- | --- |
| UI 形式 | 已採用：第一版使用 Web UI |
| Python／Pi 整合 | 建議採用：Python 直接啟動 Pi 官方 RPC 子程序；詳細設計見 6.2 |
| LessonLens 路徑 | 已採用：由設定檔指定本機 Obsidian Vault |
| 進度儲存 | 已採用：第一版使用 SQLite，與 LessonLens 分離 |
| STT／TTS 協定 | 已採用：provider adapter 隔離；實際地端協定屬實作設定 |
| 語音處理 | 已採用：第一版批次處理，接口預留串流 |
| 使用者識別 | 已採用：第一版以單一小朋友學習 session 建模 |
| 模型供應商 | 已採用：核心程式不寫死，透過 adapter 與設定切換 |

進入實作前，Python／Pi 方案只需要確認本機 Pi CLI、TalkPath extension 的打包方式，以及內部工具呼叫採用 loopback HTTP 或其他 IPC；這些不會改變 TalkPath 的外部 API 與資料格式。

## 15. 參考資料

- [Pi Documentation](https://pi.dev/docs/latest)
- [Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)
- [Obsidian URI](https://help.obsidian.md/Extending%2BObsidian/Obsidian%2BURI)
## Task 9/10 implementation and acceptance status (2026-08-11)

The current implementation preserves the single child-facing role described in
this specification. Task 9 supplies the saved-lesson activity service,
trusted answer evaluation, SQLite attempt/review persistence, public answer
redaction, and replaceable STT/TTS contracts with a text fallback.

Task 10 verifies the end-to-end fake-provider path: confirmed course scope and
textbook image upload, LessonLens `lesson.md` plus vocabulary/grammar notes,
`vocabulary_quiz` generation, incorrect public answer feedback, SQLite attempt
and review item persistence, public lesson/activity/progress reads, and
activity recovery after reopening the LessonLens repository. Failure tests
cover invalid/incomplete images, scope gate rejection, Vision timeout, Pi
process exit, Markdown write failure, and unavailable TTS. Error handling keeps
the existing domain exception boundary and marks failed imports as `FAILED`
without publishing partial lesson or learning records.

The acceptance evidence uses deterministic fakes and temporary SQLite and
LessonLens paths. Actual model services, real Pi/browser/device integration,
and physical audio capture/playback are intentionally not claimed as complete.
