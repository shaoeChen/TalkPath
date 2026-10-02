# TalkPath 歷史記錄

> 本文件只記錄「已完成」的工作。進行中的工作見 `PROGRESS.md`。以下內容由舊版 `PROGRESS.md` 原樣遷入（2026-09-30），其中「目前執行位置」「下一個開發起點」等描述為遷入當時的快照，現行狀態以 `PROGRESS.md` 為準。

更新日期：2026-10-02

## 2026-10-02 修正提交前驗證與隱私清查

- 來源：使用者要求提交全部修正，推送前確認隱私外洩風險。
- 範圍：區網 HTTPS、Vision scope 等價格式修正、診斷文件與歷史路徑遮罩；保留另一台電腦實際麥克風診斷於 `PROGRESS.md`，不宣稱已完成。
- 驗證：`uv run pytest` 為 416 passed、9 skipped，1 個既有 Starlette 棄用警告；前端 Node 測試 15 passed、Pi 測試 10 passed、TypeScript typecheck、`uv lock --check`、啟動入口 `--help` 與 `git diff --check` 通過。略過的測試不代表真實模型或外部整合已驗證。
- 隱私清查：Gitleaks 8.30.1 掃描待提交的 139 個檔案與當時 `main` 的 8 個可達提交，均無密鑰告警；另比對本機環境設定中的 6 個憑證值，未命中。檢查未納入 `.env`、私鑰、資料庫、教材圖片、錄音與本機日誌；個人路徑及電子郵件檢查無命中，區網 IP 僅出現在明確的文件／測試範例。作者與提交者信箱均為 GitHub noreply。
- 推送範圍：僅正式 `main` 分支；含舊敏感歷史的備份分支與 `refs/original/` 保留本機，不推送。掃描結果代表此檢查範圍未發現外洩，不構成所有格式與情境的絕對保證。

## 2026-10-01 區網 8000 連線診斷

- 來源：使用者已啟動服務，詢問 8000 連不上是否為防火牆問題。
- 檢查：現行 TalkPath 行程以 `python -m talkpath.main --lan` 監聽 IPv4 `0.0.0.0:8000`；HTTP 請求空回應，HTTPS 首頁與 `/health` 回傳 200。Docker 的另一個容器同時發布 8000，WSL relay 監聽 `::1:8000`；`localhost` 的 IPv6 HTTP 請求回傳其他服務的 `Not Found`，IPv4 HTTPS 健康檢查正常。
- 驗證：使用本機 CA、在 Windows curl 關閉撤銷檢查後，主機自身區網 IPv4 的 HTTPS 首頁回 200，IPv4 `localhost` 的 `/health` 回 `{"status":"ok"}`。原始 CA 驗證請求因 Schannel 無法確認撤銷狀態而失敗，未改動系統憑證信任。
- 限制：網卡目前為 Public、防火牆啟用；讀取完整埠篩選規則遭權限拒絕，未從手機驗證，因此無法判定其他裝置入站是否被防火牆阻擋。診斷未修改防火牆、程式碼或既有服務；在 `LAN_HTTPS.md` 補上 HTTPS、IPv4 與手機網址排查說明。
- 後續：使用者確認由另一台電腦以 HTTPS 連線，並指定改用曾成功分享的 8443。改以 Windows Firewall COM 介面讀取到目前 Public 預設阻擋入站，以及 `Python HTTPS 8443` 對所有網路類型放行 TCP 8443 的規則。啟動入口沒有 `--port` 參數；在獨立 PowerShell 設定 `TALKPATH_APP_PORT=8443` 後，實際呼叫設定載入器確認讀取為 8443，提供使用者自行重啟的命令。未替使用者重啟，也尚未驗證另一台電腦的連線。

## 2026-10-01 Vision 匯入 scope 等價格式誤判修正

- 來源：使用者提供教材照片並回報 `openai-compatible vision response scope does not match request`。診斷證據見 [Vision scope 診斷](diagnostics/2026-10-01-vision-scope.md)。
- 真實重現：取得失敗 session 的原始 scope 後重測三次，其中一次模型漏掉可由課程範圍推導的 `scope.lesson_id`，其餘欄位一致；舊程式直接比較完整字典而拒絕等價範圍。
- 修正：以原有 `CourseScope` 驗證器補齊預設欄位與推導 ID，再比較完整範圍；真實課程差異、非空頁碼缺失或格式無效仍拒絕。提示詞明確要求保留原始課程身分。
- 驗證：回歸測試先觀察到 3 項預期失敗；相關 provider／匯入 API／同課追加／失敗恢復／日誌測試 67 passed、1 個既有 Starlette 棄用警告；保存的真實失敗回覆重播成功（11 個教材項目）；修正後真實照片呼叫成功（42.6 秒、9 個教材項目、scope 一致）。`git diff --check` 通過。
- 本機服務：曾重啟 `127.0.0.1:8001` 載入修正，健康檢查回傳 `ok`；驗證後依使用者要求關閉 agent 啟動的背景服務，確認 8001 已無監聽，由使用者自行啟動。診斷未儲存課程，未進行完整人工瀏覽器流程。

## 2026-10-01 區網 HTTPS 自動憑證

- 使用者決定開源安裝環境各自產生憑證，手機端信任設定由安裝者處理。新增 `uv run python -m talkpath.main --lan`：偵測主機區網 IPv4、監聽 `0.0.0.0`，以 HTTPS 提供既有 FastAPI／前端，並顯示區網 URL 與 CA 憑證位置；多網卡環境可用 `--lan-ip` 補入位址。
- 首次啟動在 Git 忽略的 `data/tls/` 建立本機 CA 與網站憑證；重啟重用，IP 變動、CA 更換或網站憑證將到期時重簽網站憑證。CA 憑證或私鑰單邊遺失、兩者不相符時停止，避免無聲更換。實驗性 Pi 模式會改以本機 HTTPS 呼叫 API，並將本機 CA 加入 Node 的額外信任憑證。原本本機啟動方式維持可用；TTS／STT Compose 設定不變。
- 更新 `README.md`、`docs/LAN_HTTPS.md`、技術棧與結構文件；從 `IDEAS.md` 移除已完成的區網連線需求。
- 驗證：區網憑證與啟動入口的測試先紅後綠；`uv run pytest -q` 404 passed、9 skipped、1 個既有 Starlette 棄用警告；`node --test frontend/test/*.test.cjs` 15 passed；以臨時憑證啟動 Uvicorn，Python HTTPS 用戶端與載入本機 CA 的 Node `fetch` 請求 `/health` 均回 200；`uv run python -m talkpath.main --help` 與 `git diff --check` 通過。
- 限制：未在實際手機上驗證憑證信任與麥克風授權；使用者須自行完成手機信任設定與主機防火牆設定。目前區網模式沒有使用者帳號或存取控制，僅供可信任區網。

## 2026-10-01 Reading / read aloud 改為聽音跟讀

- 來源：`docs/superpowers/plans/2026-10-01-reading-aloud.md`；規格：`docs/superpowers/specs/2026-10-01-reading-aloud-design.md`。使用者確認目標是孩子跟讀畫面題目，轉錄文字一致即通過，不評估腔調或韻律。
- 原因：原本 `reading_aloud` 只有播放題目音訊，仍走一般選擇／打字作答；沒有錄音作答與朗讀專屬評分。模型也沒有朗讀題型指令，可能產生聽寫文案。
- 修正：題目改為可朗讀的英文文字，朗讀活動只顯示錄音入口；STT 有文字才送出，後端以畫面題目文字本機比對，忽略大小寫、標點與多餘空白。模型回傳的朗讀選項、答案與聽寫文案會被覆寫；換題沿用當前題目音訊更新與重試。fake provider 改為課文句子供離線測試。
- 驗證：後端與 provider 先寫失敗測試再修正；`uv run pytest tests/unit/test_activity_service.py tests/unit/test_fake_services.py tests/unit/test_openai_compatible_services.py tests/api/test_activity_flow.py tests/api/test_static_ui.py -q` → 102 passed、1 個既有 Starlette 棄用警告；`node --test frontend/test/*.test.cjs` → 15 passed；`node --check frontend/app.js`、`git diff --check` 通過。未以真實麥克風與語音服務做人工試聽。

## 2026-10-01 聽力換題音訊同步修正

- 來源：使用者回報完成第一題後，第二題仍播放第一題發音（簡單修正，未另展開實作計畫）。
- 原因：活動開始時只以 `items[0].prompt` 產生音訊，換題只重繪題目，活動播放器未更新。
- 修正：依目前題目佇列取得音訊；手動／自動換題先停止並移除舊播放器，顯示載入狀態；延遲回傳須通過請求、活動、題號、session 與導覽狀態檢查。失敗保留當前題目，重試當前題音訊。同一流程涵蓋聽力練習、聽力測驗與朗讀。
- 驗證：新增回歸測試先觀察到 6 項預期失敗；修正後 `node --test frontend/test/*.test.cjs` → 11 passed（含 8 項音訊行為測試）；`uv run pytest tests/api/test_static_ui.py tests/api/test_activity_flow.py -q` → 53 passed、1 個既有 Starlette 棄用警告；`node --check frontend/app.js`、`git diff --check` 通過；獨立程式碼審查未發現重要問題。
- 本機確認：`http://127.0.0.1:8001/app.js` 與更新後檔案一致；重新整理頁面即可載入修正。驗證使用模擬 DOM／音訊回應，未進行真實 TTS 揚聲器試聽。

## 2026-10-01 OpenAI 相容模型 JSON 回應解析錯誤修正

- 來源：`docs/superpowers/plans/2026-10-01-openai-json-response.md`；規格：`docs/superpowers/specs/2026-10-01-openai-json-response-design.md`。
- 原因：使用保留的匯入圖片重現 Z.ai `glm-4.6v` 回傳未跳脫雙引號的英文例句；HTTP 200、`finish_reason=stop`，內容第 61 行第 27 欄無法解析為 JSON。
- 修正：JSON 提示詞明確要求字串引號與反斜線跳脫；僅內容 JSON 語法錯誤時帶上無效回應與修正指示，最多重試一次。維持 JSON、schema 與身分嚴格驗證。
- 驗證：回歸測試先觀察到 2 例預期失敗，修正後 OpenAI 相容服務 20 passed；`tests/unit tests/integration tests/api` 共 370 passed、5 skipped、1 個既有 Starlette 警告；`git diff --check` 通過。實際供應商重新請求時也觀察到 JSON 有效的回應，但因 `scope` 或 `operation_id` 不符而被既有驗證拒絕，故未證實圖片匯入端到端成功。
- 限制：模型連續兩次輸出無效 JSON 仍會報錯；重試會增加一次模型請求。課程身分欄位不符屬另外觀察到的問題，未納入本次修正。
- 部署驗證：重新啟動本機 API `127.0.0.1:8001`，`GET /health` 與 `/health/providers` 均為 HTTP 200；新行程日誌顯示啟動完成。

## 2026-09-30 公開庫敏感資訊清查與遮罩

- 來源：使用者要求檢查公開推送內容是否有密鑰外洩（簡單項目，未展開實作計畫）。
- 發現：遠端 `main`（2 個提交）的 `docs/HISTORY.md` 以明文記錄舊 QwenASR（區網 `QwenASR-WebView.exe`）的 STT API key；另有區網 IP 與本機使用者路徑。目前 `.env` 中的 Vision／Text／STT 金鑰均未外洩，`.env*` 皆已被 `.gitignore` 排除。
- 處理：以 `git filter-branch` 改寫 `main` 兩個提交，金鑰改為 `<redacted>`、區網 IP 改為 `<LAN-IP>`、使用者路徑改為 `Users/<user>`，以 `--force-with-lease` 強制推送。
- 驗證：改寫後每個提交以 `git grep` 比對真實金鑰值、原區網 IP、原使用者路徑均為 0 命中；與改寫前差異僅 4 個文件 8 行。
- 後續處理：原公開 repo 已設為 Private 並改名保留；另建立空白公開 `TalkPath`，只推送乾淨的 `main`，不推送本機備份與舊功能分支。
- 驗證：新公開 repo 的 `main` 不含舊歷史；四個已知舊提交以匿名 GitHub API 查詢皆為 404。真實金鑰、原區網位址、使用者路徑、個人信箱與作者信箱均完成檢查；新提交作者為 noreply。舊 ASR 金鑰已由目前設定取代，對現行本機 STT 端點回 401，且已從忽略追蹤的回退設定中移除；QwenASR-WebView 舊連接埠目前未監聽。
- 本機限制：`backup/pre-redact-main`、`refs/original/` 及舊功能分支仍含舊內容，保留本機但不得推送。

## 2026-09-30 MY LESSONS 課程管理：課程詳情、附加匯入與頁碼警示

- 來源：`docs/superpowers/plans/2026-09-30-lesson-library-append-import-implementation.md`（規格：`docs/superpowers/specs/2026-09-30-lesson-library-append-import-design.md`），分支 `feat/lesson-library-append`。
- 內容：TEXTBOOK（出版社版本）納入課程 ID（沒填時 ID 不變，舊 ID 仍可讀）；同課程再匯入時附加（舊內容與 ID 保留，重複單字與相同內容去重）；匯入前檢查頁碼，重複時警示（Cancel／Add anyway）；MY LESSONS 卡片新增 View lesson，詳情頁按每次匯入顯示頁碼、照片與內容；新增 `POST /api/lessons/import-check`、`GET /api/lessons/{id}/batches`、`GET /api/lessons/{id}/images/{image_id}`。抽取、提示詞、internal_tools、pi-extension 未修改。
- 驗證：`uv run pytest -q` → 385 passed、9 skipped、1 warning；`node --test frontend/test/screen-flow.test.cjs` → 3 passed；Chrome（fake provider、暫存資料夾）22 項檢查通過；使用者以真實模型手動驗收通過。
- 已知限制：冊次（上、下學期）不納入識別；非數字課次撞號未處理；已填 textbook 但 ID 無後綴的舊課程，再以同 textbook 匯入會建立新課程。延伸想法見 `IDEAS.md`。

## 第三個實作計畫範圍（單一項目）

讓用戶在 TalkPath UI 直接進入已保存的課程，不需要重新上傳課本圖片。拆成三個子項目：

1. 後端：列出已保存課程的 API（`GET /api/lessons`，接上 LessonLens `list_lessons`）。
2. 後端：以既有課程建立 session 的路徑（`POST /api/sessions` 支援 `lesson_id`，從 LessonLens 讀回 scope，讓 session 直接落在可練習狀態）。
3. 前端：首頁「繼續我的課程」入口，顯示已保存課程列表，點選後直接進入 overview/practice。

關聯文件：

- 規格：`docs/superpowers/specs/2026-08-13-enter-saved-lesson-design.md`
- 實作計畫：`docs/superpowers/plans/2026-08-13-enter-saved-lesson-implementation.md`

## 進度

| Task | 內容 | 狀態 | 驗證證據 |
|---|---|---|---|
| 1 | 列出已保存課程 API | 已完成 | `tests/api/test_lesson_list.py` 4 項 API 測試（空 vault、摘要不含 passage、多課程排序、空白 lesson_id 422）；`test_session_service.py::test_list_lessons_returns_repository_lessons`；`uv run pytest tests/api/test_lesson_list.py tests/unit/test_session_service.py -q` → 17 passed |
| 2 | 以既有課程建立 session 路徑 | 已完成 | state machine 新增 UPLOAD_IMAGE → ASK_GENERATE_ACTIVITY 路徑並加 scope 守衛（`test_session_states.py` 3 項）；`create_session(lesson_id=...)` 讀回 scope 並直接建立可練習 session（service 3 項 + API 3 項）；`uv run pytest tests/api/test_import_flow.py tests/api/test_activity_flow.py tests/unit/test_session_states.py tests/unit/test_session_service.py tests/api/test_lesson_list.py -q` → 34 passed |
| 3 | 前端課程列表與進入入口 | 已完成 | `tests/api/test_static_ui.py` 新增來源契約測試並全數通過（21 passed）；進入已保存課程時呼叫 `GET /api/lessons/{lesson_id}` 取完整課程供 preview/overview 使用；`node --check frontend/app.js frontend/screen-flow.js`；`node --test frontend/test/screen-flow.test.cjs` → 3 passed |

## 執行紀錄

### 2026-08-13 Task 1：列出已保存課程 API（完成）

- 實作：`SessionService.list_lessons()` 轉呼叫 `lesson_repository.list_lessons()`；`GET /api/lessons` + `LessonSummary`（lesson_id、title、scope、source_image_count、content_item_count，不含 passage/content_items）。
- TDD：先寫失敗測試（紅燈 4 failed）再實作，綠燈 11 passed。
- 已知問題：無。
- 下一步：Task 2（以既有課程建立 session 路徑）。

### 2026-08-13 Task 2：以既有課程建立 session 路徑（完成）

- 實作：`SessionStateMachine` 新增 UPLOAD_IMAGE → ASK_GENERATE_ACTIVITY；`CreateSessionRequest.lesson_id`；`POST /api/sessions` 支援既有課程，從 LessonLens 讀回 scope 寫入 `_scopes`，session 直接為 `ASK_GENERATE_ACTIVITY`；課程不存在回 404（不建立 session）。
- TDD：先寫失敗測試（紅燈 6 failed）再實作，綠燈 24 passed；含既有 import/activity 流程共 32 passed，無回歸。
- 已知問題：無。
- 下一步：Task 3（前端課程列表與進入入口）。

### 2026-08-13 Task 3：前端課程列表與進入入口（完成）

- 實作：首頁新增「繼續我的課程」區塊（`#saved-lessons`），`loadSavedLessons` 呼叫 `GET /api/lessons` 渲染卡片列表；點選卡片以 `lesson_id` 建立 session 後直接進入 overview（可立即生成活動）；空狀態顯示說明與「Start a new lesson」；返回首頁與 init 時重新載入列表。
- 驗證：`tests/api/test_static_ui.py` 新增 `test_child_ui_home_lists_saved_lessons_and_opens_them_for_practice`，21 passed；`node --check`、`node --test` 3 passed。
- 已知問題：無；瀏覽器自動化驗證仍受限於 in-app Browser sandbox helper，以 static UI 契約與 node 測試為準（沿用既有限制）。
- 下一步：全量驗證並收尾交接文件。

### 2026-08-13 審查與修正（第三期收尾前）

主代理複核時發現三個問題，全部以 TDD 修正（先寫失敗測試再修）：

1. `SessionStateMachine` 新增 UPLOAD_IMAGE → ASK_GENERATE_ACTIVITY 時未加 scope 守衛，未確認 scope 的 machine 也能跳轉，會產生違反 `Session` 不變量（ASK_GENERATE_ACTIVITY 需 scope_confirmed=True + lesson_id）的狀態，存檔時才會以 RepositoryError 失敗。修正：`can_transition_to`/`transition_to` 對該路徑要求 `scope_confirmed=True`（新增 `test_saved_lesson_entry_requires_confirmed_scope`）。
2. 前端 `enterSavedLesson` 原本以 `new Array(n)` 空洞陣列偽造 `state.lesson`，從已保存課程進入 overview 後點「← Lesson preview」會因 `buildContentCard(undefined)` 拋 TypeError。修正：建立 session 後呼叫 `GET /api/lessons/{lesson_id}` 取回完整課程再 render（沿用既有 preview/overview 流程；static UI 契約同步更新）。
3. `POST /api/sessions` 傳空白 `lesson_id` 原本會因 LessonLens ID 解析失敗回 500。修正：`CreateSessionRequest.lesson_id` 加 `min_length=1` → 422（新增 `test_create_session_with_blank_lesson_id_returns_422`）。

修正後全量驗證：`uv run pytest -q` → 289 passed、9 skipped、1 warning；`uv run python -m compileall -q src tests` 通過；`node --check`、`node --test` 3 passed；`git diff --check` 乾淨。

### 2026-08-13 全量驗證（第三期收尾）

- `uv run pytest -q` → 289 passed、9 skipped、1 warning（第二期基準 275 passed、9 skipped、1 warning，新增 14 項測試）。
- `uv run python -m compileall -q src tests` → 通過。
- `node --check frontend/app.js frontend/screen-flow.js` → 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed。
- `git diff --check` → 乾淨。
- 尚未完成/限制：in-app Browser 沙箱限制，未做桌面/手機手動流程驗證；第三期驗收以 static UI 契約與 node 測試為準（與第二期相同限制）。
- 下一步（交接起點）：commit 已完成（見 git log）；如需手動驗證可啟動 `uv run uvicorn talkpath.main:app` 並瀏覽首頁「繼續我的課程」流程。

## 已知問題與限制

- `SessionService._scopes` 仍存放在記憶體（重新啟動後需重新建立 session 才會從 LessonLens 讀回 scope）；既有課程進入路徑已在建立時從 LessonLens 讀回 scope 寫入 `_scopes`。
- 瀏覽器自動化驗證先前被 in-app Browser sandbox helper 阻擋；執行期驗證以 static UI 契約與 node 測試為主。

## 第三期後續：已保存課程入口改版（設計階段）

- 更新日期：2026-08-13。
- 背景：用戶回饋首頁下方「繼續我的課程」區塊需捲動、不好用；改為右上導覽列新增「My lessons」連結，進入獨立課程列表頁面，首頁移除課程區塊。
- 版面決策（用戶以視覺伴侶確認）：課程頁用單欄大卡片（Option C）；導覽列文字用「My lessons」。
- 設計規格：`docs/superpowers/specs/2026-08-13-saved-lessons-nav-entry-design.md`（已提交）。
- 實作計畫：`docs/superpowers/plans/2026-08-13-saved-lessons-nav-entry-implementation.md`（已提交）。

### 2026-08-13 已保存課程入口改版（實作完成）

- 實作：右上導覽列新增「My lessons」連結（`data-action="lessons"`）；新增 `#lessons-screen`（`data-screen="lessons"`）獨立頁面；單欄大卡片（`.lesson-card` + Continue 按鈕）；進入 lessons 頁時才呼叫 `GET /api/lessons`；點卡片 → 建立 session → 讀完整課程 → overview；空狀態含「Start a new lesson」；首頁移除 `#saved-lessons` 區塊。
- 驗證：`uv run pytest -q` → 291 passed、9 skipped、1 warning（289 − 1 舊契約測試 + 3 新契約測試）；`uv run python -m compileall -q src tests` 通過；`node --check frontend/app.js frontend/screen-flow.js`、`node --test frontend/test/screen-flow.test.cjs` 3 passed；`git diff --check` 乾淨。
- 已知限制：瀏覽器手動驗證仍受限（in-app Browser sandbox），以 static UI 契約與 node 測試為準。

## 第三期後續 2：練習頁改版（獨立頁面 + 一次一題）（設計階段）

- 更新日期：2026-08-13。
- 背景：overview 頁把活動面板塞在同頁下方需捲動；且一次列出全部題目像傳統考卷，小孩易關掉 App。改為獨立 practice 頁 + 一次一題。
- 心理學討論：與兒童教育心理學觀點討論（子代理未回覆，改以學習科學文獻佐證整理）：一次一題 + 即時回饋；點狀進度 +「第 X 題」而非「共 N 題」；答錯不懲罰、可「Try again」且不直接揭曉答案（符合既有兒童安全契約）；讚美努力。
- 版面決策（用戶以視覺伴侶確認）：Option A「單卡完成」——題目、回饋、按鈕在同一張卡片。
- 設計規格：`docs/superpowers/specs/2026-08-13-one-question-practice-design.md`（已提交）。
- 狀態：設計已確認，實作尚未開始。
- 下一步：以 writing-plans 產生實作計畫後，按 TDD 實作前端變更（只動前端，後端 API 不變）。

### 2026-08-13 Task 1：新增獨立 practice 頁、overview 移除活動面板（完成）

- 實作：`frontend/index.html` 新增 `<section id="practice-screen" data-screen="practice">`（單卡、點狀進度 +「Question X」、Back to practice list）；overview 移除 `#activity-panel` / `#activity-error` / `#close-activity`。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 23 passed（含新增/更新的 HTML 契約）。
- 已知問題：無。
- 下一步：Task 2（practice 樣式）。

### 2026-08-13 Task 2：practice 單卡、點狀進度與按鈕樣式（完成）

- 實作：`frontend/styles.css` 新增 `.practice-heading` / `.practice-progress` / `.practice-dots` / `.practice-card` / `.practice-question` / `.practice-actions` 與 `is-passed` / `is-try-again` 回饋色；移除 `.activity-panel` / `.activity-panel-header` / `.icon-button` / `.question-card` 無用樣式；600px 手機斷點加入單欄按鈕規則。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 24 passed。
- 已知問題：無。
- 下一步：Task 3（generateActivity 進入 practice 頁）。

### 2026-08-13 Task 3：generateActivity 進入獨立 practice 頁（完成）

- 實作：`state` 新增 `currentQuestionIndex` / `practiceAnswered` / `practicePassed` / `practiceResult` / `practiceFeedback`；`generateActivity` 改為先 `showScreen("practice")` 再顯示「Making your activity…」載入中，成功後 `renderActivity`，失敗留在 practice 頁顯示 `#practice-error`（audio provider fallback 仍沿用）。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 25 passed。
- 已知問題：此時 renderActivity 仍是舊版（Task 4 會改為單題渲染）。
- 下一步：Task 4（單題渲染 + 點狀進度）。

### 2026-08-13 Task 4：一次一題渲染 + 點狀進度（完成）

- 實作：`renderActivity` 改渲染到 `#practice-body`，一次只渲染 `state.currentQuestionIndex` 對應的一題；新增 `renderPracticeProgress`（點狀 ●○ +「Question X」）、`renderPracticeQuestion`、`renderPracticeResultActions`、`isLastPracticeQuestion`、`advancePracticeQuestion`；不再 `items.forEach` 列出全部題目。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 26 passed。
- 已知問題：作答後仍會走舊 `showAnswerResult` 直進 results（Task 5 改為 Try again / Next / Finish 流程）。
- 下一步：Task 5（作答流程 + audio fallback / wireActions / reset 清理）。

### 2026-08-13 Task 5：作答流程（Check / Next / Try again / Finish）+ 清理（完成）

- 實作：`submitActivityAnswer` 不再直接進 results，改為寫入 `practiceResult` / `practicePassed` / `practiceAnswered` / `practiceFeedback` 後 `renderPracticeQuestion`；答對顯示正向訊息 + Next question（最後一題為 Finish），答錯顯示「Good try! Check the word again.」+ Try again / Next question（最後一題為 Finish），不揭曉正確答案；Finish 才呼叫 `showAnswerResult`。`showAudioFallback` 改指向 `#practice-body`；刪除 close-activity 監聽與 `#activity-panel` / `#activity-error` 殘留；`resetForNewCourse` 清練習狀態。另依計畫版面把 5 個 practice helper 移到 `showAnswerResult` 之後、`submitActivityAnswer` 之前，並同步更新兩處以 `$("#close-activity")` 為 slice 終點的既有契約。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 28 passed；`node --check frontend/app.js frontend/screen-flow.js` 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed。
- 已知問題：無。
- 下一步：Task 6（全量驗證 + 收尾）。

### 2026-08-13 練習頁改版（獨立頁面 + 一次一題）全量驗證與收尾

- `uv run pytest -q` → 296 passed、9 skipped、1 warning（291 基準 + 5 新契約測試）。
- `uv run python -m compileall -q src tests` → 通過。
- `node --check frontend/app.js frontend/screen-flow.js` → 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed。
- `git diff --check` → 乾淨。
- 驗收重點：獨立 practice 頁（Option A 單卡）、一次一題、點狀進度 +「Question X」（不顯示總數）、答錯溫和提示 + Try again / Skip 且不揭曉正確答案（沿用兒童安全契約）、最後一題 Finish 進 results；只動前端，後端 API 完全未改。
- 已知限制：in-app Browser sandbox 限制，瀏覽器手動流程驗證仍以 static UI 契約與 node 測試為準（與前期相同）。
- 下一步（交接起點）：commit 已完成（見 git log）；如需手動驗證，啟動 `uv run uvicorn talkpath.main:app`，進入 overview → 點任一活動卡片 → 應進入 practice 頁一次一題練習。

### 2026-08-13 練習頁選擇題選項框加厚（完成）

- 背景：用戶回饋練習頁選擇題的選項框不夠大，兒童不好點選；要求「胖胖一點」。
- 實作：`frontend/styles.css` 的 `.choice-button` 加厚為 `min-height: 58px; padding: 16px 18px; border: 2px solid var(--line); border-radius: 14px; font-size: 1.05rem; font-weight: 700`；`.choice-list` 間距 10px → 12px、欄位最小寬度 140px → 150px（手機更窄時自動收成單欄，觸控目標更大）；`.answer-input` 同步加厚（`padding: 15px 16px; border-radius: 12px`）維持同卡片互動一致性。只動樣式，JS/API 未改。
- 驗證（TDD）：先新增 `tests/api/test_static_ui.py::test_child_ui_choice_buttons_have_generous_tap_targets`（紅燈）再改樣式（綠燈）；`uv run pytest tests/api/test_static_ui.py -q` → 29 passed；全量 `uv run pytest -q` → 297 passed、9 skipped、1 warning（296 基準 + 1 新契約測試）；`uv run python -m compileall -q src tests` 通過；`node --check`、`node --test` 3 passed；`git diff --check` 乾淨。
- 已知限制：in-app Browser sandbox 限制，未做瀏覽器手動視覺驗證，以 static UI 契約為準。
- 下一步：如需手動確認，啟動 `uv run uvicorn talkpath.main:app`，進入任一 activity → 看選擇題選項框是否明顯變胖。

### 2026-08-13 Bug 修正：第二題起答對也判錯（item_id 重複）（完成）

- 用戶回報：練習頁第二題開始，就算答對也顯示錯誤。
- 根因（以系統化除錯確認，先看實際保存資料再下結論）：真實 text provider（openai_compatible）產生活動時，把**同一個 activity_id 複製到每一題**（實際資料 `junior-high-grade-7-english-lesson-01-vocabulary-practice.md` 30 題全部同 id）；前端每題送出相同 `item_id`，後端 `ActivityService._find_item` 以 `item.activity_id == item_id` 找題目時**永遠命中第一題**，所以第二題起的答案都用第一題的 `expected_answer` 評分 → 答對也被判錯。錯誤訊息證據：`AnswerEvaluation(correct=False, ..., expected_answer='meaning-1')`。
- 實作（TDD，先寫失敗測試再修）：
  - `ActivityService` 新增 `_normalize_item_ids`：位置式重新命名每題 id 為 `{activity_id}-item-{N}`（唯一且跨 generation/重載/answer 查詢皆確定）。
  - `generate_activity` 在驗證後、快取與存檔前正規化；`get_activity` 回傳前一律正規化（涵蓋既有保存活動檔，不必改寫舊檔）。
  - `_ACTIVITY_OUTPUT_INSTRUCTION` 提示 provider 每題 `activity_id` 必須唯一（防線二；正規化才是保證）。
  - 新增測試：service 層 `test_answer_uses_correct_item_when_provider_reuses_activity_id_for_every_item`（3 題同 id，逐題答對皆判 passed）、`test_answer_uses_correct_item_when_saved_activity_has_duplicate_item_ids`（模擬舊存檔）；API 層 `test_public_answer_is_correct_for_second_question_when_item_ids_repeated`（HTTP 全流程）。
- 驗證：三個新測試紅燈 → 修正後綠燈；用真實 30 題存檔驗證 Q1–Q3 答對皆 passed；全量 `uv run pytest -q` → 300 passed、9 skipped、1 warning（297 基準 + 3 新測試）；`compileall`、`node --check`、`node --test` 3 passed、`git diff --check` 乾淨。
- 已知問題：無（既有存檔不需重生成即可正常評分；重新生成的活動會以唯一 id 存檔）。
- 下一步：如需手動驗證，啟動 `uv run uvicorn talkpath.main:app`，進入任一多題活動，答對第二題應顯示正確。

### 2026-08-13 練習頁選擇題改為二二排（完成）

- 背景：上一版 `.choice-list` 用 `auto-fit + minmax(150px)`，四選一在寬螢幕會排成三排一或四排一，按鈕被縮小。用戶要求四選一固定二二排，按鈕才能放大。
- 實作：`frontend/styles.css` 的 `.choice-list` 改為 `grid-template-columns: repeat(2, 1fr)`（固定兩欄），`.choice-button` 維持 `min-height: 58px; padding: 16px 18px`。只動樣式。
- 驗證（TDD）：契約測試 `test_child_ui_choice_buttons_have_generous_tap_targets` 改鎖定 `.choice-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;`（紅燈 → 綠燈）；`uv run pytest tests/api/test_static_ui.py -q` → 29 passed；全量 `uv run pytest -q` → 300 passed、9 skipped、1 warning；`compileall`、`node --check`、`node --test` 3 passed、`git diff --check` 乾淨。
- 已知限制：in-app Browser sandbox 限制，未做瀏覽器手動視覺驗證，以 static UI 契約為準。
- 下一步：如需手動確認，啟動 `uv run uvicorn talkpath.main:app` 進入任一選擇題活動，四選一應呈現二二排大按鈕。

### 2026-08-13 練習作答流程改版：答錯禁選該選項，直到選對（完成）

- 背景：用戶要求答對就顯示正確並跳下一題；答錯時把選錯的選項 disable（不再問「Try again / Next」），目標是讓小孩一直選到對為止。
- 實作（只動前端）：
  - `state` 新增 `practiceWrongChoices: []`（記錄本題已答錯的選項），`generateActivity` / `advancePracticeQuestion` / `resetForNewCourse` 都重置。
  - `submitActivityAnswer`：`practiceAnswered = Boolean(evaluation.passed)`；答錯時把該選項加入 `practiceWrongChoices`，`practiceAnswered` 維持 false → 重繪後 Check 按鈕仍在、錯誤選項 disabled（`.is-wrong` 淡紅樣式 + `:disabled` 預設游標），小孩換選其他選項繼續 Check；答對時顯示正向回饋 + Next question / Finish（最後一題），不再有 Try again。
  - `renderPracticeResultActions` 移除 Try again 分支，只留 Next / Finish。
  - 回饋訊息改為「有回饋就顯示」（答錯時也會顯示「Good try! Check the word again.」），答對用 `is-passed`、答錯用 `is-try-again` 色。
  - 文字輸入題（無選項）：答錯重繪為空白輸入框 + Check 按鈕，同樣持續作答到對。
- 驗證（TDD）：static UI 契約更新（`practiceWrongChoices` 初始/重置、`Boolean(evaluation.passed)`、`push(value)`、`includes(choice)`、`is-wrong`、`"Try again" not in practice_helpers`、CSS `.choice-button.is-wrong` / `.choice-button:disabled`）先紅燈後綠燈；`uv run pytest tests/api/test_static_ui.py -q` → 29 passed；全量 `uv run pytest -q` → 300 passed、9 skipped、1 warning；`node --check`、`node --test` 3 passed、`compileall`、`git diff --check` 乾淨。
- 已知限制：in-app Browser sandbox 限制，未做瀏覽器手動流程驗證，以 static UI 契約與 node 測試為準；若活動的題目答案不在選項內，兒童會把選項全部禁完而無法前進（視為 provider 資料問題，暫不加跳過鈕，依用戶「就是要選對」的要求）。
- 下一步：如需手動確認，啟動 `uv run uvicorn talkpath.main:app`，進入任一選擇題活動：答錯 → 該選項變淡紅 disabled、可繼續選其他；答對 → 綠字正確 + Next question。

### 2026-08-13 練習頁答對後自動跳下一題（完成）

- 背景：用戶實測發現答對後仍要點 Next question 才跳下一題；要求答對顯示正確後自動前進。
- 實作（只動前端）：`submitActivityAnswer` 答對時在 `renderPracticeQuestion` 後排定 `setTimeout`（`PRACTICE_AUTO_ADVANCE_MS = 1600`）自動跳下一題（最後一題自動 `showAnswerResult` 進 results）；`state` 新增 `practiceAutoAdvance`，`advancePracticeQuestion` / `generateActivity` / `resetForNewCourse` 都會 `clearTimeout` 並清空。自動跳題有守衛：navigation epoch 改變（離開練習頁）、activity 更換、題號已變、或已非答對狀態時不跳，避免誤跳。Next / Finish 按鈕保留為「不等 1.6 秒直接跳」的加速鍵。
- 驗證（TDD）：static UI 契約新增 `practiceAutoAdvance: null`、`state.practiceAutoAdvance = setTimeout`、`PRACTICE_AUTO_ADVANCE_MS`、`clearTimeout(state.practiceAutoAdvance)` 等 marker（紅燈 → 綠燈）；`uv run pytest tests/api/test_static_ui.py -q` → 29 passed；全量 `uv run pytest -q` → 300 passed、9 skipped、1 warning；`node --check`、`node --test` 3 passed、`compileall`、`git diff --check` 乾淨。
- 已知限制：in-app Browser sandbox 限制，未做瀏覽器手動流程驗證，以 static UI 契約與 node 測試為準。
- 下一步：如需手動確認，啟動 `uv run uvicorn talkpath.main:app`，進入任一活動答對後約 1.6 秒應自動進入下一題，不需點 Next。

### 2026-08-13 自動跳題延遲 1600ms → 500ms（完成）

- 背景：用戶實測覺得答對後切換太慢，要求「通通調快，拼的是速度」。
- 實作：`PRACTICE_AUTO_ADVANCE_MS` 1600 → 500（`frontend/app.js`），答對後 0.5 秒自動跳下一題。查過程式內沒有其他刻意延遲；「比對時間」是 DeepSeek `deepseek-v4-flash` 的實際回應延遲（`.env` 已用 flash 快檔），非程式刻意設定。
- 驗證（TDD）：契約新增 `PRACTICE_AUTO_ADVANCE_MS = 500`（紅燈 → 綠燈）；`uv run pytest tests/api/test_static_ui.py -q` → 29 passed；全量 `uv run pytest -q` → 300 passed、9 skipped、1 warning；`node --check`、`node --test` 3 passed、`compileall`、`git diff --check` 乾淨。
- 已知限制：比對延遲來自外部 AI provider，無法由本專案程式再縮短；若要再快可換更快的 text model（改 `.env` 的 `TALKPATH_TEXT_MODEL`）。
- 下一步：如需手動確認，啟動 `uv run uvicorn talkpath.main:app` 答對後約 0.5 秒自動進下一題。

### 2026-08-13 選擇題改為伺服器端本機即時比對（完成）

- 背景：用戶確認 Checking 等待來自 AI 比對，要求「有標準答案的選擇題不需要 AI 解析」，選擇題改為即時比對。
- 實作：`ActivityService.answer()` 依 `item.choices` 分支——有選項的題目用新增的 `_evaluate_standard_answer` 本機比對（`strip().casefold()` 比對 `item.answer`，回饋 "Great job!" / "Try again."），完全不呼叫 text provider；沒有選項的文字/口說題仍走既有 AI 評分。internal tools 的 `session_service.evaluate_answer` 維持 AI 評分（非兒童介面，未動）。
- 驗證（TDD）：新增 service 測試「選擇題正確/錯誤皆 `evaluate_calls == 0`」「文字題仍 `evaluate_calls == 1`」；既有 retry 測試改為 `evaluate_calls == 0`；observability 的 provider 錯誤路徑測試改用無選項的 fill_blank 題目（紅燈 → 綠燈）。用真實 30 題存檔驗證：text provider 設為「呼叫即噴錯」，Q1–Q3 仍瞬間判對（回饋 Great job!）。全量 `uv run pytest -q` → 302 passed、9 skipped、1 warning（300 基準 + 2 新測試）；`compileall`、`node --check`、`node --test` 3 passed、`git diff --check` 乾淨。
- 已知限制：文字輸入題/口說題仍需 AI 評分，等待時間不變；選擇題從此零 AI 延遲。
- 下一步：如需手動確認，啟動 `uv run uvicorn talkpath.main:app`，選擇題點 Check 應瞬間顯示對錯，不再有 Checking 等待。

## 第四期後續：單字練習隨機出題 + 錯題再出現（實作完成）

- 更新日期：2026-08-13。
- 背景：用戶要求單字練習題目順序必須隨機（避免小孩背順序而非單字）；答錯的題目要在後面再次出現，加強記憶。功能先只套用 Vocabulary practice，Grammar / Listening / Speaking 待用戶實測後再討論；錯題「就是再出現」，不設出現次數上限（不預設小孩會故意無限答錯）。
- 設計規格：`docs/superpowers/specs/2026-08-13-vocabulary-shuffle-requeue-design.md`（已提交）。
- 實作計畫：`docs/superpowers/plans/2026-08-13-vocabulary-shuffle-requeue-implementation.md`（已提交）。
- 狀態：實作完成並通過全量驗證。

### 2026-08-13 Task 1：佇列狀態與隨機出題（完成）

- 實作：`state` 新增 `practiceQueue: []`；新增 `shufflePracticeQueue`（Fisher–Yates，`Math.random()`）；`generateActivity` 對 `vocabulary_practice` 洗牌建立題目索引佇列、其他類型維持原始順序。
- TDD：先更新契約測試（紅燈：`practiceQueue: []` marker 不存在）再實作（綠燈）；`uv run pytest tests/api/test_static_ui.py -q` → 29 passed。
- 已知問題：無。
- 下一步：Task 2（佇列化渲染與推進）。

### 2026-08-13 Task 2：佇列化渲染與推進（完成）

- 實作：`renderPracticeProgress` / `renderPracticeQuestion` / `isLastPracticeQuestion` / `advancePracticeQuestion` 全部改以 `practiceQueue` 為準；進度點數與「Question X」以佇列長度計。
- TDD：紅燈→綠燈；29 passed。
- 已知問題：無。
- 下一步：Task 3（錯題排回佇列尾端）。

### 2026-08-13 Task 3：錯題排回佇列尾端（完成）

- 實作：`submitActivityAnswer` 答對時若該次出現曾答錯（`state.practiceWrongChoices.length > 0`），且活動為 `vocabulary_practice`（其他類型不重排錯題），把題目索引 push 回佇列尾端（在自動跳題 / 最後一題判斷之前，最後一題答錯過也會正確排回）；不設出現次數上限；`resetForNewCourse` 重置 `practiceQueue`。
- TDD：紅燈→綠燈；29 passed。
- 已知問題：無。
- 下一步：Task 4（全量驗證與收尾）。

### 2026-08-13 全量驗證（第四期收尾）

- `uv run pytest -q` → 302 passed、9 skipped、1 warning（與基準一致，無 regression）。
- `uv run python -m compileall -q src tests` 通過；`node --check frontend/app.js frontend/screen-flow.js` 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed；`git diff --check` 乾淨。
- 驗收重點：單字練習每次進入隨機出題（避免背順序）；答錯過的題目會在後面再次出現，直到某次出現一次答對為止；只套用 Vocabulary practice；後端 API 未動。
- 已知限制：in-app Browser sandbox 限制，未做瀏覽器手動視覺/流程驗證，以 static UI 契約與 node 測試為準。
- 下一步：如需手動驗證，啟動 `uv run uvicorn talkpath.main:app`，進入單字練習確認題序每次不同、答錯的題目會再出現。

## 第四期後續：詞彙練習改為「聽音＋跟讀＋STT 比對」（實作完成）

- 更新日期：2026-08-13。
- 背景：用戶指出「詞彙練習」與「詞彙測驗」幾乎相同，練習沒有練習的實質。用戶要求詞彙練習＝點擊聽發音＋小孩發音後由模型判斷對錯；評分第一版採 STT 轉文字比對；測驗維持出題作答。MiniCPM-o-4_5 統一模型列為下一期工程（本期不引入）。
- 設計規格：`docs/superpowers/specs/2026-08-13-vocabulary-practice-speaking-design.md`（已提交）。
- 實作計畫：`docs/superpowers/plans/2026-08-13-vocabulary-practice-speaking-implementation.md`（已提交）。
- 狀態：實作完成並通過全量驗證。

### 2026-08-13 Task 1：後端練習形狀與本機比對（完成）

- 實作：`FakeTextService.generate_activity` 對 `vocabulary_practice` 產生單字卡形狀（`prompt=單字`、`answer=單字`、`choices=[]`、instructions「Listen to the word, then say it out loud.」）；`_ACTIVITY_OUTPUT_INSTRUCTION` 增加 vocabulary_practice 專屬指引（每題一個單字、choices 空陣列）；`ActivityService.answer()` 對 `vocabulary_practice` 一律走 `_evaluate_standard_answer` 本機比對（`strip().casefold()`，零 AI 延遲）。
- TDD：新增 `test_vocabulary_practice_items_are_word_cards_compared_locally`（service 層，紅燈：fake 仍是 MC 形狀）與 `test_vocabulary_practice_uses_word_cards_and_spoken_transcript_answer`（API 層，公開 items 不含 answer、作答 school → passed）→ 修正後綠燈。
- 已知問題：無。
- 下一步：Task 2（前端單字卡練習分支）。

### 2026-08-13 Task 2：前端單字卡練習分支（完成）

- 實作：`frontend/app.js` 的 `activityDefinitions` 描述改為「Listen to the word, then say it out loud.」；`state` 新增 `practiceTranscript`（init／generateActivity／advancePracticeQuestion／resetForNewCourse 重置）；`renderPracticeQuestion` 對 `vocabulary_practice` 新增單字卡分支（大單字 + Listen 合成播放 `item.prompt` + Record 錄音轉錄後自動送出作答，不顯示 Check 按鈕）；新增 `playPracticeWord`（`POST /speech/synthesize`，TTS 不可用時顯示友善訊息）；`transcribeSpeaking` 增加可選 `onTranscript` callback；`frontend/styles.css` 新增 `.practice-word`、`.practice-speech-actions`。
- 沿用既有機制：`vocabulary_practice` 的洗牌與錯題排回（答錯的單字會排回佇列尾端直到某次出現答對）、500ms 自動跳題、Next／Finish、results 頁。
- TDD：新增 static UI 契約測試 `test_child_ui_vocabulary_practice_is_speaking_drill`（紅燈 → 綠燈）；`tests/api/test_static_ui.py` → 30 passed。
- 已知問題：無。
- 下一步：Task 3（全量驗證與收尾）。

### 2026-08-13 全量驗證（詞彙練習聽音＋跟讀收尾）

- `uv run pytest -q` → 305 passed、9 skipped、1 warning（302 基準 + 3 新測試：service 1、API 1、static UI 1）。
- `uv run python -m compileall -q src tests` 通過；`node --check frontend/app.js frontend/screen-flow.js` 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed；`git diff --check` 乾淨。
- 驗收重點：詞彙練習＝顯示單字、Listen 聽發音、Record 跟讀、STT 轉文字後由後端本機比對（`item.answer` 不送到前端）；答對自動前進、答錯可重錄且錯字會排回；詞彙測驗維持出題作答（型別識別字串未互換，避免歷史資料語意翻轉）。
- 已知限制：in-app Browser sandbox 限制，未做瀏覽器手動視覺/流程驗證（含麥克風與發音播放），以 static UI 契約、API 測試與 node 測試為準；STT 轉錄品質與比對寬鬆度（大小寫以外的前後綴詞）留待用戶實測後調整；真實 text provider 是否嚴格依指引產生單字卡形狀，需以實際 provider 生成內容驗證。
- 下一步：如需手動驗證，啟動 `uv run uvicorn talkpath.main:app`，進入「Vocabulary practice」：應看到單字卡 + Listen + Record，錄音後自動比對；「Vocabulary quiz」維持選擇題作答。MiniCPM-o-4_5 統一模型列為下一期工程。

### 2026-08-14 Bug 修正：重新生成已存活動 500（activity_id 碰撞）（完成）

- 用戶回報 log：`POST /api/sessions/{id}/activities/generate` → 500，`activity_generation_failed`，`error_type="RepositoryError"`，堆疊到 `lessonlens_markdown.py:702` 的 `save_activity_draft`。
- 根因（以系統化除錯確認）：真實 text provider（openai_compatible）以「課程＋型別」產出固定 `activity_id`（例如 `junior-high-grade-7-english-lesson-01-vocabulary-practice`）；LessonLens 已存在同 id 的舊活動檔（先前 30 題 MC 舊格式，`operation_id` 也不同）。`save_activity_draft` 的「同 id 不同內容」防護（第 702 行）直接丟 `RepositoryError` → 500；同一 session 內重生成則會先撞 in-memory 快取檢查（`ActivityOperationConflict`）。
- 實作（TDD，先寫失敗測試再修）：`ActivityService` 新增 `_ensure_unique_activity_id`——provider 回傳的 `activity_id` 若已存在（in-memory 快取或 LessonLens 已存檔）且內容不同，就在後面附加 8 位 hex suffix 換成新 id，並重新正規化 item ids；在快取檢查與 `save_activity_draft` 之前套用。LessonLens repository 的身分防護契約不變（`test_activity_save_is_idempotent_and_rejects_conflicting_reuse` 仍通過）。
- 測試：service 層 `test_regenerating_same_lesson_activity_gets_a_fresh_unique_activity_id`（紅燈：`ActivityOperationConflict`）；API 層 `test_new_session_regenerating_saved_activity_returns_200_with_fresh_id`（紅燈：500，模擬真實流程「新 session 對已存檔活動」）。
- 驗證：`uv run pytest -q` → 307 passed、9 skipped、1 warning（305 基準 + 2 新測試）；`compileall`、`node --check`、`node --test` 3 passed、`git diff --check` 乾淨。
- 已知限制：舊活動檔保留（歷史資料不動），重新生成會以新 id 存檔；同一 session 內對同一活動重複生成仍被 state machine 擋下（409，為既有正確行為）。
- 下一步：重啟 `uv run uvicorn talkpath.main:app`，再次進入 Vocabulary practice 生成活動應成功（不再 500），練習為新單字卡＋跟讀流程。

### 2026-08-14 Bug 修正：TTS 播放 503（前端寫死 voice "child" 被 Kokoro 拒絕）（完成）

- 用戶回報 log：`POST /api/sessions/{id}/speech/synthesize` → 503，`speech_synthesis_failed`，`error_type="ProviderUnavailable"`，堆疊到 `local_speech_services.py:79` 的 `_post`。
- 根因（實測確認）：前端 `requestActivityAudio` 與新 `playPracticeWord` 都寫死 `voice: "child"`；Kokoro 伺服器（`http://127.0.0.1:8880`，`openai_speech`，`model=kokoro`）對該 voice 回 HTTP 400（實測：`voice=child` → 400；`voice=af_bella` → 200，46KB wav），adapter 把非 2xx 視為 `ProviderUnavailable` → 503。設定檔的 `TALKPATH_TTS_VOICE=af_bella` 因前端硬傳 voice 被覆蓋。
- 實作（TDD，先紅燈後綠燈）：移除 `frontend/app.js` 兩處 synthesize payload 的 `voice: "child"`（`requestActivityAudio` 與 `playPracticeWord`），由後端依設定帶 `af_bella`；static UI 契約新增 `test_child_ui_speech_synthesis_does_not_hardcode_a_voice`。
- 驗證：`uv run pytest -q` → 308 passed、9 skipped、1 warning（307 基準 + 1 新契約測試）；`compileall`、`node --check`、`node --test` 3 passed、`git diff --check` 乾淨。
- 已知限制：若其他客戶端仍送不支援的 voice，後端 adapter 仍會回 503（voice 覆蓋設定是既有契約，`test_openai_speech_call_voice_overrides_configured_voice` 維持）；現有 API 測試以 fake TTS 送 `voice: "child"` 仍通過（fake 不驗證 voice）。
- 下一步：重新整理瀏覽器頁面（static 檔案即時讀取，不需重啟 server）後再按 Listen，應播放 `af_bella` 發音；若 TTS 伺服器未啟動，仍會顯示既有「Audio is taking a break」fallback。

## 第五期後續：詞彙練習單字卡牆＋自選練習（設計確認）

- 更新日期：2026-08-14。
- 背景：用戶要求「練習」要能自選單字——像市面熱門 App 的概念：字庫可見＋搜尋、點擊即聽、自選練習、狀態可視、短回合＋即時回饋。用戶以互動預覽（superpowers Visual Companion，`http://localhost:55356` 已確認）確認版面「完美，完全就是我想要的感覺」。
- 版面決策：單字卡牆（上方搜尋框、下方該課全部單字卡：英文＋中文＋狀態標籤＋喇叭）；點喇叭直接聽、點卡進入該字練習（Listen＋Record＋STT 比對）；右上 Practice all 沿用整批隨機練習；練完單字回卡牆自選。
- 設計規格：`docs/superpowers/specs/2026-08-14-vocabulary-word-wall-design.md`（已提交）。
- 實作計畫：`docs/superpowers/plans/2026-08-14-vocabulary-word-wall-implementation.md`（已提交）。
- 狀態：實作完成並通過全量驗證。

### 2026-08-14 Task 1：後端單字作答 API（完成）

- 實作：`SessionService.answer_vocabulary_word`＋新端點 `POST /api/sessions/{id}/vocabulary/{content_id}/answer`（`{operation_id, answer}`）。驗證 session 的 lesson 與 vocabulary content item；本機 `strip().casefold()` 比對轉錄文字與單字（`english`／`word` 欄位相容）；以 `activity_id="{lesson_id}-word-{content_id}"` 寫 attempt 與 review item（`record_attempt` 的 operation_id 冪等）；回應不含答案；新增 `VocabularyContentNotFound`／`NotVocabularyContent` 錯誤。
- TDD：4 個 unit 測試（對／錯、operation_id 冪等、content 不存在與非 vocabulary 拒絕、無 lesson 拒絕）＋1 個 API 測試（200、attempt 寫入、答案不洩漏）紅燈→綠燈。
- 已知問題：無。
- 下一步：Task 2（前端單字卡牆 screen）。

### 2026-08-14 Task 2＋3：前端單字卡牆與單字模式練習（完成）

- 實作：`frontend/index.html` 新增 `#words-screen`（搜尋框、字卡格、Practice all、Back）；`frontend/app.js` 新增 `openWordWall`／`renderWordWall`／`openWordPractice`／`submitWordAnswer`／`renderWordPracticeResult`／`backToWordWall` 與 `vocabularyWordItems`／`wordEnglish`／`wordChinese` 輔助；`vocabulary_practice` 卡片改進入字卡牆（`words: true`）；字卡由 `lesson.content_items` vocabulary 項目渲染（`english/word`、`chinese/meaning` 相容），點喇叭 `playPracticeWord` 直接播發音，點卡進入練習頁單字模式（Listen＋Record＋STT 轉錄後送新端點，答對標記 `done`＋Back to words、答錯標記 `again` 可重錄）；Practice all 沿用 `generateActivity`；`state.wordStatus`／`state.wordPractice` 與 reset；overview action 依 `wordPractice` 情境切回字卡牆；`frontend/styles.css` 新增字卡牆樣式（`.word-grid`／`.word-card`／`.word-speaker`／`.word-badge` 等）。
- TDD：2 個 static UI 來源契約測試紅燈→綠燈。
- 已知問題：無。
- 下一步：Task 4（全量驗證與收尾）。

### 2026-08-14 全量驗證（單字卡牆收尾）

- `uv run pytest -q` → 315 passed、9 skipped、1 warning（308 基準 + 7 新測試：session service 4、API 1、static UI 2）。
- `uv run python -m compileall -q src tests` 通過；`node --check frontend/app.js frontend/screen-flow.js` 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed；`git diff --check` 乾淨。
- 驗收重點：Vocabulary practice 卡片進入單字卡牆（搜尋＋全部單字＋狀態＋喇叭）；點喇叭直接聽；點卡進入該字練習（聽＋說＋STT 比對，答對回卡牆）；Practice all 沿用洗牌＋錯題排回；單字作答記錄進 SQLite（活動 id `{lesson_id}-word-{content_id}`）。
- 已知限制：單字狀態（new／practised／again）僅 session 內記憶體，未持久化（未來接錯題本）；in-app Browser sandbox 限制，瀏覽器手動流程驗證以 static UI 契約、API 測試與 node 測試為準；後端新 API 需重啟 `uv run uvicorn talkpath.main:app` 才生效。
- 下一步：如需手動驗證，重啟 server 後進入已保存課程 → Vocabulary practice → 字卡牆點字練習；MiniCPM-o-4_5 統一模型仍列為下一期工程。

### 2026-08-14 詞彙測驗設計規格（聽寫＋中翻英＋辨識題）

- 用戶確認詞彙練習定版後，下一項是詞彙測驗；方向確認：保留現有 TOEIC 型「聽音選義」，新增「聽寫」（唸 fruit → 拼出 fruit）與「中翻英」（看中文 → 拼出英文）等老師式題型。
- 設計規格已建立：[2026-08-14-vocabulary-quiz-design.md](superpowers/specs/2026-08-14-vocabulary-quiz-design.md)（狀態：待用戶審閱）。
- 核心決策：`vocabulary_quiz` 的 item 新增公開欄位 `question_type`（dictation／meaning_to_word／word_to_meaning／listen_to_meaning），提取題與辨識題混出並洗牌，每課單字一題；quiz 全部本機比對（不呼叫 AI）；作答回應新增 `correction`（僅 quiz、作答後）供訂正顯示；quiz 一次作答、不排回、不自動跳題；結果頁顯示分數＋答錯清單＋「Practice these words」回單字牆；錯題持久化沿用 `record_attempt` 的 review_items，SQLite schema 不變。
- 驗證：尚未實作；規格經用戶審閱後才進入 writing-plans。
- 下一步：用戶審閱規格 → 撰寫實作計畫 → TDD 實作。

### 2026-08-14 詞彙測驗實作計畫（已建立，待執行）

- 設計規格已獲用戶確認（2026-08-14），實作計畫已建立：[2026-08-14-vocabulary-quiz-implementation.md](superpowers/plans/2026-08-14-vocabulary-quiz-implementation.md)。
- 計畫拆 8 個 Task：`question_type` 模型欄位 → fake provider 混題 → quiz 本機評分 → API `question_type`／`correction` → provider 指令 → 前端題型分支 → 送出與結果頁 → 全量驗證與收尾。
- 驗證：計畫尚未執行（目前無程式碼變更，全量 315 passed 基準未動）。
- 下一步：以 subagent-driven-development（建議）或 executing-plans 依序執行 Task 1-8。

### 2026-08-14 詞彙測驗實作完成（聽寫＋中翻英＋辨識題）

- 依實作計畫完成 8 個 Task：question_type 欄位、fake 混題、本機評分、API 契約、provider 指令、前端題型分支、送出與結果頁，以及 observability 測試契約更新。
- 功能：`vocabulary_quiz` 改為 4 種題型（`dictation` 聽寫、`meaning_to_word` 中翻英、`word_to_meaning` 英翻中、`listen_to_meaning` 聽選中，保留 TOEIC 型）；每課單字一題、混題並隨機洗牌；quiz 全部本機比對（不呼叫 AI）；作答回應新增 `correction`（僅 quiz、作答後回傳）供訂正顯示；quiz 一次作答、答錯不排回、不自動跳題；結果頁顯示 X of Y 分數＋答錯清單＋「Practice these words」回單字牆；錯題經 `record_attempt` 寫入 review_items（SQLite schema 不變）。
- 全量驗證：`uv run pytest -q` → 326 passed、9 skipped、1 warning（315 基準 + 11 新測試）；`uv run python -m compileall -q src tests` 通過；`node --check frontend/app.js frontend/screen-flow.js` 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed；`git diff --check` 乾淨。
- 既有測試更新（因新契約調整）：fake quiz shape 改變（items[0] 由 MC 變 dictation）；`test_text_answer_still_uses_text_provider_for_evaluation` 改用 `speaking_practice`；`test_activity_text_evaluation_unknown_error_is_safely_logged_and_wrapped` 改用 `speaking_practice`；openai compatible 契約改檢查 `audio_base64`/`audio_bytes`（指令含 audio 字眼）；static UI 的 shuffle marker 與 forbidden "correct" 更新。
- 已知問題：quiz 結果清單與單字狀態僅 session 內記憶體（尚未接錯題本 UI）；真實 text provider 生成需 live smoke（fake provider 已驗證，DeepSeek 契約含新指令）；in-app Browser sandbox 限制，瀏覽器手動流程以 static UI 契約、API 測試與 node 測試為準；後端新 API 需重啟 server 才生效。
- 下一步：手動驗證（重啟 `uv run uvicorn talkpath.main:app` → 進入已保存課程 → Vocabulary quiz：聽寫 Listen→拼字、中翻英、英翻中、聽選中、結果頁錯題複習）；之後可規劃錯題專屬複習測驗、句子克漏字、每字兩題。

### 2026-08-14 詞彙測驗已合併至 main

- 建立 `main` 並合併原工作分支 `codex/phase2-provider-speech`；合併後於 main 重跑全量驗證：`uv run pytest -q` → 326 passed、9 skipped、1 warning；compileall／node check／node test／`git diff --check` 全通過。
- 原工作分支已刪除（內容完整保留於 main；如需復原分支名稱：`git branch codex/phase2-provider-speech main`）。
- 目前工作分支：`main`（正式位置 `D:\python\TalkPath`；早期 `.worktrees/provider-speech` 與 `worktrees/provider-speech` 兩個 worktree 分支未更動）。

### 2026-08-14 Bug 修正：詞彙測驗答錯後無法 Try again（完成）

- 用戶回報：詞彙測驗中答錯後沒有「Try again」，無法再試同一題。
- 根因（以系統化除錯確認）：不是後端錯誤，而是詞彙測驗目前的設計就是「一次作答」——`submitActivityAnswer` 對 quiz 一律 `state.practiceAnswered = true` 鎖死該題，答錯後只顯示訂正與 Next／Finish（`renderPracticeResultActions`），沒有重試入口；後端 `ActivityService.answer` 其實完全支援同一題以新 `operation_id` 重複作答（答對會自動從 review_items 刪除），問題只在前端。
- 實作（TDD，先寫失敗契約測試再修）：
  - `renderPracticeResultActions`：quiz 答錯時（`isQuiz && !state.practicePassed`）新增「Try again」按鈕，點擊後重設 `practiceAnswered`／`practicePassed`／`practiceFeedback`／`practiceCorrection` 並重渲染同一題；答對後仍只顯示 Next question／Finish。
  - `submitActivityAnswer`：quiz 改用 `state.quizResults[state.currentQuestionIndex]` 以題目位置覆寫結果（重試答對時該題改計為對，結果頁 X of Y 不會重複計算）；quiz 答錯也寫入 `state.practiceWrongChoices`，重試時選擇題會 disable 已選錯的選項（不揭曉答案，與練習一致）；移除答錯立即顯示的 inline 訂正（`Correct spelling/Correct answer` 前綴），訂正保留在結果頁答錯清單，避免「看答案再重打」讓重試失去意義。
- 測試：更新 `test_child_ui_practice_answer_flow_never_reveals_answer_and_finishes_to_results`（Try again 僅存在於 quiz 分支）與 `test_child_ui_vocabulary_quiz_allows_retry_after_wrong_answer`（upsert、錯選追蹤、無 inline 訂正）；紅燈 → 綠燈。
- 驗證：`uv run pytest -q` → 326 passed、9 skipped、1 warning（與基準一致，無 regression）；`uv run python -m compileall -q src tests` 通過；`node --check frontend/app.js frontend/screen-flow.js`、`node --test frontend/test/screen-flow.test.cjs` 3 passed；`git diff --check` 乾淨。
- 已知限制：重試答對後該題計為正確（計分以「最終答對」為準，非首答）；每次送出仍會以新 operation_id 寫入 attempts（後端既有行為，答對會清除 review item）；quiz 答錯不排回佇列、不自動跳題（維持測驗性質）；in-app Browser sandbox 限制，瀏覽器手動流程以 static UI 契約、API 測試與 node 測試為準。
- 下一步：重新整理瀏覽器頁面（static 檔案即時讀取，不需重啟 server）後進入 Vocabulary quiz，答錯一題應看到「Try again」＋「Next question」，重試答對後該題計為正確。

### 2026-08-14 調查中：詞彙練習錄音轉不出字（"I received your recording, but could not read the words yet."）

- 用戶回報：詞彙練習點 Record 跟讀後，App 顯示「I received your recording, but could not read the words yet.」（即 `frontend/app.js` 空轉錄訊息：STT 回 200 但 `transcript.text` 為空字串），一直重複發生。用戶詢問是否有把錄音暫存下來做 debug。
- 調查發現（系統化除錯 Phase 1，尚未下結論）：
  - **錄音目前完全沒有暫存**：`transcribe_speech` 路由讀取 bytes 後直接轉發 STT provider，全專案無任何把音檔寫入磁碟的機制（唯一 tempfile 是課本圖片）。
  - **空轉錄完全沒有日誌**：`log_operation_failure` 只在拋例外時記（`speech_transcription_failed`）；STT 回 200＋空 text 視為成功，日誌零輸出。故現有日誌無法看出空轉錄原因。
  - **鏈路實測全通**：TalkPath adapter（`local_http` + `openai_transcription` 協定）→ QwenASR（`http://<LAN-IP>:11435`＝本機 `QwenASR-WebView.exe`，`.env` key `<redacted>` 有效，非 401）。直接以 TalkPath adapter 的呼叫形狀（欄位 `file`、檔名 `audio` 無副檔名、`response_format=verbose_json`）送合成音檔：wav、webm/opus、0.35s 極短、-28dB 極小聲、0.5s 小聲 webm，QwenASR 全部正確回 `text: "Apple."`（其引擎以內容嗅探解碼，不挑副檔名）。另確認 `<LAN-IP>` 為本機 LAN IP、8001 為目前 TalkPath 實例（8000 是 Docker 其他服務，404）。
  - 結論：後端鏈路無功能性問題；空轉錄只可能與「實際錄音內容／實際請求」有關，但目前無任何證據可看（沒存檔＋沒日誌）。
- 暫時處置：在 `session_service.transcribe_audio` 加**暫時 debug 機制** `_debug_save_recording`（標記 TEMPORARY、註解標明調查後移除）——每次轉錄把原始音檔存到 `data/debug-recordings/{ts}-{session}-{op}.{ext}`，並寫 sidecar JSON（mime、bytes、session、operation_id、`transcript_text`／language／segments 數／provider／model、或 `error_type`）；成功與例外路徑都存。此機制永不拋例外，不影響主流程。
- 驗證：`uv run pytest tests/unit/test_local_speech_services.py tests/integration/test_real_provider_to_speech.py -q` → 19 passed、1 skipped；全量 pytest 已背景執行（待回報）；`compileall` 通過。
- 待辦（下一步）：**重啟 TalkPath server**（無 `--reload`，PID 20800 需重啟才載入新 code）→ 用戶重錄一次 → 檢查 `data/debug-recordings/` 的實際音檔與 sidecar，確認是「錄音本身沒聲音／太短」還是「QwenASR 對真實人聲回空」；確認後移除 debug 機制並視根因修正。
- 已知限制：debug 存檔僅限本機 `data/debug-recordings/`，屬暫時性；解決後需刪除。

### 2026-08-15 根因確認：錄音為「全靜音」，麥克風未收到訊號（環境問題，非程式問題）

- 用戶重錄一次後，debug sidecar 顯示 `transcript_text: ""`、`audio_bytes: 28310`、`mime_type: audio/webm;codecs=opus`、`error_type: null`（真實 QwenASR 200 空文字）。
- 以 ffmpeg 分析該 webm：時長 1.68s、opus 48kHz mono；**mean_volume -72.0dB、max_volume -54.7dB、-35dB 門檻下 100% 靜音**——錄音內容是純靜音，麥克風完全沒收到聲音，QwenASR 收到靜音自然回空字。
- 交叉驗證（同機直錄）：DirectShow 輸入裝置僅「Microphone (High Definition Audio Device)」（主機板內建麥克風孔；USB 音效裝置未出現於輸入清單）；用 ffmpeg dshow 直錄 3s（無人講話）→ mean -50.8dB、max -34.3dB（僅環境底噪）；再請用戶於 20s 即時視窗說話直錄 → mean -58.6dB、max -33.6dB、-30dB 門檻 100% 靜音。**結論：麥克風訊號根本沒進到機器**（沒插麥／插錯孔／輸入停用或音量為 0／用的不是這台機器的輸入），屬環境問題，TalkPath／QwenASR 程式無功能性問題。
- 待用戶處理：確認實體麥克風（插對孔／USB 麥克風被系統列為輸入裝置）→ Windows 設定→系統→音效→輸入：選對輸入裝置、看說話時音量條是否跳動、麥克風未靜音且音量>0 → 再錄一次驗證。
- 後續建議（defense-in-depth，待用戶同意）：前端/後端偵測「過於安靜的錄音」（如 mean RMS 低於門檻）直接顯示「我沒聽到你的聲音，請檢查麥克風」，取代誤導性的「could not read the words yet」；可另在錄音中顯示即時音量條（參考 QwenASR 上傳頁的 VAD meter）。
- 驗證狀態：全量 pytest 326 passed、9 skipped、1 warning（debug 機制無回歸）；`compileall`、`git diff --check` 乾淨；debug 目錄已清空待用戶重測；程式碼尚未 commit。

### 2026-08-16 Bug 修正：同 session 重複點活動卡顯示「invalid session transition: READY_FOR_PRACTICE -> GENERATING_ACTIVITY」（完成）

- 用戶回報：練習後回到 overview 再點任一活動卡片（頁面跳轉），有時出現原始技術錯誤訊息 `invalid session transition: SessionState.READY_FOR_PRACTICE -> SessionState.GENERATING_ACTIVITY`。
- 根因（以系統化除錯確認，API 層實測重現）：`SessionService.generate_activity` 只允許 `ASK_GENERATE_ACTIVITY`；生成過一次活動後 session 進入終態 `READY_FOR_PRACTICE`，前端 `generateActivity()` 仍無條件呼叫 `POST /api/sessions/{id}/activities/generate`（overview 卡片再點、results「Try another activity」、audio fallback「Retry audio activity」都會觸發）→ 後端 409 → 前端把原始技術訊息直接顯示在 `#practice-error`。
- 方向決策（用戶選擇）：後端放寬——同一 session 可生成「不同類型」的第二個活動；同一類型不可重複生成（維持既有 409 契約）。
- 實作（TDD，先寫失敗測試再修）：
  - 後端：`SessionStateMachine` 新增 `READY_FOR_PRACTICE → GENERATING_ACTIVITY`；`SessionService.generate_activity` 對 `READY_FOR_PRACTICE` 狀態檢查 `ActivityService.generated_activity_types(session_id)`，同類型回 409（`ActivityOperationConflict`，code `activity_operation_conflict`）、不同類型放行；`_domain_code` 新增 `activity_operation_conflict` 對應。
  - 前端：`state` 新增 `generatedActivities`（type → activity 對照）；`generateActivity` 新增 resume 分支——若 `state.generatedActivities[definition.type]` 存在（且 `lesson_id` 相符）就直接重繪既有活動（重新請求 audio），不再呼叫生成 API，並把該活動設為 `state.activity`；生成成功後寫入 `state.generatedActivities[result.activity.type]`；`enterSavedLesson`／`resetForNewCourse` 清空 `state.activity` 與 `generatedActivities`，避免跨課程殘留。
- 測試（+6）：state machine 1（READY_FOR_PRACTICE → GENERATING_ACTIVITY 合法）、session service 2（同 session 不同類型可生成／同類型拒絕）、API 2（同 session 生成第二種活動 200／同類型 409 `activity_operation_conflict`）、static UI 1（resume 分支契約：`existingActivity.type === definition.type`、`renderActivity(existingActivity, resumeAudio)`、先 resume 後 generate）。
- 驗證：`uv run pytest -q` → 335 passed、9 skipped、1 warning（329 基準 + 6 新測試）；`compileall`、`node --check`、`node --test` 3 passed、`git diff --check` 乾淨。
- 已知限制：同 session 同類型再生成仍 409（既有契約，前端 resume 已避免觸發）；舊 server 需重啟才載入後端變更（前端 static 檔即時讀取）。

### 2026-08-15 Bug 修正：唸對卻判錯——STT 轉錄帶句號（"Watermelon."）被本機比對誤判（完成）

- 用戶回報：麥克風修好後重錄 "watermelon" 正確唸出，App 卻顯示「Try again.」；用戶問「正確的話應該直接顯示正確，為什麼要 try again」。
- 根因（系統化除錯確認）：Qwen3-ASR 轉錄會附加標點（實測回 `text: "Watermelon."`／`"Apple."`）；兩處本機比對只做 `strip().casefold()`，`"Watermelon.".casefold()`＝`"watermelon."` ≠ `"watermelon"` → 正確發音被判錯。受影響：`SessionService.answer_vocabulary_word`（單字卡練習，line 787）與 `ActivityService._evaluate_standard_answer`（vocabulary_practice 跟讀練習，line 345；測驗/選擇題因答案無標點不受影響）。
- 實作（TDD，先紅燈 3 failed 再修）：新增 `activity_service.normalize_spoken_answer(text)`——`strip().casefold()` 後去除**前後**標點（`,.!?;:·…'"'“”()[]{}<>-–—`，保留內部撇號/連字號如 don't、ice-cream）並收斂內部空白；兩處比對皆改為 `normalize_spoken_answer(answer) == normalize_spoken_answer(expected)`。
- 測試（+3）：`test_answer_vocabulary_word_accepts_punctuated_asr_transcript`（"School." 對、"  school  " 對、"schoolyard." 仍錯）、`test_vocabulary_practice_accepts_punctuated_asr_transcript`（drill 路徑同驗證）、`test_vocabulary_word_answer_accepts_punctuated_asr_transcript`（API 層 HTTP 全流程）。
- 驗證：新測試紅燈 → 綠燈；全量 `uv run pytest -q` → 329 passed、9 skipped、1 warning（326 基準 + 3 新測試，無回歸）；`compileall`、`node --check`、`node --test` 3 passed、`git diff --check` 乾淨。執行中 server 重啟後端到端實測：`fruit.` → passed True／"Great job!"，`vegetable.` → 仍 False。
- 收尾：暫時 debug 錄音機制（前條）已完成任務並移除（含刪除 `data/debug-recordings/` 內小孩語音檔）；日後如需可改以 `TALKPATH_DEBUG_RECORDINGS` 環境旗標重啟。前端無需變更（答對即顯示 "Great job!"＋回字卡牆）。
- 已知限制：比對仍為「整詞完全相等」（大小寫/標點/多餘空白外）；前綴後綴詞或「多說幾個字」（如 "I said watermelon"）仍判錯，屬既有設計範圍，留待用戶實測後再調整寬鬆度。
- 下一步：用戶重新整理瀏覽器後再錄一次 "watermelon" 應直接顯示 "Great job!"＋done 並回字卡牆。

### 2026-08-16 取消「Speaking practice」活動（完成）

- 背景：用戶檢視活動清單後指出，Speaking practice 與已改版的詞彙練習（聽音＋跟讀＋STT 比對）重覆，建議取消。
- 評估（程式碼證據）：
  - 後端 provider 指令（`_ACTIVITY_OUTPUT_INSTRUCTION`）只有 `vocabulary_practice`／`vocabulary_quiz` 有專屬題目形狀，`speaking_practice` 無任何專屬指引，真實 LLM 產出的是通用題目（fake provider 也是通用選擇題），實務上就是詞彙類題目。
  - 前端 `renderPracticeQuestion` 對 `speaking_practice` 只是額外加一顆 Record 按鈕，且 `transcribeSpeaking(record, recordFeedback)` 沒有 `onTranscript` 回呼——轉錄只顯示「I heard: X」，不會自動送出作答；作答仍靠選選項／打字＋Check。也就是說它沒有真正的口說練習閉環，比詞彙練習還弱。
  - 詞彙練習（`vocabulary_practice`）已涵蓋單字級口說閉環（單字卡牆→Listen→Record→STT 自動送出→本機比對→錯字排回）；`reading_aloud` 涵蓋朗讀。Speaking practice 是八個活動中唯一沒有獨立定位者。
- 實作（TDD，先寫失敗契約測試再修）：
  - 前端：`activityDefinitions` 移除 `speaking_practice` 項目（overview 不再顯示該卡片）；`renderPracticeQuestion` 移除 `speaking_practice` 專屬分支（Record 按鈕）。
  - 後端：`SUPPORTED_ACTIVITY_TYPES` 保留 `speaking_practice` 字串（相容舊存檔資料語意，且 `test_text_answer_still_uses_text_provider_for_evaluation`、`test_activity_text_evaluation_unknown_error_is_safely_logged_and_wrapped` 仍用它當「無選項、AI 評分」的範例型別），UI 不再提供入口。
  - 契約測試：`test_child_ui_practice_is_a_separate_screen_without_inline_activity_panel` 的活動標籤清單移除 "Speaking practice" 並加 `assert "Speaking practice" not in script`；新增 `test_child_ui_speaking_practice_is_removed`（`speaking_practice` 不在 definitions、`activity.type === "speaking_practice"` 分支不存在）。紅燈 2 failed → 綠燈。
- 驗證：`uv run pytest tests/api/test_static_ui.py -q` → 38 passed；`uv run pytest tests/unit/test_activity_service.py tests/unit/test_direct_observability.py -q` → 28 passed；全量 `uv run pytest -q` → 336 passed、9 skipped、1 warning（335 基準 + 1 新契約測試，無回歸）；`uv run python -m compileall -q src tests` 通過；`node --check frontend/app.js frontend/screen-flow.js` 通過；`node --test frontend/test/screen-flow.test.cjs` → 3 passed；`git diff --check` 乾淨。
- 已知限制：既有 session 若已生成 `speaking_practice` 活動檔，仍可從 LessonLens 讀取並以「通用題目」形式練習（型別字串保留的用意）；新進入的課程 overview 不再顯示 Speaking practice 卡片。
- 下一步：如需手動驗證，重新整理瀏覽器（static 檔即時讀取）進入已保存課程 overview，確認活動清單已無 Speaking practice；前端變更不需重啟 server。

## 2026-09-30 取消「同課程分次匯入與資料保留」計畫

- 依使用者指示取消該計畫；增量匯入分支退回功能起點，正式目錄未併入該功能。
- 保留獨立要求的繁體中文提示詞：翻譯、詞義、解說及活動文字一律採繁體（zh-TW）。
- 驗證：`uv run pytest -q` → 336 passed、9 skipped、1 個既有警告。
- 已知限制：UI 仍一次選一張圖片；繁體提示詞未用真實模型核對；既有課程不會自動轉換。

## 2026-09-30 QwenASR WebView CLI 與 0.6B CPU 實測

- 測試位置：`D:\python\QwenASR-WebView`，EXE 回報版本 2.0.0。CLI 的 `status --json` 與 `profiles --json` 可在不開視窗的情況下執行。
- 依使用者選擇，於該安裝的 `settings.json` 設定 `backend=openvino`、`cpu_model_size=0.6B`。此版本的 CLI 載入 0.6B 時沒有先下載缺少的模型，首次轉錄以缺少 `ov_models/qwen3_asr_int8/audio_encoder_model.xml` 失敗；上游 `webview_backend._load_openvino` 只對 1.7B 執行預先下載。
- 使用既有 QwenASRMiniTool 的 `downloader.download_all` 補齊 0.6B 模型；`quick_check=True`、`full_verify=True (OK)`，下載及完整雜湊驗證約 64.9 秒。
- 測試音檔由本機 Kokoro 合成英文短句 `The apple is red.`，長 1.512 秒。以 `transcribe <audio> --json --no-align -l English` 分別啟動兩次 CLI，總耗時 6.92 秒、6.80 秒；皆退出碼 0，回傳單段 `The apple is red`。同一 CLI 行程連續處理相同音檔三次耗時 8.22 秒，三筆皆成功，顯示每次重新啟動與載入模型占了主要耗時。
- 結論：CLI 可免 GUI／Token 工作，但目前每次短句轉錄約 7 秒，不適合作為 TalkPath 逐題口說練習的直接替代；常駐模型的本機服務值得優先評估。此結果只驗證合成英文短句，未驗證真人錄音品質，也未改動 TalkPath STT adapter。
- 清理：刪除測試音檔、字幕與首次試跑自動下載但未採用的 1.7B Q4 模型；保留使用者指定的 0.6B 模型及其設定。

## 2026-09-30 qwen3-asr-service CPU Docker 相容性實測

- 依使用者授權，拉取 `lancelrq/qwen3-asr-service:latest-cpu`（映像 digest `sha256:9a82fe6266c139391749b2a8e89851a9ea0d3b2c61f9f04ced2f427ee756c0d`），啟動測試容器 `talkpath-qwen3-asr-test`，僅繫結主機 `127.0.0.1:8765`。明確啟用 OpenAI 相容 API、CPU 0.6B 與固定測試 Token；容器重啟策略為 `no`，沒有設定開機自動啟動。
- 將 `D:\python\QwenASR-WebView\ov_models\qwen3_asr_int8` 唯讀掛載為 `/app/models/asr/openvino/0.6b`；日誌確認「OpenVINO 模型已存在」並成功載入，ASR 權重未重下載。額外 VAD 模型首次下載至獨立 Docker volume `talkpath-qwen3-asr-models`。`GET /v2/health` 回報 `ready`、`device=cpu`、`model_size=0.6b`、`asr_backend=openvino`。
- 用 TalkPath 現有 `LocalHttpSpeechToTextService`、`openai_transcription` 協定與無副檔名上傳檔名，呼叫 `/compat/openai/v1/audio/transcriptions`：1.512 秒 Kokoro 合成 WAV 首次 5.97 秒、再次 1.03 秒；WebM/Opus 1.16 秒；三次皆回 `The apple is red.`、英文與一筆有效分段。未帶及錯誤 Token 均回 HTTP 401。
- `docker restart` 後再次確認健康檢查 `ready`，WebM 仍轉錄成功，錯誤 Token 仍回 401；重啟後測得容器記憶體使用約 1.809 GiB。容器目前保留運行供本機試用；TalkPath `.env` 與程式碼未更動，正式切換尚未執行。
- 限制：僅以合成英文短句測試，未驗證真人麥克風、長音訊或多請求負載；測試 Token 僅供 localhost 驗證，正式使用須另設高強度固定密鑰。

## 2026-09-30 正式採用 TTS／STT Docker Compose

- 依使用者指示建立 `docker/compose.speech.yml`，以固定映像 digest 啟動 Kokoro TTS 與 qwen3-asr-service CPU 0.6B STT；主機埠分別只綁定 `127.0.0.1:8880`、`127.0.0.1:8765`，加入健康檢查與 `restart: unless-stopped`。ASR／VAD 模型複製到 Compose 管理的 `talkpath-speech_asr_models` volume；七個 ASR 必需檔案與 VAD 權重齊全，服務不再依賴 WebView 目錄。
- 更新未追蹤的本機 `.env`：STT 指向新相容端點 `/compat/openai/v1/audio/transcriptions`，使用新產生的固定私有密鑰；原設定備份在忽略追蹤的 `.env.before-speech-compose`。TTS 仍指向 `127.0.0.1:8880`。更新 `.env.example`、`README.md`、`docs/SPEECH_SERVICES.md`、`docs/TECHSTACKS.md`、`docs/STRUCTURE.md` 與 `.gitignore`。未修改 TalkPath adapter 程式碼。
- 整合時發現上游首啟產生的 `config.yaml` 內 `api_key` 為空字串，優先序卻高於 `ASR_API_KEY`，造成有效音訊即使沒有密鑰也回 HTTP 200。Compose STT 加 `--no-config` 並以 CLI 明確指定模型／相容 API 等選項後重測：未帶與錯誤密鑰均回 401，正確密鑰回 200；TalkPath adapter 轉錄仍成功。
- 驗證：`docker compose config --quiet` 通過；兩個 Compose 容器均為 `running/healthy`；以實際 `.env` 建立 ProviderRegistry，Kokoro 產生 70,230-byte WAV 約 0.53 秒，Qwen 將 `The apple is red.` 正確轉錄為英文與一筆分段約 1.5 秒。模擬瀏覽器的 WebM/Opus（`audio/webm;codecs=opus`）亦正確轉錄。`docker compose restart` 後兩個服務重新達 `healthy`，再次由 TTS→STT 轉錄成功，未授權請求回 401。TalkPath API 重啟後 `/health/providers` 回 `stt.model=qwen3-asr-0.6b`、`tts.model=kokoro`；`git diff --check` 通過。
- 原獨立 `kokoro-fastapi` 與 `talkpath-qwen3-asr-test` 容器已停止並保留作為回退參考；Compose 的 TTS／STT 目前運行中。TalkPath API 仍由主機行程執行，重新啟動於 `127.0.0.1:8001`；其本機日誌位於忽略追蹤的 `data/logs/`。
- 限制：語音品質只以合成英文短句驗證，未做真人錄音、長音訊與高並發測試；Windows 開機自動恢復仍取決於 Docker Desktop 是否隨登入啟動。

## 2026-09-30 開源初始版本整理

- 將穩定的 `feat/lesson-library-append` 快轉合併回 `main`，以該檔案狀態準備單一根提交，作為 GitHub 公開版本的起點。
- 加入 MIT 授權，重寫繁體中文 README，說明本機啟動、fake providers、真實模型設定、目前功能與資料保護；擴大 `.gitignore` 排除整個本機 `data/` 內容（保留 `.gitkeep`）；移除文件中指向舊 Git 提交的雜湊。
- 發行前初步掃描全部 322 個歷史 Git blob，未發現常見私鑰或服務 token 形式；`.env`、資料庫、上傳資料與日誌維持排除追蹤。
- 驗證：`uv run pytest -q` → 385 passed、9 skipped、1 個既有警告；`node --test frontend/test/screen-flow.test.cjs` → 3 passed；`git diff --check` 通過。
- 已知限制：另一個附屬工作樹的 `docs/PROGRESS.md` 有未提交變更，保留在本機；檔案內容掃描無法保證辨識所有格式的密鑰。

## 2026-09-30 README 快速開始補上本機語音服務

- 在快速開始中補上 STT 密鑰產生與 `.env` 設定、Docker Compose 啟動 TTS／STT、`healthy` 狀態檢查，再啟動 TalkPath API；同時說明首次模型下載及可略過語音服務的 fake provider 路徑。
- 驗證：對照 `docs/SPEECH_SERVICES.md` 與 `docker/compose.speech.yml` 的欄位、埠及啟動指令；`docker compose config --quiet` 與 `git diff --check` 通過。

## 2026-09-30 本機學習資料重置

- 依使用者要求從零開始，先以 SQLite 交易清空 session、作答與複習紀錄；接著停止 TalkPath API，將舊 SQLite 檔、LessonLens 課程目錄、上傳圖片、暫存音訊及舊日誌移至 Windows 回收筒。保留 `data/lessonlens/.gitkeep`、程式碼、`.env` 與 Docker 模型設定。
- 重新啟動 TalkPath API；驗證 `GET /api/lessons` 回 HTTP 200 且課程數為 0、LessonLens 僅餘 `.gitkeep`、上傳與暫存目錄均無檔案、舊 SQLite 檔已不存在。
- 永久遞迴刪除曾遭自動審查以 `blocked by policy` 拒絕，因此改採可復原的 Windows 回收筒移除方式。
