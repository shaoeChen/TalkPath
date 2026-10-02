# 2026-10-01 區網錄音診斷

## 已確認的結果

- TalkPath 以區網 HTTPS 模式在 IPv4 `0.0.0.0:8443` 監聽，provider 健康報告確認使用真實 `local_http` STT／TTS；健康報告的 `not_checked` 並不代表完成轉錄驗證。
- STT／TTS Compose 容器皆為 healthy，STT `/v2/health` 回報模型 ready。
- 使用者回報前的近期三筆錄音送達 STT，完成音訊解碼，時長分別約 4.7、1.7、2.5 秒；三筆 VAD 都偵測到 0 個語音段。本文件不保留精確操作時間。這些日誌沒有瀏覽器／session 身分，無法直接證明每筆都屬於使用者回報的操作。
- 經現行 TalkPath provider adapter，讓本機 TTS 合成 `Hello world. This is a microphone test.`，用 STT 容器的 FFmpeg 轉為 WebM／Opus，再送入 STT；實際轉錄為 `Hello world, this is a microphone test.`。
- 經相同 STT adapter 送入兩秒合成靜音 WAV，實際回傳空字串；沒有出現連線、驗證或格式例外。

## 判讀與限制

近期錄音確實已送達辨識服務，但未被偵測為語音。合成語音的 WebM 測試通過，說明現行 adapter、密鑰、音訊格式解碼及模型在此測試條件下可用；不能據此宣稱另一台電腦的麥克風正常，或所有弱音量／短單字都能正確辨識。

原錄音的 STT 暫存檔已清除，檢查 uploads 目錄為空，無法量測峰值與平均音量，也未保存使用者錄音。尚待在用戶端確認瀏覽器實際選用的輸入裝置、是否靜音、輸入音量及畫面錯誤；低音量或 VAD 漏判仍未排除。診斷未調整 VAD 門檻、憑證、防火牆或程式碼，也未重新啟動使用者的服務。

Chrome 可在麥克風設定選擇預設裝置，參考 [Chrome 官方麥克風說明](https://support.google.com/chrome/answer/2693767)。
