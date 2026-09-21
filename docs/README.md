# 文件索引

最後整理：2026-09-18

## 現行操作文件

- `active_customer_service_handoff_2026-09-14.md`：客服 AI 的現行架構、規則邊界、知識庫原則與真實 API 回歸測試方式。修改客服回答行為前優先閱讀。
- `customer_reply_alignment_2026-09-16.md`：客服建議轉成回答契約的現行規則、線上知識資料維護欄位，以及「待整理」案例的恢復驗證流程。調整線上資料或回饋案例前必讀。
- `feedback_backlog_organization_2026-09-18.md`：164 筆待整理回饋壓縮為 55 組專業案例的規則、追蹤方式與後續驗證邊界。
- `router_architecture.md`：LLM-first Router、結構化決策與 guard 的維護契約。
- `local_rag_admin.md`：本地知識庫匯入、索引與回答證據保護。
- `deployment_switch_guide.md`：部署、環境變數、啟動與上線檢查。
- `web_api_integration_guide.md`、`web_partner_integration.md`：外部網站串接 API。
- `regional_policy_guide.md`：跨系統台與方案顯示政策。
- `current_billing_reply_rules_2026-09-07.md`：帳務回覆規則。不可擅自變更帳務 API 的商業轉譯。

## 歷史紀錄

下列檔案保留做為回饋、缺口與過去決策的可追溯紀錄，不可當成現行行為規格：

- `customer_service_feedback_review_*.md`
- `customer_service_kb_qa_2026-06-19.md`
- `customer_service_missing_kb_content_*.md`
- `knowledge_base_gaps_2026-06-19.md`
- `website_content_feedback_2026-09-10.md`
- `channel_api_architecture.md` 中的「變更紀錄」章節。

## 已同步的舊說明

2026-09-14 已更新 `README.md`、`router_architecture.md`、`local_rag_admin.md`、`deployment_switch_guide.md` 與 `project_overview.md`，移除或標記下列已不適用的現行說法：

- 用關鍵字或 deterministic rule 直接回答客戶。
- 模型無法使用時退回舊規則客服答案。
- 優惠、促銷與推薦方案一律不檢索、只讀公司資訊單一文字欄位。

本次未刪除日期型回饋或決策文件，因其仍是歷史紀錄；往後若要刪除，僅刪除沒有追溯價值、且已由現行文件完整取代的重複草稿。
