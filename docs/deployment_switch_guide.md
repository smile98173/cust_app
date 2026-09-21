# 正式上線快速指南

本文件給部署或專案負責人使用，目標是快速知道正式上線要改哪些設定、怎麼啟動、怎麼驗證。

正式機密不要提交到 repo。建議放在部署平台的環境變數；若要用檔案，請用 `CUST_APP_ENV_FILE` 指到正式 env 檔。

## 1. Env 檔怎麼用

專案目前有三份 env：

```text
.env              安全預設值，適合本機或測試預設
.env.local        個人本機測試用，不提交正式機密
.env.production   正式上線範本，不提交正式機密
```

指定正式 env：

```powershell
$env:CUST_APP_ENV_FILE="D:\AI智能客服\cust_app\.env.production"
```

CMD：

```cmd
set CUST_APP_ENV_FILE=D:\AI智能客服\cust_app\.env.production
```

也可以把正式 env 放到專案外，例如：

```powershell
$env:CUST_APP_ENV_FILE="D:\AI智能客服\cust_app.production.env"
```

設定載入順序：

```text
.env
-> CUST_APP_ENV_FILE 指定的 env
-> 系統 / 部署平台環境變數
```

## 2. 正式上線最少要設定

### 資料庫

測試預設使用 SQLite：

```env
STATE_REPOSITORY_BACKEND=sqlite
```

LINE 若要改用 MongoDB：

```env
STATE_REPOSITORY_BACKEND=mongodb
MONGODB_URI=mongodb://<mongodb-username>:<url-encoded-password>@<正式-mongodb-host>:27017/?authSource=admin
MONGODB_DATABASE=aicust_service
MONGODB_WEB_COLLECTION=web_conversations
MONGODB_TEST_WEB_COLLECTION=test_web_conversations
MONGODB_LINE_COLLECTION=line_conversations
```

MongoDB 目前採 Web / LINE 分 collection：

```text
aicust_service.web_conversations
aicust_service.test_web_conversations
aicust_service.line_conversations
```

正式 Web 的 `ai_state` 與 `chat_logs` 寫入 `web_conversations`；Web UI 測試入口 `/chat` 寫入 `test_web_conversations`；LINE 對話與 LINE 跨 Bot profile 寫入 `line_conversations`。詳細格式看 `docs/database_collection_plan.md`。

如果 MongoDB 密碼包含 `@`、`:`、`/`、`#` 等特殊字元，請先做 URL encode 再放進 `MONGODB_URI`。

### 程式與資料夾邊界

正式更新主要客服對話核心時，目標是本專案 `cust_app`。同層的 `customer_service_km` 是另一套 Laravel 版 KM / RAG 系統，除非確認正式環境仍要同步維護那套系統，否則不要在部署 `cust_app` 時覆蓋它。

更新程式碼時也不要覆蓋正式資料目錄：

```text
customer_service_km/        舊版或獨立 KM / RAG 系統，部署 cust_app 時不要覆蓋
data/kb_documents/          舊版 Web UI 上傳知識文件位置；新部署不建議放正式資料
data/chroma_db/             舊版本地 ChromaDB 位置；新部署不建議放正式資料
cust_app_runtime/           正式 runtime logs、feedback、company_profiles.json、ChromaDB 與知識文件
```

建議部署原則是「程式歸程式，資料歸資料」：更新 `app/`、`scripts/`、`requirements.txt`、文件與設定範本時，保留正式 `.env.production` 與 `cust_app_runtime`。目前公司資訊與本地 RAG 資料預設都放在 `cust_app_runtime`。

### OpenAI

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=<正式 OpenAI API key>
OPENAI_MODEL=<正式使用模型>
OPENAI_TEMPERATURE=0.4
OPENAI_BASE_URL=
```

### Ollama 備援

```env
LLM_FALLBACK_PROVIDER=ollama
LLM_ENABLE_FALLBACK=true
OLLAMA_MODEL=<遠端 Ollama model>
OLLAMA_BASE_URL=http://<remote-ollama-host>:11434
OLLAMA_TEMPERATURE=0.5
```

正式環境的 `OLLAMA_BASE_URL` 請指向遠端 Ollama 服務，不要依賴部署機本機 Ollama。

RAG 找到知識後的客服語氣整理預設使用 OpenAI，並沿用 `OPENAI_MODEL`。正式環境通常不需要設定下列參數；只有要切換摘要模型或測小模型時才解除註解：

```env
# LLM_RAG_SUMMARY_PROVIDER=openai
# LLM_RAG_SUMMARY_MODEL=<正式 OpenAI model>
# LLM_RAG_SUMMARY_BASE_URL=
# LLM_RAG_SUMMARY_TEMPERATURE=0.3
# LLM_RAG_SUMMARY_TIMEOUT_SECONDS=20
# LLM_RAG_SUMMARY_ENABLE_FALLBACK=false
# RAG_SUMMARY_MAX_DOCS=5
# RAG_SUMMARY_MAX_CHARS_PER_DOC=900
```

預設值為 `LLM_RAG_SUMMARY_PROVIDER=openai`、`LLM_RAG_SUMMARY_TIMEOUT_SECONDS=20`、`LLM_RAG_SUMMARY_ENABLE_FALLBACK=false`、`RAG_SUMMARY_MAX_DOCS=5`、`RAG_SUMMARY_MAX_CHARS_PER_DOC=900`。若改成 `ollama` 且 `LLM_RAG_SUMMARY_BASE_URL` 留空，會沿用 `OLLAMA_BASE_URL`。正式環境可先觀察 latency log 裡 `llm_events[].task = rag_summary` 的平均耗時，再決定是否擴大到其他任務。

### RAG / Local Knowledge Base

```env
RAG_BACKEND=local
RAG_LOCAL_PERSIST_DIR=
RAG_LOCAL_COLLECTION=company_kb
RAG_LOCAL_DOCS_DIR=
RAG_LOCAL_MANIFEST_PATH=
RAG_LOCAL_EMBED_MODEL=BAAI/bge-m3
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=200
RAG_LOCAL_MAX_DISTANCE=0.65
```

三個 RAG 路徑留空時會使用 `cust_app_runtime/chroma_db`、`cust_app_runtime/kb_documents` 與 `cust_app_runtime/kb_documents/documents.json`。正式環境需讓 `cust_app_runtime` 保持可寫且可備份。若要保留外部 RAG API 作為備援，可使用：

```env
RAG_BACKEND=hybrid
RAG_API_URL=<內部 RAG API URL>
RAG_API_TIMEOUT_SECONDS=15
RAG_API_INCLUDE_EXPIRED=false
```

目前 RAG 知識庫分類可選 `通用` 或各系統台名稱。客服查詢會先由 LLM 判斷是否需檢索，再查 `通用` 與 `company_code` 對應系統台，例如 `tdtv -> 大屯`；回答前會進行對題與服務證據檢查，避免不相關文件主導回覆。

### Gemini OCR

```env
GEMINI_API_KEY=<正式 Gemini API key>
GEMINI_IMAGE_TEXT_MODEL=gemini-2.5-pro
IMAGE_TEXT_MAX_SIZE=1024
```

### Logs

```env
CUST_APP_RUNTIME_DIR=
APP_LOG_DIR=
FEEDBACK_DIR=
APP_ERROR_LOG_PATH=
APP_ERROR_LOG_DAILY=true
CHAT_LATENCY_LOG_PATH=
CHAT_LATENCY_LOG_DAILY=true
FEEDBACK_CSV_PATH=
FEEDBACK_CSV_DAILY=true
PUBLIC_ERROR_MESSAGE=抱歉，系統目前暫時無法完成處理，請稍後再試一次。
COMPANY_PROFILE_PATH=
```

若不指定 `CUST_APP_RUNTIME_DIR`，預設會使用專案同層資料夾，例如 `D:\AI智能客服\cust_app_runtime`。每日分檔範例：

```text
D:\AI智能客服\cust_app_runtime\logs\app_errors_2026-05-28.log
D:\AI智能客服\cust_app_runtime\logs\chat_latency_2026-05-28.log
D:\AI智能客服\cust_app_runtime\feedback\ai_feedback_2026-05-28.csv
```

內部例外會寫入每日 log，對外 API 不回傳 MongoDB、堆疊或其他技術細節。回饋 CSV 也會每日分檔，避免部署更新專案資料夾時覆蓋測試資料。

每輪對話耗時會寫入 `CHAT_LATENCY_LOG_PATH`，預設每日分檔到 `cust_app_runtime/logs/chat_latency_YYYY-MM-DD.log`。每行是一筆 JSON，包含來源通道、公司代碼、route / intent、各階段 latency、LLM 呼叫次數與每次 LLM 耗時；不寫入完整使用者訊息，只記錄訊息長度，方便正式環境排查慢在哪一段。

`COMPANY_PROFILE_PATH` 若留空，預設會使用 `D:\AI智能客服\cust_app_runtime\company_profiles.json`。Web UI 修改公司基本資訊後會寫入這個 JSON，後續 AI 回覆、服務地區判斷與公司資訊查詢都會使用更新後資料。

目前 Web UI「公司資訊維護」可編輯欄位包含地址電話、營業時間、服務地區、區域故障、優惠活動、公司網址與加值服務網址。公司網址與加值服務網址由 LLM 依使用者意圖選擇正確資料來源。優惠欄位僅適合放高層公告；優惠、促銷與推薦方案應由知識庫文件或結構化方案資料提供證據，已下架方案不得主動推薦。

### Web UI URL

```env
WEB_BACKEND_API_BASE_URL=http://127.0.0.1:8123
WEB_PUBLIC_API_BASE_URL=https://<正式網域>:8000
# 與真人文字客服系統共用，建議使用 16 個 ASCII 字元。
WEB_HUMAN_HANDOFF_TOKEN_KEY=<雙方約定的16字元密鑰>
# Optional legacy fixed token. 正式若只走 /api/auth/token，可留空。
API_AUTH_TOKEN=
API_AUTH_HEADER=X-API-Token
API_AUTH_NAME=<提供給 Web server 取 token 的帳號>
API_AUTH_PASSWORD=<提供給 Web server 取 token 的密碼>
API_AUTH_SECRET=<token 簽章密鑰，請換成高強度隨機字串>
API_AUTH_TOKEN_TTL_SECONDS=86400
API_AUTH_EXEMPT_PATH_PREFIXES=/api/line/,/api/auth/token
# Streamlit 後台呼叫 FastAPI 用；若只走 /api/auth/token，可留空。
WEB_BACKEND_API_TOKEN=
WEB_BACKEND_API_AUTH_HEADER=X-API-Token
```

`WEB_BACKEND_API_BASE_URL` 是 Streamlit 伺服器自己呼叫 FastAPI 用的網址。若兩者在同一台機器，保留 `127.0.0.1` 通常可以。

`WEB_PUBLIC_API_BASE_URL` 是使用者瀏覽器開啟 RAG 原始檔預覽分頁用的網址。遠端部署不能填 `127.0.0.1`，也不要填 Python 內部 port `:8123`；請填使用者實際能開啟的 Apache 對外 API 網址，例如 `https://aiia.topmso.com.tw:8000`。

`WEB_HUMAN_HANDOFF_TOKEN_KEY` 是 AI 客服與真人文字客服系統共用的 AES key。兩端必須設定相同值；Token 內容為 `{流水號或客編}+{Unix timestamp}`，使用 `AES-128-ECB` 加密後轉成 Base64URL。

`API_AUTH_SECRET`、`API_AUTH_NAME`、`API_AUTH_PASSWORD` 設定後，除了 `/api/line/*/webhook` 與 `/api/auth/token` 以外的 FastAPI 路由都會要求 token。外部 Web server 先用 `API_AUTH_NAME` / `API_AUTH_PASSWORD` 呼叫 `/api/auth/token` 取得 `access_token`，再呼叫 `/api/v1/chat` 或 `/api/ocr/image`。`API_AUTH_TOKEN` 只是相容舊式固定 token，正式若不想用固定 token 可留空。

### LINE

正式 LINE Bot 至少要填：

```env
LINE_TOP_CHANNEL_ACCESS_TOKEN=
LINE_TOP_CHANNEL_SECRET=
LINE_TDTV_CHANNEL_ACCESS_TOKEN=
LINE_TDTV_CHANNEL_SECRET=
LINE_CLTV_CHANNEL_ACCESS_TOKEN=
LINE_CLTV_CHANNEL_SECRET=
LINE_PKTV_CHANNEL_ACCESS_TOKEN=
LINE_PKTV_CHANNEL_SECRET=
```

真人客服模式：

```env
LINE_HUMAN_MODE_TIMEOUT_SECONDS=1200
LINE_TOP_HUMAN_GROUP_ID=
LINE_TOP_HUMAN_ACCESS_TOKEN=
LINE_TDTV_HUMAN_GROUP_ID=
LINE_TDTV_HUMAN_ACCESS_TOKEN=
LINE_CLTV_HUMAN_GROUP_ID=
LINE_CLTV_HUMAN_ACCESS_TOKEN=
LINE_PKTV_HUMAN_GROUP_ID=
LINE_PKTV_HUMAN_ACCESS_TOKEN=
```

Webhook URL：

```text
https://<正式網域>:8000/api/line/top/webhook
https://<正式網域>:8000/api/line/tdtv/webhook
https://<正式網域>:8000/api/line/cltv/webhook
https://<正式網域>:8000/api/line/pktv/webhook
```

### 客戶服務 API

測試環境：

```env
CUST_API_USE_MOCK=true
```

正式環境：

```env
CUST_API_USE_MOCK=false
CUST_API_TIMEOUT=30
CUST_API_TOKEN_URL=
CUST_API_SEARCH_BILL_URL=
CUST_API_INTERNET_RETURN_URL=
CUST_API_TV_RETURN_URL=
CUST_API_SEND_MESSAGE_URL=
CUST_API_CONTRACT_INFO_URL=
CUST_API_PAYMENT_BARCODE_URL=
CUST_API_CHANNEL_QUERY_URL=
```

合約/服務內容查詢會使用 `CUST_API_CONTRACT_INFO_URL`；API 登入/傳入可用客戶識別時可直接查詢，否則改用戶名+電話核對。回覆會略過基本頻道與數位電視頻道，並整理網路速率與合約/加值服務到期資訊。

超商繳費收據復線會使用 `CUST_API_PAYMENT_BARCODE_URL`，收到第一段、第二段、第三段條碼後確認繳費並進行復線處理。適用 7-11、全家、萊爾富、OK 等超商收據。

所有需要客戶身分的 CUST_API 都會優先使用明確傳入的 `custnum` 查詢；沒有 `custnum` 時，才會向用戶補問戶名與聯絡電話。`user_id` / `member_id` 只代表 Web 使用者識別，不會自動當成 CUST_API 客戶編號。

目前報修、取消報修、申請裝機、查地址可申辦、加值方案查詢仍停用。報修/取消報修停用訊息會引導真人客服並附上維修申告連結；排錯流程中若使用者回覆 `不知道`、`不清楚`、`沒用`、`不行` 或拒絕排錯，也會直接走這段停用訊息。優惠、促銷與推薦方案仍需先由 LLM 判斷意圖，再依知識庫或結構化方案資料回答。

## 3. 啟動服務

安裝套件：

```powershell
pip install -r requirements.txt
```

啟動 API：

```powershell
uvicorn app.app_backend:app --host 127.0.0.1 --port 8123
```

啟動 Streamlit：

```powershell
streamlit run app\web_ui.py --server.address 127.0.0.1 --server.port 8443 --server.baseUrlPath assistant --server.enableCORS false --server.enableXsrfProtection false
```

後端 port 由 `uvicorn --port` 決定；前端 port 由 `streamlit --server.port` 決定。`--server.baseUrlPath assistant` 會讓 Streamlit 掛在 `/assistant`。目前正式環境由 Apache 對外 `:8501` 轉到內部 `127.0.0.1:8443`，因此 Streamlit 對外網址是 `https://<正式網域>:8501/assistant`。若反向代理外部網址與 Streamlit 內部 port 不一致，保留 `--server.enableCORS false --server.enableXsrfProtection false`，避免 Streamlit 因來源檢查擋下請求。

健康檢查：

```text
GET https://<正式網域>:8000/health
```

## 4. Web 串接

正式 Web 建議使用：

```text
POST https://<正式網域>:8000/api/v1/chat
```

Web server 負責傳入：

```text
company_code
user_id
is_logged_in
msg
```

Web server 不需要保存 `history` / `ai_state`，正式 Web 狀態由本系統資料庫保存。不要讓正式 Web 流程依賴 `/api/web/chat`，那是本機測試入口。

Web request / response 範例看：

```text
docs/web_api_integration_guide.md
```

## 5. 上線前檢查

建議至少跑：

```powershell
python -m pytest tests -q
```

人工確認：

- `GET /health` 回 `ok`。
- OpenAI key 可用。
- 遠端 Ollama 可連線。
- Web UI「知識庫維護」可上傳文件並成功建立 Chroma 索引；以不同服務主題測試，確認 RAG 不會用不相干文件回答。
- LINE 每個 Bot webhook verify 成功。
- LINE 傳「真人客服」會進真人模式並通知群組。
- Web `/api/v1/chat` 第一輪和第二輪帶 `user_id`、`company_code`、`msg`、`is_logged_in`；若有 CUST_API 客戶編號另帶 `custnum` 或 `metadata.custnum`；並能收到 response `msg`。
- 客戶 API 在 `CUST_API_USE_MOCK=false` 前已確認 endpoint、payload、timeout、錯誤格式。

## 6. 回退方式

若正式服務異常，先用 env 回退：

```env
CUST_API_USE_MOCK=true
RAG_BACKEND=local
LLM_ENABLE_FALLBACK=false
STATE_REPOSITORY_BACKEND=sqlite
```

回退效果：

- 客戶 API 回到 mock。
- RAG 維持本地 Chroma 查詢；若需完全停用，先備份 `cust_app_runtime/chroma_db` 並停止知識型問題導流。
- 暫停 LLM fallback，方便排查主模型問題。
- 儲存回到 SQLite。

LINE 若有重大問題，可先在 LINE Developers 暫停 webhook 或改回舊 endpoint。

## 7. 相關文件

```text
docs/web_api_integration_guide.md   Web API request / response
docs/database_collection_plan.md    LINE MongoDB collection 格式
docs/project_overview.md            專案總覽
PRODUCTION_CHECKLIST.md             上線檢查表
```
