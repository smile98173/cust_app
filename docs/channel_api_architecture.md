# WEB / LINE Channel API Architecture

本文件整理目前專案的多通道 API 設計。目標是讓 WEB 與 LINE 有各自的前置處理入口，但最後共用同一套 AI 客服核心。

> 文件說明：本文件的 API 入口與通道責任可作為參考；「變更紀錄」保留當時的實作背景，不代表現行客服判斷規則。現行 LLM-first、知識檢索與帳務邊界以 `active_customer_service_handoff_2026-09-14.md` 為準。

## 設計原則

```text
不同來源入口
  -> 各自整理 channel context
  -> 套用 company context
  -> 共用核心 AI 問答流程
```

WEB 與 LINE 的差異應該停在「前置作業」：

- WEB：通常可以從網站、網域、前端設定或 request 直接知道系統台。
- LINE：可能需要從不同 Bot、使用者訊息、地區或歷史狀態判斷系統台。
- 核心 AI：Router、RAG、tool manager、memory 只維護一套。

## 變更紀錄

### 2026-05-28

RAG 查詢切回本地 ChromaDB，並新增知識文件維護流程。

主要變更：

- `retrieve_knowledge()` 預設使用 `RAG_BACKEND=local` 查詢 `cust_app_runtime/chroma_db`。
- 新增 `/api/kb/*` 管理 API，可上傳、列表、重建索引、刪除與搜尋知識文件。
- Web UI 新增「知識庫維護」區，可上傳內部流程文件並自動建立索引。
- 外部 RAG API 保留為 `RAG_BACKEND=api` 或 `RAG_BACKEND=hybrid` 選項。
- RAG 知識庫分類可選「通用」或各系統台名稱；文件主題分類由匯入時自動判斷，客服查詢不使用主題分類過濾，避免漏查。

### 2026-05-26

本次更新曾將 RAG 查詢改為外部 API，並將 Ollama fallback 定位為遠端備援服務；2026-05-28 已因內部知識流程需求切回本地 ChromaDB。

主要變更：

- `retrieve_knowledge()` 不再載入本地 Chroma / embedding model，改為呼叫 `RAG_API_URL`。
- RAG API request 使用 `plan_name`、`knowledge_base`、`limit`、`include_expired`。
- 目前 RAG 只建立「大屯」知識庫，因此 `knowledge_base` 先固定送 `大屯`；其他系統台或共用知識庫建立後，再調整為動態對應。
- RAG API response 的 `sources` 會轉成核心客服既有 doc 格式，供 `compose_knowledge_reply()` 與 `last_knowledge_results` 使用。
- `OLLAMA_BASE_URL` 正式環境應指向遠端 Ollama，例如 `http://<remote-host>:11434`。
- `requirements.txt` 已註解本地 Chroma/BGE RAG 套件與目前未使用的 LangGraph 套件。
- 優惠、促銷、推薦方案、優惠套餐等資訊查詢暫停走 RAG，改回覆公司資訊維護中的 `優惠活動` 欄位。（此為 2026-05-26 的歷史設計，已由 2026-09-16 的 LLM-first 動態檢索流程取代。）
- 超商繳費收據圖片 OCR 出第一段、第二段、第三段條碼後，可走 `payment_bill_batch` 確認繳費並處理欠費停用後復線。
- RAG 命中內容會再由 LLM 整理成簡短重點，避免直接輸出整段內部文件；LLM 摘要失敗時才退回原文。

### 2026-05-25

本次更新將目前系統調整為「正式 Web API 簡化串接，Web / LINE 狀態由本系統保存，本機測試環境可用 SQLite，正式環境可切 MongoDB，報修不再保留本機 tickets 資料」。

主要變更：

- 正式 Web server 串接入口 `POST /api/v1/chat` 改為簡化格式：接收 `user_id`、`company_code`、`msg`，回傳 `msg`。
- Web 對話紀錄與 `ai_state` 改由本系統 repository 保存，不再要求外部 Web server 帶回 `history` / `ai_state`。
- 新增 Repository 儲存層：
  - `CustomerStateRepository`
  - `SQLiteCustomerStateRepository`
  - `MongoCustomerStateRepository`
- 新增設定 `STATE_REPOSITORY_BACKEND=sqlite`，目前測試/本機環境使用 SQLite。
- MongoDB 可用 `STATE_REPOSITORY_BACKEND=mongodb` 切換，Web / LINE 分開寫入 `aicust_service.web_conversations` 與 `aicust_service.line_conversations`。
- `memory_service` 改由 repository 存取 `sessions`、`chat_logs`、`customer_profiles`。
- LINE 跨 Bot 共用公司資訊改走 `customer_profiles` repository，不再直接在 channel context 操作 SQLite。
- 移除本機 `tickets` 資料表與 `/tickets/{user_id}` API。
- 測試 UI 移除工單狀態與歷史工單顯示。
- `init_db()` 會清掉舊的 `tickets` table，避免測試資料殘留。
- `repair_ticket_id` 欄位辨識保留，因未來取消報修或報修查詢若改走外部 API，仍可能需要使用者提供報修單號。

目前定位：

```text
Web 正式串接
  -> 外部 Web server 傳 user_id、company_code、msg
  -> 本系統 /api/v1/chat 保存 ai_state/chat_logs 並回傳 msg

LINE / 本機測試入口
  -> 本機 SQLite repository 保存 session、chat logs、customer_profiles
  -> 不保存 tickets

報修流程
  -> 目前停用
  -> Web 告知使用者改洽真人客服
  -> LINE 轉真人客服模式
  -> 不建立本機工單
```

## API 入口

### WEB

```text
POST /api/web/chat
```

用途：官網或其他 WEB 系統呼叫。

Request 範例：

```json
{
  "user_id": "web-session-id",
  "user_input": "家裡網路不能用",
  "tv_cable": "tdtv",
  "metadata": {
    "source": "official_site"
  }
}
```

後端處理：

```text
/api/web/chat
  -> user_id 正規化為 web:{user_id}
  -> 用 request.tv_cable 套用系統台
  -> 寫入 channel_context
  -> run_core_chat()
  -> handle_chat_message()
```

### WEB Server 正式串接

```text
POST /api/v1/chat
```

用途：提供外部 Web server 串接。此端點會自行讀寫後端 `sessions` / `chat_logs`，外部 Web server 不需要保存或回傳 `ai_state` / `history`。

最小 Request：

```json
{
  "user_id": "member_123456",
  "is_logged_in": true,
  "company_code": "tdtv",
  "msg": "我想知道HBO在哪個頻道"
}
```

訪客可由 Web server 提供暫時 session id：

```json
{
  "user_id": "guest_000001",
  "is_logged_in": false,
  "company_code": "tdtv",
  "msg": "網路不能用"
}
```

Response：

```json
{
  "status": "success",
  "user_id": "web:member_123456",
  "msg": "已查詢到「HBO」相關頻道：\nHBO：第 65 台\nHBO HD：第 220 台",
  "actions": []
}
```

本系統會保存：

```text
user_id = web:{外部 user_id}
is_logged_in
known_info.member_id = member_id 或 user_id
known_info.custnum = custnum（僅明確傳入 CUST_API 客戶編號時）
ai_state / memory
chat_logs
company_code
updated_at
```

登入會員若帶 `is_logged_in=true`，後端會保存會員識別到 `member_id`，但不會自動當成 CUST_API 的 `custNo`。需要客戶身分的 CUST_API，例如帳單查詢、補發簡訊帳單、網路/電視復機、合約與服務內容查詢，只有在 Web 端明確傳入 `custnum` 或 `metadata.custnum` 時才會用客戶編號查詢；沒有 `custnum` 時會追問戶名與聯絡電話。下一輪呼叫時，外部仍只需帶相同 `user_id`、`company_code` 與新的 `msg`，會員情境建議持續帶 `is_logged_in=true`。

### LINE

```text
POST /api/line/{bot_code}/webhook
```

後端處理：

```text
/api/line/{bot_code}/webhook
  -> 依 bot_code 取得 LINE token / secret / 預設系統台
  -> 驗證 X-Line-Signature
  -> 解析 LINE event
  -> user_id 正規化為 line:{bot_code}:{line_user_id}
  -> 判斷或套用系統台
  -> run_core_chat()
  -> handle_chat_message()
  -> 用 LINE reply API 回覆
```

目前 LINE 文字訊息已接入共用核心。圖片訊息會下載 LINE image content，呼叫共用 OCR service，並把辨識結果送入同一套客服問答流程。

## 多 LINE Bot 啟用方式

目前支援同一套程式用不同 webhook URL 啟用多個 LINE Bot。

```text
/api/line/top/webhook   -> 台數科 / 共用入口，不預設系統台
/api/line/test_bot/webhook -> 測試 Bot / 共用入口，不預設系統台
/api/line/tdtv/webhook  -> 大屯，預設 company_code=tdtv
/api/line/cltv/webhook  -> 佳聯，預設 company_code=cltv
/api/line/pktv/webhook  -> 北港，預設 company_code=pktv
```

LINE Developers 後台分別設定：

```text
https://你的網域/api/line/tdtv/webhook
https://你的網域/api/line/cltv/webhook
https://你的網域/api/line/pktv/webhook
https://你的網域/api/line/test_bot/webhook
```

這取代舊版單檔程式中的：

```python
tv_num = 0
tv_dict = [["台數科", ""], ["大屯", "大屯"], ["佳聯", "佳聯"], ["北港", "北港"]]
```

新版不用改程式切 `tv_num`，而是由 URL path 的 `bot_code` 決定 Bot 設定與預設系統台。

## LINE 環境變數

多 Bot token 與 secret 建議全部放環境變數，不要寫死在程式裡。

```env
LINE_TDTV_CHANNEL_ACCESS_TOKEN=大屯_bot_token
LINE_TDTV_CHANNEL_SECRET=大屯_bot_secret

LINE_CLTV_CHANNEL_ACCESS_TOKEN=佳聯_bot_token
LINE_CLTV_CHANNEL_SECRET=佳聯_bot_secret

LINE_PKTV_CHANNEL_ACCESS_TOKEN=北港_bot_token
LINE_PKTV_CHANNEL_SECRET=北港_bot_secret
```

台數科入口使用：

```env
LINE_TOP_CHANNEL_ACCESS_TOKEN=台數科_bot_token
LINE_TOP_CHANNEL_SECRET=台數科_bot_secret
```

測試 Bot 入口使用：

```env
LINE_TEST_BOT_CHANNEL_ACCESS_TOKEN=test_bot_token
LINE_TEST_BOT_CHANNEL_SECRET=test_bot_secret
```

真人客服群組通知可針對每個 Bot 設定：

```env
LINE_TOP_HUMAN_GROUP_ID=台數科真人客服群組ID
LINE_TOP_HUMAN_ACCESS_TOKEN=台數科真人通知token

LINE_TEST_BOT_HUMAN_GROUP_ID=測試Bot真人客服群組ID
LINE_TEST_BOT_HUMAN_ACCESS_TOKEN=測試Bot真人通知token

LINE_TDTV_HUMAN_GROUP_ID=大屯真人客服群組ID
LINE_TDTV_HUMAN_ACCESS_TOKEN=大屯真人通知token

LINE_CLTV_HUMAN_GROUP_ID=佳聯真人客服群組ID
LINE_CLTV_HUMAN_ACCESS_TOKEN=佳聯真人通知token

LINE_PKTV_HUMAN_GROUP_ID=北港真人客服群組ID
LINE_PKTV_HUMAN_ACCESS_TOKEN=北港真人通知token
```

若未設定 `LINE_{BOT_CODE}_HUMAN_ACCESS_TOKEN`，會改用該 Bot 的 `LINE_{BOT_CODE}_CHANNEL_ACCESS_TOKEN` 發送通知。

真人模式逾時設定：

```env
LINE_HUMAN_MODE_TIMEOUT_SECONDS=1200
```

相關設定集中在：

```text
app/config/settings.py
```

LINE 前置處理集中在：

```text
app/services/channel_context.py
```

## Company Context

系統台資料集中在：

```text
app/services/company_profile.py
```

目前常用代碼：

```text
tdtv  -> 大屯有線
cltv  -> 佳聯有線
pktv  -> 北港有線
cnt   -> 中投有線
wctv  -> 西海岸
toplight -> 佳光市區
hya   -> 新永安
tycable -> 大揚
tinp  -> 台基科
```

WEB 測試入口 `/api/web/chat` 會使用 request 的 `tv_cable`。正式 Web server 串接入口 `/api/v1/chat` 會使用 request 的 `company.company_code`，且不在本機保存 session / chat logs。

LINE 入口會依序判斷：

1. 使用者本輪文字是否明確包含系統台名稱或服務地區。
2. `customer_profiles` 是否已有同一 LINE 使用者最近確認的系統台。
3. memory 中是否已確認系統台。
4. Bot 本身是否有預設系統台，例如 `/api/line/cltv/webhook`。
5. 若仍無法判斷，先請使用者提供居住行政區、服務地區或附近地標，不進核心 AI。

共用入口不應優先詢問「哪一個系統台」，因為一般使用者通常更知道自己的所在地區。後端會用行政區或地區關鍵字對應內部系統台，例如「沙鹿區」會對應西海岸服務範圍，「西屯區」會對應佳光市區服務範圍。

## 資料儲存

目前專案已儲存使用者狀態與對話紀錄，資料庫是本機 SQLite。

資料庫位置：

```text
data/customer_state.db
```

儲存層已改為 Repository 架構：

```text
聊天與 channel 流程
  -> memory_service 公開函式
      -> CustomerStateRepository
          -> SQLiteCustomerStateRepository     # 目前本機/測試環境
          -> MongoCustomerStateRepository      # Web / LINE 分 collection MongoDB 儲存
```

目前設定：

```text
STATE_REPOSITORY_BACKEND=sqlite
```

SQLite 會用 document-style 的 repository 方法模擬未來 MongoDB collection，例如：

```text
get_session_document(user_id)
save_session_document(user_id, memory, customer_key)
append_chat_log(user_id, role, message, customer_key)
get_customer_profile(customer_key)
save_customer_profile(profile)
```

也就是上層流程只認得「文件型資料」與 repository 方法，不直接依賴 SQLite 查詢語法。正式 Web / LINE 若要由本系統保存狀態，可使用 `MongoCustomerStateRepository`，把 Web session `ai_state` 與 `chat_logs` 寫入 `aicust_service.web_conversations`，LINE session 與跨 Bot profile 寫入 `aicust_service.line_conversations`。

主要表格：

```text
sessions
  - user_id
  - customer_key
  - memory_json
  - updated_at

chat_logs
  - user_id
  - customer_key
  - role
  - message
  - created_at

customer_profiles
  - customer_key
  - last_company_code
  - last_company
  - last_area
  - last_user_id
  - last_line_bot_code
  - resolution_source
  - updated_at

feedback_records
  - 測試回饋資料
```

WEB user id 會正規化為：

```text
web:{user_id}
```

LINE user id 會正規化為：

```text
line:{bot_code}:{line_user_id}
```

例如：

```text
line:tdtv:Uxxxxxxxx
line:cltv:Uxxxxxxxx
line:pktv:Uxxxxxxxx
```

LINE 另有跨 Bot 共用身份鍵：

```text
line:{line_user_id}
```

這個值會存在 `customer_key`，用來讓同一個 LINE 使用者在不同 Bot 入口間同步「已確認的系統台」。例如同一個 `Uxxxxxxxx` 先在大屯 Bot 確認為大屯用戶，之後進 TOP Bot 或其他 Bot 時，若沒有明確改口，會優先套用大屯資訊；但各 Bot 的 `sessions` 與 `chat_logs` 仍以 `line:{bot_code}:{line_user_id}` 分開保存，不會互相覆蓋。

## 真人客服轉接

真人客服轉接由共用 AI Router 判斷意圖，不再由 LINE 前置流程用固定關鍵字直接觸發。使用者若已說明具體服務問題後仍要求真人處理，或系統已判定該事項需真人處理，Router 才會輸出：

```text
intent = human_handoff_request
route = direct_reply
```

單純提到「真人客服」不一定代表轉接。例如使用者詢問客服電話、營業時間或如何聯絡客服時，仍應依公司資訊或知識問題處理。

使用者只說「轉真人」、「找真人客服」、「不想跟 AI 講」或只是試探是否有真人，例如「有沒有真人」、「有真人嗎」、「真人在嗎」、「真人客服」時，系統都先請使用者說明問題：

```text
可以，請先告訴我遇到什麼問題，我會先協助確認；若仍需要真人客服，我會提供轉接方式。
```

短肯定語不會直接轉接，系統會繼續請使用者說明服務問題；回覆 `不用`、`不要`、`先不用` 則取消轉接確認。使用者提供具體服務問題後，才輸出真人客服轉接結果。

### LINE 真人客服模式

LINE 入口收到 `human_handoff_request` 後，會啟動真人客服模式。真人模式只存放在 LINE channel session，不影響 WEB。

處理流程：

```text
LINE 使用者訊息
  -> run_core_chat()
  -> AI Router 判斷 intent = human_handoff_request
  -> memory.channel_context.human_mode = true
  -> 回覆使用者「已轉換為真人客服模式。」
  -> 推送最近對話與最新訊息到真人客服群組

human_mode = true 期間
  -> 使用者後續訊息不進核心 AI
  -> 後續訊息轉發到真人客服群組
  -> 每次訊息會延長真人模式逾時時間

超過 LINE_HUMAN_MODE_TIMEOUT_SECONDS 後再次收到訊息
  -> 自動關閉 human_mode
  -> 該訊息恢復走 AI 流程
```

### WEB 真人客服轉接

WEB 不會自行切換真人模式。Router 判定 `human_handoff_request` 時，回覆真人文字客服連結，並在 response `actions` 帶出 `human_handoff`，讓 Web 同事或前端流程接手：

```text
此項需由真人文字客服協助處理。
請按 <a href="http://pweb.topmso.com.tw:96/smartCustomerService/real/{流水號或客編}/0/{系統代號}?token={Base64URL token}">轉真人文字客服</a>
或者繼續提問
```

```json
{
  "type": "human_handoff",
  "reason": "user_requested"
}
```

Token 原文為 `{流水號或客編}+{Unix timestamp}`，使用雙方約定的 key 執行 `AES-128-ECB` 與 PKCS7 padding，再轉成 Base64URL。真人客服系統解密後依 timestamp 判斷是否逾時。

系統代號：北港 `P`、台灣佳光 `W`、佳聯 `L`、大屯 `T`、中投 `N`、台灣佳光（跨區）`A`、新永安 `J`、大揚 `K`、台基科 `Y`。

真人模式儲存在：

```text
memory["channel_context"]["human_mode"]
memory["channel_context"]["human_mode_started_at"]
memory["channel_context"]["human_mode_last_activity_at"]
memory["channel_context"]["human_mode_until"]
```

WEB 入口不會讀取或處理這些 LINE-only 欄位，因此 LINE 真人模式不會影響 WEB 對話。

未來若要改用 MongoDB，建議新增 repository 抽象層：

```text
app/repositories/conversation_repository.py
app/repositories/sqlite_conversation_repository.py
app/repositories/mongo_conversation_repository.py
```

核心服務只呼叫 repository，不直接依賴 MongoDB 或 SQLite。

## OCR 下一步

圖片轉文字應該獨立成共用 service：

```text
app/services/image_text_service.py
app/services/image_normalizer.py
```

目前已建立：

```text
app/services/image_text_service.py
```

並提供 API：

```text
POST /api/ocr/image
```

Request 範例：

```json
{
  "image_base64": "base64-encoded-image",
  "mime_type": "image/png",
  "source": "web"
}
```

Response 範例：

```json
{
  "status": "success",
  "source": "web",
  "text": "辨識出的文字",
  "model": "gemini-2.5-pro",
  "mime_type": "image/png",
  "width": 1024,
  "height": 768
}
```

需要設定：

```env
GEMINI_API_KEY=你的 Gemini API key
GEMINI_IMAGE_TEXT_MODEL=gemini-2.5-pro
IMAGE_TEXT_MAX_SIZE=1024
```

LINE 與 WEB 分別只負責取得圖片：

```text
LINE
  -> message_id
  -> LINE API 下載 image bytes
  -> image_text_service.extract_text()
  -> OCR 結果送入核心客服流程

WEB
  -> base64
  -> image_text_service.extract_text()
  -> 回傳文字或接續問答
```

Gemini、OpenAI Vision 或其他 OCR provider 不應直接散落在 API endpoint 裡，應該包在 provider 介面後面。

## 驗證方式

目前可用以下指令驗證主要流程：

```powershell
python -m py_compile app\services\state_repository.py app\services\memory_service.py app\services\ticket_service.py app\services\controller_service.py app\app_backend.py app\handlers\chat_handler.py app\web_ui.py
python -m pytest tests\test_memory_schema.py tests\test_state_repository.py tests\test_channel_context.py tests\test_external_chat_schema.py tests\test_tool_manager.py tests\test_router_architecture.py tests\test_customer_validation.py tests\test_repair_flow_disabled.py -q
```

目前驗證結果：

```text
95 passed
```

驗證範圍包含：

- SQLite repository 模擬 MongoDB-style document 存取。
- LINE 跨 Bot `customer_profiles` 同步。
- `/api/v1/chat` request schema。
- HBO 頻道 mock 查詢。
- 停用報修流程。
- 移除 legacy `tickets` table。
