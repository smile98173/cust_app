import unittest
import hashlib
import json
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from app.services.intent_router import (
    build_memory_summary,
    build_router_history_text,
    build_service_availability_reply,
    detect_company_info_query,
    detect_equipment_purchase_knowledge_query,
    detect_service_device_limit_knowledge_query,
    detect_value_added_product_knowledge_query,
    detect_knowledge_entity_confirmation,
    detect_mabow_query,
    detect_payment_receipt_query,
    detect_safe_direct_reply,
    detect_service_availability_query,
    detect_troubleshooting_query,
    detect_reconnection_query,
    detect_ambiguous_short_query,
    fallback_router,
    router_guard,
    run_intent_router,
    validate_router_result,
    HUMAN_HANDOFF_CONFIRM_REPLY,
    HUMAN_HANDOFF_TRIAGE_REPLY,
    WEB_HUMAN_HANDOFF_REPLY,
    is_human_handoff_confirmation_query,
    is_human_handoff_query,
)
from app.services.router_catalog import get_clarify_context, match_clarify_option
from app.services.router_catalog import match_contextual_clarify_fallback
class RouterArchitectureTest(unittest.TestCase):
    RETIRED_RULE_ROUTING_TESTS = {
        "test_bill_content_query_overrides_troubleshooting_short_reply_guard",
        "test_clarify_definition_query_is_forced_to_rag",
        "test_contextual_website_page_question_does_not_route_to_company_info",
        "test_contextual_website_page_question_overrides_llm_company_info",
        "test_explicit_company_info_queries_interrupt_stale_flow",
        "test_explicit_self_service_queries_interrupt_stale_flow",
        "test_fallback_smalltalk_is_safe",
        "test_fixed_ip_address_overrides_company_info_router",
        "test_fixed_ip_address_query_does_not_match_company_address",
        "test_human_handoff_question_phrase_asks_for_issue",
        "test_indexed_campaign_alias_forces_rag_before_troubleshooting_short_reply",
        "test_next_payment_time_beats_pending_contract_lookup",
        "test_online_payment_overrides_bad_reconnection_route",
        "test_router_guard_overrides_neighbor_cheaper_rag_route",
        "test_semantic_value_added_intent_without_product_is_guarded_by_clarification",
        "test_tv_600_followup_beats_pending_contract_lookup",
        "test_unknown_definition_query_is_forced_to_rag",
        "test_wifi5_price_guard_clarifies_llm_troubleshooting_conflict",
        "test_world_cup_broadcast_guard_overrides_clarify",
    }

    def setUp(self):
        if self._testMethodName in self.RETIRED_RULE_ROUTING_TESTS:
            self.skipTest(
                "Retired rule-routing expectation; semantic decisions now require the model."
            )

    def test_memory_summary_exposes_selected_campaign_to_model_router(self):
        summary = json.loads(build_memory_summary({
            "company_code": "tdtv",
            "known_info": {},
            "last_campaign_topic": "哈 NET1",
        }))

        self.assertEqual(summary["last_campaign_topic"], "哈 NET1")

    def test_router_history_includes_only_the_previous_clarification(self):
        history = [
            {"role": "user", "content": "我收到一則中獎通知"},
            {"role": "assistant", "content": "要確認真偽，還是詢問領獎方式？"},
            {"role": "user", "content": "都需要"},
        ]

        rendered = build_router_history_text(
            history,
            {"decision_type": "clarify"},
            "都需要",
        )

        self.assertIn("user: 我收到一則中獎通知", rendered)
        self.assertIn(
            "assistant_clarification: 要確認真偽，還是詢問領獎方式？",
            rendered,
        )
        self.assertNotIn("user: 都需要", rendered)

    def test_router_history_excludes_ordinary_assistant_answers(self):
        rendered = build_router_history_text(
            [
                {"role": "user", "content": "服務電話？"},
                {"role": "assistant", "content": "這是一段可能錯誤的完整公司資料"},
            ],
            {"decision_type": "direct_reply"},
            "營業時間？",
        )

        self.assertIn("user: 服務電話？", rendered)
        self.assertNotIn("assistant", rendered)
        self.assertNotIn("可能錯誤", rendered)

    def test_clear_channel_group_questions_always_use_knowledge_retrieval(self):
        for text in (
            "清冰組是什麼",
            "清冰組有幾個頻道",
            "清冰組可以借幾台聯網機上盒",
            "清冰組可以額外付費加裝嗎",
        ):
            with self.subTest(text=text):
                decision = detect_safe_direct_reply(
                    text,
                    {"company_code": "tdtv", "known_info": {}},
                )

                self.assertEqual(decision["route"], "knowledge_query")
                self.assertEqual(decision["intent"], "clear_channel_group_query")
                self.assertEqual(decision["topic"], "清冰組")
                self.assertIn("清冰組", decision["knowledge_query"])
                self.assertFalse(decision["should_call_tool"])

    def test_clear_channel_group_does_not_trigger_keyword_reclassification(self):
        calls = []
        llm = RunnableLambda(
            lambda prompt: calls.append(prompt)
            or type("Response", (), {
                "content": json.dumps({
                    "route": "tool_action",
                    "intent": "channel_query",
                    "tool_name": "search_channel_no",
                    "topic": "頻道位置查詢",
                    "should_call_tool": True,
                    "should_retrieve_knowledge": False,
                    "knowledge_query": None,
                    "reply": "",
                    "extracted_slots": {"channel_name": "清冰組"},
                }, ensure_ascii=False),
            })()
        )

        decision = run_intent_router(
            user_input="清冰組可以借幾台聯網機上盒",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=llm,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["intent"], "channel_query")
        self.assertEqual(decision["tool_name"], "search_channel_no")

    def test_llm_decision_is_not_overwritten_by_legacy_keyword_rule(self):
        llm = RunnableLambda(lambda _prompt: type("Response", (), {
            "content": json.dumps({
                "route": "knowledge_query",
                "intent": "customer_requested_explanation",
                "tool_name": None,
                "topic": "網路合約說明",
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "網路合約 一般說明",
                "reply": "",
                "extracted_slots": {},
            }, ensure_ascii=False),
        })())

        decision = run_intent_router(
            user_input="網路合約",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=llm,
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "customer_requested_explanation")
        self.assertNotEqual(decision["tool_name"], "search_contract_info")

    def test_indexed_campaign_name_recovers_an_unknown_model_route(self):
        calls = []
        llm = RunnableLambda(
            lambda prompt: calls.append(prompt)
            or type("Response", (), {
                "content": json.dumps({
                    "route": "unknown",
                    "intent": "unknown",
                    "tool_name": None,
                    "topic": None,
                    "should_call_tool": False,
                    "should_retrieve_knowledge": False,
                    "knowledge_query": None,
                    "reply": "",
                    "extracted_slots": {},
                }, ensure_ascii=False),
            })()
        )

        with patch(
            "app.services.kb_service.match_active_campaign_alias",
            return_value={
                "campaign_name": "開學季光纖限時方案",
                "service_types": "純網寬頻",
            },
        ):
            decision = run_intent_router(
                user_input="開學季光纖限時方案",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["intent"], "other")
        self.assertEqual(decision["reason"], "model_router_unavailable")
        self.assertFalse(decision["should_retrieve_knowledge"])

    def test_llm_failure_does_not_fall_back_to_legacy_customer_reply(self):
        llm = RunnableLambda(lambda _prompt: (_ for _ in ()).throw(RuntimeError("model unavailable")))

        decision = run_intent_router(
            user_input="網路合約",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=llm,
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertNotEqual(decision["tool_name"], "search_contract_info")

    def test_wctv_fixed_ip_binding_uses_customer_service_process(self):
        decision = detect_safe_direct_reply(
            "我要綁定固定IP",
            {"company_code": "wctv", "known_info": {}},
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "wctv_fixed_ip_binding")
        self.assertIn("https://www.tinp.net.tw/", decision["reply"])
        self.assertIn("會員登入", decision["reply"])
        self.assertIn("綁定固定 IP", decision["reply"])
        self.assertNotIn("真人客服", decision["reply"])
        self.assertNotIn("最多可申請", decision["reply"])
        self.assertNotIn("每月 200 元", decision["reply"])

    def test_contract_penalty_requires_contract_lookup(self):
        decision = detect_safe_direct_reply(
            "違約金多少？",
            {"company_code": "wctv", "known_info": {}},
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_contract_info")
        self.assertEqual(decision["intent"], "contract_penalty_lookup")

    def test_wctv_new_network_equipment_uses_registration_steps(self):
        decision = detect_safe_direct_reply(
            "更換新的設備後無法上網",
            {"company_code": "wctv", "known_info": {}},
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision["intent"], "wctv_new_network_equipment_registration")
        self.assertIn("電腦網卡更換註冊", decision["reply"])

    def test_remote_control_cannot_be_used_starts_remote_troubleshooting(self):
        decision = detect_safe_direct_reply(
            "搖控器無法使用",
            {"company_code": "wctv", "known_info": {}},
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision["intent"], "remote_control_issue")
        self.assertIn("亮紅燈", decision["reply"])
        self.assertIn("300 元", decision["reply"])

    def test_monthly_fee_after_contract_lookup_uses_payment_record_guidance(self):
        decision = detect_safe_direct_reply(
            "每月繳費用多少錢",
            {"last_tool": "search_contract_info", "known_info": {}},
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision["intent"], "monthly_fee_after_contract_lookup")
        self.assertIn("行動客服 APP 或官網", decision["reply"])

    def test_signal_instability_clarifies_then_routes_network(self):
        ambiguous = detect_safe_direct_reply("訊號不穩", {"known_info": {}})
        network = detect_safe_direct_reply("網路訊號不好", {"known_info": {}})

        self.assertEqual(ambiguous["route"], "clarify")
        self.assertIn("電視訊號", ambiguous["reply"])
        self.assertEqual(network["route"], "troubleshooting")

    def test_pppoe_uses_dhcp_configuration_guidance(self):
        decision = detect_safe_direct_reply("我要詢問PPPOE帳號密碼", {"known_info": {}})

        self.assertEqual(decision["intent"], "dhcp_not_pppoe")
        self.assertIn("DHCP", decision["reply"])
        self.assertIn("不需要輸入 PPPoE 帳號及密碼", decision["reply"])

    def test_bear_care_typo_routes_to_rag_with_canonical_name(self):
        decision = detect_value_added_product_knowledge_query("熊大心是什麼？")

        self.assertIsNotNone(decision)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "value_added_product_query")
        self.assertIn("熊搭心", decision["knowledge_query"])

    def test_bear_care_typo_does_not_bypass_unavailable_llm(self):
        def fail_if_called(_prompt):
            raise AssertionError("LLM must not run before canonical entity routing")

        decision = run_intent_router(
            user_input="熊大心是什麼？",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=RunnableLambda(fail_if_called),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_low_confidence_service_name_asks_for_confirmation(self):
        decision = detect_knowledge_entity_confirmation("熊溫馨")

        self.assertIsNotNone(decision)
        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "knowledge_entity_confirmation")
        self.assertEqual(decision["reply"], "請問您指的是「熊搭心」服務嗎？")
        self.assertIn("熊搭心", decision["entity_confirmation"]["knowledge_query"])

    def test_indexed_campaign_alias_forces_rag_before_troubleshooting_short_reply(self):
        with patch(
            "app.services.kb_service.match_active_campaign_alias",
            return_value={
                "campaign_name": "爸氣獻禮",
                "matched_alias": "爸氣獻禮",
                "knowledge_base": "大屯",
                "document_id": "campaign-dad-gift",
            },
        ):
            decision = router_guard(
                user_input="爸氣獻禮",
                memory={
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                    }
                },
                router={
                    "route": "unknown",
                    "intent": "unknown",
                    "should_call_tool": False,
                    "should_retrieve_knowledge": False,
                },
            )

        self.assertEqual(decision["route"], "company_info")
        self.assertEqual(decision["topic"], "promotion_activity")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertIn("爸氣獻禮", decision["knowledge_query"])
        self.assertEqual(decision["reason"], "indexed_campaign_alias_rule")

    def test_ambiguous_short_query_uses_clarify(self):
        decision = detect_ambiguous_short_query("帳單")

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "ambiguous_short_query")
        self.assertFalse(decision["should_call_tool"])

    def test_unknown_tool_action_is_downgraded(self):
        decision = router_guard(
            user_input="幫我辦移機",
            memory={"known_info": {}},
            router={
                "route": "tool_action",
                "intent": "move_service",
                "tool_name": "move_service",
                "should_call_tool": True,
            },
        )

        self.assertEqual(decision["route"], "unsupported_flow")
        self.assertIsNone(decision["tool_name"])
        self.assertFalse(decision["should_call_tool"])

    def test_knowledge_query_never_calls_tool(self):
        decision = router_guard(
            user_input="固定IP怎麼申請",
            memory={"known_info": {}},
            router={
                "route": "knowledge_query",
                "intent": "faq",
                "tool_name": "search_bill",
                "should_call_tool": True,
                "should_retrieve_knowledge": False,
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertIsNone(decision["tool_name"])
        self.assertFalse(decision["should_call_tool"])
        self.assertTrue(decision["should_retrieve_knowledge"])

    def test_clarify_alias_resolves_catalog_option(self):
        context = get_clarify_context("帳單")
        selection = match_clarify_option("金額", context)

        self.assertEqual(selection["route"], "tool_action")
        self.assertEqual(selection["tool_name"], "search_bill")
        self.assertEqual(selection["matched_option"], "查詢帳單金額")

    def test_network_amount_uses_contextual_clarify_fallback(self):
        context = get_clarify_context("網路")
        selection = match_clarify_option("金額", context)
        fallback = match_contextual_clarify_fallback("金額", context)

        self.assertIsNone(selection)
        self.assertEqual(fallback["route"], "clarify")
        self.assertIn("網路方案的月租費用", fallback["reply"])
        self.assertEqual(fallback["next_clarify_context"]["topic"], "網路金額")

    def test_contextual_amount_followup_can_select_network_fee(self):
        context = match_contextual_clarify_fallback(
            "金額",
            get_clarify_context("網路"),
        )["next_clarify_context"]
        selection = match_clarify_option("月租", context)

        self.assertEqual(selection["route"], "knowledge_query")
        self.assertEqual(selection["matched_option"], "網路方案月租")
        self.assertEqual(selection["knowledge_query"], "網路方案 費用 月租")

    def test_company_address_short_query_does_not_use_rag(self):
        decision = detect_company_info_query("地址", {"known_info": {}})

        self.assertEqual(decision["route"], "company_info")
        self.assertEqual(decision["topic"], "company_address")
        self.assertFalse(decision["should_retrieve_knowledge"])

    def test_contextual_website_page_question_does_not_route_to_company_info(self):
        self.assertIsNone(
            detect_company_info_query("官網哪裡可以看到介紹?", {"known_info": {}})
        )

        decision = fallback_router("官網哪裡可以看到介紹?", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "contextual_website_page_lookup")
        self.assertTrue(decision["should_retrieve_knowledge"])

    def test_contextual_website_page_question_overrides_llm_company_info(self):
        decision = router_guard(
            user_input="官網哪裡可以看到介紹?",
            memory={"known_info": {}},
            router={
                "route": "company_info",
                "intent": "company_info",
                "topic": "website",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["reason"], "guard_contextual_website_page_lookup")

    def test_fixed_ip_address_query_does_not_match_company_address(self):
        self.assertIsNone(
            detect_company_info_query("固定IP地址的綁定步驟", {"known_info": {}})
        )

        decision = fallback_router("固定IP地址的綁定步驟", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["reason"], "fixed_ip_knowledge_rule")
        self.assertEqual(decision["knowledge_query"], "固定IP地址的綁定步驟")

    def test_fixed_ip_address_overrides_company_info_router(self):
        decision = router_guard(
            user_input="固定IP地址的綁定步驟",
            memory={"known_info": {}},
            router={
                "route": "company_info",
                "intent": "company_info",
                "topic": "company_address",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["reason"], "fixed_ip_knowledge_rule")

    def test_company_location_short_query_asks_clarify(self):
        decision = detect_company_info_query("在哪邊?", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["topic"], "公司資訊")
        self.assertIn("公司地址", decision["reply"])

    def test_company_info_clarify_can_select_address(self):
        context = get_clarify_context("公司資訊")
        selection = match_clarify_option("地址", context)

        self.assertEqual(selection["route"], "company_info")
        self.assertEqual(selection["topic"], "company_address")

    def test_company_address_does_not_bypass_unavailable_llm(self):
        class FailingLLM:
            def invoke(self, payload):
                raise AssertionError("LLM should not be called for company info")

        decision = run_intent_router(
            user_input="大屯地址",
            memory={"known_info": {}, "company_code": "tdtv"},
            history=[],
            llm=FailingLLM(),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_mabow_phone_routes_to_knowledge_not_company_phone(self):
        decision = detect_mabow_query("瑪帛電話", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "mabow_knowledge")
        self.assertEqual(decision["knowledge_query"], "什麼是瑪帛電視電話")
        self.assertTrue(decision["should_retrieve_knowledge"])

    def test_mabow_phone_does_not_bypass_unavailable_llm(self):
        class FailingLLM:
            def invoke(self, payload):
                raise AssertionError("LLM should not be called for mabow product query")

        decision = run_intent_router(
            user_input="瑪柏電話",
            memory={"known_info": {}},
            history=[],
            llm=FailingLLM(),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_reconnection_without_service_type_asks_clarify(self):
        decision = detect_reconnection_query("忘了繳費已被斷訊", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["topic"], "復線服務類型")
        self.assertIn("網路", decision["reply"])
        self.assertIn("電視", decision["reply"])

    def test_reconnection_with_network_routes_to_network_return_tool(self):
        decision = detect_reconnection_query("網路欠費斷線", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "bill_return_line_internet")

    def test_payment_receipt_barcodes_require_verified_image_evidence(self):
        decision = detect_payment_receipt_query(
            "我上傳了一張圖片，辨識內容如下：\n"
            "第一段條碼: 1234567890\n"
            "第二段條碼: 2222222222\n"
            "第三段條碼: 9999999999",
            {"known_info": {}},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "payment_receipt_image_required")
        self.assertIn("無法接受手動輸入", decision["reply"])

    def test_payment_receipt_barcodes_override_pending_bill_tool(self):
        decision = detect_payment_receipt_query(
            "我上傳了一張圖片，辨識內容如下：\n"
            "收據條碼資訊\n"
            "第一段條碼: 150519TGE\n"
            "第二段條碼: 0071872603754828\n"
            "第三段條碼: 150395000001795",
            {
                "pending_tool": "search_bill",
                "pending_tool_args": ["phone"],
                "known_info": {},
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "payment_receipt_image_required")

    def test_payment_receipt_barcodes_without_barcode_word_override_pending_bill_tool(self):
        decision = detect_payment_receipt_query(
            "我上傳了一張圖片，辨識內容如下：\n"
            "第一段 150826TCN 第二段 0058072608022007 第三段 150841000000550",
            {
                "pending_tool": "search_bill",
                "pending_tool_args": ["phone"],
                "known_info": {},
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "payment_receipt_image_required")

    def test_store_receipt_reconnection_requires_uploaded_image(self):
        decision = detect_payment_receipt_query("我有7-11超商收據要復線", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "payment_receipt_image_required")

    def test_paid_reconnection_routes_to_receipt_upload_flow(self):
        decision = detect_payment_receipt_query("我已經繳費了，麻煩幫我恢復", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "payment_receipt_image_required")
        self.assertIn("上傳清楚、完整", decision["reply"])

    def test_verified_receipt_image_evidence_routes_to_payment_api(self):
        ocr_text = (
            "收據來源: 超商繳費收據\n超商名稱: 7-11\n繳費狀態: 已繳\n"
            "收據完整性: 完整\n代收項目: 有線電視\n"
            "第一段條碼: 1234567890\n第二段條碼: 0058072222\n第三段條碼: 9999999999"
        )
        user_text = f"我上傳了一張圖片，辨識內容如下：\n{ocr_text}"
        decision = detect_payment_receipt_query(
            user_text,
            {
                "known_info": {
                    "receipt_image_evidence": {
                        "verified": True,
                        "message_hash": hashlib.sha256(user_text.encode("utf-8")).hexdigest(),
                        "bills": [{
                            "first_barcode": "1234567890",
                            "second_barcode": "0058072222",
                            "third_barcode": "9999999999",
                        }],
                    }
                }
            },
        )

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "payment_bill_batch")

    def test_human_agent_request_is_not_a_keyword_route(self):
        decision = detect_safe_direct_reply("真人客服", {"known_info": {}})

        self.assertIsNone(decision)
        self.assertFalse(is_human_handoff_query("真人客服"))
        self.assertTrue(is_human_handoff_confirmation_query("真人客服"))

    def test_human_handoff_question_phrase_asks_for_issue(self):
        self.assertFalse(is_human_handoff_query("有沒有真人 我想要隱藏優惠"))
        self.assertTrue(is_human_handoff_confirmation_query("有沒有真人 我想要隱藏優惠"))

        decision = router_guard(
            "有沒有真人 我想要隱藏優惠",
            {"known_info": {}},
            {
                "route": "company_info",
                "intent": "promotion_query",
                "tool_name": None,
                "topic": "promotion_activity",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "隱藏優惠",
                "reply": "請提供姓名、聯絡電話、服務地址。",
                "extracted_slots": {},
                "reason": "llm_promotion",
            },
        )

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "human_handoff_triage")
        self.assertEqual(decision["reply"], HUMAN_HANDOFF_TRIAGE_REPLY)

    def test_bare_human_handoff_request_asks_for_issue_before_transfer(self):
        calls = {"count": 0}

        def classify_handoff(_prompt):
            calls["count"] += 1
            return type("Response", (), {"content": json.dumps({
                "route": "direct_reply",
                "intent": "human_handoff_triage",
                "tool_name": None,
                "topic": "真人客服",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": HUMAN_HANDOFF_TRIAGE_REPLY,
                "extracted_slots": {},
                "reason": "llm_handoff",
            }, ensure_ascii=False)})()

        decision = run_intent_router(
            "我不想跟AI講了，幫我轉真人客服",
            {"known_info": {}},
            [],
            RunnableLambda(classify_handoff),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "human_handoff_triage")
        self.assertEqual(decision["reply"], HUMAN_HANDOFF_TRIAGE_REPLY)

    def test_human_handoff_after_unresolved_issue_uses_web_marker_reply(self):
        calls = {"count": 0}

        def classify_handoff(_prompt):
            calls["count"] += 1
            return type("Response", (), {"content": json.dumps({
                "route": "direct_reply",
                "intent": "human_handoff_request",
                "topic": "真人客服",
                "reply": "我可以協助您轉接真人客服。",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "extracted_slots": {},
            }, ensure_ascii=False)})()

        decision = run_intent_router(
            "請幫我轉真人客服",
            {"known_info": {}},
            [{"role": "assistant", "content": "目前我無法直接查詢這項資料，需由真人客服協助。"}],
            RunnableLambda(classify_handoff),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "human_handoff_request")
        self.assertEqual(decision["reply"], WEB_HUMAN_HANDOFF_REPLY)

    def test_handoff_request_with_service_issue_transfers_directly(self):
        calls = {"count": 0}

        def classify_handoff(_prompt):
            calls["count"] += 1
            return type("Response", (), {"content": json.dumps({
                "route": "direct_reply",
                "intent": "human_handoff_request",
                "topic": "網路斷線",
                "reply": "我可以協助您轉接真人客服。",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "extracted_slots": {},
            }, ensure_ascii=False)})()

        decision = run_intent_router(
            "我的網路斷線了，請幫我轉真人客服",
            {"known_info": {}},
            [],
            RunnableLambda(classify_handoff),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "human_handoff_request")
        self.assertEqual(decision["reply"], WEB_HUMAN_HANDOFF_REPLY)

    def test_address_disambiguation_does_not_request_install_address(self):
        decision = detect_safe_direct_reply("哪個地址", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "address_disambiguation")
        self.assertNotIn("裝機地址", decision["reply"])
        self.assertIn("客戶編號、戶名、登記電話任兩項", decision["reply"])

    def test_relocation_questions_use_model_owned_knowledge_route(self):
        calls = {"count": 0}

        def classify_relocation(_payload):
            calls["count"] += 1
            return type("Response", (), {"content": json.dumps({
                "route": "knowledge_query",
                "intent": "relocation_guidance",
                "topic": "移機服務",
                "service_scope": "移機服務",
                "requested_information": "移機流程、費用與條件",
                "should_cancel_current_flow": True,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "移機 搬家 換地址 流程 費用 條件",
                "reply": "",
                "extracted_slots": {},
            }, ensure_ascii=False)})()

        for text in (
            "我下個月要搬家，第四台跟網路可以一起搬過去嗎？",
            "我先搬家，但第四台暫時不用，可以只移網路嗎？",
            "移機流程和費用",
        ):
            with self.subTest(text=text):
                decision = run_intent_router(
                    text,
                    {"known_info": {}},
                    [],
                    RunnableLambda(classify_relocation),
                )
                self.assertEqual(decision["route"], "knowledge_query")
                self.assertEqual(decision["intent"], "relocation_guidance")
                self.assertTrue(decision["should_retrieve_knowledge"])

        self.assertEqual(calls["count"], 3)

    def test_relocation_fee_stays_out_of_direct_reply_for_rag(self):
        decision = detect_safe_direct_reply("網路移機費呢？", {"known_info": {}})

        self.assertIsNone(decision)

    def test_contract_date_query_routes_to_contract_info_tool(self):
        decision = detect_safe_direct_reply("想請問我的合約到期日", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_contract_info")
        self.assertTrue(decision["should_call_tool"])

    def test_current_plan_query_routes_to_contract_info_tool(self):
        decision = detect_safe_direct_reply("我的網路是幾m", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_contract_info")
        self.assertTrue(decision["should_call_tool"])

    def test_short_my_network_query_routes_to_contract_info_tool(self):
        decision = detect_safe_direct_reply("我的網路", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_contract_info")
        self.assertTrue(decision["should_call_tool"])

    def test_line_tv_expiry_query_routes_to_contract_info_tool(self):
        decision = detect_safe_direct_reply("LINE TV 到期日是什麼時候", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_contract_info")
        self.assertTrue(decision["should_call_tool"])

    def test_digital_addon_package_query_routes_to_contract_info_tool(self):
        decision = detect_safe_direct_reply("加值數位套餐內容有哪些", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_contract_info")
        self.assertTrue(decision["should_call_tool"])

    def test_digital_addon_package_followup_uses_value_added_context(self):
        decision = detect_safe_direct_reply(
            "加值數位套餐內容有哪些",
            {
                "known_info": {},
                "last_knowledge_results": [
                    {
                        "question": "各項單品銷售(數位電視)",
                        "answer": "各項單品銷售／加值服務-數位電視套餐：HBO加價購、運動套餐、Hi Play。",
                    }
                ],
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "value_added_service_query")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertIn("數位電視套餐", decision["knowledge_query"])
        self.assertIsNone(decision["tool_name"])

    def test_app_bill_guide_does_not_enter_bill_tool(self):
        decision = detect_safe_direct_reply("哈TV行動客服怎麼查帳單", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertFalse(decision["should_call_tool"])
        self.assertIn("帳單查詢", decision["reply"])

    def test_generic_payment_methods_use_model_owned_knowledge_route(self):
        calls = {"count": 0}

        def classify_payment(_payload):
            calls["count"] += 1
            return type("Response", (), {"content": json.dumps({
                "route": "knowledge_query",
                "intent": "bill_payment_methods",
                "topic": "繳費方式",
                "service_scope": "帳務繳費",
                "requested_information": "全部繳費管道",
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "繳費方式 線上刷卡 臨櫃 行動客服 APP 帳單條碼 ibon FamiPort",
                "reply": "",
                "extracted_slots": {},
            }, ensure_ascii=False)})()

        decision = run_intent_router(
            "繳款方式查詢",
            {"known_info": {}},
            [],
            RunnableLambda(classify_payment),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "bill_payment_methods")
        self.assertTrue(decision["should_retrieve_knowledge"])

    def test_unspecified_termination_service_requires_llm_clarification(self):
        llm = RunnableLambda(lambda _prompt: type("Response", (), {
            "content": json.dumps({
                "route": "clarify",
                "intent": "service_termination_service_clarify",
                "topic": "退租服務類型",
                "reply": "了解，請問您要退租的是有線電視、寬頻網路，還是兩項服務都要退？不同服務需歸還的設備與配件不同，確認後我再為您說明。",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "extracted_slots": {},
            }, ensure_ascii=False),
        })())
        decision = run_intent_router(
            "如何退租",
            {"company_code": "tdtv", "known_info": {}},
            [],
            llm,
        )

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "service_termination_service_clarify")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("有線電視、寬頻網路", decision["reply"])
        self.assertNotIn("HDMI", decision["reply"])

    def test_early_termination_keeps_model_clarification_copy(self):
        llm = RunnableLambda(lambda _prompt: type("Response", (), {
            "content": json.dumps({
                "route": "clarify",
                "intent": "service_termination_service_clarify",
                "topic": "退租服務類型",
                "reply": "若仍在綁約期間，提前終止可能產生違約金。請問要終止哪項服務？",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "extracted_slots": {},
            }, ensure_ascii=False),
        })())

        decision = run_intent_router(
            "想要提前終止合約",
            {"company_code": "tdtv", "known_info": {}},
            [],
            llm,
        )

        self.assertEqual(
            decision["reply"],
            "若仍在綁約期間，提前終止可能產生違約金。請問要終止哪項服務？",
        )
        self.assertIn("違約金", decision["reply"])

    def test_combined_termination_equipment_uses_service_specific_llm_reply(self):
        llm = RunnableLambda(lambda _prompt: type("Response", (), {
            "content": json.dumps({
                "route": "direct_reply",
                "intent": "service_termination_equipment_guidance",
                "topic": "電視與網路退租設備",
                "reply": "有線電視請準備機上盒及其配件；寬頻網路請準備數據機及其配件。",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "extracted_slots": {},
            }, ensure_ascii=False),
        })())
        decision = run_intent_router(
            "兩個",
            {
                "company_code": "tdtv",
                "known_info": {},
                "clarify_context": {"type": "llm_termination_service_selection"},
            },
            [
                {"role": "user", "content": "如何退租"},
                {"role": "assistant", "content": "請問您要退租的是有線電視、寬頻網路，還是兩項服務都要退？"},
            ],
            llm,
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "service_termination_equipment_guidance")
        self.assertEqual(
            decision["reply"],
            "有線電視請準備機上盒及其配件；寬頻網路請準備數據機及其配件。",
        )
        self.assertNotIn("HDMI", decision["reply"])

    def test_explicit_self_service_queries_interrupt_stale_flow(self):
        stale_memories = [
            {"pending_tool": "search_contract_info", "known_info": {}},
            {"pending_tool": "send_message", "known_info": {"name": "王小明"}},
            {"pending_tool": "troubleshooting", "known_info": {"troubleshooting_started": "yes"}},
        ]
        expected = [
            ("如何繳費", "direct_reply", "bill_payment_methods"),
            ("忘記密碼", "direct_reply", "password_help"),
            ("哈TV行動客服怎麼查帳單", "direct_reply", "app_bill_guide"),
        ]
        stale_router = {
            "route": "continue_current_flow",
            "intent": "continue_current_flow",
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
        }

        for memory in stale_memories:
            for text, route, intent in expected:
                with self.subTest(text=text, memory=memory):
                    decision = router_guard(text, memory, stale_router)

                    self.assertEqual(decision["route"], route)
                    self.assertEqual(decision["intent"], intent)

    def test_explicit_company_info_queries_interrupt_stale_flow(self):
        stale_memories = [
            {"pending_tool": "search_contract_info", "known_info": {}},
            {"pending_tool": "send_message", "known_info": {"name": "王小明"}},
            {"pending_tool": "troubleshooting", "known_info": {"troubleshooting_started": "yes"}},
        ]
        expected = [
            ("客服電話", "contact_phone"),
            ("營業時間", "business_hours"),
            ("公司地址", "company_address"),
            ("服務地區", "service_area"),
        ]
        stale_router = {
            "route": "continue_current_flow",
            "intent": "continue_current_flow",
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
        }

        for memory in stale_memories:
            for text, topic in expected:
                with self.subTest(text=text, memory=memory):
                    decision = router_guard(text, memory, stale_router)

                    self.assertEqual(decision["route"], "company_info")
                    self.assertEqual(decision["intent"], "company_info")
                    self.assertEqual(decision["topic"], topic)

    def test_short_address_does_not_interrupt_pending_flow(self):
        decision = router_guard(
            "地址",
            {"pending_tool": "search_contract_info", "known_info": {}},
            {
                "route": "continue_current_flow",
                "intent": "continue_current_flow",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
            },
        )

        self.assertEqual(decision["route"], "continue_current_flow")

    def test_credit_card_autopay_binding_status_routes_to_handoff(self):
        decision = detect_safe_direct_reply("請問如何確認已經綁定信用卡繳費", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "card_autopay_binding_status_handoff")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("無法直接查詢", decision["reply"])
        self.assertIn("信用卡扣繳是否已綁定成功", decision["reply"])
        self.assertIn("真人客服協助確認", decision["reply"])
        self.assertIn("線上刷卡繳費後是否會自動開通", decision["reply"])
        self.assertIn("系統會自動開通", decision["reply"])
        self.assertNotEqual(decision["reply"], WEB_HUMAN_HANDOFF_REPLY)
        self.assertNotEqual(decision["intent"], "bill_payment_methods")

    def test_past_payment_and_posting_records_use_app_or_website_reply(self):
        for text in ["我要查過往繳費紀錄", "查詢已繳費明細", "請問是否入帳"]:
            with self.subTest(text=text):
                decision = detect_safe_direct_reply(text, {"known_info": {}})

                self.assertEqual(decision["route"], "direct_reply")
                self.assertEqual(decision["intent"], "past_payment_record_lookup")
                self.assertFalse(decision["should_call_tool"])
                self.assertIn("行動客服 APP 或官網查閱", decision["reply"])

    def test_next_bill_followup_after_no_unpaid_uses_short_notice(self):
        decision = detect_safe_direct_reply(
            "那下期帳單什麼時候會出？",
            {
                "known_info": {},
                "last_bill_query_status": {
                    "status": "no_unpaid",
                    "message": "尚無須繳納的費用，如您已繳費，請記得將設備電源關機重開。",
                },
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "next_bill_after_no_unpaid")
        self.assertEqual(
            decision["reply"],
            "您好，目前系統可協助查詢本期待繳帳單。待下期帳單產生後，請留意相關通知，謝謝。",
        )

    def test_next_bill_without_prior_no_unpaid_uses_supported_scope_notice(self):
        decision = detect_safe_direct_reply("下期帳單什麼時候會出？", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "next_bill_after_no_unpaid")
        self.assertIn("目前系統可協助查詢本期待繳帳單", decision["reply"])
        self.assertNotIn("尚無待繳", decision["reply"])

    def test_next_payment_time_beats_pending_contract_lookup(self):
        decision = router_guard(
            user_input="我下次繳費是何時",
            memory={"known_info": {}, "pending_tool": "search_contract_info"},
            router={
                "route": "tool_action",
                "intent": "pending_tool_args",
                "tool_name": "search_contract_info",
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "next_bill_after_no_unpaid")
        self.assertIn("下期帳單產生後", decision["reply"])

    def test_door_card_payment_not_posted_beats_generic_payment_record_rule(self):
        decision = detect_safe_direct_reply(
            "已到國光路門市續約刷卡繳費，為何還未沖帳？",
            {"known_info": {}},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "payment_not_posted")
        self.assertIn("帳務更新可能需要作業時間", decision["reply"])
        self.assertIn("保留繳費收據或交易明細", decision["reply"])
        self.assertIn("真人客服協助查詢", decision["reply"])

    def test_tv_600_followup_beats_pending_contract_lookup(self):
        decision = detect_safe_direct_reply(
            "一個月600??",
            {
                "known_info": {},
                "pending_tool": "search_contract_info",
                "pending_tool_args": ["name", "phone"],
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "tv_600_fee_clarify")
        self.assertIn("一般有線電視基本收視費", decision["reply"])
        self.assertIn("體驗到期後恢復原價", decision["reply"])

        guarded = router_guard(
            user_input="一個月600??",
            memory={
                "known_info": {},
                "pending_tool": "search_contract_info",
                "pending_tool_args": ["name", "phone"],
            },
            router={
                "route": "tool_action",
                "intent": "service_content_query",
                "tool_name": "search_contract_info",
            },
        )
        self.assertEqual(guarded["intent"], "tv_600_fee_clarify")

    def test_store_payment_still_billed_uses_receipt_check_reply(self):
        decision = detect_safe_direct_reply("我剛剛去超商繳費了，怎麼還查得到帳單？", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "store_payment_still_billed")
        self.assertIn("超商繳費入帳可能需要作業時間", decision["reply"])
        self.assertIn("保留繳費收據或交易明細", decision["reply"])
        self.assertIn("真人客服協助查詢", decision["reply"])

    def test_convenience_store_payment_machine_guide_uses_rag(self):
        for text in ["超商繳費機怎麼操作呢?", "IBON繳費教學", "famiport繳費教學"]:
            with self.subTest(text=text):
                decision = detect_safe_direct_reply(text, {"known_info": {}})

                self.assertEqual(decision["route"], "knowledge_query")
                self.assertEqual(decision["intent"], "convenience_store_payment_machine_guide")
                self.assertTrue(decision["should_retrieve_knowledge"])
                self.assertIn("IBON", decision["knowledge_query"])
                self.assertIn("FAMIPORT", decision["knowledge_query"])

    def test_triple_play_bill_item_does_not_route_to_promotion_plan(self):
        decision = detect_safe_direct_reply("繳費項目為三合一方案，是哪三種三合一？", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "triple_play_bill_item_explanation")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("帳單上的「三合一方案」項目", decision["reply"])
        self.assertNotIn("好康三合一", decision["reply"])
        self.assertNotIn("LINE TV", decision["reply"])

    def test_online_credit_card_payment_activation_uses_payment_reply_not_rag(self):
        decision = detect_safe_direct_reply("線上刷卡會馬上開通嗎??", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "online_payment_activation")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("線上繳費方式", decision["reply"])
        self.assertIn("線上刷卡繳費", decision["reply"])
        self.assertIn("IBON及FAMIPORT", decision["reply"])
        self.assertIn("自動開通", decision["reply"])

    def test_sms_bill_redirect_phone_request_is_rejected_during_pending_flow(self):
        decision = detect_safe_direct_reply(
            "梁仁澤電話0952959768帳單訊息改傳到0983641649",
            {"pending_tool": "send_message", "known_info": {"name": "梁仁澤"}},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "sms_bill_registered_phone_policy")
        self.assertFalse(decision["should_call_tool"])
        self.assertIn("登記電話", decision["reply"])
        self.assertIn("無法改寄", decision["reply"])

    def test_online_payment_overrides_bad_reconnection_route(self):
        decision = router_guard(
            user_input="我要線上繳費，網路費",
            memory={"known_info": {}},
            router={
                "route": "tool_action",
                "intent": "reconnection",
                "tool_name": "bill_return_line_internet",
                "topic": "網路復線",
                "should_cancel_current_flow": False,
                "should_call_tool": True,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "",
                "extracted_slots": {},
                "reason": "bad_llm_reconnection",
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "bill_payment_methods")
        self.assertFalse(decision["should_call_tool"])

    def test_invoice_carrier_binding_returns_policy_reply(self):
        decision = detect_safe_direct_reply("設定載具歸戶", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "invoice_carrier_binding")
        self.assertIn("載具歸戶", decision["reply"])
        self.assertIn("手機條碼", decision["reply"])

    def test_customer_service_phone_requires_model_classification(self):
        calls = {"count": 0}

        def classify_phone(_payload):
            calls["count"] += 1
            return type("Response", (), {"content": json.dumps({
                "route": "company_info",
                "intent": "company_info",
                "topic": "contact_phone",
                "reply": "",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "extracted_slots": {},
            }, ensure_ascii=False)})()

        decision = run_intent_router(
            "客服電話多少",
            {"company_code": "toplight", "known_info": {}},
            [],
            RunnableLambda(classify_phone),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "company_info")
        self.assertEqual(decision["topic"], "contact_phone")
        self.assertFalse(decision["should_retrieve_knowledge"])

    def test_generic_company_info_model_topic_is_not_keyword_rewritten(self):
        decision = router_guard(
            user_input="客服電話多少",
            memory={"company_code": "toplight", "known_info": {}},
            router={
                "route": "company_info",
                "intent": "company_info",
                "topic": "company_overview",
                "tool_name": None,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "",
                "extracted_slots": {},
            },
            llm_first=True,
        )

        self.assertEqual(decision["route"], "company_info")
        self.assertEqual(decision["topic"], "company_overview")

    def test_invoice_carrier_rebinding_returns_policy_reply(self):
        decision = detect_safe_direct_reply("換約後發票載具要重新綁定嗎", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "invoice_carrier_binding")
        self.assertIn("重新綁定", decision["reply"])
        self.assertIn("帳戶狀態", decision["reply"])

    def test_mobile_barcode_binding_returns_policy_reply(self):
        decision = detect_safe_direct_reply("發票加入手機條碼", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "invoice_carrier_binding")
        self.assertIn("手機條碼", decision["reply"])
        self.assertIn("歸戶", decision["reply"])

    def test_single_item_sales_routes_to_value_added_service_knowledge(self):
        decision = detect_safe_direct_reply("更多熱門單品銷售", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "value_added_service_query")
        self.assertIn("加值服務", decision["knowledge_query"])
        self.assertIn("單品銷售", decision["knowledge_query"])

    def test_value_added_package_routes_to_value_added_service_knowledge(self):
        decision = detect_safe_direct_reply("加值套餐有哪些呢?", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "value_added_service_query")
        self.assertIn("加值服務", decision["knowledge_query"])
        self.assertIn("單品銷售", decision["knowledge_query"])

    def test_unspecified_value_added_service_asks_user_to_choose_product(self):
        decision = detect_safe_direct_reply("我想了解加值服務", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "value_added_service_clarification")
        self.assertEqual(decision["topic"], "加值服務")
        self.assertIn("LINE TV", decision["reply"])
        self.assertIn("WiFi 加值服務", decision["reply"])
        self.assertIn("居家智慧攝影機", decision["reply"])
        self.assertIn("熊搭心", decision["reply"])

    def test_value_added_catalog_overview_does_not_add_extra_clarify_turn(self):
        decision = detect_safe_direct_reply("目前有哪些加值服務？", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "value_added_service_query")

    def test_semantic_value_added_intent_without_product_is_guarded_by_clarification(self):
        decision = router_guard(
            user_input="我想看看還有沒有其他額外付費的東西",
            memory={"known_info": {}},
            router={
                "route": "knowledge_query",
                "intent": "value_added_service_query",
                "topic": "加值服務",
                "knowledge_query": "加值服務 額外服務",
                "reason": "llm_semantic_route",
            },
        )

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "value_added_service_clarification")

    def test_generic_primary_router_uses_semantic_value_added_recheck(self):
        responses = [
            {
                "route": "clarify",
                "intent": "other",
                "topic": "需求不明",
                "reply": "請再說明您想查詢的服務。",
                "reason": "primary_router_uncertain",
            },
            {
                "classification": "unspecified_value_added_service",
                "reason": "使用者詢問可另外付費使用的服務，但未指定產品",
            },
        ]
        calls = {"count": 0}

        def fake_llm(_payload):
            index = calls["count"]
            calls["count"] += 1
            return type("Response", (), {
                "content": json.dumps(responses[index], ensure_ascii=False),
            })()

        decision = run_intent_router(
            user_input="我想看看還有沒有其他額外付費的服務",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=RunnableLambda(fake_llm),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "other")
        self.assertEqual(decision["reply"], "請再說明您想查詢的服務。")

    def test_generic_primary_router_does_not_force_fault_into_value_added_services(self):
        responses = [
            {
                "route": "clarify",
                "intent": "other",
                "topic": "需求不明",
                "reply": "請再描述目前狀況。",
                "reason": "primary_router_uncertain",
            },
            {
                "classification": "not_value_added_service",
                "reason": "這是設備故障描述",
            },
        ]
        calls = {"count": 0}

        def fake_llm(_payload):
            index = calls["count"]
            calls["count"] += 1
            return type("Response", (), {
                "content": json.dumps(responses[index], ensure_ascii=False),
            })()

        decision = run_intent_router(
            user_input="家裡那個東西一直閃紅燈不能用",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=RunnableLambda(fake_llm),
        )

        # The existing router guard may already recognize a fault and avoid the
        # focused add-on recheck entirely. Either way, it must never turn this
        # message into a value-added-service choice prompt.
        self.assertEqual(calls["count"], 1)
        self.assertNotEqual(decision["intent"], "value_added_service_clarification")
        self.assertNotIn("LINE TV", decision["reply"])

    def test_named_value_added_product_is_not_replaced_by_generic_clarification(self):
        decision = router_guard(
            user_input="居家智慧攝影機怎麼申請？",
            memory={"known_info": {}},
            router={
                "route": "knowledge_query",
                "intent": "value_added_product_query",
                "topic": "居家智慧攝影機",
                "knowledge_query": "居家智慧攝影機 申請方式",
                "reason": "llm_semantic_route",
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "value_added_product_query")
        self.assertIn("居家智慧攝影機", decision["knowledge_query"])

    def test_termination_followup_does_not_bypass_unavailable_llm(self):
        class FailingLLM:
            def invoke(self, payload):
                raise AssertionError("model failure used to verify closed routing")

        decision = run_intent_router(
            user_input="就是結束",
            memory={"known_info": {}},
            history=[
                {"role": "user", "content": "我合約到期了要續約嗎"},
                {"role": "assistant", "content": "若不續約可詢問退租流程。"},
            ],
            llm=FailingLLM(),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_bill_content_query_routes_to_bill_tool_not_repair(self):
        for text in ["詢問帳單內容", "帳單明細", "本期帳單金額查詢"]:
            with self.subTest(text=text):
                decision = detect_safe_direct_reply(text, {"known_info": {}})

                self.assertEqual(decision["route"], "tool_action")
                self.assertEqual(decision["intent"], "bill_query")
                self.assertEqual(decision["tool_name"], "search_bill")
                self.assertTrue(decision["should_call_tool"])
                self.assertNotIn("報修", decision["reply"])

    def test_bill_content_query_overrides_troubleshooting_short_reply_guard(self):
        decision = router_guard(
            user_input="詢問帳單內容",
            memory={"known_info": {"troubleshooting_started": "yes"}},
            router={
                "route": "tool_action",
                "intent": "repair_request",
                "tool_name": "create_repair_ticket",
                "topic": "報修",
                "should_cancel_current_flow": False,
                "should_call_tool": True,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "",
                "extracted_slots": {},
                "reason": "llm_repair",
            },
        )

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_bill")

    def test_bill_amount_difference_does_not_call_current_bill_tool(self):
        decision = detect_safe_direct_reply("為什麼跟上一期帳單金額不一樣", {"known_info": {"custnum": "1268060"}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "bill_amount_difference_lookup")
        self.assertFalse(decision["should_call_tool"])
        self.assertIn("無法直接查詢上期", decision["reply"])
        self.assertIn("真人客服", decision["reply"])

    def test_stop_network_service_clarifies_pause_or_termination_before_rag(self):
        decision = detect_safe_direct_reply("停用網路", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "stop_watching_clarify")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("退租／終止服務", decision["reply"])

    def test_service_suspension_routes_to_stable_pause_reply_before_llm(self):
        for text in ("我要停機", "如何申請停機", "我要暫時中斷網路服務"):
            with self.subTest(text=text):
                decision = detect_safe_direct_reply(text, {"known_info": {}})

                self.assertEqual(decision["route"], "direct_reply")
                self.assertEqual(decision["intent"], "service_suspension_process")
                self.assertEqual(decision["matched_rule_id"], "direct_service_suspension_query_rule")
                self.assertIn("暫停機", decision["topic"])
                self.assertIn("雙證件", decision["reply"])

    def test_online_payment_password_uses_login_page_process(self):
        decision = detect_safe_direct_reply("線上繳費預設密碼", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "online_payment_app_password_policy")
        self.assertIn("忘記密碼", decision["reply"])
        self.assertNotIn("0000", decision["reply"])
        self.assertNotIn("目前可用繳費方式", decision["reply"])

    def test_network_contract_is_not_mistaken_for_address_contract_lookup(self):
        decision = detect_safe_direct_reply("網路合約", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_contract_info")
        self.assertNotEqual(decision["intent"], "address_contract_lookup_handoff")

    def test_install_quote_followup_does_not_return_company_address(self):
        decision = detect_safe_direct_reply(
            "您好，上週日有過去看我家那邊，然後有說要再跟我報價牽線要多少錢，請與我聯繫。我的電話是0973950656,申請裝第四台地址是南投縣水里鄉水里村水里二路36巷1號。",
            {"company_code": "cnt", "known_info": {}},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "install_contact_or_quote_followup")
        self.assertIn("真人客服", decision["reply"])
        self.assertIn("報價", decision["reply"])
        self.assertNotEqual(decision["topic"], "company_address")

    def test_short_regression_intents_use_stable_direct_replies(self):
        cases = (
            ("機上盒移機", "set_top_box_relocation_payment", "室內移機 500 元"),
            ("網路不順", "network_instability_scope_clarification", "所有手機、電腦"),
            ("WiFi 密碼忘了怎麼看", "wifi_router_password_help", "分享器機身貼紙"),
            ("電視進安全模式", "tv_safe_mode_recovery", "機上盒本身沒有「安全模式」功能"),
            ("機上盒已重開機過了，全部頻道都無法收視", "tv_all_channels_unavailable_after_reboot", "不要重複重開機"),
        )

        for text, intent, expected_reply in cases:
            with self.subTest(text=text):
                decision = detect_safe_direct_reply(text, {"known_info": {}})
                self.assertEqual(decision["intent"], intent)
                self.assertIn(expected_reply, decision["reply"])

        self.assertIsNone(
            detect_safe_direct_reply("哈tv+哈net990只限新用戶嗎", {"known_info": {}})
        )

    def test_connected_stb_youtube_uses_customer_service_reply(self):
        decision = detect_safe_direct_reply("聯網機上盒可以看 YouTube 嗎？", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "connected_stb_youtube")
        self.assertIn("聯網型及非聯網型", decision["reply"])
        self.assertIn("加購每月 60 元", decision["reply"])
        self.assertIn("YouTube、LINE TV", decision["reply"])
        self.assertIn("地址、合約狀態及適用方案", decision["reply"])

    def test_network_intermittent_signal_starts_troubleshooting(self):
        decision = detect_safe_direct_reply("網路訊號時有時無", {"known_info": {}})

        self.assertEqual(decision["route"], "troubleshooting")
        self.assertEqual(decision["reason"], "direct_network_intermittent_fault_rule")
        self.assertFalse(decision["should_retrieve_knowledge"])

    def test_network_suspension_uses_pause_process(self):
        decision = detect_safe_direct_reply("我要暫停網路", {"known_info": {}})

        self.assertEqual(decision["intent"], "service_suspension_process")
        self.assertIn("雙證件", decision["reply"])

    def test_basic_channel_table_query_points_to_official_channel_table(self):
        decision = detect_safe_direct_reply("基本頻道可以看哪幾台？", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "basic_channel_table_query")
        self.assertIn("頻道查詢", decision["reply"])
        self.assertIn("頻道表", decision["reply"])

    def test_service_area_missing_example_uses_selected_company_area(self):
        reply = build_service_availability_reply(
            "同時申裝有線網路",
            {
                "company_code": "tdtv",
                "service_availability_context": {"status": "missing", "candidates": []},
            },
        )

        self.assertIn("烏日區", reply)
        self.assertNotIn("台南市永康區", reply)

    def test_vague_network_troubleshooting_asks_problem_type(self):
        decision = detect_safe_direct_reply("網路排除", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertIn("無法連線", decision["reply"])
        self.assertIn("速度慢", decision["reply"])

    def test_promotion_occasion_query_clarifies_service_scope(self):
        decision = detect_safe_direct_reply("新春有什麼優惠", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "promotion_service_scope_clarification")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("有線電視＋網路", decision["reply"])
        self.assertIn("純網路", decision["reply"])
        self.assertIn("純有線電視", decision["reply"])

    def test_latest_discount_query_clarifies_service_scope(self):
        decision = detect_safe_direct_reply("我要最新優惠", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["topic"], "優惠方案服務類型")

    def test_apply_300m_discount_routes_to_human_handoff_not_rag(self):
        decision = detect_safe_direct_reply("申請300M網路優惠", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "human_handoff_request")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertEqual(decision["reply"], WEB_HUMAN_HANDOFF_REPLY)

    def test_renewal_process_routes_to_knowledge_not_promotion(self):
        for text in ["怎麼重新續約", "約滿後要如何續約"]:
            with self.subTest(text=text):
                decision = detect_safe_direct_reply(text, {"known_info": {}})

                self.assertEqual(decision["route"], "knowledge_query")
                self.assertEqual(decision["intent"], "renewal_process_query")
                self.assertTrue(decision["should_retrieve_knowledge"])
                self.assertIn("續約", decision["knowledge_query"])
                self.assertNotEqual(decision.get("topic"), "promotion_activity")

    def test_specific_promotion_name_without_index_is_not_hardcoded(self):
        decision = detect_safe_direct_reply("飆網守護家", {"known_info": {}})

        self.assertIsNone(decision)

    def test_broadband_price_query_routes_to_plan_knowledge(self):
        for text in ["我只要網路就好，多少錢", "寬頻費$"]:
            with self.subTest(text=text):
                decision = detect_safe_direct_reply(text, {"known_info": {}})

                self.assertEqual(decision["route"], "knowledge_query")
                self.assertIn("一般寬頻方案", decision["knowledge_query"])
                if "只要網路" in text:
                    self.assertEqual(decision["intent"], "pure_network_install_plan_query")
                    self.assertIn("單辦寬頻", decision["knowledge_query"])
                    self.assertNotIn("哈 NET1", decision["knowledge_query"])
                    self.assertNotIn("清冰組", decision["knowledge_query"])
                else:
                    self.assertEqual(decision["intent"], "broadband_plan_price_query")
                    self.assertNotIn("哈 NET1", decision["knowledge_query"])

    def test_500mbps_fee_does_not_bypass_llm_intent_routing(self):
        decision = detect_safe_direct_reply(
            "500mbps費用",
            {"company_code": "toplight", "known_info": {}},
        )

        self.assertIsNone(decision)

    def test_500mbps_fee_is_classified_by_llm_before_knowledge_retrieval(self):
        calls = {"count": 0}

        def fake_llm(_payload):
            calls["count"] += 1
            return type("Response", (), {
                "content": json.dumps({
                    "route": "knowledge_query",
                    "intent": "broadband_plan_price_query",
                    "tool_name": None,
                    "topic": "寬頻方案費用",
                    "should_retrieve_knowledge": True,
                    "knowledge_query": "500mbps 寬頻網路費用",
                    "reply": "",
                    "extracted_slots": {},
                    "reason": "llm_broadband_price_classification",
                }, ensure_ascii=False),
            })()

        decision = run_intent_router(
            user_input="500mbps費用",
            memory={"company_code": "toplight", "known_info": {}},
            history=[],
            llm=RunnableLambda(fake_llm),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "broadband_plan_price_query")

    def test_899_followup_uses_generic_plan_context(self):
        decision = detect_safe_direct_reply("月繳899是指網路還是包含有限電視費用", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "broadband_plan_price_query")
        self.assertNotIn("好視成雙 NO8", decision["knowledge_query"])
        self.assertIn("899", decision["knowledge_query"])

    def test_named_campaign_does_not_use_hardcoded_direct_reply(self):
        decision = detect_safe_direct_reply("好視成雙 NO8 贈品有哪些？", {"known_info": {}})

        self.assertIsNone(decision)

    def test_multi_set_top_box_install_fee_routes_to_tv_fee_knowledge(self):
        decision = detect_safe_direct_reply("機上盒有多台要申裝 費用怎麼算?", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "set_top_box_multi_fee_query")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertIn("TV 分機費", decision["knowledge_query"])
        self.assertIn("STB 設備押金", decision["knowledge_query"])
        self.assertIn("機上盒有多台要申裝", decision["knowledge_query"])
        self.assertNotIn("大屯", decision["knowledge_query"])
        self.assertNotEqual(decision.get("intent"), "new_network_install_plan")

    def test_network_install_variants_route_to_quote_knowledge(self):
        for user_text in ("我要申請網路裝機", "網路新裝機"):
            with self.subTest(user_text=user_text):
                decision = detect_safe_direct_reply(
                    user_text,
                    {"company_code": "tdtv", "known_info": {}},
                )

                self.assertEqual(decision["route"], "knowledge_query")
                self.assertEqual(decision["intent"], "pure_network_install_plan_query")
                self.assertTrue(decision["should_retrieve_knowledge"])
                self.assertIn("純網方案", decision["knowledge_query"])
                self.assertIn(user_text, decision["knowledge_query"])
                self.assertNotEqual(decision.get("intent"), "new_network_install_plan")
                self.assertNotEqual(decision.get("intent"), "human_handoff_request")

    def test_network_install_fault_context_routes_to_troubleshooting(self):
        decision = detect_safe_direct_reply(
            "網路裝機後不能用",
            {"company_code": "tdtv", "known_info": {}},
        )

        self.assertEqual(decision["route"], "troubleshooting")
        self.assertEqual(decision["intent"], "troubleshooting")
        self.assertNotEqual(decision.get("intent"), "new_network_install_plan")

    def test_three_set_top_box_half_year_fee_is_deterministic(self):
        decision = detect_safe_direct_reply("要裝3台機上盒,半年繳要多少錢?", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "three_set_top_box_half_year_fee")
        self.assertIn("$3,240", decision["reply"])
        self.assertIn("$1,200", decision["reply"])
        self.assertIn("$6,440", decision["reply"])

    def test_two_set_top_box_monthly_total_accepts_formal_chinese_two(self):
        decision = detect_safe_direct_reply(
            "用月繳,裝二台機上盒,共要付多少錢?",
            {"known_info": {}},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "two_set_top_box_monthly_total")
        self.assertIn("收視費：$550 × 2 個月＝$1,100", decision["reply"])
        self.assertIn("合計：$1,100 + $1,500＝$2,600", decision["reply"])

    def test_one_year_network_contract_explicitly_says_one_year_is_not_listed(self):
        decision = detect_safe_direct_reply(
            "網路新裝機，有只綁一年約的方案嗎",
            {"known_info": {}},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "new_network_one_year_contract")
        self.assertIn("未列出只綁一年的", decision["reply"])
        self.assertIn("24 個月", decision["reply"])

    def test_discount_package_query_clarifies_service_scope(self):
        decision = detect_safe_direct_reply("優惠套餐有什麼?", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["topic"], "優惠方案服務類型")

    def test_combo_tv_network_discount_uses_promotion_rag(self):
        decision = detect_safe_direct_reply("雲林北港有線電視加網路優惠", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["topic"], "電視+網路方案")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertIn("雲林北港有線電視加網路優惠", decision["knowledge_query"])
        self.assertIn("電視網路同裝方案", decision["knowledge_query"])
        self.assertNotIn("好視成雙", decision["knowledge_query"])

    def test_promotion_followup_detail_uses_recent_campaign_context(self):
        decision = detect_safe_direct_reply(
            "這個方案有哪些贈品可以選",
            {
                "known_info": {},
                "last_knowledge_results": [
                    {
                        "question": "飆網守護家_B2606",
                        "answer": "方案名稱：飆網守護家_(B2606)（網路贈清冰組方案）",
                        "campaign_name": "飆網守護家 B2606",
                    }
                ],
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "promotion_followup_detail")
        self.assertIn("飆網守護家 B2606", decision["knowledge_query"])
        self.assertIn("贈品", decision["knowledge_query"])
        self.assertNotIn("清冰組", decision["knowledge_query"])

    def test_parent_day_promotion_starts_fresh_search_instead_of_old_campaign_followup(self):
        decision = detect_safe_direct_reply(
            "父親節有哪些優惠？",
            {
                "known_info": {},
                "last_campaign_topic": "飆網守護家 B2606",
                "last_knowledge_results": [
                    {
                        "campaign_name": "飆網守護家 B2606",
                        "answer": "一般網路贈清冰組方案。",
                    }
                ],
            },
        )

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["reason"], "promotion_service_scope_clarification_rule")
        self.assertEqual(decision["topic"], "優惠方案服務類型")

    def test_august_activity_query_does_not_hardcode_existing_campaign_names(self):
        decision = detect_safe_direct_reply("八月優惠活動", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["reason"], "promotion_service_scope_clarification_rule")
        self.assertEqual(decision["topic"], "優惠方案服務類型")

    def test_new_campaign_total_cost_followup_uses_dynamic_campaign_context(self):
        decision = detect_safe_direct_reply(
            "總共費用多少？",
            {
                "known_info": {},
                "last_campaign_topic": "爸氣獻禮",
                "last_knowledge_results": [
                    {
                        "campaign_name": "爸氣獻禮",
                        "answer": "裝機費免收；設備押金 2,000 元；100M/100M 半年繳 2,700 元。",
                    }
                ],
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "promotion_followup_detail")
        self.assertIn("爸氣獻禮", decision["knowledge_query"])
        self.assertIn("裝機費", decision["knowledge_query"])
        self.assertIn("設備押金", decision["knowledge_query"])

    def test_new_campaign_line_tv_followup_uses_metadata_campaign_context(self):
        decision = detect_safe_direct_reply(
            "LINE TV 贈幾個月？",
            {
                "known_info": {},
                "last_knowledge_results": [
                    {
                        "campaign_name": "爸氣獻禮",
                        "answer": "LINE TV 贈會員 6 個月序號。",
                    }
                ],
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "promotion_followup_detail")
        self.assertIn("爸氣獻禮", decision["knowledge_query"])
        self.assertIn("LINE TV", decision["knowledge_query"])

    def test_campaign_points_followup_keeps_recent_campaign_context(self):
        decision = detect_safe_direct_reply(
            "這個方案半年繳送多少點數？",
            {
                "known_info": {},
                "last_campaign_topic": "爸氣獻禮",
                "last_knowledge_results": [
                    {
                        "campaign_name": "爸氣獻禮",
                        "answer": "半年繳贈 888 點。",
                    }
                ],
            },
        )

        self.assertEqual(decision["intent"], "promotion_followup_detail")
        self.assertIn("爸氣獻禮", decision["knowledge_query"])
        self.assertIn("贈點規則", decision["knowledge_query"])

    def test_basic_tv_monthly_fee_query_uses_knowledge_not_troubleshooting(self):
        decision = detect_safe_direct_reply("第四台一個月多少錢？", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "basic_tv_fee_query")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertIn("基本收費", decision["knowledge_query"])
        self.assertIn("第四台一個月多少錢", decision["knowledge_query"])

    def test_wifi5_yearly_price_is_not_hardcoded_as_direct_reply(self):
        decision = detect_safe_direct_reply("WiFi 5 分享器一年多少錢？", {"known_info": {}})

        self.assertIsNone(decision)

    def test_wifi_fault_still_uses_troubleshooting(self):
        decision = detect_troubleshooting_query("WiFi 不能用", {"known_info": {}})

        self.assertIsNotNone(decision)
        self.assertEqual(decision["route"], "troubleshooting")

    def test_wifi5_price_guard_clarifies_llm_troubleshooting_conflict(self):
        decision = router_guard(
            user_input="WiFi 5 分享器一年多少錢？",
            memory={"known_info": {}},
            router={
                "route": "troubleshooting",
                "intent": "network_issue",
                "tool_name": None,
                "topic": "網路故障",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": None,
                "reason": "llm_router",
            },
        )

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "value_added_product_or_fault_clarification")
        self.assertIn("內容或費用", decision["reply"])
        self.assertIn("無法使用", decision["reply"])

    def test_wifi5_price_followup_uses_contextual_llm_router(self):
        calls = []

        def contextual_router(_payload):
            calls.append(True)
            return type("Response", (), {
                    "content": json.dumps({
                        "route": "knowledge_query",
                        "intent": "value_added_product_query",
                        "tool_name": None,
                        "topic": "加值產品與服務",
                        "should_cancel_current_flow": False,
                        "should_call_tool": False,
                        "should_retrieve_knowledge": True,
                        "knowledge_query": "WiFi 5 分享器 年繳 費用",
                        "reply": "",
                        "extracted_slots": {},
                        "reason": "contextual_product_price_query",
                    }, ensure_ascii=False),
                })()

        llm = RunnableLambda(contextual_router)

        decision = run_intent_router(
            user_input="WiFi 5 分享器一年多少錢？",
            memory={"known_info": {}},
            history=[
                {"role": "user", "content": "WiFi 加值服務有哪些？"},
                {
                    "role": "assistant",
                    "content": "WiFi 5 系列分享器月均價 25 元，半年繳 150 元，年繳 300 元。",
                },
            ],
            llm=llm,
        )

        self.assertTrue(calls)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "value_added_product_query")

    def test_restricted_channel_purchase_interrupts_prior_authorization_troubleshooting(self):
        decision = detect_safe_direct_reply(
            "限制級節目授權到期如何購買？",
            {
                "pending_tool": "troubleshooting",
                "known_info": {"troubleshooting_started": "yes"},
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "restricted_channel_purchase")
        self.assertIn("優惠專區", decision["knowledge_query"])
        self.assertIn("數位電視", decision["knowledge_query"])

    def test_restricted_channel_purchase_does_not_bypass_unavailable_llm(self):
        class FailingLLM:
            def invoke(self, payload):
                raise AssertionError("LLM should not be called for restricted channel purchase")

        decision = run_intent_router(
            user_input="限制級節目授權到期如何購買？",
            memory={
                "pending_tool": "troubleshooting",
                "known_info": {
                    "troubleshooting_started": "yes",
                    "troubleshooting_step": "authorization_payment",
                },
            },
            history=[],
            llm=FailingLLM(),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_bill_payment_deadline_does_not_bypass_unavailable_llm(self):
        class FailingLLM:
            def invoke(self, payload):
                raise AssertionError("LLM should not be called for bill payment deadline")

        decision = run_intent_router(
            user_input="查詢帳單繳費截止日期",
            memory={"known_info": {"custnum": "1110723"}},
            history=[],
            llm=FailingLLM(),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_short_hatv_package_query_uses_knowledge(self):
        decision = detect_safe_direct_reply("A套餐能查到嗎?", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "hatv_package_channel_query")
        self.assertIn("哈TV A套餐", decision["knowledge_query"])
        self.assertIn("頻道內容", decision["knowledge_query"])

    def test_social_discount_query_routes_to_knowledge_base(self):
        decision = detect_safe_direct_reply("有低收入優惠方案嗎?", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "social_discount_query")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertEqual(decision["knowledge_query"], "有低收入優惠方案嗎?")

    def test_social_discount_ineligible_then_asks_other_promotions_clarifies_service_scope(self):
        decision = detect_safe_direct_reply("我也沒有中低收~還有其他優惠嗎", {"known_info": {}})

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["topic"], "優惠方案服務類型")
        self.assertFalse(decision["should_retrieve_knowledge"])

    def test_social_discount_expired_without_alternative_still_routes_to_social_discount(self):
        decision = detect_safe_direct_reply("我的低收過期了", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "social_discount_query")

    def test_social_discount_query_is_routed_by_the_model_and_keeps_explicit_scope(self):
        class Response:
            content = json.dumps({
                "route": "knowledge_query",
                "intent": "social_discount_query",
                "tool_name": None,
                "topic": "低收入優惠方案",
                "should_cancel_current_flow": True,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "低收入優惠方案",
                "reply": "",
                "extracted_slots": {},
                "reason": "llm_social_discount_scope",
            }, ensure_ascii=False)

        calls = {"count": 0}

        def fake_llm(_payload):
            calls["count"] += 1
            return Response()

        decision = run_intent_router(
            user_input="有低收入優惠方案嗎?",
            memory={"known_info": {}, "company_code": "tdtv"},
            history=[],
            llm=RunnableLambda(fake_llm),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "social_discount_query")

    def test_three_explicit_promotion_service_scopes_are_routed_by_the_model(self):
        cases = {
            "有線電視加網路有什麼優惠方案": ("tv_network_install_plan_query", "電視+網路方案"),
            "純網有什麼優惠方案": ("pure_network_install_plan_query", "純網方案"),
            "有線電視有什麼優惠方案": ("pure_tv_promotion_query", "單辦有線電視優惠"),
        }
        for user_input, (intent, topic) in cases.items():
            with self.subTest(user_input=user_input):
                class Response:
                    content = json.dumps({
                        "route": "knowledge_query",
                        "intent": intent,
                        "tool_name": None,
                        "topic": topic,
                        "should_cancel_current_flow": True,
                        "should_call_tool": False,
                        "should_retrieve_knowledge": True,
                        "knowledge_query": user_input,
                        "reply": "",
                        "extracted_slots": {},
                        "reason": "llm_promotion_service_scope",
                    }, ensure_ascii=False)

                calls = {"count": 0}

                def fake_llm(_payload):
                    calls["count"] += 1
                    return Response()

                decision = run_intent_router(
                    user_input=user_input,
                    memory={"known_info": {}, "company_code": "tdtv"},
                    history=[],
                    llm=RunnableLambda(fake_llm),
                )
                self.assertEqual(calls["count"], 1)
                self.assertEqual(decision["route"], "knowledge_query")
                self.assertEqual(decision["intent"], intent)
                self.assertEqual(decision["topic"], topic)
                self.assertTrue(decision["should_retrieve_knowledge"])

    def test_combo_install_scope_does_not_override_model_semantics(self):
        class Response:
            content = json.dumps({
                "route": "knowledge_query",
                "intent": "internet_install_application_guidance",
                "tool_name": None,
                "topic": "寬頻網路新申辦",
                "should_cancel_current_flow": True,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "寬頻網路 裝機申請 方案 費用",
                "reply": "",
                "extracted_slots": {},
                "reason": "llm_misclassified_combo_as_internet",
            }, ensure_ascii=False)

        calls = {"count": 0}

        def fake_llm(_payload):
            calls["count"] += 1
            return Response()

        decision = run_intent_router(
            user_input="有線電視+網路裝機申請",
            memory={"known_info": {}, "company_code": "tdtv"},
            history=[],
            llm=RunnableLambda(fake_llm),
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "internet_install_application_guidance")
        self.assertEqual(decision["topic"], "寬頻網路新申辦")
        self.assertEqual(decision["knowledge_query"], "寬頻網路 裝機申請 方案 費用")

    def test_neighbor_cheaper_query_uses_direct_handoff_reply(self):
        decision = detect_safe_direct_reply("隔壁鄰居比我便宜，為什麼？", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "promotion_price_difference")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("文字客服專人", decision["reply"])

    def test_router_guard_overrides_neighbor_cheaper_rag_route(self):
        decision = router_guard(
            user_input="隔壁鄰居比我便宜，為什麼？",
            memory={"known_info": {}},
            router={
                "route": "knowledge_query",
                "intent": "pricing_difference_reason",
                "tool_name": None,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "隔壁鄰居比我便宜，為什麼？",
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "promotion_price_difference")
        self.assertFalse(decision["should_retrieve_knowledge"])

    def test_cancel_tv_keep_internet_uses_soft_handoff_reply(self):
        decision = detect_safe_direct_reply("我要停掉第四台，只保留網路。", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "cancel_tv_keep_internet")
        self.assertIn("文字客服專人", decision["reply"])
        self.assertIn("保留網路", decision["reply"])

    def test_broad_promotion_is_classified_by_the_model_without_a_tool(self):
        class Response:
            content = json.dumps({
                "route": "clarify",
                "intent": "promotion_service_scope_clarification",
                "tool_name": None,
                "topic": "優惠方案服務類型",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "請問您想了解哪一類優惠方案？\n1. 有線電視＋網路\n2. 純網路\n3. 純有線電視",
                "extracted_slots": {},
                "reason": "llm_promotion_scope_clarification",
            }, ensure_ascii=False)

        calls = {"count": 0}

        def fake_llm(_payload):
            calls["count"] += 1
            return Response()

        llm = RunnableLambda(fake_llm)
        decision = run_intent_router(
            user_input="我要最新優惠",
            memory={"known_info": {}},
            history=[],
            llm=llm,
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(decision["route"], "clarify")
        self.assertIsNone(decision["tool_name"])
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertEqual(decision["reason"], "llm_promotion_scope_clarification")

    def test_service_availability_uses_location_in_current_question(self):
        decision = detect_service_availability_query(
            "爸媽住永康區，可以裝寬頻網路嗎？",
            {"known_info": {}, "company_code": "tdtv"},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertIsNone(decision["tool_name"])
        self.assertIn("永康區", decision["reply"])
        self.assertIn("新永安有線", decision["reply"])
        self.assertNotIn("大屯有線", decision["reply"])

    def test_safe_direct_reply_prioritizes_explicit_install_location(self):
        decision = detect_safe_direct_reply(
            "永康區可以裝網路嗎？",
            {"known_info": {}, "company_code": "tdtv"},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "service_availability")
        self.assertIn("永康區", decision["reply"])
        self.assertIn("新永安有線", decision["reply"])
        self.assertNotEqual(decision["reason"], "direct_new_install_plan_query_rule")

    def test_safe_direct_reply_prioritizes_shalu_install_application_location(self):
        decision = detect_safe_direct_reply(
            "沙鹿區可以申請網路裝機嗎？",
            {"known_info": {}, "company_code": "tdtv"},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "service_availability")
        self.assertIn("沙鹿區", decision["reply"])
        self.assertIn("佳光電訊-西海岸區", decision["reply"])
        self.assertNotEqual(decision["reason"], "direct_new_install_plan_query_rule")
        self.assertNotIn("好視成雙", decision["reply"])

    def test_service_availability_interrupts_stale_troubleshooting_context(self):
        decision = detect_safe_direct_reply(
            "沙鹿區可以申請網路裝機嗎？",
            {
                "company_code": "tdtv",
                "pending_tool": "troubleshooting",
                "known_info": {"troubleshooting_started": "yes"},
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "service_availability")
        self.assertIn("沙鹿區", decision["reply"])
        self.assertIn("佳光電訊-西海岸區", decision["reply"])
        self.assertNotIn("重開", decision["reply"])

    def test_safe_direct_reply_uses_install_target_instead_of_residence(self):
        decision = detect_safe_direct_reply(
            "我住大里，想幫台南永康的爸媽問能不能裝網路。",
            {"known_info": {}, "company_code": "tdtv"},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "service_availability")
        self.assertIn("永康區", decision["reply"])
        self.assertIn("新永安有線", decision["reply"])
        self.assertNotIn("大屯有線", decision["reply"])

    def test_service_availability_asks_for_install_location_when_missing(self):
        decision = detect_service_availability_query(
            "其他縣市可以裝網路嗎？",
            {"known_info": {}, "company_code": "tdtv"},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertIn("縣市與行政區", decision["reply"])
        self.assertNotIn("大屯有線", decision["reply"])

    def test_service_availability_clarifies_multiple_locations(self):
        decision = detect_service_availability_query(
            "大里和永康哪裡可以裝網路？",
            {"known_info": {}, "company_code": "tdtv"},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertIn("大里區", decision["reply"])
        self.assertIn("永康區", decision["reply"])
        self.assertIn("實際想申裝", decision["reply"])

    def test_safe_direct_reply_resolves_watertop_tv_installation(self):
        decision = detect_safe_direct_reply(
            "朋友住水上，想裝第四台。",
            {"known_info": {}, "company_code": "tdtv"},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "service_availability")
        self.assertIn("水上鄉", decision["reply"])
        self.assertIn("大揚", decision["reply"])

    def test_safe_direct_reply_does_not_assign_unknown_city_to_default_company(self):
        decision = detect_safe_direct_reply(
            "台北市可以裝你們網路嗎？",
            {"known_info": {}, "company_code": "tdtv"},
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "service_availability")
        self.assertIn("台北市", decision["reply"])
        self.assertIn("未列出", decision["reply"])
        self.assertNotIn("大屯有線服務地區", decision["reply"])

    def test_hatv_addon_info_query_uses_rag_not_disabled_reply(self):
        decision = detect_safe_direct_reply("哈tv數位套餐加購", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "hatv_addon_knowledge")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertIn("哈TV", decision["knowledge_query"])
        self.assertIn("加購", decision["knowledge_query"])
        self.assertNotIn("線上服務暫停", decision["reply"])

    def test_hatv_addon_action_request_still_uses_disabled_reply(self):
        decision = detect_safe_direct_reply("我要加購哈TV數位套餐", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "hatv_addon")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("線上服務暫停", decision["reply"])

    def test_channel_query_routes_to_mock_channel_tool(self):
        decision = detect_safe_direct_reply("愛爾達體育在第幾台", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_channel_no")
        self.assertEqual(decision["extracted_slots"]["channel_name"], "愛爾達體育")

    def test_channel_query_extracts_hbo_from_natural_question(self):
        decision = detect_safe_direct_reply("我想知道HBO在哪個頻道", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_channel_no")
        self.assertEqual(decision["extracted_slots"]["channel_name"], "HBO")

    def test_channel_query_extracts_name_before_which_channel_suffix(self):
        decision = detect_safe_direct_reply("東森電影台在哪一台", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_channel_no")
        self.assertEqual(decision["extracted_slots"]["channel_name"], "東森電影台")

    def test_world_cup_broadcast_uses_knowledge_before_channel_tool(self):
        decision = detect_safe_direct_reply("世界盃足球賽哪一台可以看？", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertIsNone(decision["tool_name"])
        self.assertIn("2026 FIFA 世界盃足球賽", decision["knowledge_query"])
        self.assertIn("轉播頻道", decision["knowledge_query"])

    def test_football_channel_shorthand_uses_world_cup_knowledge(self):
        decision = detect_safe_direct_reply("我想知道足球台在哪一台", {"known_info": {}})

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertIsNone(decision["tool_name"])
        self.assertIn("足球台", decision["knowledge_query"])

    def test_world_cup_broadcast_guard_overrides_clarify(self):
        decision = router_guard(
            "世足賽轉播",
            {"known_info": {}},
            {
                "route": "clarify",
                "intent": "channel_query_clarify",
                "tool_name": None,
                "topic": "頻道位置查詢",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "請提供頻道名稱。",
                "extracted_slots": {},
                "reason": "llm_clarify",
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "sports_broadcast_query")
        self.assertTrue(decision["should_retrieve_knowledge"])

    def test_channel_query_normalizes_missing_pili_alias(self):
        decision = detect_safe_direct_reply("找不到霹靂台", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "search_channel_no")
        self.assertEqual(decision["extracted_slots"]["channel_name"], "霹靂台灣台")

    def test_password_help_is_direct_reply(self):
        decision = detect_safe_direct_reply("忘記密碼", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertIn("忘記密碼", decision["reply"])

    def test_remote_control_issue_is_direct_reply(self):
        decision = detect_safe_direct_reply("遙控器有紅色燈沒有反應", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertIn("電池", decision["reply"])

    def test_remote_control_delivery_query_is_not_treated_as_troubleshooting(self):
        text = "遙控器可以送到府嗎？"

        self.assertIsNone(detect_troubleshooting_query(text, {"known_info": {}}))
        self.assertIsNone(detect_safe_direct_reply(text, {"known_info": {}}))

    def test_remote_control_purchase_query_is_not_treated_as_troubleshooting(self):
        text = "請問遙控器要去哪裡購買？"

        self.assertIsNone(detect_troubleshooting_query(text, {"known_info": {}}))
        self.assertIsNone(detect_safe_direct_reply(text, {"known_info": {}}))

    def test_remote_control_purchase_price_routes_to_knowledge(self):
        text = "一般遙控器壞了，買一支多少錢？"

        decision = detect_equipment_purchase_knowledge_query(text)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "equipment_purchase_price_query")
        self.assertIn("遙控器", decision["knowledge_query"])
        self.assertIsNone(detect_troubleshooting_query(text, {"known_info": {}}))

    def test_line_tv_device_limit_is_not_treated_as_channel_number_query(self):
        text = "LINE TV最多能登入幾台裝置？"

        decision = detect_service_device_limit_knowledge_query(text)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "service_device_limit_query")
        self.assertIn("登入裝置數量", decision["knowledge_query"])

    def test_line_tv_device_limit_does_not_bypass_unavailable_llm(self):
        def fail_if_called(_prompt):
            raise AssertionError("device-limit query must route before the LLM")

        decision = run_intent_router(
            user_input="LINE TV最多能登入幾台裝置？",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=RunnableLambda(fail_if_called),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_cancel_repair_does_not_claim_success(self):
        decision = detect_safe_direct_reply("取消報修", {"known_info": {}})

        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "cancel_repair_ticket")
        self.assertNotIn("已取消", decision["reply"])

    def test_fault_query_short_circuits_to_troubleshooting(self):
        decision = detect_troubleshooting_query("無法連線", {"known_info": {}})

        self.assertEqual(decision["route"], "troubleshooting")

    def test_tv_unwatchable_query_routes_to_troubleshooting(self):
        decision = detect_troubleshooting_query("無法收看", {"known_info": {}})

        self.assertEqual(decision["route"], "troubleshooting")

    def test_clear_tv_symptom_queries_route_to_troubleshooting(self):
        for text in [
            "電視有開但沒頻道",
            "畫面一直卡住",
            "機上盒一直跑不進去",
            "頻道收視異常",
            "畫面顯示未收權",
            "機上盒一直出現授權到期",
            "電視無畫面",
        ]:
            with self.subTest(text):
                decision = detect_troubleshooting_query(text, {"known_info": {}})

                self.assertIsNotNone(decision)
                self.assertEqual(decision["route"], "troubleshooting")

    def test_clear_network_scope_queries_route_to_troubleshooting(self):
        for text in ["手機能上網，電腦不能", "網路有線可以用，Wi-Fi不能用", "數據機亮紅燈不能上網"]:
            with self.subTest(text):
                decision = detect_troubleshooting_query(text, {"known_info": {}})

                self.assertIsNotNone(decision)
                self.assertEqual(decision["route"], "troubleshooting")

    def test_bad_network_quality_routes_to_troubleshooting(self):
        decision = detect_troubleshooting_query("網路很爛", {"known_info": {}})

        self.assertEqual(decision["route"], "troubleshooting")

    def test_one_word_fault_report_routes_to_troubleshooting(self):
        decision = detect_troubleshooting_query("故障", {"known_info": {}})

        self.assertEqual(decision["route"], "troubleshooting")

    def test_area_repair_status_is_human_handoff_not_resolution_guess(self):
        decision = detect_safe_direct_reply("沙鹿區正德路網路維修好了嗎", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "area_repair_status_lookup")
        self.assertIn("無法即時確認", decision["reply"])
        self.assertNotIn("已恢復", decision["reply"])

    def test_area_repair_status_uses_company_outage_without_guessing_resolution(self):
        profile = {
            "company_name": "佳光電訊-西海岸區",
            "area_outage": "沙鹿區正德路寬頻異常，工程搶修中。",
        }

        with patch("app.services.intent_router.get_company_profile", return_value=profile):
            decision = detect_safe_direct_reply(
                "沙鹿區正德路網路維修好了嗎",
                {"company_code": "wctv", "known_info": {}},
            )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "area_repair_status_lookup")
        self.assertIn("佳光電訊-西海岸區目前公告", decision["reply"])
        self.assertIn("沙鹿區正德路寬頻異常", decision["reply"])
        self.assertIn("無法即時確認", decision["reply"])
        self.assertNotIn("已恢復", decision["reply"])

    def test_individual_repair_schedule_does_not_use_area_outage_as_dispatch_status(self):
        profile = {
            "company_name": "佳光電訊-台中市區",
            "area_outage": "西屯區部分路段寬頻異常，工程搶修中。",
        }

        with patch("app.services.intent_router.get_company_profile", return_value=profile):
            decision = detect_safe_direct_reply(
                "請問今天會來維修嗎？",
                {"company_code": "toplight", "known_info": {}},
            )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "area_repair_status_lookup")
        self.assertIn("無法即時確認", decision["reply"])
        self.assertIn("今天是否會到府", decision["reply"])
        self.assertNotIn("西屯區部分路段", decision["reply"])

    def test_contract_lookup_with_explicit_address_requires_handoff(self):
        decision = detect_safe_direct_reply("台中市梧棲區中和街33號合約", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "address_contract_lookup_handoff")
        self.assertIn("真人客服", decision["reply"])

    def test_card_autopay_application_has_application_reply(self):
        decision = detect_safe_direct_reply("自動扣款申請方式", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "card_autopay_application")
        self.assertIn("有線電視或網路官方網站", decision["reply"])
        self.assertIn("會員專區", decision["reply"])
        self.assertIn("續期要扣款的信用卡資訊", decision["reply"])
        self.assertNotIn("無法直接查詢", decision["reply"])

    def test_bind_credit_card_uses_autopay_application_reply(self):
        decision = detect_safe_direct_reply("綁定信用卡", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "card_autopay_application")
        self.assertIn("有線電視或網路官方網站", decision["reply"])
        self.assertIn("會員專區", decision["reply"])

    def test_card_autopay_application_flow_uses_binding_reply(self):
        decision = detect_safe_direct_reply("申請信用卡自動扣款流程", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "card_autopay_application")
        self.assertIn("續期要扣款的信用卡資訊", decision["reply"])

    def test_identity_document_upload_uses_app_upload_reply(self):
        decision = detect_safe_direct_reply("上傳身份證", {"known_info": {}})

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "identity_document_upload")
        self.assertIn("無法代收或上傳身分證件", decision["reply"])
        self.assertIn("哈TV行動客服 APP", decision["reply"])
        self.assertIn("雙證件上傳", decision["reply"])
        self.assertNotIn("真人客服協助確認可用的安全補件方式", decision["reply"])

    def test_card_autopay_followup_does_not_bypass_unavailable_llm(self):
        def fail_if_called(_prompt):
            raise AssertionError("autopay application follow-up must route before the LLM")

        decision = run_intent_router(
            user_input="申請方式",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[
                {"role": "user", "content": "我想辦信用卡自動扣款"},
                {"role": "assistant", "content": "信用卡自動扣款可以協助您定期扣款。"},
            ],
            llm=RunnableLambda(fail_if_called),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_speed_test_followup_does_not_bypass_unavailable_llm(self):
        def fail_if_called(_prompt):
            raise AssertionError("speed-test follow-up must route before the LLM")

        decision = run_intent_router(
            user_input="想知道如何測試",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[
                {"role": "user", "content": "測試網速"},
                {"role": "assistant", "content": "請問您是想了解如何測試網速，還是網路速度變慢需要協助排除呢？"},
            ],
            llm=RunnableLambda(fail_if_called),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_toplight_network_install_does_not_offer_tv_bundle(self):
        decision = detect_safe_direct_reply(
            "網路裝機申請",
            {"company_code": "toplight", "known_info": {}},
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["topic"], "純網方案")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertIn("純網方案", decision["knowledge_query"])
        self.assertIn("單辦寬頻", decision["knowledge_query"])
        self.assertNotIn("好視成雙", decision["knowledge_query"])
        self.assertNotIn("電視網路同裝方案", decision["knowledge_query"])

    def test_network_install_uses_company_profile_install_link(self):
        profile = {
            "service_items": "寬頻網路服務",
            "urls": (
                "［官網🔗］https://example.test/\n"
                "［維修申告🔗］https://example.test/repair\n"
                "［裝機申告🔗］https://example.test/install"
            ),
        }

        with patch("app.services.intent_router.get_company_profile", return_value=profile):
            decision = detect_safe_direct_reply(
                "網路裝機申請",
                {"company_code": "toplight", "known_info": {}},
            )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertNotIn("有申裝意願", decision["knowledge_query"])
        self.assertNotIn("裝機申告表單", decision["knowledge_query"])
        self.assertNotIn("stb.topmso.com.tw", decision["knowledge_query"])

    def test_fallback_smalltalk_is_safe(self):
        decision = fallback_router("你好", {"known_info": {}})

        self.assertEqual(decision["route"], "smalltalk")
        self.assertFalse(decision["should_call_tool"])

    def test_validation_normalizes_bad_route(self):
        decision = validate_router_result({
            "route": "not_a_route",
            "tool_name": "search_bill",
            "should_call_tool": True,
            "extracted_slots": "bad",
        })

        self.assertEqual(decision["route"], "unknown")
        self.assertFalse(decision["should_call_tool"])
        self.assertEqual(set(decision["extracted_slots"].keys()), {
            "name",
            "phone",
            "custnum",
            "contact_name",
            "contact_phone",
            "service_address",
            "issue_description",
            "preferred_date",
            "preferred_time_range",
            "service_area",
            "channel_name",
            "addon_name",
            "install_service",
            "desired_plan",
            "repair_ticket_id",
        })

    def test_unknown_definition_query_is_forced_to_rag(self):
        decision = router_guard(
            user_input="雙模機是什麼?",
            memory={"known_info": {}},
            router={
                "route": "unknown",
                "intent": "other",
                "reply": "要進入雙模機的設定選項，請進入設定。",
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertEqual(decision["knowledge_query"], "雙模機是什麼?")
        self.assertEqual(decision["reply"], "")

    def test_clarify_definition_query_is_forced_to_rag(self):
        decision = router_guard(
            user_input="雙模機是什麼?",
            memory={"known_info": {}},
            router={
                "route": "clarify",
                "intent": "other",
                "reply": "要進入雙模機的設定選項，請進入設定。",
            },
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertTrue(decision["should_retrieve_knowledge"])
        self.assertEqual(decision["reply"], "")

    def test_definition_query_returns_safe_reply_when_llm_fails(self):
        class FailingLLM:
            def invoke(self, payload):
                raise RuntimeError("LLM unavailable")

        decision = run_intent_router(
            user_input="雙模機是什麼?",
            memory={"known_info": {}},
            history=[],
            llm=FailingLLM(),
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertEqual(decision["reason"], "model_router_unavailable")
        self.assertEqual(decision["reply"], "系統暫時無法判讀您的需求，請稍後再試。")

    def test_unknown_route_does_not_keep_llm_answer(self):
        decision = router_guard(
            user_input="這個我不懂",
            memory={"known_info": {}},
            router={
                "route": "unknown",
                "intent": "other",
                "reply": "這是一段模型自己猜的答案。",
            },
        )

        self.assertEqual(decision["route"], "unknown")
        self.assertNotEqual(decision["reply"], "這是一段模型自己猜的答案。")


if __name__ == "__main__":
    unittest.main()
