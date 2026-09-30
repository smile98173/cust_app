import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import (
    build_repeat_repair_escalation_router,
    add_repair_form_to_handoff_offer,
    build_clarify_context,
    build_plan_from_router,
    build_memory_without_active_flow,
    is_repair_form_available,
    detect_active_flow_switch,
    focus_knowledge_process_docs,
    compose_knowledge_reply,
    build_promotion_catalog_reply,
    resolve_model_selected_context,
)
from app.services.intent_router import build_memory_summary, router_guard, run_intent_router
from app.services.troubleshooting_engine import apply_troubleshooting_engine


def troubleshooting_plan(intent: str) -> dict:
    return {
        "intent": intent,
        "reply": "",
        "should_call_tool": False,
        "tool_name": None,
    }


class Feedback20260922RegressionTest(unittest.TestCase):
    def test_generic_transfer_uses_approved_common_documents(self):
        plan = build_plan_from_router(
            {"route": "direct_reply", "intent": "service_account_transfer", "reply": ""}
        )
        self.assertIn("原使用者與新使用者", plan["reply"])
        self.assertIn("第二證件", plan["reply"])
        self.assertNotIn("資料未提供", plan["reply"])

    def test_generic_transfer_knowledge_route_normalizes_to_approved_contract(self):
        decision = router_guard(
            "了解過戶流程",
            {"known_info": {}},
            {"route": "knowledge_query", "intent": "service_account_transfer", "should_retrieve_knowledge": True},
        )
        self.assertEqual(decision["route"], "direct_reply")
        self.assertIn("第二證件", decision["reply"])

    def test_active_fault_does_not_restart_generic_repair_intake(self):
        memory = {"known_info": {"troubleshooting_started": "yes", "troubleshooting_type": "remote"}}
        with patch(
            "app.handlers.chat_handler.run_intent_router",
            return_value={
                "route": "troubleshooting",
                "intent": "repair_troubleshooting_intake",
                "should_cancel_current_flow": True,
            },
        ):
            decision = detect_active_flow_switch("登記維修", memory, [], None, {})
        self.assertIsNone(decision)
        self.assertEqual(memory["known_info"]["troubleshooting_started"], "yes")

    def test_repair_equipment_clarification_preserves_reported_fault(self):
        for clarify_intent in ("repair_troubleshooting_intake", "service_signal_type_clarify"):
            with self.subTest(clarify_intent=clarify_intent):
                context = build_clarify_context(
                    {
                        "route": "clarify",
                        "intent": clarify_intent,
                        "topic": "故障設備確認",
                        "reply": "請問是哪一項設備無亮燈？",
                    },
                    original_query="都有插電，但是無亮燈",
                )
                memory = {
                    "clarify_context": context,
                    "known_info": {"power_status": "off", "issue_description": "設備已插電但無亮燈"},
                }
                selected, validated = resolve_model_selected_context(
                    memory,
                    {
                        "route": "continue_current_flow",
                        "intent": "troubleshooting",
                        "selected_option_id": "repair_equipment_set_top_box",
                    },
                )

                self.assertTrue(validated)
                self.assertEqual(selected["route"], "troubleshooting")
                result = apply_troubleshooting_engine(
                    "機上盒", memory, troubleshooting_plan(selected["intent"])
                )
                self.assertIn("已插電但沒有亮燈", result["reply"])
                self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_check_power_cable")

    def test_model_boot_loop_alias_uses_boot_sop(self):
        for alias in (
            "tv_stb_reboot_loop_troubleshooting",
            "stb_reboot_loop_troubleshooting",
        ):
            with self.subTest(alias=alias):
                decision = router_guard(
                    "重複一直開機中",
                    {"known_info": {}},
                    {
                        "route": "continue_current_flow",
                        "intent": alias,
                        "should_cancel_current_flow": False,
                        "reason": "model_boot_loop",
                    },
                )

                self.assertEqual(decision["intent"], "tv_set_top_box_boot_issue")
                memory = {"known_info": {}}
                result = apply_troubleshooting_engine(
                    "機上盒重複一直開機中", memory, troubleshooting_plan(decision["intent"])
                )
                self.assertIn("重複開機", result["reply"])
                self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")

    def test_boot_screen_followup_checks_result_instead_of_repeating_reboot(self):
        memory = {"known_info": {}}
        apply_troubleshooting_engine(
            "機上盒重複一直開機中",
            memory,
            troubleshooting_plan("tv_set_top_box_boot_issue"),
        )
        result = apply_troubleshooting_engine(
            "開機中請稍後的畫面",
            memory,
            troubleshooting_plan("tv_set_top_box_boot_issue"),
            llm=RunnableLambda(lambda _: AIMessage(content='{"label":"unknown"}')),
        )

        self.assertIn("是否已", result["reply"])
        self.assertNotIn("請先將機上盒電源拔掉", result["reply"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")

    def test_troubleshooting_does_not_promise_ticket_creation(self):
        for user_text, intent in (
            ("機上盒排除", "repair_troubleshooting_intake"),
            ("網路故障", "internet_connection_issue"),
        ):
            with self.subTest(intent=intent):
                result = apply_troubleshooting_engine(
                    user_text, {"known_info": {}}, troubleshooting_plan(intent)
                )
                self.assertNotIn("建立報修工單", result["reply"])
                self.assertNotIn("維修申告", result["reply"])

    def test_speed_test_guidance_does_not_clear_active_speed_fault(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_speed_retest",
                "declared_plan_speed_mbps": 300.0,
                "download_speed": 30.0,
            },
        }
        with patch(
            "app.handlers.chat_handler.run_intent_router",
            return_value={
                "route": "direct_reply",
                "intent": "network_speed_test_guidance",
                "should_cancel_current_flow": False,
                "reason": "model_speed_test_guidance_contract",
            },
        ):
            result = detect_active_flow_switch(
                "測速只有30M", memory, [], RunnableLambda(lambda _: AIMessage(content="{}")), {}
            )

        self.assertEqual(result["route"], "continue_current_flow")
        self.assertFalse(result["should_cancel_current_flow"])
        self.assertEqual(memory["known_info"]["declared_plan_speed_mbps"], 300.0)

    def test_handoff_acceptance_keeps_repair_escalation_state(self):
        memory = {
            "company_code": "tdtv",
            "clarify_context": {"type": "human_handoff_offer"},
            "known_info": {
                "troubleshooting_type": "network",
                "troubleshooting_failed": "yes",
                "repair_ready": "yes",
                "declared_plan_speed_mbps": 300.0,
                "download_speed": 30.0,
            },
        }
        with patch(
            "app.handlers.chat_handler.run_intent_router",
            return_value={
                "route": "direct_reply",
                "intent": "human_handoff_request",
                "should_cancel_current_flow": False,
                "reason": "model_accepted_handoff",
            },
        ):
            result = detect_active_flow_switch(
                "對", memory, [], RunnableLambda(lambda _: AIMessage(content="{}")), {}
            )

        self.assertFalse(result["should_cancel_current_flow"])
        memory["known_info"]["human_handoff_active"] = "yes"
        repeated = build_repeat_repair_escalation_router(memory)
        self.assertEqual(repeated["intent"], "human_handoff_request")
        self.assertNotIn("測速", repeated["reply"])

    def test_account_transfer_service_selection_keeps_transfer_context(self):
        context = build_clarify_context(
            {"intent": "service_account_transfer_service_clarify", "topic": "更名服務類型"},
            original_query="更換戶名",
        )
        memory = {"clarify_context": context, "known_info": {}}
        selected, validated = resolve_model_selected_context(
            memory,
            {"route": "continue_current_flow", "intent": "service_account_transfer", "selected_option_id": "account_transfer_cable_tv"},
        )

        self.assertTrue(validated)
        self.assertEqual(selected["route"], "knowledge_query")
        self.assertIn("更名過戶", selected["knowledge_query"])
        self.assertNotIn("收視費", selected["knowledge_query"])
        self.assertIn("身分證正本", selected["reply"])

    def test_account_transfer_document_question_can_leave_optional_service_menu(self):
        context = build_clarify_context(
            {"intent": "service_account_transfer_service_clarify", "topic": "更名服務類型"},
            original_query="過戶",
        )
        memory = {"clarify_context": context, "known_info": {}}
        decision, validated = resolve_model_selected_context(
            memory,
            {
                "route": "direct_reply",
                "intent": "account_holder_change_required_documents",
                "should_cancel_current_flow": False,
                "reply": "辦理更名過戶所需的共通證件",
            },
        )
        self.assertFalse(validated)
        self.assertIsNone(memory["clarify_context"])
        self.assertEqual(decision["intent"], "account_holder_change_required_documents")

    def test_repair_form_is_distinct_from_human_handoff_offer(self):
        plan = build_plan_from_router({
            "route": "direct_reply",
            "intent": "repair_form_guidance",
            "reply": "",
        })
        self.assertIn("維修申告", plan["reply"])
        self.assertNotIn("請問是否需要", plan["reply"])
        self.assertNotIn("前述排錯仍未恢復", plan["reply"])

        memory = {"company_code": "tdtv", "known_info": {
            "troubleshooting_type": "remote",
            "troubleshooting_failed": "yes",
            "repair_ready": "yes",
        }}
        with patch("app.handlers.chat_handler.run_intent_router", return_value={
            "route": "direct_reply",
            "intent": "repair_form_guidance",
            "should_cancel_current_flow": False,
            "reply": "請填寫維修申告表單",
        }):
            decision = detect_active_flow_switch(
                "登記維修", memory, [], RunnableLambda(lambda _: AIMessage(content="{}")), {}
            )
        self.assertEqual(decision["intent"], "repair_form_guidance")
        self.assertFalse(decision["should_cancel_current_flow"])

    def test_customer_can_choose_repair_form_after_first_guided_step(self):
        memory = {"company_code": "tdtv", "known_info": {
            "troubleshooting_started": "yes",
            "troubleshooting_type": "remote",
            "troubleshooting_step": "remote_check_light",
            "troubleshooting_failed": "no",
            "repair_ready": "no",
        }}
        self.assertTrue(is_repair_form_available(memory))
        self.assertFalse(is_repair_form_available({"known_info": {}}))
        self.assertFalse(is_repair_form_available({"known_info": {
            "troubleshooting_started": "yes",
            "troubleshooting_type": "unknown",
            "troubleshooting_step": "ask_fault_category",
        }}))
        with patch("app.handlers.chat_handler.run_intent_router", return_value={
            "route": "direct_reply",
            "intent": "repair_form_guidance",
            "should_cancel_current_flow": True,
            "reply": "請填寫維修申告表單",
        }):
            decision = detect_active_flow_switch("登記維修", memory, [], None, {})
        self.assertEqual(decision["intent"], "repair_form_guidance")
        self.assertFalse(decision["should_cancel_current_flow"])

        candidate = build_memory_without_active_flow(memory)
        self.assertEqual(candidate["known_info"]["troubleshooting_started"], "no")
        self.assertIn('"repair_form_available":"yes"', build_memory_summary(candidate))

    def test_same_fault_after_form_offer_does_not_restart_troubleshooting(self):
        memory = {"company_code": "tdtv", "known_info": {
            "troubleshooting_started": "yes",
            "troubleshooting_type": "remote",
            "troubleshooting_step": "remote_check_light",
            "repair_form_offered": "yes",
        }}
        with patch("app.handlers.chat_handler.run_intent_router", return_value={
            "route": "continue_current_flow",
            "intent": "remote_control_issue",
            "should_cancel_current_flow": False,
        }):
            decision = detect_active_flow_switch("有亮但仍不能選台", memory, [], None, {})
        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "repair_form_guidance")

    def test_combined_fee_scope_requires_validated_choice(self):
        context = build_clarify_context(
            {
                "intent": "existing_vs_new_tv_network_clarify",
                "topic": "電視加網路月費",
                "reply": "請問是現有電視加辦網路，還是新申裝兩項服務？",
            },
            original_query="第四台再加Wi-Fi網路月費要多少",
        )
        memory = {"clarify_context": context, "known_info": {}}
        undecided, validated = resolve_model_selected_context(
            memory,
            {
                "route": "knowledge_query",
                "intent": "pure_network_install_plan_query",
                "should_cancel_current_flow": False,
            },
        )
        self.assertFalse(validated)
        self.assertEqual(undecided["route"], "clarify")
        self.assertIn("現有電視加辦網路", undecided["reply"])

        selected, validated = resolve_model_selected_context(
            memory,
            {
                "route": "knowledge_query",
                "intent": "other",
                "selected_option_id": "tv_network_new_install",
            },
        )
        self.assertTrue(validated)
        self.assertEqual(selected["promotion_scope"], "tv_network")
        self.assertEqual(selected["intent"], "tv_network_install_plan_query")

        existing, validated = resolve_model_selected_context(
            memory,
            {
                "route": "knowledge_query",
                "intent": "other",
                "selected_option_id": "tv_existing_add_broadband",
            },
        )
        self.assertTrue(validated)
        self.assertEqual(existing["promotion_scope"], "tv_network")
        self.assertEqual(existing["promotion_query_kind"], "catalog")
        self.assertEqual(existing["intent"], "existing_tv_add_broadband_fee_query")
        self.assertIn("資格", existing["requested_information"])

    def test_existing_tv_add_broadband_catalog_is_reference_not_account_quote(self):
        docs = [{
            "campaign_name": "測試同裝方案",
            "document_type": "promotion_campaign",
            "record_type": "campaign_rate",
            "service_types": "電視網路同裝",
            "answer": "100M/10M：月繳 890 元",
        }]
        scoped = focus_knowledge_process_docs(
            docs,
            "existing_tv_add_broadband_fee_query",
            promotion_query_kind="catalog",
        )
        reply = build_promotion_catalog_reply(
            "加上Wi-Fi網路月費",
            scoped,
            intent="existing_tv_add_broadband_fee_query",
            promotion_scope="tv_network",
            promotion_query_kind="catalog",
        )
        self.assertIn("測試同裝方案", reply)
        self.assertIn("890 元", reply)
        self.assertIn("現有合約", reply)
        self.assertIn("適用資格", reply)

    def test_catalog_requery_is_not_forced_to_select_a_named_campaign(self):
        memory = {
            "clarify_context": {
                "type": "campaign_catalog_selection",
                "topic": "優惠方案清單",
                "options": {"方案甲": {
                    "option_id": "option_1",
                    "intent": "promotion_named_campaign_selection",
                    "route": "knowledge_query",
                }},
            }
        }
        router = {
            "route": "knowledge_query",
            "intent": "tv_network_install_plan_query",
            "promotion_scope": "tv_network",
            "promotion_query_kind": "catalog",
            "should_cancel_current_flow": False,
        }
        decision, validated = resolve_model_selected_context(memory, router)
        self.assertFalse(validated)
        self.assertEqual(decision["route"], "knowledge_query")
        self.assertIsNone(memory["clarify_context"])

    def test_transfer_without_matching_documents_uses_approved_contract(self):
        reply = compose_knowledge_reply(
            "更換戶名", "", [], intent="account_transfer_process",
            fallback_reply="辦理變更使用者，請由雙方攜帶核准證件至門市。",
        )
        self.assertIn("雙方", reply)
        self.assertNotIn("沒有查到足夠明確", reply)

    def test_transfer_documents_exclude_unrelated_social_documents(self):
        docs = [
            {"question": "低收入戶申請應備證件", "answer": "身心障礙優惠文件"},
            {"question": "更名過戶應備證件", "answer": "變更使用者須由原用戶與新用戶準備證件"},
        ]
        scoped = focus_knowledge_process_docs(docs, "service_transfer_document_requirements")
        self.assertEqual([doc["question"] for doc in scoped], ["更名過戶應備證件"])

    def test_existing_tv_add_broadband_rejects_wifi_device_fees(self):
        docs = [
            {"question": "Wi-Fi 分享器加購月費", "answer": "分享器月費 25 元"},
            {"question": "有線電視基本收視費", "answer": "電視月費 550 元"},
            {"question": "既有電視用戶加辦寬頻", "answer": "現有有線電視用戶加辦寬頻須確認合約與方案"},
        ]
        scoped = focus_knowledge_process_docs(docs, "existing_tv_add_broadband_fee_query")
        self.assertEqual([doc["question"] for doc in scoped], ["既有電視用戶加辦寬頻"])

        fallback = compose_knowledge_reply(
            "加上Wi-Fi網路月費", "", [], intent="existing_tv_add_broadband_fee_query"
        )
        self.assertIn("現有合約", fallback)
        self.assertNotIn("分享器", fallback)

    def test_repair_escalation_survives_set_top_box_network_detail(self):
        memory = {"company_code": "tdtv", "known_info": {
            "troubleshooting_started": "no",
            "troubleshooting_type": "tv",
            "troubleshooting_failed": "yes",
            "repair_ready": "yes",
            "issue_description": "哈TV機上盒仍無法連網",
        }}
        with patch("app.handlers.chat_handler.run_intent_router", return_value={
            "route": "troubleshooting",
            "intent": "tv_set_top_box_network_connection_issue",
            "service_scope": "哈TV機上盒聯網",
            "should_cancel_current_flow": False,
        }):
            result = detect_active_flow_switch(
                "網路正常，是哈TV機上盒無法連網",
                memory,
                [],
                RunnableLambda(lambda _: AIMessage(content="{}")),
                {},
            )
        self.assertEqual(result["intent"], "human_handoff_offer")
        self.assertIn("申告維修", result["reply"])

    def test_handoff_offer_keeps_active_fault_context_and_form(self):
        memory = {"company_code": "tdtv", "known_info": {
            "troubleshooting_started": "yes",
            "troubleshooting_type": "remote",
            "troubleshooting_step": "remote_check_receiver",
            "issue_description": "遙控器有亮但不能選台",
        }}
        with patch("app.handlers.chat_handler.run_intent_router", return_value={
            "route": "clarify",
            "intent": "human_handoff_offer",
            "reply": "請問是否需要幫您轉接真人文字客服？",
            "should_cancel_current_flow": False,
        }):
            result = detect_active_flow_switch(
                "有試過了，沒用", memory, [],
                RunnableLambda(lambda _: AIMessage(content="{}")), {},
            )
        self.assertFalse(result["should_cancel_current_flow"])
        reply = add_repair_form_to_handoff_offer(result["reply"], memory)
        self.assertIn("維修申告", reply)
        self.assertIn("尚未代您登記", reply)

    def test_remote_first_reply_does_not_claim_diagnosis(self):
        memory = {"known_info": {}}
        result = apply_troubleshooting_engine(
            "遙控器不能使用", memory, troubleshooting_plan("remote_control_issue")
        )
        self.assertNotIn("比較像是遙控器控制異常", result["reply"])
        self.assertIn("更換新電池", result["reply"])

    def test_bare_repair_request_is_forced_to_troubleshooting_first(self):
        decision = router_guard(
            user_input="我要登記維修",
            memory={"known_info": {}},
            router={
                "route": "tool_action",
                "intent": "repair_ticket_request",
                "tool_name": "create_repair_ticket",
                "topic": "維修申告",
                "should_cancel_current_flow": False,
                "should_call_tool": True,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "",
                "extracted_slots": {},
                "reason": "llm_bare_repair_request",
            },
        )

        self.assertEqual(decision["route"], "troubleshooting")
        self.assertEqual(decision["intent"], "repair_troubleshooting_intake")
        self.assertFalse(decision["should_call_tool"])
        self.assertIsNone(decision["tool_name"])

    def test_termination_selection_uses_validated_model_option_id(self):
        context = build_clarify_context(
            {
                "intent": "service_termination_service_clarify",
                "topic": "退租服務類型",
            },
            original_query="解約要繳回什麼東西",
        )
        memory = {"clarify_context": context}

        decision, validated = resolve_model_selected_context(
            memory,
            {
                "route": "knowledge_query",
                "intent": "other",
                "selected_option_id": "termination_cable_tv",
            },
        )

        self.assertTrue(validated)
        self.assertEqual(decision["intent"], "cable_tv_termination_guidance")
        self.assertEqual(decision["route"], "direct_reply")
        self.assertIn("機上盒", decision["reply"])
        self.assertEqual(
            memory["known_info"]["termination_service_scope"],
            "cable_tv",
        )

    def test_termination_selection_accepts_unique_model_intent_alias(self):
        context = build_clarify_context(
            {
                "intent": "service_termination_service_clarify",
                "topic": "退租服務類型",
            },
            original_query="解約要繳回什麼東西",
        )
        memory = {"clarify_context": context}

        decision, validated = resolve_model_selected_context(
            memory,
            {
                "route": "knowledge_query",
                "intent": "cable_tv_termination_equipment_return",
            },
        )

        self.assertTrue(validated)
        self.assertEqual(decision["intent"], "cable_tv_termination_guidance")
        self.assertEqual(decision["route"], "direct_reply")
        self.assertIn("機上盒", decision["reply"])
        self.assertEqual(
            memory["known_info"]["termination_service_scope"],
            "cable_tv",
        )

    def test_cancellation_handoff_model_alias_uses_real_handoff_contract(self):
        memory = {"known_info": {}}
        decision = router_guard(
            user_input="如何取消，怎麼找客服",
            memory=memory,
            router={
                "route": "unsupported_flow",
                "intent": "internet_service_cancellation_handoff",
                "topic": "寬頻網路退租",
                "reply": "請撥打客服電話。",
                "reason": "model_cancellation_handoff",
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertEqual(decision["intent"], "human_handoff_request")
        self.assertIn("真人文字客服", decision["reply"])
        self.assertNotIn("電話", decision["reply"])
        self.assertEqual(memory["known_info"]["human_handoff_active"], "yes")

        followup = router_guard(
            user_input="如何取消，怎麼找客服",
            memory=memory,
            router={
                "route": "direct_reply",
                "intent": "internet_cancellation_guidance",
                "topic": "寬頻網路退租",
                "reply": "請撥打客服電話。",
                "reason": "model_cancellation_guidance",
            },
        )

        self.assertEqual(followup["intent"], "human_handoff_request")
        self.assertNotIn("電話", followup["reply"])

    def test_member_login_model_intent_uses_two_system_contract(self):
        decision = router_guard(
            user_input="如何登入會員",
            memory={"known_info": {}},
            router={
                "route": "knowledge_query",
                "intent": "member_login_guidance",
                "knowledge_query": "會員登入",
                "reason": "model_member_login",
            },
        )

        self.assertEqual(decision["route"], "direct_reply")
        self.assertFalse(decision["should_retrieve_knowledge"])
        self.assertIn("登入資料是分開的", decision["reply"])
        self.assertIn("官網", decision["reply"])
        self.assertIn("哈TV行動客服 APP", decision["reply"])

    def test_account_holder_change_model_intents_use_approved_contracts(self):
        fee = router_guard(
            user_input="變更使用者需要費用嗎",
            memory={"known_info": {}},
            router={
                "route": "knowledge_query",
                "intent": "account_holder_change_fee_query",
                "reason": "model_account_holder_change_fee",
            },
        )
        documents = router_guard(
            user_input="要準備哪些身分資料",
            memory={"known_info": {}},
            router={
                "route": "knowledge_query",
                "intent": "account_user_change_required_documents",
                "reason": "model_account_holder_change_documents",
            },
        )

        self.assertIn("不需收取費用", fee["reply"])
        self.assertFalse(fee["should_retrieve_knowledge"])
        self.assertIn("原使用者", documents["reply"])
        self.assertIn("新使用者", documents["reply"])
        self.assertIn("健保卡或駕照", documents["reply"])

    def test_account_holder_change_contract_normalizes_model_intents(self):
        def wrong_route(intent: str):
            return RunnableLambda(lambda _prompt: AIMessage(content=json.dumps({
                "route": "knowledge_query",
                "intent": intent,
                "topic": "身分資料",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "身分資料",
                "reply": "",
                "extracted_slots": {},
                "reason": "model_selected_unstable_knowledge_route",
            }, ensure_ascii=False)))

        fee = run_intent_router(
            user_input="變更使用者需要費用嗎？",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=wrong_route("account_holder_change_fee_query"),
        )
        documents = run_intent_router(
            user_input="要準備那些身分資料",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[
                {"role": "user", "content": "變更使用者需要費用嗎？"},
                {"role": "assistant", "content": "變更使用者不需收取費用。"},
            ],
            llm=wrong_route("account_holder_change_required_documents"),
        )

        self.assertEqual(fee["route"], "direct_reply")
        self.assertEqual(fee["intent"], "account_holder_change_fee_query")
        self.assertIn("不需收取費用", fee["reply"])
        self.assertEqual(documents["route"], "direct_reply")
        self.assertEqual(
            documents["intent"],
            "account_holder_change_required_documents",
        )
        self.assertIn("健保卡或駕照", documents["reply"])

    def test_unknown_model_intent_is_not_reclassified_by_customer_keywords(self):
        llm = RunnableLambda(lambda _prompt: AIMessage(content=json.dumps({
            "route": "knowledge_query",
            "intent": "other",
            "topic": "變更使用者",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "變更使用者費用",
            "reply": "",
            "extracted_slots": {},
            "reason": "model_other_intent",
        }, ensure_ascii=False)))

        decision = run_intent_router(
            user_input="變更使用者需要費用嗎？",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=llm,
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "other")

    def test_account_holder_change_context_does_not_capture_other_document_flow(self):
        llm = RunnableLambda(lambda _prompt: AIMessage(content=json.dumps({
            "route": "knowledge_query",
            "intent": "cable_tv_termination_documents",
            "topic": "有線電視退租證件",
            "should_cancel_current_flow": True,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "有線電視退租 應備證件",
            "reply": "",
            "extracted_slots": {},
            "reason": "model_explicit_termination_switch",
        }, ensure_ascii=False)))

        decision = run_intent_router(
            user_input="退租要帶哪些證件",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[{"role": "user", "content": "變更使用者需要費用嗎？"}],
            llm=llm,
        )

        self.assertEqual(decision["route"], "knowledge_query")
        self.assertEqual(decision["intent"], "cable_tv_termination_documents")

    def test_recovered_direct_reply_intents_use_approved_contracts(self):
        cases = {
            "broadband_termination_guidance": "數據機",
            "line_tv_cancellation_guidance": "安心使用至當期最後一天",
            "modem_ds_light_status_guidance": "正在同步下行訊號",
            "network_speed_test_guidance": "https://www.speedtest.net/",
            "online_payment_submission_issue": "3D 驗證",
            "payment_posting_confirmation_guidance": "等待約 2 分鐘",
            "personal_contract_info_lookup": "登入會員後才能查詢",
            "wifi_router_settings_help": "Wireless／WLAN",
            "identity_document_upload": "不會代收身分證",
        }

        for intent, expected in cases.items():
            with self.subTest(intent=intent):
                decision = router_guard(
                    user_input="測試訊息",
                    memory={"known_info": {}},
                    router={
                        "route": "knowledge_query",
                        "intent": intent,
                        "should_retrieve_knowledge": True,
                        "knowledge_query": "錯誤的泛用查詢",
                        "reply": "錯誤回覆",
                        "reason": "model_selected_known_intent",
                    },
                )

                self.assertEqual(decision["route"], "direct_reply")
                self.assertFalse(decision["should_retrieve_knowledge"])
                self.assertIn(expected, decision["reply"])

    def test_repair_offer_blocks_phone_only_model_reply(self):
        decision = router_guard(
            user_input="所以要打客服電話",
            memory={
                "clarify_context": {"type": "human_handoff_offer"},
                "known_info": {
                    "troubleshooting_failed": "yes",
                    "repair_ready": "yes",
                },
            },
            router={
                "route": "company_info",
                "intent": "contact_phone",
                "topic": "contact_phone",
                "reason": "model_contact_phone",
            },
        )

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "human_handoff_offer")
        self.assertIn("申告維修單", decision["reply"])
        self.assertIn("轉真人", decision["reply"])

    def test_repair_offer_blocks_generic_company_info_phone_topic(self):
        decision = router_guard(
            user_input="所以要打客服電話",
            memory={
                "clarify_context": {"type": "human_handoff_offer"},
                "known_info": {
                    "troubleshooting_failed": "yes",
                    "repair_ready": "yes",
                },
            },
            router={
                "route": "company_info",
                "intent": "company_info",
                "topic": "contact_phone",
                "reason": "model_company_info_phone_topic",
            },
        )

        self.assertEqual(decision["route"], "clarify")
        self.assertEqual(decision["intent"], "human_handoff_offer")
        self.assertIn("申告維修單", decision["reply"])
        self.assertIn("轉真人", decision["reply"])

    def test_active_termination_handoff_does_not_return_to_guidance(self):
        decision = router_guard(
            user_input="如何取消，怎麼找客服",
            memory={
                "known_info": {
                    "human_handoff_active": "yes",
                    "human_handoff_topic": "寬頻網路退租",
                },
            },
            router={
                "route": "direct_reply",
                "intent": "broadband_termination_guidance",
                "topic": "寬頻網路退租",
                "should_cancel_current_flow": False,
                "reason": "model_returned_to_termination_guidance",
            },
        )

        self.assertEqual(decision["intent"], "human_handoff_request")
        self.assertIn("真人", decision["reply"])

    def test_dynamic_campaign_selection_persists_validated_topic(self):
        memory = {
            "clarify_context": {
                "type": "campaign_catalog_selection",
                "topic": "優惠方案清單",
                "options": {
                    "動態方案 X9": {
                        "option_id": "option_1",
                        "entity_type": "knowledge_document",
                        "route": "knowledge_query",
                        "intent": "promotion_named_campaign_selection",
                        "topic": "動態方案 X9",
                        "knowledge_query": "動態方案 X9 優惠方案",
                        "promotion_query_kind": "campaign_detail",
                        "document_id": "doc-x9",
                    }
                },
            }
        }

        _, validated = resolve_model_selected_context(
            memory,
            {
                "route": "knowledge_query",
                "intent": "other",
                "selected_option_id": "option_1",
            },
        )

        self.assertTrue(validated)
        self.assertEqual(memory["last_campaign_topic"], "動態方案 X9")
        self.assertEqual(
            memory["known_info"]["last_campaign_topic"],
            "動態方案 X9",
        )

    def test_picture_quality_followup_offers_human_after_failed_steps(self):
        memory = {"known_info": {}}

        first = apply_troubleshooting_engine(
            "電視節目有些頻道會抖動",
            memory,
            troubleshooting_plan("tv_picture_quality_issue"),
        )
        second = apply_troubleshooting_engine(
            "還是會抖動有異音",
            memory,
            troubleshooting_plan("tv_picture_quality_issue"),
        )

        self.assertFalse(first["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")
        self.assertFalse(second["should_call_tool"])
        self.assertEqual(second["intent"], "human_handoff_offer")
        self.assertIn("是否需要", second["reply"])

    def test_picture_quality_model_intent_aliases_enter_same_flow(self):
        memory = {"known_info": {}}

        first = apply_troubleshooting_engine(
            "電視節目有些頻道會抖動",
            memory,
            troubleshooting_plan("tv_channel_jitter_issue"),
        )
        second = apply_troubleshooting_engine(
            "還是會抖動有異音",
            memory,
            troubleshooting_plan("tv_channel_picture_audio_issue"),
        )

        self.assertIn("重新搜頻", first["reply"])
        self.assertEqual(second["intent"], "human_handoff_offer")
        self.assertIn("是否需要", second["reply"])

    def test_remote_control_model_intent_alias_starts_remote_flow(self):
        memory = {"known_info": {}}

        result = apply_troubleshooting_engine(
            "遙控器壞掉，不能選台",
            memory,
            troubleshooting_plan("tv_remote_control_channel_issue"),
        )

        self.assertEqual(memory["known_info"]["troubleshooting_type"], "remote")
        self.assertTrue(memory["known_info"]["troubleshooting_step"].startswith("remote_"))
        self.assertNotIn("查詢資料", result["reply"])

    def test_set_top_box_network_flow_never_claims_recovery_without_confirmation(self):
        memory = {"known_info": {}}

        first = apply_troubleshooting_engine(
            "哈TV機上盒，網路連線有問題",
            memory,
            troubleshooting_plan("tv_set_top_box_network_connection_issue"),
        )
        second = apply_troubleshooting_engine(
            "Wi-Fi訊號正常，但應用程式無法連上網路",
            memory,
            troubleshooting_plan("tv_set_top_box_app_network_issue"),
            llm=RunnableLambda(lambda _: AIMessage(content='{"label":"unknown"}')),
        )

        self.assertEqual(memory["known_info"]["troubleshooting_type"], "set_top_box_network")
        self.assertNotIn("數據機燈號", first["reply"])
        self.assertNotIn("已恢復正常", second["reply"])
        self.assertIn("機上盒", second["reply"])

    def test_set_top_box_failed_step_offers_human_handoff(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "set_top_box_network",
                "troubleshooting_step": "stb_app_connectivity_check",
                "issue_description": "機上盒應用程式無法連網",
                "repair_ready": "no",
            }
        }

        result = apply_troubleshooting_engine(
            "還是不行",
            memory,
            troubleshooting_plan("tv_set_top_box_app_network_issue"),
            llm=RunnableLambda(lambda _: AIMessage(content='{"label":"failed"}')),
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(result["intent"], "human_handoff_offer")
        self.assertIn("是否需要", result["reply"])

    def test_repeated_same_fault_after_repair_offer_skips_troubleshooting(self):
        memory = {
            "company_code": "tdtv",
            "clarify_context": {"type": "human_handoff_offer"},
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "set_top_box_network",
                "troubleshooting_failed": "yes",
                "repair_ready": "yes",
                "issue_description": "哈TV機上盒的網路連線有問題",
            },
        }

        with patch(
            "app.handlers.chat_handler.run_intent_router",
            return_value={
                "route": "troubleshooting",
                "intent": "tv_set_top_box_network_connection_issue",
                "service_scope": "哈TV機上盒聯網",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "reply": "",
                "reason": "same_set_top_box_fault",
            },
        ):
            result = detect_active_flow_switch(
                "網路正常，是哈TV機上盒的網路連線有問題",
                memory,
                [],
                RunnableLambda(lambda _: AIMessage(content="{}")),
                {},
            )

        self.assertEqual(result["intent"], "human_handoff_offer")
        self.assertEqual(
            result["reason"],
            "repair_escalation_already_offered_same_issue",
        )
        self.assertIn("您的問題需進一步協助處理", result["reply"])
        self.assertIn("維修申告", result["reply"])
        self.assertIn("轉真人服務", result["reply"])
        self.assertNotIn("不會再要求", result["reply"])

    def test_repeat_repair_offer_reply_uses_customer_service_wording(self):
        router = build_repeat_repair_escalation_router(
            {"company_code": "tdtv", "known_info": {"repair_ready": "yes"}}
        )

        self.assertEqual(router["route"], "clarify")
        self.assertEqual(router["intent"], "human_handoff_offer")
        self.assertIn(
            "您的問題需進一步協助處理，請填寫申告維修單",
            router["reply"],
        )
        self.assertIn("或選擇轉真人服務", router["reply"])

    def test_set_top_box_app_detail_starts_app_step_before_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "set_top_box_network",
                "troubleshooting_step": "stb_network_check",
                "issue_description": "哈TV機上盒網路連線有問題",
                "repair_ready": "no",
            }
        }

        result = apply_troubleshooting_engine(
            "Wi-Fi訊號正常，但應用程式無法連上網路",
            memory,
            troubleshooting_plan("troubleshooting"),
            llm=RunnableLambda(
                lambda _: AIMessage(content='{"label":"app_connectivity_detail"}')
            ),
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(
            memory["known_info"]["troubleshooting_step"],
            "stb_app_connectivity_check",
        )
        self.assertIn("中斷後重新連線", result["reply"])

    def test_set_top_box_unknown_followups_do_not_force_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "set_top_box_network",
                "troubleshooting_step": "stb_network_check",
                "issue_description": "哈TV機上盒網路連線有問題",
                "repair_ready": "no",
            }
        }
        llm = RunnableLambda(lambda _: AIMessage(content='{"label":"unknown"}'))

        first = apply_troubleshooting_engine(
            "想知道怎麼解決問題",
            memory,
            troubleshooting_plan("tv_set_top_box_network_connection_issue"),
            llm=llm,
        )
        second = apply_troubleshooting_engine(
            "如何排除",
            memory,
            troubleshooting_plan("tv_set_top_box_network_connection_issue"),
            llm=llm,
        )
        third = apply_troubleshooting_engine(
            "排錯流程是什麼",
            memory,
            troubleshooting_plan("tv_set_top_box_network_connection_issue"),
            llm=llm,
        )

        self.assertFalse(first["should_call_tool"])
        self.assertFalse(second["should_call_tool"])
        self.assertNotEqual(memory["known_info"].get("repair_ready"), "yes")
        self.assertNotEqual(first["reply"], second["reply"])
        self.assertNotEqual(second["reply"], third["reply"])
        self.assertIn("完成", second["reply"])
        self.assertIn("1.", third["reply"])
        self.assertNotIn("一般寬頻斷線流程", first["reply"])

    def test_punctuation_only_followup_keeps_active_troubleshooting_flow(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "set_top_box_network",
                "troubleshooting_step": "stb_app_connectivity_check",
            }
        }
        latency = {}

        with patch("app.handlers.chat_handler.run_intent_router") as run_router:
            result = detect_active_flow_switch(
                "？",
                memory,
                [],
                RunnableLambda(lambda _: AIMessage(content="{}")),
                latency,
            )

        self.assertIsNone(result)
        run_router.assert_not_called()
        self.assertNotIn("intent_router_interrupt", latency)

    def test_human_only_information_requires_confirmation_before_handoff(self):
        context = build_clarify_context(
            {
                "route": "clarify",
                "intent": "human_handoff_offer",
                "topic": "活動贈品型號",
                "reply": (
                    "500M 寬頻活動的電視與冰箱型號需由客服依當期庫存確認。"
                    "請問是否需要幫您轉接真人文字客服？"
                ),
            },
            original_query="請提供500M活動的電視和冰箱型號",
        )

        self.assertEqual(context["type"], "human_handoff_offer")
        self.assertNotIn("轉真人文字客服</a>", context["prompt"])

        decision, validated = resolve_model_selected_context(
            {"clarify_context": context},
            {
                "route": "direct_reply",
                "intent": "other",
                "selected_option_id": "human_handoff_offer_accept",
            },
        )

        self.assertTrue(validated)
        self.assertEqual(decision["intent"], "human_handoff_request")
        self.assertIn("真人文字客服", decision["reply"])

    def test_router_path_flow_gives_device_specific_checks(self):
        memory = {"known_info": {}}

        result = apply_troubleshooting_engine(
            "透過路由器很慢",
            memory,
            troubleshooting_plan("router_path_slow_issue"),
        )

        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_router_path_check")
        self.assertIn("QoS", result["reply"])
        self.assertIn("Gigabit", result["reply"])
        self.assertNotIn("所有網站", result["reply"])

    def test_router_path_requires_two_failed_results_before_handoff_offer(self):
        memory = {"known_info": {}}
        start_router = troubleshooting_plan("router_path_slow_issue")
        apply_troubleshooting_engine("透過路由器很慢", memory, start_router)
        llm = RunnableLambda(lambda _: AIMessage(content='{"label":"failed"}'))

        first = apply_troubleshooting_engine(
            "測了還是很慢",
            memory,
            troubleshooting_plan("router_path_slow_issue"),
            llm=llm,
        )
        second = apply_troubleshooting_engine(
            "直連跟路由器都還是很慢",
            memory,
            troubleshooting_plan("router_path_slow_issue"),
            llm=llm,
        )

        self.assertFalse(first["should_call_tool"])
        self.assertFalse(second["should_call_tool"])
        self.assertEqual(second["intent"], "human_handoff_offer")
        self.assertIn("是否需要", second["reply"])

    def test_router_business_answers_are_normalized_from_model_intents(self):
        cases = (
            (
                "self_owned_router_compatibility_guidance",
                "公司沒有指定分享器品牌或型號",
                "DHCP／自動取得 IP",
            ),
            (
                "self_owned_router_setup_guidance",
                "WAN／Internet",
                "自動註冊機制",
            ),
            (
                "modem_dual_router_dhcp_guidance",
                "原則上可以",
                "再由真人客服協助確認",
            ),
            (
                "dynamic_ip_allocation_count",
                "8 組浮動 IP",
                "特殊方案",
            ),
            (
                "router_manual_registration_guidance",
                "電腦網卡更換註冊",
                "轉接真人文字客服",
            ),
            (
                "tv_safe_mode_guidance",
                "電視機本身的系統狀態",
                "電視電源拔除約 1 分鐘",
            ),
            (
                "pppoe_connection_type_guidance",
                "不需要 PPPoE 帳號或密碼",
                "DHCP／自動取得 IP",
            ),
            (
                "basic_vs_digital_channels_comparison",
                "基本收視頻道",
                "另行付費加購",
            ),
            (
                "service_suspension_process",
                "臨櫃辦理",
                "復機費每戶 200 元",
            ),
        )

        for intent, expected, extra in cases:
            with self.subTest(intent=intent):
                decision = router_guard(
                    user_input=(
                        "電視畫面顯示安全模式"
                        if intent == "tv_safe_mode_guidance" else "測試問題"
                    ),
                    memory={"known_info": {}},
                    router={
                        "route": "direct_reply",
                        "intent": intent,
                        "topic": "路由器設定",
                        "reply": "模型自由回答",
                        "reason": "model_router_guidance",
                    },
                )

                self.assertEqual(decision["route"], "direct_reply")
                self.assertIn(expected, decision["reply"])
                self.assertIn(extra, decision["reply"])

    def test_router_replacement_runs_dhcp_then_manual_registration_then_handoff(self):
        memory = {"known_info": {}}
        start = apply_troubleshooting_engine(
            "換新路由器後不能上網，舊的正常",
            memory,
            troubleshooting_plan("router_replacement_registration_issue"),
        )

        self.assertEqual(
            memory["known_info"]["troubleshooting_step"],
            "net_device_registration",
        )
        self.assertIn("DHCP／自動取得 IP", start["reply"])
        self.assertNotIn("電腦網卡更換註冊", start["reply"])

        failed_llm = RunnableLambda(lambda _: AIMessage(content='{"label":"failed"}'))
        manual = apply_troubleshooting_engine(
            "已設為自動取得 IP，還是不能上網",
            memory,
            troubleshooting_plan("continue_current_flow"),
            llm=failed_llm,
        )

        self.assertEqual(
            memory["known_info"]["troubleshooting_step"],
            "net_manual_device_registration",
        )
        self.assertIn("電腦網卡更換註冊", manual["reply"])

        handoff = apply_troubleshooting_engine(
            "手動註冊後仍無法上網",
            memory,
            troubleshooting_plan("continue_current_flow"),
            llm=failed_llm,
        )

        self.assertEqual(handoff["intent"], "human_handoff_offer")
        self.assertIn("是否需要", handoff["reply"])
        self.assertNotIn("申告維修", handoff["reply"])

    def test_picture_quality_legacy_repair_state_offers_human_handoff(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "tv",
                "troubleshooting_failed": "yes",
                "repair_followup_active": "yes",
                "repair_flow_status": "disabled",
                "issue_description": "畫面抖動",
            }
        }

        result = apply_troubleshooting_engine(
            "還是會抖動有異音",
            memory,
            troubleshooting_plan("tv_picture_quality_issue"),
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(result["intent"], "human_handoff_offer")
        self.assertIn("是否需要", result["reply"])
        self.assertIn("不需要再重複", result["reply"])

if __name__ == "__main__":
    unittest.main()
