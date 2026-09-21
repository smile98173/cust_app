# 本地 RAG 知識庫維護

目前 RAG 使用本地 ChromaDB，讓客服系統查詢公司知識、內部流程與已匯入的方案資料。客戶問題會先由 LLM 判斷意圖，再依需求檢索；命中文件還必須通過對題與服務證據檢查，避免問 A 答 B。

優惠或方案資料不應只依公司資訊的單一文字欄位回答。正式方案知識應以系統台範圍、有效期間與方案內容維護；已下架方案應保留為可查詢的歷史資料，但不可被主動推薦。線上資料更新的必填欄位、回答摘要規則與重新驗證流程詳見 `customer_reply_alignment_2026-09-16.md`。

## 流程

1. 在 Web UI 打開「知識庫維護」。
2. 上傳文件，填寫：
   - `知識庫分類`：預設 `通用`，也可選各系統台名稱，例如 `大屯`、`佳聯`、`北港`
3. 後端會抽取文字、切 chunk、自動判斷文件主題分類、建立 embedding，預設寫入 `cust_app_runtime/chroma_db`。
4. 客服聊天觸發 RAG 時，會先查 `通用`，再查使用者所屬系統台，並合併排序結果。
5. 回答前會以問題與文件內容進行對題檢查；對特定服務問題，文件必須有該服務的明確證據，否則不會拿來回答。

## CSV 知識格式與顯示

CSV 匯入時每列會切成類似 `question: ...；answer: ...；company: ...` 的 chunk。Web UI 側欄「知識庫命中結果」會將這種 chunk 拆成獨立的 `question`、`answer`、`company` 顯示，避免整段內容塞在 answer 欄位裡。

知識庫 CSV 內的連結建議保留純文字標記，例如：

```text
新用戶僅提供LINE帳號註冊，詳請可參考網站：［LINE TV客服中心🔗］服務公告。
```

側欄命中結果會保留原樣，不會把 CSV 內容改成 Markdown 超連結。正式聊天回覆顯示時，前端會再把 `［名稱🔗］URL` 或已知的 `［LINE TV客服中心🔗］` 標記轉為可點連結。

如果直接修改 `cust_app_runtime/kb_documents/*.csv` 或 `data/knowledge_source/*.csv`，需要對該文件執行重新索引，ChromaDB 才會更新舊 chunk。

## 支援格式

- `txt`
- `md`
- `html` / `htm`
- `csv`
- `jsonl`
- `pdf`：需要 `pypdf`
- `docx`：需要 `python-docx`

## 重要環境參數

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

上述路徑留空時，預設會使用：

- `D:\AI智能客服\cust_app_runtime\chroma_db`
- `D:\AI智能客服\cust_app_runtime\kb_documents`
- `D:\AI智能客服\cust_app_runtime\kb_documents\documents.json`

若要保留外部 RAG API 當備援，可設：

```env
RAG_BACKEND=hybrid
RAG_API_URL=<外部 RAG API URL>
```

## 管理 API

- `GET /api/kb/status`
- `GET /api/kb/documents`
- `POST /api/kb/documents`
- `GET /api/kb/documents/{document_id}`
- `GET /api/kb/documents/{document_id}/chunks`
- `POST /api/kb/documents/{document_id}/reindex`
- `DELETE /api/kb/documents/{document_id}`
- `POST /api/kb/search`

上傳 API 使用 JSON base64，避免額外依賴 multipart：

```json
{
  "file_name": "退租流程.txt",
  "file_base64": "<base64>",
  "title": "退租流程",
  "knowledge_base": "通用",
  "category": "billing",
  "status": "active"
}
```
