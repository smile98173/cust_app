import unittest
import json
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from app.services.intent_router import (
    build_memory_summary,
    build_router_history_text,
    build_service_availability_reply,
    router_guard,
    run_intent_router,
    validate_router_result,
    HUMAN_HANDOFF_TRIAGE_REPLY,
    WEB_HUMAN_HANDOFF_REPLY,
)
from app.services.router_catalog import get_clarify_context, match_clarify_option
from app.services.router_catalog import match_contextual_clarify_fallback


class RouterArchitectureTest(unittest.TestCase):
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
        )

        self.assertEqual(decision["route"], "company_info")
        self.assertEqual(decision["topic"], "company_overview")

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
