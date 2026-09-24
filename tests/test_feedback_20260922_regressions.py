import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import (
    build_repeat_repair_escalation_router,
    build_clarify_context,
    detect_active_flow_switch,
    resolve_model_selected_context,
)
from app.services.intent_router import router_guard, run_intent_router
from app.services.troubleshooting_engine import apply_troubleshooting_engine


def troubleshooting_plan(intent: str) -> dict:
    return {
        "intent": intent,
        "reply": "",
        "should_call_tool": False,
        "tool_name": None,
    }


class Feedback20260922RegressionTest(unittest.TestCase):
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

        self.assertFalse(first["should_call_tool"])
        self.assertFalse(second["should_call_tool"])
        self.assertNotEqual(memory["known_info"].get("repair_ready"), "yes")

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
        )

        for intent, expected, extra in cases:
            with self.subTest(intent=intent):
                decision = router_guard(
                    user_input="測試問題",
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
