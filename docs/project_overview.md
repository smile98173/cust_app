# 專案總覽與目前進度

本文件整理目前智慧客服系統的專案狀態、主要架構、近期變更與後續待辦。細節規格請依文件導覽連到對應文件。

## 目前定位

本專案是一套受控型 AI 客服系統，支援 WEB 與 LINE 入口，核心目標是讓 AI 在明確規則、工具白名單與流程限制下協助客服問答，不讓模型自行代辦未知流程、收集不必要個資或承諾未串接的服務。

目前系統重點：

- WEB 正式串接走 `POST /api/v1/chat`，外部傳 `user_id`、`company_code`、`msg`、`is_logged_in`，若有 CUST_API 客戶編號另傳 `custnum`，由本系統保存 `chat_logs` 與 `ai_state`。
- LINE 多 Bot 入口仍保留本機 session 與 chat logs，並透過 `customer_profiles` 同步同一 LINE 使用者已確認的系統台。
- 每次需要新語意判斷時由 LLM-first Router 決定意圖；既有排錯、工具與授權狀態由狀態機承接。模型無法判讀時回固定暫時無法判讀訊息，不退回舊規則回答。
- RAG 使用本地 ChromaDB 與文件上傳維護流程；回答前需通過對題與服務證據檢查。
- Ollama fallback 以遠端 Ollama 服務為目標，由 `OLLAMA_BASE_URL` 指定。
- 對話不直接建立或取消報修工單；先引導安全排錯。排錯失敗或客戶明確無法操作時，提供維修申告表單並詢問是否轉真人，只有同意後才轉接。
- Web UI 可維護系統台公司資訊，包含地址電話、營業時間、服務地區、區域故障、公司網址與加值服務網址。
- 本機 SQLite 目前只作為測試/LINE 狀態保存與 MongoDB-style repository 模擬。

## 專案架構

```text
WEB / LINE 使用者
  -> app_backend.py
      -> channel_context.py
          -> 套用 WEB / LINE / Bot / customer profile context
      -> chat_handler.py
          -> pending tool / troubleshooting / LLM router
      -> intent_router.py
          -> route decision
      -> tool_manager.py / kb_service.py / troubleshooting_engine.py
          -> mock or external API / local Chroma RAG / guided troubleshooting
      -> memory_service.py
          -> state_repository.py
              -> SQLiteCustomerStateRepository
              -> MongoCustomerStateRepository
```

主要模組：

- API 入口：`app/app_backend.py`
- WEB 測試 UI：`app/web_ui.py`
- 正式 WEB API 串接文件：`docs/web_api_integration_guide.md`
- PHP 串接範例：`docs/web_api_php_example.php`
- 對話核心：`app/handlers/chat_handler.py`
- Router：`app/services/intent_router.py`、`router_catalog.py`、`router_prompt.py`
- RAG 查詢：`app/services/kb_service.py`
- RAG 文件維護：`app/services/kb_admin_service.py`
- LLM provider / fallback：`app/services/model_manager.py`
- LINE / WEB channel context：`app/services/channel_context.py`
- 客戶狀態儲存：`app/services/memory_service.py`、`state_repository.py`
- 錯誤紀錄：`app/services/error_logging.py`，預設每日分檔寫入專案同層 `cust_app_runtime/logs`
- 客戶工具 API/mock：`app/services/tool_manager.py`
- 系統台資料：`app/services/company_profile.py`

## 資料與儲存

目前本機 SQLite 資料庫位置：

```text
data/customer_state.db
```

目前保留的主要資料：

- `sessions`：本機/LINE 對話 memory。
- `chat_logs`：本機/LINE 對話紀錄。
- `customer_profiles`：LINE 跨 Bot 共用的已確認系統台資訊。
- `feedback_records`：測試回饋資料；測試環境也會寫 CSV。

已移除：

- `tickets` 本機資料表。
- `/tickets/{user_id}` API。
- 測試 UI 的工單狀態與歷史工單區塊。

## API 與外部串接

目前重要入口：

- `POST /api/v1/chat`：正式 Web server 串接，外部傳 `user_id`、`company_code`、`msg`、`is_logged_in`，若有 CUST_API 客戶編號另傳 `custnum`，由本系統保存 session/chat logs。
- `POST /api/web/chat`：WEB 測試入口，使用本機 session/chat logs。
- `POST /api/line/{bot_code}/webhook`：LINE webhook，多 Bot 入口。
- `GET /state/{user_id}`：測試/除錯用，查目前 memory。
- `POST /reset/{user_id}`：測試/除錯用，清 session 與 chat logs。

外部服務：

- RAG：`RAG_BACKEND`、`RAG_LOCAL_PERSIST_DIR`、`RAG_LOCAL_COLLECTION`
- OpenAI：`OPENAI_API_KEY`、`OPENAI_MODEL`
- 遠端 Ollama fallback：`OLLAMA_BASE_URL`、`OLLAMA_MODEL`
- Gemini OCR：`GEMINI_API_KEY`
- 客戶資料 mock/API：`CUST_API_*`

Env 檔：

- `.env`：安全預設值。
- `.env.local`：個人本機測試用。
- `.env.production`：正式上線範本。
- `CUST_APP_ENV_FILE`：指定要載入的 env 檔，可用相對路徑或絕對路徑。
- Web / LINE MongoDB 分 collection 規劃：`docs/database_collection_plan.md`，正式 database 建議為 `aicust_service`，collections 為 `web_conversations` 與 `line_conversations`。

## 目前進度

已完成：

- Router catalog/schema/prompt 拆分，降低 prompt 與工具白名單散落問題。
- WEB / LINE channel context 分流。
- LINE 跨 Bot `customer_key = line:{line_user_id}` 與 `customer_profiles` 同步。
- 正式 Web API `/api/v1/chat`，改由本系統保存 `ai_state` 與對話紀錄。
- 新增正式 Web API 串接文件與 PHP 範例，說明第一次/第二次 request/response 與外部保存方式。
- Repository 儲存層，SQLite 作為 MongoDB-style document 模擬。
- 報修與取消報修流程停用。
- 移除本機 `tickets` 儲存。
- HBO 頻道 mock 查詢。
- RAG 切回本地 ChromaDB，並新增 `/api/kb/*` 文件維護 API 與 Web UI 維護區。
- 公司資訊維護支援編輯 `公司網址`、`加值服務網址` 與 `優惠活動`；網址類問題由 LLM 判斷意圖，優惠欄位僅放高層公告，正式方案回答需有知識庫或結構化方案資料佐證。
- RAG 命中側欄會將 CSV chunk 的 `question: ...；answer: ...；company: ...` 顯示拆成獨立欄位，原始連結標記維持純文字；聊天回覆時才將 `［名稱🔗］` 標記轉成可點連結。
- Ollama fallback 改為遠端服務設定導向。
- `requirements.txt` 重新啟用本機 Chroma/BGE RAG 套件，並加入 PDF/DOCX 匯入依賴。
- SQLite user state 查詢工具：`scripts/query_sqlite_user_state.py`。

待確認 / 後續工作：

- 正式環境需確認 `cust_app_runtime/chroma_db` 與 `cust_app_runtime/kb_documents` 有備份策略。
- 後續若有更多系統台知識文件，需確認各系統台文件維護責任與更新頻率。
- Web / LINE MongoDB 分 collection 儲存已可透過 `STATE_REPOSITORY_BACKEND=mongodb` 啟用；正式連線資訊仍需由部署環境提供。
- 正式 Web 狀態保存若使用 MongoDB，需確認正式 `MONGODB_URI`、帳密與 collection 權限。
- LINE 真人客服模式正式 token/group 設定與營運流程。
- 報修查詢/取消報修若恢復，需改走外部 API，不回復本機 `tickets` 表。

## 專案紀錄

### 2026-06-04

- 公司資訊維護開放編輯 `公司網址`、`加值服務網址` 與 `優惠活動`，儲存後寫入 `COMPANY_PROFILE_PATH` 對應 runtime JSON。
- 公司資訊查詢分流為公司網址與加值服務網址；問公司網站時不顯示 LINE TV 等加值服務網址。
- 前端聊天回覆會將 `［名稱🔗］URL` 或已知 `［LINE TV客服中心🔗］` 標記轉為可點連結；知識庫命中側欄保留資料原樣，避免誤以為 CSV 已寫入 Markdown 超連結。
- RAG 命中側欄新增 CSV chunk 顯示整理，將 `question`、`answer`、`company` 拆開呈現。
- 排錯流程中若使用者回覆 `不知道`、`不清楚`、`沒用`、`不行` 或拒絕排錯，直接導向報修暫停訊息並附維修申告連結。

### 2026-05-28

- RAG runtime 切回本地 ChromaDB，外部 RAG API 改為可選 `api` / `hybrid` 模式。
- 新增 `RAG_BACKEND`、`RAG_LOCAL_PERSIST_DIR`、`RAG_LOCAL_COLLECTION`、`RAG_LOCAL_DOCS_DIR` 等本地 RAG 設定。
- RAG 上傳知識庫分類可選 `通用` 或各系統台名稱；文件主題分類由匯入時自動判斷，客服查詢不使用主題分類過濾，避免漏查。
- 新增錯誤 log 機制，MongoDB/API/RAG/OCR 等內部錯誤會每日分檔寫入專案同層 `cust_app_runtime/logs`，回饋 CSV 會每日分檔寫入 `cust_app_runtime/feedback`，對外 API 只回友善錯誤訊息。
- `requirements.txt` 重新啟用本機 Chroma/BGE RAG 套件。
- 新增本地 RAG 與文件匯入測試。
- 此為當時的歷史做法：優惠、促銷、推薦方案、優惠套餐曾暫停走 RAG，改回覆公司資訊維護的 `優惠活動`。現行規則以本文件「目前定位」與 `active_customer_service_handoff_2026-09-14.md` 為準。
- RAG 命中的內容會再經 LLM 精簡成客服聊天室適合閱讀的重點摘要；LLM 摘要失敗時才退回原文。

### 2026-05-26

- Ollama fallback 文案改為遠端 Ollama / Ollama 備援服務。

### 2026-05-25

- 新增 `/api/v1/chat` 正式 Web server 串接介面。
- 新增 `ExternalChatRequest` schema。
- 新增正式 Web API request/response 文件與 PHP 串接範例。
- 新增 Repository 儲存層與 SQLite implementation。
- 新增 `customer_profiles` 與 LINE 跨 Bot 使用者系統台同步。
- 移除本機 `tickets` 表與工單查詢 API/UI。
- 報修流程維持停用，引導真人客服。
- 新增 SQLite user state 查詢工具。

### 2026-05-22 前後

- 整理 Router 架構與 route guard。
- 補強 customer validation、slot extraction、工具白名單與 mock API 測試。
- 補強 RAG answer guard 與 general knowledge fallback。

## 文件導覽

- `README.md`：專案入口、啟動方式、核心流程摘要。
- `docs/project_overview.md`：專案總覽、目前進度與近期紀錄。
- `docs/deployment_switch_guide.md`：測試環境切正式環境的參數對照、切換步驟、驗證與回退方式。
- `docs/database_collection_plan.md`：Web / LINE MongoDB 分 collection 儲存規劃。
- `docs/web_api_integration_guide.md`：正式 Web API URL、第一次/第二次 request/response、保存責任與 PHP 範例索引。
- `docs/web_api_php_example.php`：PHP 串接範例。
- `docs/channel_api_architecture.md`：WEB / LINE API、channel context、儲存與變更紀錄。
- `docs/local_rag_admin.md`：本地 Chroma RAG 與文件上傳維護說明。
- `docs/router_architecture.md`：Router 架構與維護方式。
- `PRODUCTION_ENV.md`：正式環境變數。
- `PRODUCTION_CHECKLIST.md`：正式部署檢查表。
- `docs/testing/manual_test_cases.md`：手動測試案例。
- `docs/planning/api_improvements_20260508.md`：早期 API 改善規劃。

## 驗證狀態

最近一次完整測試：

```powershell
python -m pytest tests -q
```

結果：

```text
159 passed, 1 warning
```

已知 warning：`tests/test_model_manager.py` 中的 `TestableModelManager` 因有 `__init__`，pytest 不收集該類別；目前不影響測試結果。
