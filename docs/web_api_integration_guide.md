# Web API 串接說明

正式 Web API 已改為由本系統保存對話紀錄與 `ai_state`。外部 Web server 只需要提供使用者識別、系統台與使用者訊息。

## API URL

Token API：

```text
POST https://<正式網域>:8000/api/auth/token
```

Request：

```json
{
  "name": "<API_AUTH_NAME>",
  "password": "<API_AUTH_PASSWORD>"
}
```

Response：

```json
{
  "status": "success",
  "token_type": "Bearer",
  "access_token": "<access_token>",
  "expires_at": 1790000000,
  "expires_in": 86400,
  "header_name": "X-API-Token"
}
```

取得 `access_token` 後，再呼叫聊天或 OCR API。

測試環境：

```text
POST http://127.0.0.1:8123/api/v1/chat
```

正式環境：

```text
POST https://<正式網域>:8000/api/v1/chat
```

Header：

```text
Content-Type: application/json
X-API-Token: <access_token>
```

也可改用：

```text
Authorization: Bearer <access_token>
```

LINE webhook `/api/line/{bot_code}/webhook` 不使用這個 token，仍使用 LINE signature 驗證。

## Request 欄位

| 欄位 | 必填 | 說明 |
| --- | --- | --- |
| `user_id` | 是 | 會員識別或訪客流水號。後端會正規化為 `web:{user_id}`。登入會員且未另傳 `custnum` 時，系統會沿用會員識別作為 CUST_API 客戶編號。 |
| `is_logged_in` | 是 | 是否為登入會員。會員帶 `true`，訪客帶 `false`。 |
| `company_code` | 是 | 系統台代碼，例如 `tdtv`。 |
| `msg` | 是 | 使用者本輪輸入文字。 |
| `request_id` | 否 | 呼叫方的請求識別碼，方便查 log。 |
| `custnum` | 否 | CUST_API 使用的客戶編號。只有確定此值就是 CUST_API `custNo` 時才傳；也相容 `custNo`、`cust_no`、`customerNo`、`customer_number`。 |
| `metadata` | 否 | 頁面或來源資訊，非必要；也可用 `metadata.custnum`、`metadata.custNo` 等客編欄位傳 CUST_API 客戶編號。 |

相容欄位：

- 舊格式的 `user.user_id`、`user.member_id`、`company.company_code`、`message.text` 仍可解析。
- 舊格式的 `ai_state`、`history` 會被忽略，因為現在由本系統資料庫保存。

## 第一次輸入

會員範例：

```json
{
  "request_id": "req_001",
  "user_id": "member_123456",
  "is_logged_in": true,
  "company_code": "tdtv",
  "custnum": "A000001",
  "msg": "優惠套餐有哪些?",
  "metadata": {
    "page": "customer-service"
  }
}
```

訪客範例：

```json
{
  "request_id": "req_guest_001",
  "user_id": "guest_000001",
  "is_logged_in": false,
  "company_code": "tdtv",
  "msg": "我想知道HBO在哪個頻道"
}
```

## 第一次輸出

```json
{
  "status": "success",
  "request_id": "req_001",
  "user_id": "web:member_123456",
  "msg": "目前查到的優惠重點如下：\n1. ...\n2. ...",
  "links": [],
  "actions": []
}
```

## 第二次輸入

第二輪不需要帶回 `ai_state` 或 `history`，只要使用同一個 `user_id`。

```json
{
  "request_id": "req_002",
  "user_id": "member_123456",
  "is_logged_in": true,
  "company_code": "tdtv",
  "msg": "那100M的月租是多少?"
}
```

## 第二次輸出

```json
{
  "status": "success",
  "request_id": "req_002",
  "user_id": "web:member_123456",
  "msg": "100M 相關方案目前查到的重點如下：\n1. ...\n2. ...",
  "links": [],
  "actions": []
}
```

## 後端儲存

本系統會自行保存：

```text
user_id = web:{外部傳入 user_id}
is_logged_in
known_info.member_id = member_id 或 user_id（登入會員）
known_info.custnum = custnum；若未傳 custnum，登入會員會沿用 member_id / user_id
ai_state / memory
chat_logs
company_code
updated_at
```

登入會員若 `is_logged_in = true`，後端會保存會員識別到 `member_id`，並在未另傳 `custnum` 時沿用它作為 CUST_API 的 `custNo`。若 Web 端會員識別不等於 CUST_API 客戶編號，請明確傳入正確 `custnum`，或不要讓會員識別走客編查詢流程。

SQLite 測試環境會寫入：

```text
sessions
chat_logs
```

MongoDB 正式環境會寫入：

```text
aicust_service.web_conversations
```

## 網址顯示

如果回覆內容包含公司網址、維修申告、裝機申告或 LINE TV 客服中心等網址，後端會直接在 `msg` 內放入 HTML `<a>` 標籤。Web 前端顯示 AI 回覆時，請將 `msg` 當 HTML 片段渲染，連結就會直接可點。

範例：

```json
{
  "status": "success",
  "request_id": "req_003",
  "user_id": "web:member_123456",
  "msg": "大屯有線公司網址：\n<a href=\"https://www.tdtv.com.tw/\" target=\"_blank\" rel=\"noopener noreferrer\">官網</a>",
  "links": [
    {
      "label": "官網",
      "url": "https://www.tdtv.com.tw/"
    }
  ],
  "actions": []
}
```

`links` 欄位仍會保留作為相容資料；若前端不想額外處理 `links`，只渲染 `msg` 即可。

## actions 欄位

`actions` 用來通知 Web server 是否需要顯示或切換真人客服。

```json
[
  {
    "type": "human_handoff",
    "reason": "service_disabled",
    "tool_name": "apply_new_install"
  }
]
```

常見情境：

- `reason = "service_disabled"`：此功能目前暫停，Web 端可顯示「請洽真人客服」。
- `reason = "user_requested"`：使用者明確要求真人客服。

### 使用者要求真人客服

真人客服轉接由 AI Router 判斷意圖，不再單純依固定關鍵字觸發。當使用者明確表示要真人接手、人工客服、專人協助、不想再由 AI 回覆，或在服務處理中要求轉真人時，API 會回真人文字客服連結：

```json
{
  "status": "success",
  "request_id": "req_handoff_001",
  "user_id": "web:member_123456",
  "msg": "此項需由真人文字客服協助處理。<br>請按 <a href=\"http://pweb.topmso.com.tw:96/smartCustomerService/real/member_123456/0/T?token={Base64URL token}\">轉真人文字客服</a><br>或者繼續提問",
  "links": [],
  "actions": [
    {
      "type": "human_handoff",
      "reason": "user_requested"
    }
  ]
}
```

Web 端建議優先判斷 `actions[].type == "human_handoff"`；若既有前端暫時只能抓文字，可先抓 `msg` 是否包含 `轉真人文字客服`。單純詢問客服電話、營業時間或聯絡方式時，AI 不應輸出此轉接 action，會依公司資訊正常回答。

轉真人文字客服對外 URL 格式：

```text
http://pweb.topmso.com.tw:96/smartCustomerService/real/{流水號或客編}/0/{系統代號}?token={Base64URL token}
```

Token 原文為 `{流水號或客編}+{Unix timestamp}`，使用雙方約定的 key 執行 `AES-128-ECB` 與 PKCS7 padding，再將加密結果轉成不含 padding `=` 的 Base64URL。真人客服系統解密後，可依 timestamp 判斷連結是否逾時。

`{流水號或客編}` 會優先使用 `custnum`，若沒有 custnum，則使用 `member_id`、`external_user_id` 或 `user_id`。系統代號對照：

| company_code | 系統台 | 系統代號 |
| --- | --- | --- |
| `pktv` | 北港 | `P` |
| `wctv` | 台灣佳光 | `W` |
| `cltv` | 佳聯 | `L` |
| `tdtv` | 大屯 | `T` |
| `cnt` | 中投 | `N` |
| `toplight` | 台灣佳光（跨區） | `A` |
| `hya` | 新永安 | `J` |
| `tycable` | 大揚 | `K` |
| `tinp` | 台基科 | `Y` |

若使用者只是試探是否有真人，例如「有沒有真人」、「有真人嗎」、「真人客服」，API 會先請使用者說明問題，不會立刻帶 `human_handoff` action：

```json
{
  "status": "success",
  "request_id": "req_handoff_confirm_001",
  "user_id": "web:member_123456",
  "msg": "請問您目前遇到什麼問題？我會先協助您處理；若確認無法在線上協助，再幫您轉接真人客服。",
  "links": [],
  "actions": []
}
```

使用者下一輪回覆 `是`、`好`、`OK`、`可以` 等短肯定語時，才會回傳真人文字客服連結與 `human_handoff` action。

## OCR API

圖片辨識是獨立 API，適合 Web 端上傳截圖、帳單、超商繳費收據或其他圖片。此 API 只回傳辨識文字，不會自動寫入對話狀態；若要讓 AI 客服接續處理圖片內容，請把 OCR 結果再送一輪 `/api/v1/chat`。

Endpoint：

```text
POST https://<正式網域>:8000/api/ocr/image
```

Header：

```text
Content-Type: application/json
X-API-Token: <access_token>
```

Request：

```json
{
  "image_base64": "<圖片檔案 base64，不含 data:image/... 前綴>",
  "mime_type": "image/jpeg",
  "source": "web",
  "prompt": null
}
```

欄位：

| 欄位 | 必填 | 說明 |
| --- | --- | --- |
| `image_base64` | 是 | 圖片 bytes 轉 base64。不要包含 `data:image/...;base64,`。 |
| `mime_type` | 建議 | 例如 `image/jpeg`、`image/png`、`image/webp`。 |
| `source` | 否 | 呼叫來源，建議填 `web`。 |
| `prompt` | 否 | 自訂辨識提示。省略或 `null` 時使用後端預設提示。 |

Response：

```json
{
  "status": "success",
  "source": "web",
  "text": "代收項目: ...\n第一段條碼: ...\n第二段條碼: ...\n第三段條碼: ...",
  "model": "gemini-...",
  "mime_type": "image/jpeg",
  "width": 1280,
  "height": 720,
  "ocr_time_sec": 3.482
}
```

`ocr_time_sec` 是後端圖片辨識實際耗時秒數。如果圖片是超商收據或繳費單，預設提示會盡量整理出第一段、第二段、第三段條碼；一般圖片則回傳圖片描述與可辨識文字。

OCR 後接續 AI 對話範例：

```json
{
  "request_id": "req_ocr_001",
  "user_id": "member_123456",
  "is_logged_in": true,
  "company_code": "tdtv",
  "msg": "我上傳了一張圖片，辨識內容如下：\n代收項目: ...\n第一段條碼: ...\n第二段條碼: ...\n第三段條碼: ..."
}
```

錯誤處理：

- HTTP 400：base64 格式錯誤、圖片格式無法辨識、OCR 金鑰未設定或圖片分析失敗。
- HTTP 5xx 或 timeout：顯示通用錯誤並記錄 request 內容；OCR timeout 建議設 60 秒。

## 與 web_ui.py 的差異

`app/web_ui.py` 是本地測試 UI，仍會在畫面上保存 `chat_history` 方便顯示。

正式 Web server 不需要保存 AI 狀態，只需要：

1. 決定會員或訪客 `user_id`。
2. 登入會員帶 `is_logged_in = true`，並讓 `user_id` 使用穩定會員識別。
3. 帶入 `company_code`。
4. 把使用者輸入放在 `msg`。
5. 呼叫 `POST /api/v1/chat`。
6. 顯示 response 的 `msg`。

PHP 範例可看 `docs/web_api_php_example.php`。
