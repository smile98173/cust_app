# Production Launch Checklist

本清單用於正式上線前確認需要替換、添加或驗證的項目。

## 1. 程式與依賴

- [ ] 使用正式部署分支或打包版本。
- [ ] 安裝 `requirements.txt`。
- [ ] 確認 `google-genai` 與 `Pillow` 已安裝，否則圖片 OCR 不能使用。
- [ ] 複製 `.env.example` 為 `.env`，或在部署平台設定等價環境變數。
- [ ] 確認 `.env` 不會提交到版本控制。
- [ ] 確認 `app/config/settings.py` 只保留測試預設值，不含正式 key。
- [ ] 更新主要客服對話核心時，只部署 `cust_app`；不要覆蓋同層的 `customer_service_km`，它是獨立 Laravel 版 KM / RAG 系統。
- [ ] 部署程式時不要覆蓋正式資料目錄：`cust_app_runtime`、正式 `.env.production`。

驗證：

```powershell
conda run -n cust_app python -c "import app.app_backend; print('app_backend import ok')"
conda run -n cust_app python -m unittest tests.test_channel_context tests.test_image_text_service tests.test_company_profile tests.test_router_architecture
```

## 2. LLM 與 OCR

- [ ] 設定 `OPENAI_API_KEY`。
- [ ] 確認 `OPENAI_MODEL`。
- [ ] 設定 `GEMINI_API_KEY`。
- [ ] 確認 `GEMINI_IMAGE_TEXT_MODEL`。
- [ ] 用 `/api/ocr/image` 測試一張圖片。

## 3. LINE Bot

正式 webhook path：

```text
/api/line/top/webhook
/api/line/test_bot/webhook
/api/line/tdtv/webhook
/api/line/cltv/webhook
/api/line/pktv/webhook
```

LINE Developers 後台設定：

- [ ] `top` Bot webhook URL 設為 `https://正式網域/api/line/top/webhook`。
- [ ] `test_bot` webhook URL 設為 `https://正式網域/api/line/test_bot/webhook`。
- [ ] `tdtv` webhook URL 設為 `https://正式網域/api/line/tdtv/webhook`。
- [ ] `cltv` webhook URL 設為 `https://正式網域/api/line/cltv/webhook`。
- [ ] `pktv` webhook URL 設為 `https://正式網域/api/line/pktv/webhook`。
- [ ] 每個 Bot 的 `Use webhook` 已啟用。
- [ ] 每個 Bot 的自動回覆依正式策略關閉或調整。
- [ ] 每個 Bot 的 `Channel access token` 與 `Channel secret` 已設定到部署環境。
- [ ] 按 LINE Developers Verify，確認 webhook 驗證成功。

## 4. LINE 真人客服模式

- [ ] 設定每個 Bot 的 `LINE_{BOT_CODE}_HUMAN_GROUP_ID`。
- [ ] 若真人通知要用不同 token，設定 `LINE_{BOT_CODE}_HUMAN_ACCESS_TOKEN`。
- [ ] 確認 `LINE_HUMAN_MODE_TIMEOUT_SECONDS`，預設 1200 秒。
- [ ] 實測輸入「真人客服」會回覆已轉真人模式。
- [ ] 實測真人客服群組收到最近對話與最新訊息。
- [ ] 實測真人模式期間後續訊息不進 AI，會轉發到真人客服群組。
- [ ] 實測逾時後可恢復 AI。

## 5. WEB API

- [ ] 正式 Web server 優先呼叫 `POST /api/v1/chat`。
- [ ] request 必須帶 `user.user_id`、`company.company_code`、`message.text`。
- [ ] 第二輪之後需帶回上一輪 `ai_state` 與最近對話 `history`。
- [ ] 若仍使用 `/api/web/chat`，需確認這只是測試入口，會寫入本機 SQLite。
- [ ] 確認官網來源能正確決定 `company.company_code`。
- [ ] 確認 WEB 對話 user id 使用 `web:{user_id}`，不與 LINE session 混用。

## 6. 客戶服務 API

- [ ] 決定是否關閉 mock：`CUST_API_USE_MOCK=false`。
- [ ] 填入正式 `CUST_API_*_URL`。
- [ ] 與後端 API 擁有者確認 method、payload、timeout 與錯誤格式。
- [ ] 用測試客戶資料驗證查帳單。
- [ ] 用測試客戶資料驗證補發帳單。
- [ ] 用測試客戶資料驗證網路復線。
- [ ] 用測試客戶資料驗證電視復線。
- [ ] 未確認安全前，不要開啟會異動真實客戶狀態的 endpoint。

## 7. 資料庫與保存

- [ ] 確認 `data/customer_state.db` 的部署位置。
- [ ] 若使用容器，確認 `data/` 有掛載持久化 volume。
- [ ] 確認 sessions、chat_logs、customer_profiles、feedback_records 是否符合內部保存政策。
- [ ] 確認本機 `tickets` 已移除，不要恢復本機工單資料表。
- [ ] 若正式要改 MongoDB，實作 `MongoCustomerStateRepository`，不要直接在業務邏輯中寫 Mongo。
- [ ] 建立資料備份與還原策略。

## 8. 知識庫

- [ ] 設定 `RAG_BACKEND=local`。
- [ ] 確認 `cust_app_runtime/chroma_db` 與 `cust_app_runtime/kb_documents` 有備份策略。
- [ ] 安裝 `chromadb`、`sentence-transformers`、`transformers`、`accelerate` 等本地 RAG 依賴。
- [ ] 透過 Web UI「知識庫維護」上傳內部流程/優惠文件並建立索引。
- [ ] 用人工測試案例驗證 RAG 回答。

若需要外部 RAG API 備援，才設定 `RAG_BACKEND=hybrid` 與 `RAG_API_URL`。

## 9. 安全與監控

- [ ] 確認正式服務只走 HTTPS。
- [ ] 確認 LINE signature 驗證有效，正式 Bot 不允許空 secret。
- [ ] 確認 log 不輸出完整 token、secret、API key。
- [ ] 確認個資資料保存與存取權限。
- [ ] 設定錯誤告警。
- [ ] 設定 API latency 監控。
- [ ] 設定 LLM/OCR 成本與 rate limit 監控。

## 10. 上線後冒煙測試

每個 LINE Bot 至少測：

- [ ] 傳文字「你好」有回覆。
- [ ] 傳「網路不能用」會進入正確流程。
- [ ] `top` / `test_bot` 傳未知問題時會先問服務地區。
- [ ] `tdtv` 不會反問系統台，會直接套用大屯。
- [ ] `cltv` 不會反問系統台，會直接套用佳聯。
- [ ] `pktv` 不會反問系統台，會直接套用北港。
- [ ] 傳圖片可 OCR，並把辨識結果送入客服流程。
- [ ] 傳「真人客服」可切換真人模式。

WEB 至少測：

- [ ] `/api/v1/chat` 會員情境正常回覆。
- [ ] `/api/v1/chat` 訪客情境正常回覆。
- [ ] 第二輪有帶回上一輪 `ai_state` 與 `history`。
- [ ] 不同 `company.company_code` 會套用不同公司資訊。
- [ ] 若保留 `/api/web/chat`，確認它只作為內部測試入口。
- [ ] WEB 不受 LINE 真人模式影響。

OCR 至少測：

- [ ] `/api/ocr/image` 可辨識正常圖片。
- [ ] 非圖片或錯誤 base64 會回清楚錯誤。
