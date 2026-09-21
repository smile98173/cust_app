# 智能客服 Agent 系統

本專案是一套受控型客服 Agent 系統，主要用於有線電視、寬頻網路、帳務、復線、報修與知識庫查詢。

系統設計重點不是讓 LLM 自由發揮，而是讓 LLM 在受控流程中協助判斷意圖，避免亂辦事、亂收個資、亂承諾未知流程。

---

## 文件導覽

- `docs/README.md`：文件索引，區分現行操作文件與歷史紀錄。
- `docs/active_customer_service_handoff_2026-09-14.md`：目前客服 AI 的架構、規則邊界與測試交接紀錄。
- `docs/project_overview.md`：專案總覽、目前進度、近期變更紀錄與後續待辦。
- `docs/deployment_switch_guide.md`：測試環境切正式環境的參數對照、切換步驟、驗證與回退方式。
- `docs/database_collection_plan.md`：Web / LINE MongoDB 分 collection 儲存規劃。
- `docs/web_api_integration_guide.md`：正式 Web API URL、簡化 request/response 範例、會員欄位與後端保存方式。
- `docs/web_partner_integration.md`：給 Web 同事的 AI 客服串接手冊。
- `docs/web_api_php_example.php`：PHP 串接範例，方便 Web 同事理解呼叫與保存流程。
- `docs/channel_api_architecture.md`：WEB / LINE API、channel context、儲存與正式 Web 串接。
- `docs/router_architecture.md`：Router 架構、route guard 與維護方式。
- `PRODUCTION_ENV.md`：正式環境變數。
- `PRODUCTION_CHECKLIST.md`：正式部署檢查表。
- `docs/testing/manual_test_cases.md`：手動測試案例。

---

## 核心架構

```text
使用者輸入
    ↓
app_backend.py
    ↓
chat_handler.py
    ↓
是否正在既有流程？
    ├─ troubleshooting_started = yes → troubleshooting_engine.py
    ├─ pending_tool 存在 → tool flow
    ├─ clarify_context 存在 → clarify resolver
    └─ 無既有流程 → intent_router.py
                    ↓
               LLM 判斷意圖與 route
                    ↓
    ┌───────────────────────────────┐
    │ clarify                       │
    │ tool_action                   │
    │ knowledge_query               │
    │ troubleshooting               │
    │ unsupported_flow              │
    │ smalltalk                     │
    └───────────────────────────────┘
```

主要入口：

- 後端 API：`app/app_backend.py`
- Streamlit UI：`app/web_ui.py`
- 對話主流程：`app/handlers/chat_handler.py`
- 意圖路由：`app/services/intent_router.py`
- 知識庫檢索：`app/services/kb_service.py`
- 工具呼叫：`app/services/tool_manager.py`
- 系統台/公司資料：`app/services/company_profile.py`
- 姓名與電話驗證：`app/services/customer_validation.py`
- 狀態儲存：`app/services/memory_service.py`、`app/services/state_repository.py`

---

## Router 架構更新

每一則新的客戶訊息都必須先由 LLM 產生結構化意圖判斷；不得以關鍵字快速路由直接生成客服答案。既有流程的 state resolver 只用於承接已由 LLM 建立的流程狀態，例如補齊工具欄位或排錯步驟。

Router 已整理成比較可擴展的結構：

- `app/schemas/router.py`
  - 定義 `RouterDecision`、route、slot schema。
  - 統一正規化 LLM 回傳結果。

- `app/services/router_catalog.py`
  - 集中管理工具白名單、route 說明、clarify 選項與固定降級訊息。
  - 新規則應轉成 LLM 可判斷的語意約束或工具契約，不可新增直接回答的短詞規則。

- `app/services/router_prompt.py`
  - 從 catalog 產生 Router prompt。
  - 避免工具白名單散落在 prompt 與程式碼多處。

詳細維護方式可看：

- `docs/router_architecture.md`
- `docs/README.md`

---

## RAG 回答策略

目前知識型問題採三層處理：

1. **RAG 命中且對題**
   - 直接回覆知識庫答案。

2. **RAG 命中但題型不符**
   - 例如使用者問「雙模機是什麼」，但 KB 只命中「雙模機設定選項」或「雙模機網路分享」。
   - 系統會視為不對題，不硬套答案。
   - 判斷邏輯在 `app/services/kb_answer_guard.py`。

3. **RAG 無對題資料，但屬於低風險概念題**
   - 例如「雙模機是什麼」、「固定 IP 是什麼」。
   - 允許 LLM 用一般常識回答，但必須標示這不是公司官方服務承諾。
   - 判斷與 prompt 在 `app/services/general_knowledge_fallback.py`。

以下問題不允許靠 LLM 常識回答：

- 申請、辦理、設定、操作、步驟、流程
- 費用、方案、優惠、月租
- 故障、報修、復線
- 公司政策或服務可用性，例如「可不可以」、「能不能」、「有沒有」

---

## 系統台與公司 Context

前端 `app/web_ui.py` 目前支援選擇系統台，預設為：

- `tdtv - 大屯有線`

可選系統台資料集中在 `app/services/company_profile.py`：

- `tv_cable` 代碼與公司名稱
- 地址電話
- 官方網站
- 營業時間
- 服務項目
- 服務地區
- App 名稱
- 統一編號

後端 `POST /chat` 會接收 `tv_cable`，並把對應公司資訊寫入 memory。Router 與一般知識 fallback prompt 也會帶入目前公司 context，避免不同系統台的客服資訊混在一起。

公司地址、服務地區、營業時間、客服電話與官網不走 RAG，一律由 `company_info` route 直接使用 `company_profile.py` 的結構化資料回答。像「在哪邊？」這類模糊問法會先反問使用者是要公司地址還是服務地區範圍，避免撈到不相關的 QA。

前端若切換系統台，會清空目前對話並重建 User ID，避免舊公司對話狀態、個資 slot 或 pending tool 影響新系統台測試。

---

## 工具呼叫與驗證

工具呼叫目前預設走 mock API，避免測試環境誤觸真實客戶服務。
正式 API endpoint 可透過環境變數覆蓋。

身份型 mock API 預設測試客戶為：

- 戶名：`王大明`
- 電話：`0988555666`
- 客戶編號：`A000001`

正確資料會回傳 mock 成功；姓名或電話不一致會回傳查無資料。

目前工具 API 包裝在 `app/services/tool_manager.py`，可用環境變數覆蓋預設 endpoint：

- `CUST_API_TOKEN_URL`
- `CUST_API_SEARCH_BILL_URL`
- `CUST_API_INTERNET_RETURN_URL`
- `CUST_API_TV_RETURN_URL`
- `CUST_API_SEND_MESSAGE_URL`
- `CUST_API_TIMEOUT`
- `CUST_API_USE_MOCK`

API 與流程改進整理可看：

- `docs/planning/api_improvements_20260508.md`

姓名與電話驗證集中在 `app/services/customer_validation.py`：

- 姓名：2 到 50 字，允許中文、英文、空白、`.`、`·`
- 電話：手機 `09xxxxxxxx`、市話 `0[2-8]...`、或未含區碼的 7 到 8 碼市話

slot 抽取仍會額外阻擋「查帳單、網路不能用、電視不能看」等意圖詞被誤存成姓名。

---

## 資料與知識庫

來源資料：

- `data/knowledge_source/帳務.csv`
- `data/knowledge_source/網路寬頻.csv`
- `data/knowledge_source/機上盒.csv`
- `data/knowledge_source/加值服務.csv`

整理後輸出：

- `data/kb_output/canonical_kb.jsonl`
- `data/kb_output/canonical_kb.json`
- `data/kb_output/canonical_kb.csv`

本地 Chroma RAG：

- 預設 `RAG_BACKEND=local`，知識查詢會載入 `cust_app_runtime/chroma_db`
- Web UI 的「知識庫維護」可上傳文件並自動建立索引
- 原外部 RAG API 保留為 `RAG_BACKEND=api` 或 `RAG_BACKEND=hybrid` 的選項

本地知識資料整理腳本仍保留供舊資料轉換參考，新的文件上傳流程請看 `docs/local_rag_admin.md`：

```powershell
python scripts/kb_build.py
```

---

## 啟動方式

```powershell
uvicorn app.app_backend:app --host 127.0.0.1 --port 8123 --reload
streamlit run app/web_ui.py --server.address 127.0.0.1 --server.port 8443 --server.baseUrlPath assistant --server.enableCORS false --server.enableXsrfProtection false
```

指定個人測試 env：

```powershell
$env:CUST_APP_ENV_FILE=".env.local"
uvicorn app.app_backend:app --reload
```

CMD：

```cmd
set CUST_APP_ENV_FILE=.env.local
uvicorn app.app_backend:app --reload
```

正式環境可用 `CUST_APP_ENV_FILE` 指到 `.env.production` 或專案外部的正式 env 檔，詳細可看 `docs/deployment_switch_guide.md`。

常用 API：

- `GET /health`
- `GET /companies`
- `POST /chat`
- `GET /state/{user_id}`
- `POST /reset/{user_id}`
- `GET /api/kb/documents`
- `POST /api/kb/documents`
- `POST /api/kb/search`

---

## 測試

目前有針對 Router、本地/API RAG client、RAG answer guard、一般知識 fallback、LINE channel context、工具流程與正式 Web schema 的單元測試。

```powershell
python -m pytest tests -q
```

最近一次整理文件時的測試結果可看 `docs/project_overview.md`。

手動測試案例可看：

- `docs/testing/manual_test_cases.md`

### Excel 情境對話測試

可依據 `三個月AI對話情境測試案例整理.xlsx` 產生並執行 live 對話測試：

```powershell
python scripts/run_excel_dialog_tests.py --request-timeout 45
```

輸出：

- `reports/dialog_scenario_report.html`
- `reports/dialog_scenario_report.json`

HTML 報告會以聊天泡泡方式呈現每個測試案例的多輪對話、Excel 期望行為、自動檢核點與 PASS/FAIL/SKIP 狀態。

工具成功/失敗路徑可用 mock API 情境測試：

```powershell
python scripts/run_mock_api_dialog_tests.py --xlsx 三個月AI對話情境測試案例整理.xlsx --output-dir reports/20260513
```

輸出：

- `reports/20260513/dialog_scenario_report.html`
- `reports/20260513/dialog_scenario_report.json`

可只跑指定案例或優先級：

```powershell
python scripts/run_excel_dialog_tests.py --case TC-001,TC-007
python scripts/run_excel_dialog_tests.py --priority P0
```

---

## 測試狀態注意

清除對話只清前端畫面；若要完整重置後端 memory，請使用 UI 的「重建 User ID」，或呼叫：

```text
POST /reset/{user_id}
```

如果同時有多份專案或多個 Streamlit / Uvicorn 在跑，請確認目前瀏覽器連到的是正確的 port，且 `127.0.0.1:8123` 是目前這份專案的後端。
