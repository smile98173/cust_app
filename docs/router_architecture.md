# Router Architecture

本專案的 Router 採「LLM-first + typed decision schema + guard」結構。

## 現行契約

- 每一則新的客戶知識問題必須先由 LLM 判斷意圖、route、工具與知識檢索需求。
- `router_catalog.py` 僅提供 LLM 可讀的 route、工具白名單、澄清選項與語意約束；不可用它的關鍵字直接產生客服答案。
- `router_guard()` 只做結構與安全保護，例如修正不存在的工具、禁止不相容欄位；不得覆寫有效的 LLM 意圖或依關鍵字回答客戶。
- LLM 路由無法使用或回傳無效 JSON 時，固定回覆 `系統暫時無法判讀您的需求，請稍後再試。`，不退回舊規則回答。
- `fallback_router()` 已停用語意降級，只能回傳 `model_router_unavailable`，不得依關鍵字產生 route 或客服答案。
- 已進行中的排錯步驟、帳務授權、工具防重送與真人轉接保護可以使用確定性狀態機；這些規則只能限制動作，不可推測產品語意或直接產生知識答案。

## 動態選項與文件鎖定

方案清單、產品清單與活動名稱都來自目前有效的知識庫，不得寫入提示詞或程式常數。多輪選擇採以下契約：

1. 第一輪檢索後，系統保存實際顯示順序，以及每個選項的 `option_id`、顯示名稱、知識庫與來源文件 ID。
2. 任何 clarify 清單的下一輪編號、名稱或自然語句都交由 LLM 理解；LLM 只能回傳既有 `selected_option_id`。
3. 後端用對話狀態驗證 `selected_option_id`，再補入 `target_document_id` 與 `target_knowledge_base`。模型輸出的文件 ID 一律忽略。
4. 有已驗證目標時，不執行通用查詢擴寫；RAG 最終結果必須再次以文件 ID 過濾。
5. 選項 ID 不存在、來源文件已下架或查不到證據時，不可改用相似活動回答，應保留澄清狀態或回覆目前無法取得該方案資料。

此流程不依賴方案名稱與排列順序，因此知識庫新增、下架或重排活動時不需修改 prompt 或路由程式。

## 檔案責任

- `app/services/intent_router.py`
  - 負責執行 Router 流程。
  - 呼叫 LLM 產生結構化決策，再透過 schema validation 與 guard 做安全保護。
  - 公司資訊、網址與加值服務的差異由 LLM 判斷後，交由對應資料來源回答。

- `app/schemas/router.py`
  - 定義 Router 回傳契約。
  - 所有 Router 輸出都會正規化成 `RouterDecision`。
  - 新增 route 或 slot 時，先從這裡擴充。
  - `selected_option_id` 是模型可填的對話選項；`target_document_id` 與 `target_knowledge_base` 是後端專用欄位，不信任模型輸入。

- `app/services/router_catalog.py`
  - 集中管理 route 說明、工具白名單、clarify options、alias 與固定降級訊息。
  - 新增情境時，補 LLM 可理解的語意與約束，不新增直接客服回答的關鍵字規則。

- `app/services/router_prompt.py`
  - 從 catalog 產生 LLM Router prompt。
  - Prompt 不應再手寫工具白名單，避免和實際工具不同步。

## 新增支援工具

1. 在 `app/services/tool_manager.py` 新增工具 function 與 `FUNCTION_REGISTRY`。
2. 在 `get_available_functions()` 補工具描述與 required parameters。
3. 在 `app/services/slot_manager.py` 補 `TOOL_SLOT_SCHEMA`。
4. 若需要澄清情境，在 `app/services/router_catalog.py` 補 options / aliases，並在 `router_prompt.py` 補足上下文語意。
5. 加 unittest 覆蓋 route、tool_name、required slots。

## 新增知識型主題

1. 在 `app/services/router_prompt.py` 補主題、排除條件與需要澄清的語意示例。
2. 如需反問選項，補 `CLARIFY_CONTEXTS` 與 `CLARIFY_ALIASES`，但由 LLM 選擇是否使用。
3. 知識庫資料由 Web UI「知識庫維護」上傳，預設寫入本地 ChromaDB；回答前仍須經 `kb_answer_guard.py` 的對題與服務證據檢查。

## Guard 原則

- 未支援工具一律降級為 `unsupported_flow`。
- `knowledge_query` 不允許 `tool_name` 或 `should_call_tool`。
- `clarify`、`unsupported_flow`、`smalltalk` 不跑 RAG。
- 排錯流程中的短回答交回 troubleshooting state machine。
- 排錯流程中若使用者回覆 `不知道`、`不清楚`、`沒用`、`不行`、`不要` 或其他拒絕排錯語意，state machine 會直接轉報修流程；若報修工具停用，回報修暫停訊息並附維修申告連結。

## 測試契約

- 每個新語意情境都必須提供可觀測的模型假件，並斷言模型確實被呼叫。
- 模型失敗測試必須斷言 `model_router_unavailable`，不得期待關鍵字規則仍能回答。
- clarify 選項測試由模型回傳 `selected_option_id`，再斷言後端只接受對話狀態中已存在的 ID。
- 只有已進入的排錯步驟、等待中的工具欄位驗證、授權與防重送能不呼叫語意模型。
- 舊 `test_flow_regressions.py` 混合了已停用的規則路由契約，目前作為歷史案例封存；現行架構以 `test_model_only_routing.py` 與 `test_model_router_contract.py` 為準。

## 真人客服轉接

真人客服轉接由 LLM Router 判斷意圖，不再在 LINE 前置流程用固定關鍵字攔截。

Router 判定使用者明確要求真人接手、人工客服、專人協助、不想再由 AI 回覆，或服務處理中要求轉真人時，應輸出：

```json
{
  "route": "direct_reply",
  "intent": "human_handoff_request",
  "should_call_tool": false,
  "should_retrieve_knowledge": false,
  "reply": "我可以協助您轉接真人客服。"
}
```

`router_guard()` 會將 `human_handoff_request` 正規化成固定轉接意圖，避免 LLM 自行改寫標記句。LINE webhook 看到此 intent 時會啟動 `human_mode` 並通知真人客服群組；WEB / external API 則回覆可點選的真人客服轉接連結，並在 `actions` 帶出 `human_handoff`。不得向使用者說「請稍後」或承諾等待時間。

若使用者只是試探或不確定，例如「有沒有真人」、「有真人嗎」、「真人在嗎」、「真人客服」，Router 應先請使用者說明問題：

```json
{
  "route": "clarify",
  "intent": "human_handoff_confirmation",
  "topic": "human_handoff_confirmation",
  "reply": "請問您目前遇到什麼問題？我會先協助您處理；若確認無法在線上協助，再幫您轉接真人客服。"
}
```

下一輪使用者回覆 `是`、`好`、`OK`、`可以` 等短肯定語時，轉成 `human_handoff_request`。若回覆 `不用`、`不要`、`先不用`，則取消轉接確認並繼續一般協助。

注意：單純詢問客服電話、營業時間或聯絡方式，不應輸出 `human_handoff_request`，應依公司資訊或知識查詢處理。
