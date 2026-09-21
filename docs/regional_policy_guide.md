# 中區與嘉南區規則分流

## 規則套用順序

每次對話會先依系統台解析區域，再依下列順序合併規則：

1. 全域預設規則
2. 中區或嘉南區規則
3. 單一系統台規則

越後面的設定優先度越高。單一系統台可以覆寫區域設定，但不會影響同區其他系統台。

## 區域與知識庫

- `central`：通用-中區
- `jiannan`：通用-嘉南區
- 舊「通用」只保留給通用-中區相容使用
- 同一系統台不可同時加入中區與嘉南區；儲存範圍時會直接阻擋
- 若既有資料發生跨區衝突，該次查詢不會混入兩區通用知識庫

## 設定檔

預設讀取：

`D:\AI智能客服\cust_app_runtime\regional_policies.json`

也可以用環境變數 `REGIONAL_POLICY_PATH` 指定其他位置。格式請參考
`docs/regional_policies.example.json`。

目前可覆寫的規則：

- `promotion.social_discount_stacking`
- `promotion.discount_stacking_caution`
- `promotion.hidden_plan_visibility`
- `promotion.non_promoted_1g_plan`
- `promotion.low_income_500m_year_fee`
- `billing.next_bill_after_no_unpaid`
- `billing.past_payment_record`
- `billing.payment_not_posted`
- `billing.store_payment_still_billed`
- `support.remote_control_price`

每個規則可設定：

- `prompt`：提供給 LLM 的區域規則
- `reply`：安全直回或回覆後處理使用的固定文字

設定檔不存在時會使用程式內的全域預設，不影響既有服務。

## 回饋追查

客服回饋 CSV 新增以下欄位：

- `region_code`
- `regional_knowledge_base`
- `station_knowledge_base`
- `policy_resolution_status`
- `resolved_knowledge_bases_json`
- `applied_policy_rules_json`

可用這些欄位確認問題發生在哪一區、檢索了哪些知識庫，以及套用了全域、區域或單一系統台規則。既有 CSV 會在下次新增回饋時自動補齊欄位。
