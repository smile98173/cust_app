# Web 端 AI 客服串接手冊

這份文件給 Web 同事串接正式 AI 客服 API 使用。Web 端只需要送出「使用者是誰、所屬系統台、這輪訊息」，AI 對話狀態與歷史紀錄由 AI 客服系統保存。

## 正式網址與 port

Web 同事只需要串 Apache 對外公開的網址，不要直接連 Python 服務內部 port。

目前部署分工：

| 用途 | Web 同事使用 | Apache 轉發到 | 說明 |
| --- | --- | --- | --- |
| AI 客服 API | `https://aiia.topmso.com.tw:8000/api/...` | `http://127.0.0.1:8123` | FastAPI 後端，Web 正式串接使用這個。 |
| Streamlit 測試介面 | `https://aiia.topmso.com.tw:8501/assistant` | `http://127.0.0.1:8443/assistant` | 內部測試/管理介面，不是正式 Web 串接 API。 |

本文件的正式 API 範例一律使用：

```text
https://aiia.topmso.com.tw:8000
```

不要讓 Web 同事串 `127.0.0.1:8123` 或 `127.0.0.1:8443`，那是部署主機內部服務 port。

## 串接方式

建議由 Web server 後端呼叫 AI 客服 API，不建議讓使用者瀏覽器直接呼叫。

```text
使用者瀏覽器
  -> Web server
  -> POST https://aiia.topmso.com.tw:8000/api/v1/chat
  -> AI 客服系統
  -> Web server 顯示 response.msg
```

串接流程：

```text
1. Web server 呼叫 /api/auth/token 取得 access_token
2. Web server 呼叫 /api/v1/chat 或 /api/ocr/image
3. 每次正式 API request 都帶 X-API-Token
4. Web 前端只顯示 API 回傳的 msg，不直接接觸 token
```

先取得 token：

```http
POST https://aiia.topmso.com.tw:8000/api/auth/token
Content-Type: application/json
```

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

正式 API：

```http
POST https://aiia.topmso.com.tw:8000/api/v1/chat
Content-Type: application/json
X-API-Token: <access_token>
```

開發機本機測試：

```http
POST http://127.0.0.1:8123/api/v1/chat
Content-Type: application/json
X-API-Token: <access_token>
```

也支援 `Authorization: Bearer <access_token>`。LINE webhook 不使用這個 token，仍由 LINE signature 驗證。

## 最小 Request

```json
{
  "request_id": "web_20260529_0001",
  "user_id": "member_123456",
  "is_logged_in": true,
  "company_code": "tdtv",
  "msg": "我想查詢帳單",
  "metadata": {
    "custnum": "A000001"
  }
}
```

欄位說明：

| 欄位 | 必填 | 說明 |
| --- | --- | --- |
| `request_id` | 否 | Web 端產生的請求 ID，方便查 log。 |
| `user_id` | 是 | 登入會員請放會員編號；訪客請放 Web 端產生的訪客 ID。 |
| `is_logged_in` | 建議 | 登入會員 `true`，訪客 `false`。 |
| `company_code` | 是 | 系統台代碼，例如 `tdtv`。 |
| `msg` | 是 | 使用者本輪輸入文字。 |
| `custnum` | 否 | CUST_API 使用的客戶編號。只有確定此值就是 CUST_API `custNo` 時才傳；也相容 `custNo`、`cust_no`、`customerNo`、`customer_number`。 |
| `metadata` | 否 | 可放頁面來源、前端版本、IP 摘要等輔助資訊；也可用 `metadata.custnum`、`metadata.custNo` 等客編欄位傳 CUST_API 客戶編號。 |

## Response

```json
{
  "status": "success",
  "request_id": "web_20260529_0001",
  "user_id": "web:member_123456",
  "msg": "請問您要查詢哪一期帳單呢？",
  "links": [],
  "actions": []
}
```

Web 端主要顯示 `msg`。

若 AI 回覆含網址，後端會直接在 `msg` 內放入 HTML `<a>` 標籤。Web 前端顯示 AI 回覆時，請將 `msg` 當 HTML 片段渲染，連結就會直接可點。

```json
{
  "status": "success",
  "request_id": "web_20260529_0003",
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

`actions` 若出現 `human_handoff`，Web 端可顯示轉真人客服、通知同事接手，或切換成真人客服流程：

```json
{
  "type": "human_handoff",
  "reason": "user_requested"
}
```

### 真人客服轉接

真人客服轉接由 AI Router 判斷意圖，不再只靠固定關鍵字。當使用者明確要求真人接手、人工客服、專人協助、不想再由 AI 回覆，或在處理過程中要求轉真人時，API 會回真人文字客服連結與 action：

```json
{
  "status": "success",
  "request_id": "web_20260626_handoff",
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

Web 端建議優先用 `actions[].type == "human_handoff"` 判斷是否轉真人；若前端暫時只能判斷文字，可抓 `msg` 中的 `轉真人文字客服`。單純問客服電話、營業時間或聯絡方式時，不應切真人，系統會照公司資訊回答。

真人文字客服對外 URL 格式：

```text
http://pweb.topmso.com.tw:96/smartCustomerService/real/{流水號或客編}/0/{系統代號}?token={Base64URL token}
```

Token 原文為 `{流水號或客編}+{Unix timestamp}`，使用雙方約定的 key 執行 `AES-128-ECB` 與 PKCS7 padding，再將加密結果轉成不含 padding `=` 的 Base64URL。真人客服系統解密後，可依 timestamp 判斷連結是否逾時。

系統代號：

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

如果使用者只是試探是否有真人，例如「有沒有真人」、「有真人嗎」、「真人客服」，AI 會先請使用者說明問題，暫時不帶 `human_handoff` action：

```json
{
  "status": "success",
  "request_id": "web_20260626_handoff_confirm",
  "user_id": "web:member_123456",
  "msg": "請問您目前遇到什麼問題？我會先協助您處理；若確認無法在線上協助，再幫您轉接真人客服。",
  "links": [],
  "actions": []
}
```

下一輪使用者回覆 `是`、`好`、`OK`、`可以` 等短肯定語時，會回真人文字客服連結與 `human_handoff` action。

## 第二輪以後

第二輪以後不用回傳 `ai_state` 或 `history`，只要使用同一個 `user_id`。

```json
{
  "request_id": "web_20260529_0002",
  "user_id": "member_123456",
  "is_logged_in": true,
  "company_code": "tdtv",
  "msg": "查五月的"
}
```

AI 客服系統會用 `web:{user_id}` 保存對話狀態與歷史紀錄。

## 圖片 OCR API

若 Web 端需要上傳截圖、帳單、超商繳費收據或其他圖片給 AI 客服辨識，請先由 Web server 後端呼叫 OCR API。辨識成功後，Web 端可選擇直接顯示 OCR 文字，或再把 OCR 文字包成一輪 `msg` 丟給 `/api/v1/chat`，讓 AI 客服接續判斷。

OCR API：

```http
POST https://aiia.topmso.com.tw:8000/api/ocr/image
Content-Type: application/json
X-API-Token: <access_token>
```

開發機本機測試：

```http
POST http://127.0.0.1:8123/api/ocr/image
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

欄位說明：

| 欄位 | 必填 | 說明 |
| --- | --- | --- |
| `image_base64` | 是 | 圖片 bytes 轉成 base64。不要加 `data:image/jpeg;base64,` 前綴。 |
| `mime_type` | 建議 | 圖片格式，例如 `image/jpeg`、`image/png`、`image/webp`。 |
| `source` | 否 | 呼叫來源，建議填 `web`，方便後端查 log。 |
| `prompt` | 否 | 自訂 OCR 指令；一般情境可傳 `null` 或省略，後端會用預設提示。 |

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

`text` 是 OCR 辨識結果，`ocr_time_sec` 是後端圖片辨識實際耗時秒數。若圖片是超商收據或繳費單，預設會盡量整理出第一段、第二段、第三段條碼。若只是一般截圖或照片，會回傳圖片內容描述與可辨識文字。

OCR 後接續聊天的建議做法：

```json
{
  "request_id": "web_ocr_20260603_0001",
  "user_id": "member_123456",
  "is_logged_in": true,
  "company_code": "tdtv",
  "msg": "我上傳了一張圖片，辨識內容如下：\n代收項目: ...\n第一段條碼: ...\n第二段條碼: ...\n第三段條碼: ..."
}
```

注意事項：

- OCR API 只負責圖片辨識，不會自行更新 AI 對話狀態。
- 要讓 AI 依圖片內容回覆，請把 OCR `text` 再送到 `/api/v1/chat`。
- OCR API timeout 建議設 60 秒。
- HTTP 400 常見原因：base64 格式錯誤、圖片格式無法辨識、OCR 金鑰未設定或圖片分析失敗。
- Web 前端不要直接暴露 OCR API 金鑰；請由 Web server 後端呼叫 AI 客服 API。

## 會員與訪客

登入會員：

```json
{
  "user_id": "會員編號",
  "is_logged_in": true
}
```

AI 系統會把會員識別保存為 `member_id`，並在未另傳 `custnum` 時沿用它作為 CUST_API 的客戶編號。若 Web 端會員識別不等於真正的 CUST_API `custNo`，請另外傳 `custnum` 或 `metadata.custnum`，避免客編查詢帶錯值。

訪客：

```json
{
  "user_id": "guest_網站自行產生的唯一值",
  "is_logged_in": false
}
```

訪客若進入需要客戶身分的流程，AI 會依流程追問必要資料。

## 系統台代碼

常用代碼：

| company_code | 系統台 |
| --- | --- |
| `toplight` | 佳光市區 |
| `wctv` | 西海岸 |
| `tdtv` | 大屯 |
| `cnt` | 中投 |
| `cltv` | 佳聯 |
| `pktv` | 北港 |
| `hya` | 新永安 |
| `tycable` | 大揚 |
| `tinp` | 台基科 |

## cURL 範例

```bash
curl -X POST "https://aiia.topmso.com.tw:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Token: <access_token>" \
  -d '{
    "request_id": "web_test_001",
    "user_id": "member_123456",
    "is_logged_in": true,
    "company_code": "tdtv",
    "msg": "我想查詢帳單"
  }'
```

## PHP 範例

完整 PHP 範例請看：

```text
docs/web_api_php_example.php
```

核心呼叫方式：

```php
$apiBaseUrl = 'https://aiia.topmso.com.tw:8000';
$apiAuthName = getenv('API_AUTH_NAME');
$apiAuthPassword = getenv('API_AUTH_PASSWORD');

$tokenPayload = [
    'name' => $apiAuthName,
    'password' => $apiAuthPassword,
];

$tokenCh = curl_init($apiBaseUrl . '/api/auth/token');
curl_setopt_array($tokenCh, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
    CURLOPT_POSTFIELDS => json_encode($tokenPayload, JSON_UNESCAPED_UNICODE),
    CURLOPT_TIMEOUT => 20,
]);
$tokenRaw = curl_exec($tokenCh);
curl_close($tokenCh);

$tokenData = json_decode($tokenRaw ?: '', true);
$apiToken = $tokenData['access_token'] ?? '';

$payload = [
    'request_id' => 'web_' . date('YmdHis'),
    'user_id' => $userId,
    'is_logged_in' => $isLoggedIn,
    'company_code' => $companyCode,
    'msg' => $message,
];

$ch = curl_init($apiBaseUrl . '/api/v1/chat');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => [
        'Content-Type: application/json',
        'X-API-Token: ' . $apiToken,
    ],
    CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
    CURLOPT_TIMEOUT => 60,
]);
$raw = curl_exec($ch);
$data = json_decode($raw, true);
curl_close($ch);

$reply = $data['msg'] ?? '系統忙碌中，請稍後再試。';
```

## 錯誤處理

建議 Web 端處理：

- HTTP 200 且 `status=success`：顯示 `msg`。
- HTTP 4xx：request 欄位缺漏或格式不正確，顯示通用錯誤並記錄 request payload。
- HTTP 5xx 或 timeout：顯示「系統忙碌中，請稍後再試」並記錄 `request_id`。
- API timeout 建議設 60 秒。

## 注意事項

- Web 端不需要保存或回傳 `ai_state` / `history`。
- Web 端可以只保存畫面顯示用聊天紀錄。
- 每位使用者的 `user_id` 要穩定；同一位會員每輪都帶同一個會員編號。
- 訪客也要有穩定訪客 ID，至少在同一個 session 中不可每輪改變。
- 正式 Web 不要呼叫 `/api/web/chat`，那是內部測試入口。
- 若正式網域使用反向代理，公開 API URL 不要加 `:8123` 或 `:8443`。
- 正式 Web API 請使用 `https://aiia.topmso.com.tw:8000/api/v1/chat`。
