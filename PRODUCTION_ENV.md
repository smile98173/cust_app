# Production Environment Variables

正式上線時，請在部署環境設定本文件列出的環境變數。不要把正式 token、secret、API key 寫進程式碼或提交到版本控制。

設定載入順序：

```text
settings.py 測試預設值
  -> 根目錄 .env
  -> CUST_APP_ENV_FILE 指定的 env 檔
  -> 系統環境變數
```

正式上線建議由部署平台提供系統環境變數。若要用 env 檔，可設定：

```powershell
$env:CUST_APP_ENV_FILE="D:\AI智能客服\cust_app\.env.production"
```

CMD：

```cmd
set CUST_APP_ENV_FILE=D:\AI智能客服\cust_app\.env.production
```

專案根目錄已提供：

```text
.env             安全預設值，不放正式機密
.env.local       個人本機測試用
.env.production  正式上線範本
```

注意：`.env.local` 與 `.env.production` 已被 `.gitignore` 忽略；不要把正式 token、secret、API key 提交到版本控制。

## LLM

```env
LLM_PROVIDER=openai
LLM_FALLBACK_PROVIDER=ollama
LLM_ENABLE_FALLBACK=true

OPENAI_API_KEY=正式 OpenAI API key
OPENAI_MODEL=gpt-5.5
OPENAI_TEMPERATURE=0.4
OPENAI_BASE_URL=

OLLAMA_MODEL=gemma4:e4b
OLLAMA_BASE_URL=http://遠端ollama主機:11434
OLLAMA_TEMPERATURE=0.5
```

注意：

- `OLLAMA_BASE_URL` 正式環境應指向遠端 Ollama 服務，不建議依賴部署機本機 Ollama。
- `app/config/settings.py` 只保留可安全提交的測試預設值。正式 OpenAI key 必須放在 `.env` 或部署環境變數。

## Backend API Token

正式環境建議啟用後端 API token。設定後，除了 `/api/line/*/webhook` 與 `/api/auth/token` 以外，所有 FastAPI 路由都需要 token。

```env
# Optional legacy fixed token. 正式若只走 /api/auth/token，可留空。
API_AUTH_TOKEN=
API_AUTH_HEADER=X-API-Token
API_AUTH_NAME=提供給 Web server 取 token 的帳號
API_AUTH_PASSWORD=提供給 Web server 取 token 的密碼
API_AUTH_SECRET=token 簽章密鑰，請換成高強度隨機字串
API_AUTH_TOKEN_TTL_SECONDS=86400
API_AUTH_EXEMPT_PATH_PREFIXES=/api/line/,/api/auth/token

# 與真人文字客服系統共用，建議使用 16 個 ASCII 字元。
WEB_HUMAN_HANDOFF_TOKEN_KEY=請替換成雙方約定的16字元密鑰

# Streamlit 呼叫 FastAPI 用；若只走 /api/auth/token，可留空。
WEB_BACKEND_API_TOKEN=
WEB_BACKEND_API_AUTH_HEADER=X-API-Token
```

外部 Web server 呼叫正式 API 時請帶：

```text
X-API-Token: <access_token>
```

也支援：

```text
Authorization: Bearer <access_token>
```

外部 Web server 先呼叫：

```text
POST /api/auth/token
```

並傳入：

```json
{
  "name": "<API_AUTH_NAME>",
  "password": "<API_AUTH_PASSWORD>"
}
```

取得 `access_token` 後再呼叫 `/api/v1/chat` 或 `/api/ocr/image`。

## RAG / Local Knowledge Base

RAG 知識查詢預設走本地 ChromaDB。正式環境預設會把 ChromaDB、上傳文件與 manifest 放在 `cust_app_runtime`，避免更新 `cust_app` 程式碼時覆蓋線上知識庫資料。

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
KB_INDEX_SHUTDOWN_WAIT_SECONDS=300
```

上述三個 RAG 路徑留空時，預設為：

- `RAG_LOCAL_PERSIST_DIR`：`D:\AI智能客服\cust_app_runtime\chroma_db`
- `RAG_LOCAL_DOCS_DIR`：`D:\AI智能客服\cust_app_runtime\kb_documents`
- `RAG_LOCAL_MANIFEST_PATH`：`D:\AI智能客服\cust_app_runtime\kb_documents\documents.json`

`KB_INDEX_SHUTDOWN_WAIT_SECONDS` 控制 API 收到 Ctrl+C / shutdown 時，最多等待本地知識庫索引寫入完成的秒數；預設 300 秒。若設為 `0`，會直接關閉不等待。

如需外部 RAG API 備援，可改用：

```env
RAG_BACKEND=hybrid
RAG_API_URL=內部RAG API URL
RAG_API_TIMEOUT_SECONDS=15
RAG_API_INCLUDE_EXPIRED=false
```

目前外部 RAG API 暫不帶授權 header；若正式環境需要 token，應再新增環境變數並避免寫入 repo。

## Gemini OCR

圖片轉文字會使用 Gemini。

```env
GEMINI_API_KEY=正式 Gemini API key
GEMINI_IMAGE_TEXT_MODEL=gemini-2.5-pro
IMAGE_TEXT_MAX_SIZE=1024
```

必須安裝：

```text
google-genai
Pillow
```

## LINE Bot

正式 LINE webhook 入口：

```text
/api/line/top/webhook
/api/line/test_bot/webhook
/api/line/tdtv/webhook
/api/line/cltv/webhook
/api/line/pktv/webhook
```

每個 Bot 都需要自己的 token 與 secret：

```env
LINE_TOP_CHANNEL_ACCESS_TOKEN=
LINE_TOP_CHANNEL_SECRET=

LINE_TEST_BOT_CHANNEL_ACCESS_TOKEN=
LINE_TEST_BOT_CHANNEL_SECRET=

LINE_TDTV_CHANNEL_ACCESS_TOKEN=
LINE_TDTV_CHANNEL_SECRET=

LINE_CLTV_CHANNEL_ACCESS_TOKEN=
LINE_CLTV_CHANNEL_SECRET=

LINE_PKTV_CHANNEL_ACCESS_TOKEN=
LINE_PKTV_CHANNEL_SECRET=
```

Bot 對應：

```text
top      -> 台數科 / 共用入口，不預設系統台
test_bot -> 測試 Bot / 共用入口，不預設系統台
tdtv     -> 大屯，預設 company_code=tdtv
cltv     -> 佳聯，預設 company_code=cltv
pktv     -> 北港，預設 company_code=pktv
```

## LINE 真人客服模式

真人模式逾時秒數：

```env
LINE_HUMAN_MODE_TIMEOUT_SECONDS=1200
```

每個 Bot 可設定真人客服群組通知：

```env
LINE_TOP_HUMAN_GROUP_ID=
LINE_TOP_HUMAN_ACCESS_TOKEN=

LINE_TEST_BOT_HUMAN_GROUP_ID=
LINE_TEST_BOT_HUMAN_ACCESS_TOKEN=

LINE_TDTV_HUMAN_GROUP_ID=
LINE_TDTV_HUMAN_ACCESS_TOKEN=

LINE_CLTV_HUMAN_GROUP_ID=
LINE_CLTV_HUMAN_ACCESS_TOKEN=

LINE_PKTV_HUMAN_GROUP_ID=
LINE_PKTV_HUMAN_ACCESS_TOKEN=
```

若未設定 `LINE_{BOT_CODE}_HUMAN_ACCESS_TOKEN`，系統會使用該 Bot 的 `LINE_{BOT_CODE}_CHANNEL_ACCESS_TOKEN` 推送通知。

真人模式只存在 LINE session 的 `channel_context`，不影響 WEB。

## 客戶服務 API

正式上線時若要連正式帳務/服務 API，請關閉 mock：

```env
CUST_API_USE_MOCK=false
CUST_API_TIMEOUT=30
```

正式 endpoint：

```env
CUST_API_TOKEN_URL=
CUST_API_SEARCH_BILL_URL=
CUST_API_INTERNET_RETURN_URL=
CUST_API_TV_RETURN_URL=
CUST_API_SEND_MESSAGE_URL=
CUST_API_CONTRACT_INFO_URL=
CUST_API_PAYMENT_BARCODE_URL=
CUST_API_PROMOTION_QUERY_URL=
CUST_API_CHANNEL_QUERY_URL=
CUST_API_SERVICE_AVAILABILITY_URL=
CUST_API_NEW_INSTALL_URL=
CUST_API_ADDON_PLAN_URL=
CUST_API_CANCEL_REPAIR_URL=
```

合約與服務內容查詢使用 `CUST_API_CONTRACT_INFO_URL`，一樣先取 token，再用戶名+電話或客戶編號查詢。系統會略過基本頻道與數位電視頻道，避免把不需綁約服務的舊日期或空日期回覆給用戶；網路速率會整理成 Mbps 顯示。

超商繳費收據復線使用 `CUST_API_PAYMENT_BARCODE_URL`，一樣先取 token，再用收據第一段、第二段、第三段條碼確認繳費並進行復線處理。

如果某些 API 尚未正式提供，請保留 `CUST_API_USE_MOCK=true` 或只開啟已確認安全的 endpoint。

## 資料庫與儲存

目前本機/LINE 對話紀錄、memory、customer profile 與 feedback 使用本機 SQLite：

```text
data/customer_state.db
```

正式上線前需要決定：

- 短期是否仍使用 SQLite。
- 若使用容器或雲端部署，`data/` 是否有持久化 volume。
- 若改 MongoDB，需設定連線與 Web / LINE collection 名稱。

目前 repository 抽象層已存在，MongoDB 寫入已支援 Web / LINE 分 collection：

```env
STATE_REPOSITORY_BACKEND=mongodb
MONGODB_URI=mongodb://<mongodb-username>:<url-encoded-password>@<正式-mongodb-host>:27017/?authSource=admin
MONGODB_DATABASE=aicust_service
MONGODB_WEB_COLLECTION=web_conversations
MONGODB_LINE_COLLECTION=line_conversations
```

注意：`tickets` 本機資料表已移除，報修流程目前停用，不會建立本機工單。

## 服務啟動

後端：

```powershell
conda activate cust_app
uvicorn app.app_backend:app --host 127.0.0.1 --port 8123
```

WEB 測試 UI：

```powershell
streamlit run app/web_ui.py --server.address 127.0.0.1 --server.port 8443 --server.baseUrlPath assistant --server.enableCORS false --server.enableXsrfProtection false
```

`--server.port 8443` 決定 Streamlit 內部 port；`--server.baseUrlPath assistant` 會讓 Streamlit 掛在 `/assistant`。目前正式環境由 Apache 對外 `:8501` 轉到內部 `127.0.0.1:8443`，對外網址例如 `https://<正式網域>:8501/assistant`。若正式環境透過反向代理轉發到不同外部 port，保留 `--server.enableCORS false --server.enableXsrfProtection false`，避免 Streamlit 因來源檢查擋下頁面請求。

正式部署時請使用 HTTPS 網域設定 LINE webhook，不要使用 localhost。
