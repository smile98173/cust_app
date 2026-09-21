# AI Test Environment Guide

本文件定義客服 AI 的實際模型測試流程。凡是要判斷模型是否理解情境、是否正確分流、或回覆是否符合客服期待，都必須依此流程執行。

## Test Environment

- 環境檔：`D:\AI智能客服\env\.env.ai-test`
- Python：`C:\Users\user\anaconda3\envs\cust_app\python.exe`
- 不使用 `.env.production` 執行客服情境測試。
- 不將環境檔中的帳密、API key 或 token 寫入程式、測試資料或文件。

啟動或執行一次性測試前，必須設定：

```powershell
$env:CUST_APP_ENV_FILE = 'D:\AI智能客服\env\.env.ai-test'
```

## What Counts As An AI Test

下列測試只能用來驗證程式流程，不能宣稱是 AI 實測：

- 使用 `RunnableLambda`、mock LLM 或固定 router 回傳值的單元測試。
- 模型連線受限、逾時或回傳 `model_router_unavailable` 時的結果。
- 只驗證關鍵字或資料庫內容、沒有呼叫設定模型的結果。

要宣稱「AI 已通過」時，必須以 `.env.ai-test` 設定的真實模型呼叫，並至少記錄：

- 輸入情境與必要的前文對話。
- LLM router 的 route、intent、reason。
- 最終客服回覆與排錯流程步驟。
- 執行時間、環境名稱與通過/未通過判斷。

## API Short-Lived Token Flow

本機測試 API 預設使用短期 token，不直接拿靜態 token 呼叫 `/chat`。

1. 先向 `POST /api/auth/token` 傳送環境檔中的 `API_AUTH_NAME`、`API_AUTH_PASSWORD`。
2. 讀取回傳的 `access_token` 與 `header_name`。
3. 後續呼叫 `/chat`、`/api/web/chat` 或其他受保護 API 時，使用回傳的 header 與 `access_token`。
4. token 過期或 API 回傳 401 時，重新取得 token 後再重試一次。

`/api/auth/token` 必須免 API token 驗證；環境檔應包含：

```env
API_AUTH_EXEMPT_PATH_PREFIXES=/api/line/,/api/auth/token
```

如果連 `/api/auth/token` 都收到 401：

1. 確認目前啟動的服務使用的是 `.env.ai-test`。
2. 確認上述免驗證路徑沒有被環境變數覆蓋。
3. 請管理者確認或重啟後端服務；服務恢復後再重新取得短期 token。Codex 不得自行重啟 8123。

## Regression Testing Rules

- LLM 負責判讀使用者語意與選擇 route；不要用 base route 或關鍵字規則強制覆蓋 LLM 的判讀。
- SOP 可依 LLM 已選定的故障類型處理症狀細節，例如網路或電視的下一步排錯。
- 對每個已處理回饋，建立或更新回歸案例，保留原始對話、客服期待、實測結果與判斷依據。
- 更新規則後，先跑該回饋情境與既有回歸案例；確認後再由管理者決定是否發布到線上。

## Customer Feedback Debugging Loop

客服提出實際錯答、延續對話失憶、內容過長或排版異常時，必須依下列循環處理，不可只改提示詞後就宣稱完成。

### 1. 先還原問題，不先猜答案

1. 保留客服提供的原始問題、完整對話順序、畫面與期待結果。
2. 從 latency log、chat history、session memory 檢查該次實際的 route、intent、reason、模型來源與 fallback 狀態。
3. 比對真正送進模型的 prompt/context，以及模型輸出、後端後處理、RAG、前端渲染各層結果。
4. 判斷問題屬於哪一層，例如：
   - 對話歷史或 memory 沒有正確傳遞。
   - Router 語意判讀或 prompt 規則不足。
   - RAG 查詢範圍、文件選擇或回答整理錯誤。
   - 後端格式化改壞模型原始回覆。
   - 前端 Markdown／HTML／CSS 渲染異常。
5. 必須先提出可由紀錄驗證的根因，不能把所有問題籠統歸因為「模型不穩定」。

### 2. 修正架構，不用捷徑遮掩

1. 修改造成問題的實際層級，保持變更範圍最小。
2. 禁止用 fastpath、關鍵字固定回覆或硬編碼活動／方案名稱繞過 LLM。
3. 優惠活動、方案名稱與有效內容必須來自當下知識庫，不可寫死在 prompt 或程式中。
4. 不可把環境檔路徑、API key、帳密或 token 寫死在主程式或測試案例。
5. 加入能保護該架構行為的單元或回歸測試，但這些測試只能證明程式結構，不能取代真實模型驗證。

### 3. 只使用管理者已啟動的 8123

1. `127.0.0.1:8123` 由管理者啟動並以 reload 模式維持。
2. Codex 不得自行啟動、停止、重啟或終止 8123 的後端程序，也不得為了測試另開一個替代服務。
3. 測試時直接呼叫既有的 8123。若無法連線，先回報管理者確認服務狀態，不可自行接管程序。
4. 呼叫 API 前仍須依本文件的短期 token 流程取得 token，不得繞過驗證。

### 4. 用真實對話重播驗證

1. 使用新的測試 user ID，避免舊 session memory 污染結果。
2. 依原始順序逐輪呼叫 8123，不可只測最後一句；代名詞、數字選項、「都需要」等延續語句必須包含前文一起測。
3. 使用 `.env.ai-test` 與 `cust_app` Conda 環境讀取測試設定及執行測試客戶端，但不藉此另行啟動後端。
4. 每一輪至少核對：
   - 最終客服回覆。
   - route、intent、reason。
   - provider、model、success 與 fallback。
   - 回覆時間及是否真的執行 RAG／工具。
5. 只有真實設定模型成功回覆且 `fallback = false`，才算真實 AI 測試。

### 5. 失敗就回到診斷，不提早結案

1. 若重播結果仍不符合客服期待，保留該次 route、reason、memory、檢索內容與最終回覆。
2. 回到步驟 1 重新判斷問題層級，再修改並重播同一段完整對話。
3. 重複此循環，直到原始案例通過，且相關回歸測試沒有出現新問題。
4. 完成後向客服清楚回報根因、修改位置、實際模型測試結果，以及略過或仍未能驗證的項目。
5. 測試通過不代表自動發布；是否更新線上環境仍由管理者決定。

## Before Reporting Results

回報「已測試」前，逐項確認：

- [ ] 使用 `.env.ai-test`。
- [ ] 使用 `cust_app` Conda 環境。
- [ ] 真實模型呼叫成功，沒有 fallback 到 `model_router_unavailable`。
- [ ] API 測試已先取得短期 token。
- [ ] 結果已區分為程式單元測試或真實 AI 實測。
- [ ] 未自動發布追蹤資料或規則到線上。
