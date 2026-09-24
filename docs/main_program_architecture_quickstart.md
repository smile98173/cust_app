# 主程式架構快速導覽

最後確認：2026-09-24

> 這份文件是給第一次接觸專案的維護者。先花 15 分鐘讀完本頁，再依實際任務追查對應模組，不需要從幾千行的 Router 或 Handler 從頭看起。

## 一句話理解這套系統

這是一套「受控型 AI 客服」：FastAPI 接收 Web 與 LINE 訊息；新語意需求由 LLM 判斷，已建立的排錯與工具狀態由狀態機承接。程式再根據決策執行知識庫查詢、客戶 API 工具、排錯流程或固定安全回覆，最後儲存對話狀態。

核心原則不是讓 LLM 自由回答，而是讓它在工具白名單、資料驗證、RAG 證據與安全 guard 之內運作。

## 從使用者訊息到回覆

```text
Web / LINE / 測試 UI
        |
        v
app/app_backend.py
  API 入口、身分驗證、channel context、載入 memory
        |
        v
run_core_chat()
        |
        v
app/handlers/chat_handler.py :: handle_chat_message()
        |
        +-- 已在排錯 / 等待工具欄位 / 等待澄清？
        |       `-- 承接既有狀態，並先判斷是否換話題
        |
        `-- 新話題
                `-- app/services/intent_router.py :: run_intent_router()
                        LLM -> RouterDecision -> schema validation -> safety guard
        |
        v
route 執行
  tool_action       -> tool_manager.py
  knowledge_query   -> kb_service.py -> kb_answer_guard.py
  troubleshooting  -> troubleshooting_engine.py
  company_info      -> company_profile.py
  clarify           -> 儲存 clarify_context，等下一輪
  direct_reply / smalltalk / unsupported_flow
        |
        v
回覆安全處理、格式化、儲存 memory/chat log、API response
```

## 六個最重要的檔案

| 先後 | 檔案 | 責任 | 建議先找的程式入口 |
| --- | --- | --- | --- |
| 1 | `app/app_backend.py` | FastAPI 組裝層；Web、LINE、OCR、知識庫與回饋 API | `run_core_chat()`、`external_chat()`、`line_webhook()` |
| 2 | `app/handlers/chat_handler.py` | 一則客服訊息的主編排；處理進行中流程、Router 結果、工具與 RAG | `handle_chat_message()`、`run_tool_or_rag_flow()` |
| 3 | `app/services/intent_router.py` | 請 LLM 產生結構化意圖，並加上安全 guard | `run_intent_router()`、`router_guard()` |
| 4 | `app/schemas/router.py` | Router 輸出契約：route、intent、tool、slots 與模型可填欄位 | `RouterDecision`、`RouterSlots` |
| 5 | `app/services/tool_manager.py` | 客戶資料 API/mock、工具 schema、參數與回應轉換 | `get_available_functions()`、`call_tool()` |
| 6 | `app/services/kb_service.py` | RAG 查詢、範圍過濾、關鍵字補強與結果排序 | `retrieve_knowledge()` |

這些檔案的行數較多，建議以上述 function/class 名搜尋，不要依靠固定行號。

專案根目錄的 `line_template.py`、`update_info.py` 與 `template_bills.py` 目前不是 FastAPI 主流程的入口；新同事可先略過，除非手上任務有特別指向它們。

## 一次請求的實際處理步驟

1. `app_backend.py` 根據入口建立 Web、test Web 或 LINE context，取得公司、登入狀態與客戶識別資訊。
2. `memory_service.py` 載入對話 memory 與最近的 chat history。
3. `handle_chat_message()` 先檢查是否正在排錯、等待工具參數或處理上一輪澄清。
4. 一般新話題交給 `run_intent_router()`；LLM 回傳 `RouterDecision`，後端再驗證 route、工具白名單與動作條件。
5. Handler 依 route 呼叫客戶工具、知識庫、排錯狀態機或公司資料。
6. 回覆經過證據、連結與安全處理後，寫回 session memory 與 chat log，再回給來源 channel。

## Router 會產生什麼

`RouterDecision` 的主要 route：

- `knowledge_query`：先查知識庫，有對題證據才回答。
- `tool_action`：收集必要欄位後呼叫白名單工具。
- `troubleshooting`：進入或繼續排錯狀態機。
- `company_info`：從結構化公司資料回答地址、電話、官網等。
- `clarify`：問一個必要的澄清問題，並把 context 留給下一輪。
- `direct_reply`、`smalltalk`、`unsupported_flow`：可控的直接回覆或降級處理。

詳細 Router 契約請看 `docs/router_architecture.md`。要特別記得：有效的 LLM 意圖不應被關鍵字規則改寫；guard 的任務是阻止不安全動作，不是另外當一個客服回答器。

## Router 規則按需載入

正式 Router 不再每輪固定傳送整份執行規則。`router_prompt.py` 會組合：

- 永遠保留的核心：安全邊界、route 契約、輸出 schema、工具白名單、對話承接及核心 intent。
- 依本輪文字、可信 memory 與必要的最近對話載入的規則包：`promotion`、`support`、`billing`、`termination`、`network`、`services`。
- 只有相符模組的 intent 索引與區域政策；未辨識的新說法會保守載入全部模組，不會因選包器漏詞而靜默遺失意圖。

模組選擇器只決定模型可看到哪些參考規則，不可輸出 route、intent、答案或工具；語意決策仍由 LLM 完成。新增 intent 時，必須同時放入 `RUNTIME_PROMPT_CORE_INTENTS` 或 `RUNTIME_PROMPT_INTENT_MODULES`，`test_prompt_usage_optimization.py` 會檢查 84 個執行 intent 是否完整覆蓋。

完整 14K prompt 仍由 `build_runtime_intent_router_rules()` 保留作審查與覆蓋基準；正式呼叫使用 `build_contextual_runtime_intent_router_rules()`。不要為了省 token 刪除完整版規則，也不要把模組線索改成直接回答客戶的 fast path。

## 狀態與資料放在哪裡

| 資料 | 責任模組 / 預設位置 | 用途 |
| --- | --- | --- |
| 對話 memory、chat logs、customer profiles | `memory_service.py` -> `state_repository.py` | 預設 SQLite，可以 env 切換 MongoDB |
| 本機 SQLite | `data/customer_state.db` | 本機/測試與 LINE 狀態；不是業務知識庫 |
| 知識庫原始文件 | `RAG_LOCAL_DOCS_DIR` | 由知識庫維護 API/UI 管理 |
| 向量索引 | `RAG_LOCAL_PERSIST_DIR` | 預設是專案外 `cust_app_runtime/chroma_db` |
| 公司資料 | `company_profile.py` + `COMPANY_PROFILE_PATH` | 系統台地址、電話、服務地區、網址等 |
| log / feedback | `cust_app_runtime/logs`、`cust_app_runtime/feedback` | 錯誤、延遲、客戶 API 診斷與回饋 |

`STATE_REPOSITORY_BACKEND=sqlite|mongodb` 決定對話狀態的 repository implementation。實際路徑與密鑰以當前 `CUST_APP_ENV_FILE` 指定的 env 為準，不要把 `.env` 內容複製進文件或 commit。

## 常見需求應該改哪裡

| 需求 | 主要修改點 | 至少驗證 |
| --- | --- | --- |
| 新增/調整意圖或 route | `router.py`、`router_catalog.py`、`router_prompt.py`、`intent_router.py`；同步登記 prompt 模組 | `test_prompt_usage_optimization.py`、`test_model_router_contract.py`、`test_model_only_routing.py` |
| 新增客戶 API 工具 | `tool_manager.py`、`slot_manager.py`、Router catalog/prompt | Router + tool manager 單元測試，再測成功/失敗/缺欄位 |
| 調整對話主流程 | `chat_handler.py` | 相關 flow regression 與安全測試 |
| 新增業務知識 | 優先從 Web UI/API 上傳知識文件，不要先寫進 prompt | KB search + 實際對話案例 |
| 調整 RAG 命中/對題條件 | `kb_service.py`、`kb_answer_guard.py` | `test_kb_service.py`、`test_kb_answer_guard.py` |
| 調整公司固定資料 | `company_profile.py` 或維護 UI | 不同 company code 的隔離測試 |
| 改 Web / LINE 入口行為 | `app_backend.py`、`channel_context.py`、`web_handoff.py` | channel、handoff、schema 測試 |
| 改對話儲存 | `memory_service.py`、`state_repository.py` | `test_state_repository.py`、`test_memory_schema.py` |

## 本機最小驗證

8123 由管理者啟動並維持 reload。維護者做 AI 情境測試時只呼叫既有服務，不自行啟動或重啟；請依 `docs/testing/ai_test_environment.md` 設定 `.env.ai-test`、取得短期 token，按原始對話順序重播。

執行全部單元測試：

```powershell
python -m pytest tests -q
```

若只改 Router，先跑較小範圍：

```powershell
python -m pytest tests/test_model_only_routing.py tests/test_model_router_contract.py -q
```

注意：請先確認 `.env.local` 使用 mock 客戶 API，再測試會改變客戶帳務或服務狀態的工具流程。

## 新同事的 15 分鐘閱讀順序

1. **0–5 分鐘**：讀本頁的架構圖、核心檔案與 route 種類。
2. **5–10 分鐘**：在 `app_backend.py` 搜 `run_core_chat` 和目標 endpoint，再在 `chat_handler.py` 搜 `handle_chat_message`。
3. **10–15 分鐘**：依第一個實際任務選讀 `router_architecture.md`、`local_rag_admin.md` 或 `web_api_integration_guide.md`，並先找到對應測試。

建議第一個練習是：用測試 UI 送一個知識型問題，從 response 的 `decision_type`、`latency` 與後端 log 追到 Router 和 RAG；這會比逐檔案閱讀更快建立全貌。

## 架構邊界：維護時不要打破

- 新話題是 LLM-first Router；不要新增「看到關鍵字就直接回答」的捷徑。
- LLM 輸出必須通過 typed schema、工具白名單與 guard；模型不能自行發明工具或文件 ID。
- 費用、方案、優惠、辦理流程與公司政策要有結構化資料或 RAG 證據，不可只靠模型常識。
- 工具欄位只在工具流程中收集，並要保留身分驗證、授權、防重送與收據圖片證據等安全條件。
- 進行中的流程不能無條件綁住使用者；要先判斷他是補欄位還是已經換話題。
- 修改客服行為前，同時核對測試與「現行」文件；日期型回饋報告是歷史資料，不是最新規格。

## 接下來看哪份文件

- 修改客服回答與安全邊界：`docs/active_customer_service_handoff_2026-09-14.md`
- 修改 Router：`docs/router_architecture.md`
- 維護知識庫：`docs/local_rag_admin.md`
- 串接正式 Web API：`docs/web_api_integration_guide.md`
- 切換測試/正式環境：`docs/deployment_switch_guide.md`
- 手動回歸測試：`docs/testing/manual_test_cases.md`
