# MongoDB Web / LINE 分 Collection 規劃

正式 MongoDB database：

```text
aicust_service
```

正式狀態 collections：

```text
aicust_service.web_conversations
aicust_service.test_web_conversations
aicust_service.line_conversations
```

正式切換時使用：

```text
STATE_REPOSITORY_BACKEND=mongodb
MONGODB_URI=mongodb://<mongodb-username>:<url-encoded-password>@<正式-mongodb-host>:27017/?authSource=admin
MONGODB_DATABASE=aicust_service
MONGODB_WEB_COLLECTION=web_conversations
MONGODB_TEST_WEB_COLLECTION=test_web_conversations
MONGODB_LINE_COLLECTION=line_conversations
```

若密碼包含特殊字元，請先 URL encode，例如 `@`、`:`、`/`、`#` 不可直接原樣放在 URI 密碼段。

測試環境預設仍維持：

```text
STATE_REPOSITORY_BACKEND=sqlite
```

## 設計原則

這版將 Web 與 LINE 對話狀態分成兩個獨立 collection 保存。

```text
web:*      -> aicust_service.web_conversations
test_web:* -> aicust_service.test_web_conversations
line:*     -> aicust_service.line_conversations
```

LINE 跨 Bot 共用 profile 也放在 `line_conversations`，不會寫入 Web collection。

主要保存：

```text
id
ai_state
chat_logs
```

索引：

```text
id unique index
```

目前實作會同時放 `_id = id`，方便用 MongoDB 原生主鍵查詢。

## Web Conversation 文件

Web API `/api/v1/chat` 現在由本系統保存 `ai_state` 與對話紀錄。

Collection：

```text
aicust_service.web_conversations
```

`id` 使用：

```text
web:{user_id}
```

例如：

```text
web:member_123456
web:guest_000001
```

文件範例：

```json
{
  "_id": "web:member_123456",
  "id": "web:member_123456",
  "doc_type": "conversation",
  "user_id": "web:member_123456",
  "channel": "web",
  "customer_key": "web:member_123456",
  "is_logged_in": true,
  "ai_state": {
    "conversation_state": {
      "mode": "idle"
    },
    "service": null,
    "issue_type": null,
    "company_code": "tdtv",
    "company": "大屯有線",
    "known_info": {
      "external_user_id": "member_123456",
      "is_logged_in": true,
      "custnum": "member_123456"
    },
    "pending_tool": null,
    "pending_tool_args": [],
    "last_tool_result": null,
    "last_extracted_fields": null,
    "clarify_context": null,
    "channel_context": {
      "channel": "web",
      "company_confirmed": true,
      "resolution_source": "api_request"
    }
  },
  "chat_logs": [
    {
      "role": "user",
      "message": "優惠套餐有哪些?",
      "created_at": "2026-05-27T10:00:00+08:00"
    },
    {
      "role": "assistant",
      "message": "目前查到的優惠重點如下：...",
      "created_at": "2026-05-27T10:00:03+08:00"
    }
  ],
  "created_at": "2026-05-27T10:00:00+08:00",
  "updated_at": "2026-05-27T10:00:03+08:00",
  "last_message_at": "2026-05-27T10:00:03+08:00"
}
```

Web 登入會員會在進 AI 流程前把 `user_id` 視為會員編號，並寫入：

```text
ai_state.known_info.is_logged_in
ai_state.known_info.custnum
```

`custnum` 只在 Web 端明確傳入 CUST_API 客戶編號時保存；`user_id` / `member_id` 只代表 Web 使用者識別，不會自動當成 CUST_API `custNo`。需要客戶身分的 CUST_API 會優先用 `custnum` 查詢；沒有 `custnum` 時，流程才會追問戶名與聯絡電話。

## LINE Conversation 文件

每一個 LINE bot 對話 session 一筆文件。

Collection：

```text
aicust_service.line_conversations
```

`id` 使用：

```text
line:{bot_code}:{line_user_id}
```

例如：

```text
line:tdtv:Uxxxxxxxx
line:top:Uxxxxxxxx
line:cltv:Uxxxxxxxx
```

文件範例：

```json
{
  "_id": "line:tdtv:Uxxxxxxxx",
  "id": "line:tdtv:Uxxxxxxxx",
  "doc_type": "conversation",
  "user_id": "line:tdtv:Uxxxxxxxx",
  "channel": "line",
  "line_bot_code": "tdtv",
  "line_user_id": "Uxxxxxxxx",
  "customer_key": "line:Uxxxxxxxx",
  "ai_state": {
    "company_code": "tdtv",
    "company": "大屯有線",
    "known_info": {},
    "customer_key": "line:Uxxxxxxxx",
    "channel_context": {
      "channel": "line",
      "line_bot_code": "tdtv",
      "customer_key": "line:Uxxxxxxxx",
      "company_confirmed": true
    }
  },
  "chat_logs": [
    {
      "role": "user",
      "message": "我想知道HBO在哪個頻道",
      "created_at": "2026-05-27T10:00:00+08:00"
    }
  ],
  "created_at": "2026-05-27T10:00:00+08:00",
  "updated_at": "2026-05-27T10:00:03+08:00",
  "last_message_at": "2026-05-27T10:00:03+08:00"
}
```

LINE 建議保留欄位：

```text
line_bot_code
line_user_id
customer_key
```

## LINE 跨 Bot Profile 文件

為了保留「同一個 LINE 使用者跨 Bot 共用已確認系統台」的能力，`line_conversations` 內會額外存一筆 profile 文件。

`id` 使用：

```text
line:{line_user_id}
```

文件範例：

```json
{
  "_id": "line:Uxxxxxxxx",
  "id": "line:Uxxxxxxxx",
  "doc_type": "line_customer_profile",
  "customer_key": "line:Uxxxxxxxx",
  "customer_profile": {
    "customer_key": "line:Uxxxxxxxx",
    "last_company_code": "tdtv",
    "last_company": "大屯有線",
    "last_area": "大屯",
    "last_user_id": "line:tdtv:Uxxxxxxxx",
    "last_line_bot_code": "tdtv",
    "resolution_source": "line_bot_config",
    "updated_at": "2026-05-27T10:00:00+08:00"
  },
  "ai_state": {
    "customer_profile": {
      "customer_key": "line:Uxxxxxxxx",
      "last_company_code": "tdtv",
      "last_company": "大屯有線",
      "last_area": "大屯",
      "last_user_id": "line:tdtv:Uxxxxxxxx",
      "last_line_bot_code": "tdtv",
      "resolution_source": "line_bot_config",
      "updated_at": "2026-05-27T10:00:00+08:00"
    }
  },
  "chat_logs": [],
  "created_at": "2026-05-27T10:00:00+08:00",
  "updated_at": "2026-05-27T10:00:00+08:00"
}
```

## 對應目前程式方法

| 方法 | Mongo 行為 |
| --- | --- |
| `save_session_document(user_id, memory, customer_key)` | 依 `user_id` prefix 選 collection，upsert `id = user_id`，更新 `ai_state`。 |
| `get_session_document(user_id)` | 依 `user_id` prefix 選 collection，讀取 `id = user_id` 的 `ai_state`。 |
| `append_chat_log(user_id, role, message, customer_key)` | 依 `user_id` prefix 選 collection，對 `id = user_id` 的 `chat_logs` push 一筆訊息。 |
| `get_recent_chat_history(user_id, limit)` | 依 `user_id` prefix 選 collection，從 `chat_logs` 取最後 N 筆。 |
| `save_customer_profile(profile)` | upsert 到 `line_conversations`，`id = customer_key`。 |
| `get_customer_profile(customer_key)` | 從 `line_conversations` 讀取 `id = customer_key` 的 profile 文件。 |
| `delete_user_state(user_id)` | 依 `user_id` prefix 選 collection，刪除 `id = user_id` 的 session 文件。 |
