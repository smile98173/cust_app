import hashlib
import json
import unittest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import (
    RAG_SUMMARY_PROMPT,
    PROMOTION_REFERRAL_FOOTER,
    append_promotion_referral_code,
    apply_basic_tv_monthly_fee_concision,
    apply_basic_tv_two_year_fee_calculation,
    build_multi_plan_broadband_price_reply,
    build_promotion_catalog_reply,
    build_named_campaign_overview_reply,
    build_campaign_valid_period_reply,
    build_campaign_gift_followup_reply,
    build_campaign_total_fee_reply,
    build_digital_tv_package_addon_process_reply,
    build_app_payment_receipt_lookup_reply,
    build_cable_tv_termination_calculation_reply,
    build_contract_change_after_termination_reply,
    build_invoice_carrier_binding_reply,
    build_invoice_issue_timing_reply,
    build_plan_from_router,
    build_cloud_account_app_usage_reply,
    build_clear_channel_group_reply,
    build_basic_channel_table_reply,
    build_convenience_store_payment_machine_reply,
    build_next_tier_plan_fallback,
    build_evidence_compact_fallback,
    build_combo_rate_inclusion_reply,
    build_combo_service_inclusion_reply,
    build_hatv_hatnet_combo_overview_reply,
    has_knowledge_reply_evidence,
    build_clarify_context,
    apply_customer_reply_policies,
    build_repair_ticket_flow_disabled_reply,
    build_install_application_reply,
    build_contextual_knowledge_query,
    expand_targeted_knowledge_query,
    is_hatv_hatnet_combo_request,
    build_contextual_website_page_switch_router,
    format_customer_reply_text,
    finalize_customer_reply,
    handle_chat_message,
    extract_basic_tv_monthly_fee,
    exact_value_added_topic,
    infer_recent_topic,
    is_likely_active_flow_switch,
    select_contextual_history,
    run_tool_or_rag_flow,
    sanitize_customer_facing_jargon,
    resolve_clarify_context,
    should_cancel_pending_tool,
    ensure_known_link_mentions,
    ensure_repair_report_link,
    detect_active_flow_switch,
    filter_docs_with_llm_evidence,
    is_install_application_router_intent,
)
from app.services.intent_router import (
    HUMAN_HANDOFF_CONFIRM_REPLY,
    WEB_HUMAN_HANDOFF_REPLY,
    build_memory_summary,
    detect_contextual_feedback_direct_reply,
    detect_safe_direct_reply,
    is_paper_bill_request,
    resolve_remembered_value_added_followup,
    run_intent_router,
)
from app.services.kb_service import extract_query_strict_identifier_terms
from app.schemas.router import RouterDecision
from app.services.router_catalog import get_clarify_context, match_clarify_option
from app.services.router_prompt import build_intent_router_rules
from app.services.tool_manager import CUSTOMER_NOT_FOUND_MESSAGE, missing_response
from app.services.troubleshooting_engine import (
    apply_troubleshooting_engine,
    build_network_slow_reply,
    is_fault,
    is_network_fault,
    is_tv_fault,
    is_tv_authorization_issue,
    start_tv_input_source_troubleshooting,
)


class Response:
    def __init__(self, content):
        self.content = content


def llm_with_router_response(router_payload):
    def _invoke(_prompt):
        return Response(json.dumps(router_payload, ensure_ascii=False))

    return RunnableLambda(_invoke)


@unittest.skip(
    "Archived mixed rule-routing suite; active model-owned flow contracts are tested separately."
)
class ArchivedFlowRegressionReference(unittest.TestCase):
    def test_clear_channel_group_reply_returns_only_requested_source_facts(self):
        docs = [{
            "question": "清冰組",
            "answer": (
                "清冰組為申裝純網方案的客戶額外贈送的電視頻道。\n"
                "申裝該方案可免費借用 1 台聯網機上盒。\n"
                "每戶最多只能借用 1 台聯網機上盒，無法另外付費加裝。\n"
                "約 20～24 個頻道。\n"
                "實際頻道依公司安排，可能異動。"
            ),
        }]

        box_reply = build_clear_channel_group_reply(
            "清冰組可以借幾台聯網機上盒",
            docs,
            intent="clear_channel_group_query",
        )
        channel_reply = build_clear_channel_group_reply(
            "清冰組有幾個頻道",
            docs,
            intent="clear_channel_group_query",
        )

        self.assertIn("免費借用 1 台", box_reply)
        self.assertIn("無法另外付費加裝", box_reply)
        self.assertNotIn("20～24", box_reply)
        self.assertIn("20～24", channel_reply)
        self.assertIn("可能異動", channel_reply)
        self.assertNotIn("機上盒", channel_reply)

    def test_network_slow_reply_does_not_request_customer_number(self):
        result = build_network_slow_reply(
            {"known_info": {}},
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertIn("下載與上傳速度", result["reply"])
        self.assertIn("戶名與聯絡電話", result["reply"])
        self.assertNotIn("客編", result["reply"])
        self.assertNotIn("客戶編號", result["reply"])

    def test_declared_speed_gap_requests_controlled_retest_then_repair(self):
        memory = {"known_info": {}}
        first = apply_troubleshooting_engine(
            "光纖申辦1G的，測試之後只有279Mbps",
            memory,
            {
                "intent": "internet_slow_buffering",
                "reply": "",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        known = memory["known_info"]
        self.assertEqual(known["declared_plan_speed_mbps"], 1000.0)
        self.assertEqual(known["download_speed"], 279.0)
        self.assertEqual(known["troubleshooting_step"], "net_speed_retest")
        self.assertIn("網路線", first["reply"])
        self.assertIn("279 Mbps", first["reply"])

        second = apply_troubleshooting_engine(
            "光纖申辦1G的，測試之後只有279Mbps",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertTrue(second["should_call_tool"])
        self.assertEqual(second["tool_name"], "create_repair_ticket")

    def test_explicit_fault_report_handoffs_active_network_troubleshooting(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_slow_scope",
                "issue_description": "網速明顯變慢",
            }
        }

        result = apply_troubleshooting_engine(
            "回報故障",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")

    def test_network_how_to_followup_explains_active_speed_steps(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_slow_scope",
            }
        }

        result = apply_troubleshooting_engine(
            "如何執行",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIn("網路線", result["reply"])
        self.assertIn("www.speedtest.net", result["reply"])
        self.assertNotIn("所有網站/APP 都很慢", result["reply"])

    def test_network_cause_question_explains_wired_test_before_scope_question(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_slow_scope",
            }
        }

        result = apply_troubleshooting_engine(
            "是基地台的關係還是線路的關係",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertIn("不是透過行動基地台", result["reply"])
        self.assertIn("網路線", result["reply"])
        self.assertNotIn("所有網站/APP 都很慢", result["reply"])

    def test_single_device_failure_negative_other_devices_moves_to_modem_check(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_single_device",
            }
        }

        first = apply_troubleshooting_engine(
            "沒有恢復",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )
        self.assertIn("其他手機或電腦", first["reply"])
        self.assertEqual(memory["known_info"]["awaiting_other_devices_after_single_failure"], "yes")

        second = apply_troubleshooting_engine(
            "否",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_check_modem_light")
        self.assertIn("數據機", second["reply"])
        self.assertNotIn("其他手機或電腦", second["reply"])

    def test_active_network_computer_issue_stays_in_connection_diagnosis(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
            }
        }
        result = apply_troubleshooting_engine(
            "電腦無法上網",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_computer_connection_type")
        self.assertIn("Wi-Fi", result["reply"])
        self.assertIn("網路線", result["reply"])

    def test_negative_computer_connection_answer_moves_to_wired_check(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_computer_connection_type",
            }
        }
        result = apply_troubleshooting_engine(
            "否",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_wired_connection_check")
        self.assertIn("網路線", result["reply"])

    def test_speed_gap_stays_in_existing_repair_context(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "network",
                "repair_ready": "yes",
                "repair_followup_active": "yes",
            }
        }

        result = apply_troubleshooting_engine(
            "光纖申辦1G的，測試之後只有279Mbps",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIn("維修申告管道", result["reply"])
        self.assertEqual(memory["known_info"]["repair_followup_active"], "yes")

    def test_concrete_no_program_screen_reopens_tv_rescan_from_repair_context(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "tv",
                "repair_ready": "yes",
                "repair_followup_active": "yes",
            }
        }

        result = apply_troubleshooting_engine(
            "顯示沒有節目卡住",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_rescan_channels")
        self.assertIn("重新搜頻", result["reply"])
        self.assertNotIn("repair_followup_active", memory["known_info"])

    def test_llm_selected_no_program_display_starts_tv_rescan(self):
        memory = {"known_info": {}}
        result = apply_troubleshooting_engine(
            "有",
            memory,
            {
                "intent": "tv_no_program_display_issue",
                "reply": "",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_rescan_channels")
        self.assertIn("重新搜頻", result["reply"])

    def test_no_program_screen_without_rescan_completion_repeats_rescan_guidance(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_rescan_channels",
            }
        }

        result = apply_troubleshooting_engine(
            "顯示沒有節目卡住",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIn("重新搜頻", result["reply"])

    def test_router_prompt_preserves_speed_test_context_and_speed_gap(self):
        rules = build_intent_router_rules()

        self.assertIn("network_speed_test_guidance", rules)
        self.assertIn("申辦速率與實測速率有明顯落差", rules)
        self.assertIn("area_repair_status_lookup", rules)
        self.assertIn("沒有公告，不能推論", rules)
        self.assertIn("不可聲稱已轉接", rules)
        self.assertIn("identity_document_upload", rules)
        self.assertIn("不必先問上傳用途", rules)
        self.assertIn("不可回到「查詢資料、辦理服務、回報故障」", rules)
        self.assertIn("service_signal_type_clarify", rules)
        self.assertIn("不可自行假設是網速慢", rules)
        self.assertIn("電腦無法上網／電腦連不上網", rules)
        self.assertIn("不可直接報修、轉真人", rules)

    def test_high_risk_aging_modem_instability_moves_to_repair(self):
        memory = {
            "known_info": {
                "issue_description": "舊款 SB6141 使用超過半年，常常不穩定而且容易發熱",
            }
        }

        result = build_network_slow_reply(
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")

    def test_tv_playback_interruption_then_fault_report_hands_off_to_repair(self):
        memory = {"known_info": {}}
        plan = {
            "intent": "tv_viewing_interruption_issue",
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        first = apply_troubleshooting_engine(
            "有線電視訊息看到一半會中斷", memory, plan,
        )

        self.assertEqual(memory["known_info"]["troubleshooting_type"], "tv")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("機上盒電源", first["reply"])

        next_plan = {"reply": "", "should_call_tool": False, "tool_name": None}
        second = apply_troubleshooting_engine("回傳故障", memory, next_plan)

        self.assertTrue(second["should_call_tool"])
        self.assertEqual(second["tool_name"], "create_repair_ticket")

    def test_tv_no_signal_fault_report_keeps_basic_power_check(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_input_source",
                "issue_description": "電視畫面顯示無訊號",
            }
        }

        result = apply_troubleshooting_engine(
            "故障",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_check_power")
        self.assertIn("電源燈", result["reply"])

    def test_tv_boot_loop_overrides_generic_screen_question(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_screen",
            }
        }

        result = apply_troubleshooting_engine(
            "重複一直開機中",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("持續重複開機", result["reply"])
        self.assertIn("10 秒", result["reply"])

    def test_tv_boot_loop_reopens_a_disabled_repair_follow_up(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_reboot",
                "troubleshooting_failed": "yes",
                "repair_ready": "no",
                "repair_flow_status": "disabled",
                "repair_followup_active": "yes",
            }
        }

        result = apply_troubleshooting_engine(
            "開機中請稍後的畫面",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_started"], "yes")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertNotIn("repair_followup_active", memory["known_info"])
        self.assertIn("持續重複開機", result["reply"])

    def test_tv_screen_question_accepts_other_descriptions(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power",
            }
        }

        result = apply_troubleshooting_engine(
            "有",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_check_screen")
        self.assertIn("其他畫面", result["reply"])
        self.assertIn("反覆開機", result["reply"])

    def test_ds_light_question_reopens_network_flow_after_repair_handoff(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "troubleshooting_failed": "yes",
                "repair_ready": "no",
                "repair_flow_status": "disabled",
                "repair_followup_active": "yes",
            }
        }

        result = apply_troubleshooting_engine(
            "DS 燈閃爍是正常嗎？",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_started"], "yes")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_reboot_modem")
        self.assertNotIn("repair_followup_active", memory["known_info"])
        self.assertIn("正在同步下行訊號", result["reply"])

    def test_repair_followup_does_not_repeat_disabled_repair_action(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "network",
                "troubleshooting_failed": "yes",
                "repair_ready": "no",
                "repair_flow_status": "disabled",
                "repair_followup_active": "yes",
            }
        }

        result = apply_troubleshooting_engine(
            "一樓的網路還是常常不穩",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIsNone(result["tool_name"])
        self.assertIn("維修申告管道", result["reply"])

    def test_tutorial_screen_starts_with_remote_check(self):
        memory = {"known_info": {}}
        plan = {
            "intent": "tv_tutorial_screen_stuck_issue",
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine("電視一直卡在機上盒教學", memory, plan)

        self.assertEqual(memory["known_info"]["troubleshooting_type"], "remote")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "remote_check_light")
        self.assertIn("遙控器", result["reply"])

    def test_active_tv_flow_switches_when_llm_selects_network_issue(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "internet_connection_issue",
            "topic": "寬頻網路故障",
            "service_scope": "寬頻網路",
            "requested_information": "網路故障排除",
            "reply": "",
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "extracted_slots": {},
            "reason": "model_network_issue",
        })
        memory = {
            "company_code": "wctv",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power",
            },
        }

        result = detect_active_flow_switch("網路排除", memory, [], router_llm, {})

        self.assertIsNotNone(result)
        self.assertTrue(result["should_cancel_current_flow"])
        self.assertEqual(result["reason"], "active_flow_switch_troubleshooting_network")

    def test_install_application_fallback_uses_configured_install_channel(self):
        reply = build_install_application_reply({"company_code": "wctv"})

        self.assertIn("裝機", reply)
        self.assertIn("真人客服", reply)

    def test_install_application_intent_variants_share_the_same_sop(self):
        for intent in (
            "internet_install_application_guidance",
            "internet_install_application_info",
            "internet_installation_application_info",
            "new_internet_install_inquiry",
        ):
            with self.subTest(intent=intent):
                self.assertTrue(is_install_application_router_intent({"intent": intent}))

    def test_two_year_cable_tv_followup_keeps_annual_rate_card_evidence(self):
        docs = [{
            "id": "tv-rate-card",
            "question": "大屯_有線電視_基本收費標準",
            "answer": "年繳 $6,550；年繳者裝機費優惠為 600 元。",
        }]
        llm = RunnableLambda(lambda _prompt: Response(
            '{"selected_document_indexes": [], "has_sufficient_evidence": false}'
        ))

        for intent in ("basic_tv_two_year_fee_query", "cable_tv_two_year_fee_inquiry"):
            with self.subTest(intent=intent):
                selected, verified = filter_docs_with_llm_evidence(
                    "2年的呢",
                    docs,
                    {
                        "intent": intent,
                        "knowledge_query": "第四台 有線電視 兩年繳 收視費 裝機費",
                    },
                    llm=llm,
                )

                self.assertTrue(verified)
                self.assertEqual(selected, docs)

    def test_distinct_intent_omits_old_history_from_context(self):
        history = [
            {"role": "user", "content": "退租"},
            {"role": "assistant", "content": "請攜帶設備至櫃檯辦理退租。"},
        ]

        contextual_history, is_new_intent = select_contextual_history("我的網路", history)

        self.assertTrue(is_new_intent)
        self.assertEqual(contextual_history, [])

    def test_same_intent_followup_keeps_history_for_context(self):
        history = [
            {"role": "user", "content": "退租"},
            {"role": "assistant", "content": "請攜帶設備至櫃檯辦理退租。"},
        ]

        contextual_history, is_new_intent = select_contextual_history("退租要帶什麼", history)

        self.assertFalse(is_new_intent)
        self.assertEqual(contextual_history, history)

    def test_new_intent_clears_old_flow_before_routing(self):
        history = [
            {"role": "user", "content": "退租"},
            {"role": "assistant", "content": "請攜帶設備至櫃檯辦理退租。"},
        ]
        captured = {}
        router = {
            "route": "direct_reply",
            "intent": "current_network_service",
            "tool_name": None,
            "topic": "目前網路服務",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "請問您想查詢目前網路方案或合約內容嗎？",
            "extracted_slots": {},
            "reason": "test_current_network_service",
        }

        def capture_router(**kwargs):
            captured["history"] = kwargs["history"]
            return router

        memory = {
            "company_code": "tdtv",
            "pending_tool": "search_bill",
            "pending_tool_args": ["custnum"],
            "clarify_context": {"type": "human_handoff_confirmation"},
            "last_knowledge_results": [{"question": "退租流程"}],
            "last_campaign_topic": "舊活動",
            "known_info": {"troubleshooting_started": "no"},
        }
        with (
            patch("app.handlers.chat_handler.run_intent_router", side_effect=capture_router),
            patch("app.handlers.chat_handler.log_chat_latency"),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我的網路",
                memory=memory,
                history=history,
                llm=None,
                persist=False,
            )

        self.assertEqual(captured["history"], [])
        self.assertIsNone(result["memory"]["clarify_context"])
        self.assertIsNone(result["memory"]["pending_tool"])
        self.assertEqual(result["memory"]["last_knowledge_results"], [])
        self.assertNotIn("last_campaign_topic", result["memory"])
        self.assertIn("目前網路方案", result["ai_response"])

    def test_customer_reply_hides_rag_source_wording(self):
        reply = "不是一定要達千元，RAG 內有多個低於 1,000 元的選擇。"

        result = finalize_customer_reply("有一千元以下的方案嗎？", reply)

        self.assertEqual(result, "不是一定要達千元，目前查到的資料中有多個低於 1,000 元的選擇。")
        self.assertNotIn("RAG", result)

    def test_mixed_case_product_name_is_strict_retrieval_evidence(self):
        self.assertIn("youtube", extract_query_strict_identifier_terms("哈TV可以使用YouTube嗎？"))
        self.assertIn("hiplay", extract_query_strict_identifier_terms("Hi Play全餐怎麼加購？"))

    def test_customer_reply_hides_api_and_industry_shorthand(self):
        reply = "目前帳務 API 可查詢 CATV、STB 與 BB 費用。"

        result = sanitize_customer_facing_jargon(reply)

        self.assertEqual(result, "目前帳務系統可查詢有線電視、數位機上盒與寬頻網路費用。")

    def test_customer_reply_rephrases_ai_sounding_install_application_fallback(self):
        reply = (
            "【申請方式】\n"
            "目前查不到明確線上申請方式，建議由客服協助確認地址是否可安裝並安排申辦。"
        )

        result = finalize_customer_reply("網路裝機申請", reply)

        self.assertIn("【申請方式】", result)
        self.assertIn("實際可安裝區域、施工條件與可約時間", result)
        self.assertNotIn("目前查不到明確", result)
        self.assertNotIn("查不到明確線上申請方式", result)

    def test_customer_reply_jargon_translation_does_not_modify_urls(self):
        url = "http://stb.topmso.com.tw:8080/csr/api/install?service=BB"
        reply = f"STB 裝機申告：{url}"

        result = sanitize_customer_facing_jargon(reply)

        self.assertEqual(result, f"數位機上盒裝機申告：{url}")

    def test_customer_reply_removes_internal_source_preface(self):
        reply = "不是，目前資料顯示「好視成雙」仍有優惠方案。"

        result = finalize_customer_reply("好視成雙沒有了嗎？", reply)

        self.assertEqual(result, "目前「好視成雙」仍有優惠方案。")

    def test_repair_report_mention_gets_company_link(self):
        reply = (
            "您好，目前線上 AI 無法直接安排客服回電。"
            "若是報修需求，也可填寫維修申告表單，我們會有專人協助處理。"
        )

        result = ensure_repair_report_link(reply, {"company_code": "tdtv"})

        self.assertIn("維修申告：［維修申告🔗］http://stb.topmso.com.tw:8080/", result)

    def test_repair_report_existing_link_is_not_duplicated(self):
        reply = (
            "若要報修，您也可填寫［維修申告🔗］http://example.test/repair"
            "送出需求。"
        )

        result = ensure_repair_report_link(reply, {"company_code": "tdtv"})

        self.assertEqual(result, reply)

    def test_known_link_mentions_without_icon_get_links(self):
        reply = "可至官網查看，也可填寫裝機申告表單；LINE TV客服中心也有說明。"

        result = ensure_known_link_mentions(reply, {"company_code": "tdtv"})

        self.assertIn("官網：［官網🔗］https://www.tdtv.com.tw/", result)
        self.assertIn("裝機申告：［裝機申告🔗］http://stb.topmso.com.tw:8080/", result)
        self.assertIn("LINE TV客服中心：［LINE TV客服中心🔗］https://help.linetv.tw/hc/zh-tw", result)

    def test_known_link_mentions_with_existing_plain_marker_are_not_duplicated(self):
        reply = "可至［官網］https://www.tdtv.com.tw/查看最新資訊。"

        result = ensure_known_link_mentions(reply, {"company_code": "tdtv"})

        self.assertEqual(result, reply)

    def test_custom_company_link_mentions_are_not_hardcoded(self):
        profile = {
            "urls": "［官網🔗］https://example.com/",
            "value_added_urls": "［熊大心🔗］https://test.com.tw",
        }
        reply = "熊大心加值服務可以參考客服中心說明。"

        with patch("app.handlers.chat_handler.get_company_profile", return_value=profile):
            result = ensure_known_link_mentions(reply, {"company_code": "tdtv"})

        self.assertIn("熊大心：［熊大心🔗］https://test.com.tw", result)

    def test_custom_company_link_marker_without_icon_gets_link(self):
        profile = {
            "urls": "",
            "value_added_urls": "［熊大心🔗］https://test.com.tw",
        }
        reply = "可至［熊大心］查看服務說明。"

        with patch("app.handlers.chat_handler.get_company_profile", return_value=profile):
            result = ensure_known_link_mentions(reply, {"company_code": "tdtv"})

        self.assertIn("熊大心：［熊大心🔗］https://test.com.tw", result)

    def test_callback_reply_with_repair_report_text_gets_link(self):
        router_llm = llm_with_router_response({
            "route": "direct_reply",
            "intent": "customer_callback_request",
            "tool_name": None,
            "topic": "客服回電",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": (
                "您好，目前線上 AI 無法直接安排客服回電。"
                "若您需要專人協助，請撥打客服電話；"
                "若是報修需求，也可填寫維修申告表單，我們會有專人協助處理。"
            ),
            "extracted_slots": {},
            "reason": "llm_callback_request",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="請回電0921007530",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertIn("維修申告：［維修申告🔗］http://stb.topmso.com.tw:8080/", result["ai_response"])

    def test_tv_install_application_is_an_explicit_topic_switch(self):
        self.assertTrue(is_likely_active_flow_switch("有線電視裝機申請"))

    def test_router_prompt_clarifies_stop_service_before_handoff(self):
        rules = build_intent_router_rules()

        self.assertIn("使用者說「我要停機」、「想停掉服務」", rules)
        self.assertIn("intent = stop_watching_clarify", rules)
        self.assertIn("第一句不得直接轉真人客服", rules)

    def test_router_prompt_requires_tv_no_program_clarification(self):
        rules = build_intent_router_rules()

        self.assertIn("intent = tv_no_program_clarify", rules)
        self.assertIn("不可直接恢復預設或重新搜頻", rules)
        self.assertIn("intent = tv_tutorial_screen_stuck_issue", rules)

    def test_router_prompt_keeps_tv_termination_evidence_scoped(self):
        rules = build_intent_router_rules()

        self.assertIn("有線電視 退租 拆機 應備物 設備 配件 流程", rules)
        self.assertIn("退費、合約費用、押金收據與櫃台地址", rules)

    def test_router_prompt_routes_standalone_online_repair_to_repair_channel(self):
        rules = build_intent_router_rules()

        self.assertIn("使用者單純詢問或要求「線上報修」", rules)
        self.assertIn("intent = repair_ticket_request", rules)
        self.assertIn("不可先反問故障種類", rules)

    def test_router_prompt_recognizes_broadband_suspension_and_stop_context(self):
        rules = build_intent_router_rules()

        self.assertIn("暫時中斷網路服務", rules)
        self.assertIn("intent = broadband_service_suspension_guidance", rules)
        self.assertIn("intent = broadband_suspend_or_termination_guidance", rules)
        self.assertIn("不可改成網路排錯或資料不足回覆", rules)

    def test_router_prompt_clarifies_router_replacement_before_any_upsell(self):
        rules = build_intent_router_rules()

        self.assertIn("intent = router_replacement_connection_clarify", rules)
        self.assertIn("更換分享器後無法上網", rules)
        self.assertIn("不可先假定是升級、加購", rules)

    def test_router_prompt_keeps_aging_heated_modem_in_network_repair_flow(self):
        rules = build_intent_router_rules()

        self.assertIn("SB6141", rules)
        self.assertIn("設備／線路檢修或報修", rules)
        self.assertIn("不可因後續提及電視卡住", rules)

    def test_router_prompt_preserves_network_repair_context_for_tv_service_symptoms(self):
        rules = build_intent_router_rules()

        self.assertIn("某樓層電視訊號不穩", rules)
        self.assertIn("route = continue_current_flow", rules)
        self.assertIn("不可只因出現「電視」一詞", rules)

    def test_router_prompt_explains_ds_light_question_before_repair(self):
        rules = build_intent_router_rules()

        self.assertIn("intent = modem_ds_light_status_guidance", rules)
        self.assertIn("正在同步下行訊號", rules)
        self.assertIn("不可把使用者的疑問直接當成「燈號正常」", rules)

    def test_router_prompt_clarifies_generic_remote_control_fault(self):
        rules = build_intent_router_rules()

        self.assertIn("intent = remote_control_symptom_clarify", rules)
        self.assertIn("整支遙控器都無法操作", rules)
        self.assertIn("使用者已明確說無法開關機", rules)

    def test_router_prompt_guides_line_tv_cancellation(self):
        rules = build_intent_router_rules()

        self.assertIn("使用者明確說「取消 LINE TV」", rules)
        self.assertIn("intent = line_tv_cancellation_guidance", rules)
        self.assertIn("停止繳納續期費用", rules)
        self.assertIn("安心使用至當期最後一天", rules)

    def test_router_prompt_covers_feedback_semantics_without_fastpath(self):
        rules = build_intent_router_rules()

        self.assertIn("intent = repair_visit_expectation", rules)
        self.assertIn("topic = contact_phone", rules)
        self.assertIn("intent = relocation_guidance", rules)
        self.assertIn("移機 搬家 換地址 流程 費用 條件", rules)
        self.assertIn("intent = fixed_ip_binding_guidance", rules)
        self.assertIn("intent = tv_picture_quality_issue", rules)

    def test_router_prompt_treats_missing_hatv_channels_as_tv_troubleshooting(self):
        rules = build_intent_router_rules()

        self.assertIn("哈TV、LINE TV 或有線電視", rules)
        self.assertIn("頻道不見、頻道少了、部分頻道不能看", rules)
        self.assertIn("「哈TV頻道不見」、「哈tv頻道不見」", rules)
        self.assertIn("intent = tv_partial_channel_issue", rules)

    def test_router_prompt_clarifies_personal_monthly_fee_lookup(self):
        rules = build_intent_router_rules()

        self.assertIn("查詢月租、查月費、月租多少、月費多少", rules)
        self.assertIn("目前待繳帳單金額", rules)
        self.assertIn("目前合約／服務內容", rules)

    def test_router_prompt_treats_short_home_network_outage_as_troubleshooting(self):
        rules = build_intent_router_rules()

        self.assertIn("「家中無網路」、「家裡沒網路」、「網路不能用」", rules)
        self.assertIn("intent = internet_connection_issue", rules)
        self.assertIn("不要直接轉真人客服", rules)
        self.assertIn("不可回覆通用澄清", rules)

    def test_router_prompt_keeps_service_scope_and_numbered_followups_in_context(self):
        rules = build_intent_router_rules()

        self.assertIn("對話脈絡與服務範圍", rules)
        self.assertIn("服務定義、差異、功能支援、加購方式", rules)
        self.assertIn("不可把不同服務混為一談或自行替換", rules)
        self.assertIn("使用者只回覆「1、2、3、4」", rules)
        self.assertIn("必須依上一輪選項內容承接", rules)

    def test_router_prompt_keeps_existing_customer_upgrade_recommendation_rules(self):
        rules = build_intent_router_rules()

        self.assertIn("優先推薦更高速率的方案", rules)
        self.assertIn("優先保留「電視＋網路」類型", rules)
        self.assertIn("實際以查詢結果為準", rules)
        self.assertIn("existing_speed_upgrade_eligibility", rules)

    def test_existing_customer_speed_upgrade_requires_authenticated_contract_lookup(self):
        router_llm = llm_with_router_response({
            "route": "knowledge_query",
            "intent": "promotion_activity",
            "topic": "寬頻優惠方案",
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "目前寬頻優惠方案",
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_wrong_campaign_route",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="原用戶是否可升級速率",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertEqual(result["router"]["intent"], "contract_lookup_login_required")
        self.assertEqual(
            result["ai_response"],
            "為保障您的個人資料安全，個人帳務及方案等資訊需登入會員後才能查詢，"
            "您可以至官網或行動客服 APP 登入後查看相關資料。",
        )
        self.assertNotIn("戶名", result["ai_response"])
        self.assertNotIn("優惠方案", result["ai_response"])

    def test_counter_account_transfer_keeps_document_question_in_service_context(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_wrong_unknown_route",
        })
        memory = {"company_code": "tdtv", "known_info": {}}

        with patch("app.handlers.chat_handler.log_chat_latency"):
            first = handle_chat_message(
                user_id="test-user",
                user_text="禮拜六有營業嗎辦理變更戶名嗎",
                memory=memory,
                history=[],
                llm=router_llm,
                persist=False,
            )
            second = handle_chat_message(
                user_id="test-user",
                user_text="陳璧鈴 台中市大里區愛心路101巷3號，明天想要去辦理",
                memory=first["memory"],
                history=[],
                llm=RunnableLambda(lambda _prompt: (_ for _ in ()).throw(AssertionError("should keep clarification context"))),
                persist=False,
            )
            third = handle_chat_message(
                user_id="test-user",
                user_text="要帶那些證件",
                memory=second["memory"],
                history=[],
                llm=RunnableLambda(lambda _prompt: (_ for _ in ()).throw(AssertionError("should keep clarification context"))),
                persist=False,
            )
            fourth = handle_chat_message(
                user_id="test-user",
                user_text="電視",
                memory=third["memory"],
                history=[],
                llm=RunnableLambda(lambda _prompt: (_ for _ in ()).throw(AssertionError("should resolve television selection"))),
                persist=False,
            )

        self.assertEqual(first["router"]["intent"], "service_account_transfer_service_clarify")
        self.assertIn("大屯有線營業時間", first["ai_response"])
        self.assertIn("有線電視更名還是寬頻網路更名", first["ai_response"])
        self.assertIn("有線電視更名還是寬頻網路更名", second["ai_response"])
        self.assertIn("有線電視更名還是寬頻網路更名", third["ai_response"])
        self.assertEqual(fourth["router"]["intent"], "tv_account_transfer_document_guidance")
        self.assertIn("有線電視更名", fourth["ai_response"])
        self.assertNotIn("月租費", fourth["ai_response"])

    def test_named_product_exits_generic_value_added_menu_for_llm_routing(self):
        memory = {
            "clarify_context": get_clarify_context("加值服務"),
        }

        selection = resolve_clarify_context("Hi Play全餐", memory)

        self.assertIsNone(selection)
        self.assertIsNone(memory["clarify_context"])

    def test_router_prompt_keeps_initial_fault_diagnosis_before_repair(self):
        rules = build_intent_router_rules()

        self.assertIn("【先排除再報修】", rules)
        self.assertIn("即使同一句也說「請人來修」", rules)

    def test_invoice_carrier_question_interrupts_pending_bill_lookup(self):
        result = detect_safe_direct_reply(
            "我上一份合約有綁載具，換約後需要從新綁定載具嗎",
            {"pending_tool": "search_bill", "known_info": {}},
        )

        self.assertEqual(result["intent"], "invoice_carrier_binding")
        self.assertIn("重新綁定", result["reply"])
        self.assertIn("帳戶狀態", result["reply"])

    def test_tv_unauthorized_reply_checks_paid_channel_before_payment(self):
        result = detect_safe_direct_reply("按0000後頻道出現未授權", {"known_info": {}})

        self.assertEqual(result["intent"], "tv_authorization_payment_check")
        self.assertIn("付費頻道", result["reply"])
        self.assertIn("200 頻道", result["reply"])
        self.assertNotIn("繳費方式", result["reply"])

    def test_set_top_box_password_prompt_uses_default_password_first(self):
        result = detect_safe_direct_reply("機上盒出現要輸入密碼?", {"known_info": {}})

        self.assertEqual(result["intent"], "tv_password_prompt")
        self.assertIn("0000", result["reply"])
        self.assertIn("未授權", result["reply"])

    def test_tv_password_then_unauthorized_paid_channel_uses_llm_response_sops(self):
        first = run_intent_router(
            "機上盒出現要輸入密碼?",
            {"company_code": "wctv", "known_info": {}},
            [],
            llm_with_router_response({
                "route": "direct_reply",
                "intent": "tv_password_prompt",
                "topic": "機上盒畫面要求輸入密碼",
                "should_retrieve_knowledge": False,
                "reply": "模型措辭不應直接顯示",
            }),
        )
        self.assertEqual(first["intent"], "tv_password_prompt")
        first_reply = build_plan_from_router(first)["reply"]
        self.assertIn("0000", first_reply)
        self.assertIn("未授權", first_reply)
        self.assertNotIn("繳費", first_reply)

        second = run_intent_router(
            "按0000 頻道出現未授權",
            {"company_code": "wctv", "known_info": {}},
            [{"role": "user", "content": "機上盒出現要輸入密碼?"}],
            llm_with_router_response({
                "route": "direct_reply",
                "intent": "tv_unauthorized_paid_channel_guidance",
                "topic": "付費頻道誤切",
                "should_retrieve_knowledge": False,
                "reply": "模型措辭不應直接顯示",
            }),
        )
        self.assertEqual(second["intent"], "tv_unauthorized_paid_channel_guidance")
        self.assertEqual(
            build_plan_from_router(second)["reply"],
            "您可能誤按到需加購的付費頻道。200 台以後通常為付費頻道，需另行訂閱才能觀看。"
            "您可使用遙控器按頻道向下鍵，切換至正常收視頻道即可。",
        )

    def test_wifi_password_question_is_not_treated_as_tv_password_prompt(self):
        result = detect_safe_direct_reply("Wi-Fi 要輸入什麼密碼？", {"known_info": {}})

        self.assertFalse(result and result.get("intent") == "tv_password_prompt")

    def test_tv_and_broadband_account_transfer_does_not_become_plan_change(self):
        result = detect_safe_direct_reply("第四台及光纖，要更換用戶需要怎麼申辦呢？", {"known_info": {}})

        self.assertEqual(result["intent"], "service_account_transfer")
        self.assertIn("【申請方式】", result["reply"])
        self.assertIn("第四台及光纖更換用戶", result["reply"])
        self.assertIn("文件", result["reply"])
        self.assertNotIn("優惠方案", result["reply"])
        self.assertNotIn("好視成雙", result["reply"])
        self.assertNotIn("違約金", result["reply"])

    def test_tv_and_broadband_account_transfer_uses_llm_selected_customer_reply(self):
        result = run_intent_router(
            "第四台及光纖，要更換用戶需要怎麼申辦呢？",
            {"company_code": "tdtv", "known_info": {}},
            [],
            llm_with_router_response({
                "route": "direct_reply",
                "intent": "service_account_transfer",
                "topic": "第四台及光纖更換用戶",
                "should_retrieve_knowledge": False,
                "reply": "模型措辭不應直接顯示",
            }),
        )

        self.assertEqual(result["route"], "direct_reply")
        self.assertEqual(result["intent"], "service_account_transfer")
        self.assertEqual(
            build_plan_from_router(result)["reply"],
            "【申請方式】\n"
            "資料未提供「第四台及光纖更換用戶」的具體流程或應備文件，需由客服依帳戶與合約狀態確認。",
        )

    def test_invoice_mobile_barcode_returns_binding_guidance(self):
        result = detect_safe_direct_reply("發票加入手機條碼", {"known_info": {}})

        self.assertEqual(result["intent"], "invoice_carrier_binding")
        self.assertIn("手機條碼", result["reply"])
        self.assertIn("歸戶", result["reply"])

    def test_overdue_disconnection_explains_payment_and_reconnection_first(self):
        result = detect_safe_direct_reply("忘了繳費已被斷訊", {"known_info": {}})

        self.assertEqual(result["intent"], "overdue_disconnection_guidance")
        self.assertIn("繳費", result["reply"])
        self.assertIn("復線", result["reply"])
        self.assertIn("入帳", result["reply"])
        self.assertNotIn("服務地址", result["reply"])

    def test_points_usage_builds_focused_knowledge_query(self):
        result = detect_safe_direct_reply(
            "哈POINT能如何使用",
            {"pending_tool": "search_contract_info", "known_info": {}},
        )

        self.assertEqual(result["intent"], "points_usage_query")
        self.assertIn("紅利點數", result["knowledge_query"])
        self.assertIn("抵扣各項服務費用", result["knowledge_query"])

    def test_bare_reward_points_starts_general_points_lookup(self):
        result = detect_safe_direct_reply(
            "紅利點數",
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

        self.assertEqual(result["intent"], "points_overview_query")
        self.assertEqual(result["topic"], "哈POINT 紅利點數說明")
        self.assertIn("如何獲得", result["knowledge_query"])
        self.assertIn("有效期限", result["knowledge_query"])
        self.assertNotIn("爸氣獻禮", result["knowledge_query"])

    def test_service_refund_question_does_not_list_unrelated_campaign_penalties(self):
        result = detect_safe_direct_reply(
            "合約到期而且已經繳費，解約可以退費嗎？",
            {"known_info": {"customer_no": "1094649"}},
        )

        self.assertEqual(result["intent"], "service_refund_calculation")
        self.assertEqual(result["route"], "direct_reply")
        self.assertIn("無法直接查詢或計算解約退費金額", result["reply"])
        self.assertIn("真人客服協助確認", result["reply"])
        self.assertNotIn("好視成雙", result["reply"])
        self.assertNotIn("2,400", result["reply"])

    def test_promotion_reply_appends_referral_code(self):
        reply = append_promotion_referral_code(
            "目前推薦好視成雙 NO8。",
            {"route": "company_info", "topic": "promotion_activity"},
            {
                "company_code": "tdtv",
                "last_knowledge_results": [{"id": "promotion-1"}],
            },
        )

        self.assertTrue(reply.endswith(PROMOTION_REFERRAL_FOOTER))

    def test_promotion_reply_does_not_duplicate_referral_code(self):
        original = f"目前推薦好視成雙 NO8。\n\n{PROMOTION_REFERRAL_FOOTER}"

        reply = append_promotion_referral_code(
            original,
            {"route": "company_info", "topic": "promotion_activity"},
            {"last_knowledge_results": [{"id": "promotion-1"}]},
        )

        self.assertEqual(reply, original)
        self.assertEqual(reply.count(PROMOTION_REFERRAL_FOOTER), 1)

    def test_named_campaign_followup_does_not_append_referral_code(self):
        reply = append_promotion_referral_code(
            "好視成雙NO7目前資料列出的贈送內容為 LINE TV，未列其他贈品。",
            {"route": "company_info", "topic": "promotion_activity"},
            {
                "company_code": "tdtv",
                "last_knowledge_results": [
                    {
                        "campaign_name": "好視成雙NO7",
                        "campaign_aliases": "好視成雙 NO7 | 好視成雙NO7",
                    }
                ],
            },
            user_text="好視成雙 NO7除了送LINE TV有其他贈品嗎？",
        )

        self.assertNotIn(PROMOTION_REFERRAL_FOOTER, reply)

    def test_non_promotion_reply_does_not_append_referral_code(self):
        reply = append_promotion_referral_code(
            "本期帳單為 990 元。",
            {"route": "tool_action", "topic": "billing"},
            {"last_knowledge_results": [{"id": "billing-1"}]},
        )

        self.assertNotIn(PROMOTION_REFERRAL_FOOTER, reply)

    def test_non_promotion_reply_strips_existing_referral_code(self):
        reply = append_promotion_referral_code(
            f"本期帳單為 990 元。\n\n{PROMOTION_REFERRAL_FOOTER}",
            {"route": "tool_action", "topic": "billing"},
            {"last_knowledge_results": [{"id": "billing-1"}]},
        )

        self.assertEqual(reply, "本期帳單為 990 元。")

    def test_non_promotion_reply_strips_bare_referral_code(self):
        reply = append_promotion_referral_code(
            "可先檢查設備電源與線路，NET06",
            {"route": "direct_reply", "topic": "troubleshooting"},
            {},
        )

        self.assertNotIn("NET06", reply)

    def test_troubleshooting_reply_does_not_append_referral_code_even_if_topic_is_promotion(self):
        reply = append_promotion_referral_code(
            "目前查不到明確故障原因。\n"
            "電視、寬頻網路、監視器都不能使用，建議先由客服協助確認是否為設備、線路或服務狀態問題。",
            {"route": "company_info", "topic": "promotion_activity"},
            {
                "company_code": "tdtv",
                "last_knowledge_results": [{"id": "promotion-1"}],
            },
            user_text="電視 網路 監視器不能使用",
        )

        self.assertNotIn(PROMOTION_REFERRAL_FOOTER, reply)

    def test_troubleshooting_reply_strips_existing_referral_code_even_if_topic_is_promotion(self):
        reply = append_promotion_referral_code(
            "目前查不到明確故障原因。\n"
            "可先檢查數據機、機上盒與監視器電源是否正常。\n\n"
            f"{PROMOTION_REFERRAL_FOOTER}",
            {"route": "company_info", "topic": "promotion_activity"},
            {
                "company_code": "tdtv",
                "last_knowledge_results": [{"id": "promotion-1"}],
            },
            user_text="電視 網路 監視器不能使用",
        )

        self.assertNotIn(PROMOTION_REFERRAL_FOOTER, reply)

    def test_promotion_without_available_content_does_not_append_referral_code(self):
        with patch(
            "app.handlers.chat_handler.get_company_profile",
            return_value={"promotion_activity": ""},
        ):
            reply = append_promotion_referral_code(
                "目前沒有優惠活動公告。",
                {"route": "company_info", "topic": "promotion_activity"},
                {"company_code": "tdtv", "last_knowledge_results": []},
            )

        self.assertNotIn(PROMOTION_REFERRAL_FOOTER, reply)

    def test_restricted_channel_purchase_is_not_treated_as_authorization_fault(self):
        text = "限制級節目授權到期如何購買？"

        self.assertFalse(is_fault(text))
        self.assertFalse(is_tv_authorization_issue(text))
        self.assertTrue(is_tv_authorization_issue("機上盒顯示 E004 授權到期"))

    def test_direct_reply_cancels_pending_tool_for_next_bill_question(self):
        memory = {"pending_tool": "search_contract", "known_info": {}}
        router = {
            "route": "direct_reply",
            "intent": "next_bill_query",
            "reply": "您好，目前系統可協助查詢本期待繳帳單。",
        }

        self.assertTrue(should_cancel_pending_tool("我下次繳費是何時", router, memory))

    def test_direct_reply_with_number_cancels_pending_tool(self):
        memory = {"pending_tool": "search_contract", "known_info": {}}
        router = {
            "route": "direct_reply",
            "intent": "tv_monthly_fee_600",
            "reply": "每月 600 元為有線電視月租費。",
        }

        self.assertTrue(should_cancel_pending_tool("一個月600??", router, memory))

    def test_combined_tv_and_network_outage_acknowledges_both_services(self):
        memory = {"known_info": {}}
        plan = {"reply": "", "should_call_tool": False, "tool_name": None}

        result = apply_troubleshooting_engine("電視跟網路都沒有訊號", memory, plan)

        self.assertIn("電視與網路同時沒有訊號", result["reply"])
        self.assertIn("機上盒與數據機", result["reply"])
        self.assertEqual(memory["known_info"]["affected_scope"], "tv_and_network")
        self.assertNotIn("只有單一手機或電腦", result["reply"])

    def test_new_install_second_floor_video_call_issue_uses_floor_context(self):
        memory = {"known_info": {}}
        plan = {"reply": "", "should_call_tool": False, "tool_name": None}

        result = apply_troubleshooting_engine(
            "最近剛申辦電視加網路，但是發現家裡二樓空間完全無法使用手機視訊，需要協助",
            memory,
            plan,
        )

        self.assertIn("特定樓層沒有網路", result["reply"])
        self.assertIn("其他樓層是否可以正常上網", result["reply"])
        self.assertEqual(memory["known_info"]["affected_scope"], "floor_or_indoor_wiring")
        self.assertNotIn("所有設備都不能上網", result["reply"])

    def test_three_identity_lookup_failures_only_remind_human_service(self):
        memory = {"company_code": "tdtv", "known_info": {}}
        replies = []

        with patch(
            "app.handlers.chat_handler.call_tool",
            return_value=missing_response(
                "search_bill",
                CUSTOMER_NOT_FOUND_MESSAGE,
                ["name", "phone"],
            ),
        ):
            for index, name in enumerate(["王測甲", "王測乙", "王測丙"]):
                memory["known_info"]["name"] = name
                memory["known_info"]["phone"] = f"09123456{index:02d}"
                reply, memory = run_tool_or_rag_flow(
                    user_text="查詢帳單",
                    memory=memory,
                    plan={
                        "reply": "",
                        "should_call_tool": True,
                        "tool_name": "search_bill",
                    },
                    router={
                        "route": "tool_action",
                        "tool_name": "search_bill",
                    },
                    latency={},
                    history=[],
                )
                replies.append(reply)

        self.assertNotIn("洽詢真人客服", replies[0])
        self.assertNotIn("洽詢真人客服", replies[1])
        self.assertIn("洽詢真人客服", replies[2])
        self.assertIn("目前不會自動轉接", replies[2])
        self.assertNotIn("【轉真人客服】", replies[2])

    def test_reply_formatter_repairs_split_new_install_fee_label(self):
        formatted = format_customer_reply_text(
            "方案名稱：佳聯有線電視基本收費\n"
            "月租/季繳：季繳收視費 $1,620\n"
            "新\n"
            "裝機費：季繳含以上裝機優惠價 $1,000\n"
            "贈品/加值：聯網機上盒體驗 3 個月"
        )

        self.assertIn("新裝機費：", formatted)
        self.assertNotIn("\n新\n裝機費", formatted)

    def test_bill_content_query_interrupts_troubleshooting_not_repair(self):
        def failing_llm(_payload):
            raise AssertionError("Explicit bill content query should not need LLM while troubleshooting")

        memory = {
            "company_code": "tdtv",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power",
                "repair_ready": "no",
            },
        }

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="詢問帳單內容",
                memory=memory,
                history=[],
                llm=RunnableLambda(failing_llm),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "tool_action")
        self.assertEqual(result["router"]["tool_name"], "search_bill")
        self.assertNotIn("報修", result["ai_response"])
        self.assertNotIn("維修申告", result["ai_response"])

    def test_search_bill_no_unpaid_status_is_remembered_for_next_bill_followup(self):
        memory = {"company_code": "tdtv", "known_info": {"name": "王大明", "phone": "0988555666"}}

        with patch(
            "app.handlers.chat_handler.call_tool",
            return_value={
                "success": True,
                "tool_name": "search_bill",
                "message": "尚無須繳納的費用，如您已繳費，請記得將設備電源關機重開。",
                "data": {"bill_status": "no_unpaid"},
            },
        ):
            reply, memory = run_tool_or_rag_flow(
                user_text="查詢帳單",
                memory=memory,
                plan={
                    "reply": "",
                    "should_call_tool": True,
                    "tool_name": "search_bill",
                },
                router={
                    "route": "tool_action",
                    "tool_name": "search_bill",
                },
                latency={},
                history=[],
            )

        self.assertIn("尚無須繳納", reply)
        self.assertEqual(memory["last_bill_query_status"]["status"], "no_unpaid")

    def test_explicit_customer_number_is_not_reused_by_customer_api_tools(self):
        memory = {"company_code": "tdtv", "known_info": {}}

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch(
                "app.handlers.chat_handler.run_intent_router",
                return_value={
                    "route": "smalltalk",
                    "intent": "smalltalk",
                    "tool_name": None,
                    "topic": None,
                    "should_cancel_current_flow": False,
                    "should_call_tool": False,
                    "should_retrieve_knowledge": False,
                    "knowledge_query": None,
                    "reply": "好的。",
                    "extracted_slots": {},
                    "reason": "test_ignore_chat_customer_number",
                },
            ),
        ):
            first = handle_chat_message(
                user_id="test-user",
                user_text="1082281客編",
                memory=memory,
                history=[],
                llm=llm_with_router_response({"route": "unknown"}),
                persist=False,
            )

        self.assertNotIn("custnum", first["memory"]["known_info"])

        cases = (
            ("search_bill", "查詢帳單"),
            ("bill_return_line_tv", "復線電視"),
            ("bill_return_line_internet", "復線網路"),
        )

        for tool_name, user_text in cases:
            with self.subTest(tool_name=tool_name):
                router = {
                    "route": "tool_action",
                    "intent": tool_name,
                    "tool_name": tool_name,
                    "topic": tool_name,
                    "should_cancel_current_flow": False,
                    "should_call_tool": True,
                    "should_retrieve_knowledge": False,
                    "knowledge_query": None,
                    "reply": "",
                    "extracted_slots": {},
                    "reason": "test_customer_number_reuse",
                }
                with (
                    patch("app.handlers.chat_handler.log_chat_latency"),
                    patch("app.handlers.chat_handler.run_intent_router", return_value=router),
                    patch("app.handlers.chat_handler.call_tool") as mocked_call_tool,
                ):
                    result = handle_chat_message(
                        user_id="test-user",
                        user_text=user_text,
                        memory=first["memory"],
                        history=[],
                        llm=llm_with_router_response({"route": "unknown"}),
                        persist=False,
                    )

                mocked_call_tool.assert_not_called()
                self.assertIn("戶名", result["ai_response"])
                self.assertIn("電話", result["ai_response"])
                self.assertNotIn("custnum", result["memory"]["known_info"])
                self.assertIn("name", result["memory"].get("pending_tool_args", []))
                self.assertIn("phone", result["memory"].get("pending_tool_args", []))

    def test_contract_lookup_requires_authenticated_web_customer_number(self):
        router = {
            "route": "tool_action",
            "intent": "service_content_query",
            "tool_name": "search_contract_info",
            "topic": "合約查詢",
            "should_cancel_current_flow": False,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_contract_login_required",
        }
        test_memories = {
            "guest_web": {"company_code": "tdtv", "known_info": {}},
            "line": {
                "company_code": "tdtv",
                "channel_context": {"channel": "line"},
                "known_info": {"name": "王大明", "phone": "0988555666"},
            },
        }

        for channel, memory in test_memories.items():
            with self.subTest(channel=channel):
                with (
                    patch("app.handlers.chat_handler.log_chat_latency"),
                    patch("app.handlers.chat_handler.run_intent_router", return_value=router),
                    patch("app.handlers.chat_handler.call_tool") as mocked_call_tool,
                ):
                    result = handle_chat_message(
                        user_id=f"test-{channel}",
                        user_text="我要查合約內容",
                        memory=memory,
                        history=[],
                        llm=llm_with_router_response({"route": "unknown"}),
                        persist=False,
                    )

                mocked_call_tool.assert_not_called()
                self.assertEqual(result["router"]["route"], "direct_reply")
                self.assertEqual(result["router"]["intent"], "contract_lookup_login_required")
                self.assertEqual(
                    result["ai_response"],
                    "為保障您的個人資料安全，個人帳務及方案等資訊需登入會員後才能查詢，"
                    "您可以至官網或行動客服 APP 登入後查看相關資料。",
                )
                self.assertIsNone(result["memory"].get("pending_tool"))

    def test_authenticated_web_customer_number_can_query_contract(self):
        router = {
            "route": "tool_action",
            "intent": "service_content_query",
            "tool_name": "search_contract_info",
            "topic": "合約查詢",
            "should_cancel_current_flow": False,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_authenticated_contract_lookup",
        }
        memory = {
            "company_code": "tdtv",
            "is_logged_in": True,
            "known_info": {
                "custnum": "1082281",
                "custnum_source": "web_authenticated",
                "is_logged_in": True,
            },
        }
        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch(
                "app.handlers.chat_handler.call_tool",
                return_value={
                    "success": True,
                    "tool_name": "search_contract_info",
                    "message": "已為您查詢目前服務與合約資訊。",
                    "data": {},
                },
            ) as mocked_call_tool,
        ):
            result = handle_chat_message(
                user_id="test-authenticated-web",
                user_text="我要查合約內容",
                memory=memory,
                history=[],
                llm=llm_with_router_response({"route": "unknown"}),
                persist=False,
            )

        mocked_call_tool.assert_called_once()
        self.assertEqual(result["router"]["tool_name"], "search_contract_info")
        self.assertIn("合約資訊", result["ai_response"])

    def test_authenticated_web_customer_number_bill_lookup_does_not_ask_name_phone(self):
        memory = {
            "company_code": "tdtv",
            "is_logged_in": True,
            "known_info": {
                "custnum": "1049621",
                "custnum_source": "web_authenticated",
                "is_logged_in": True,
            },
        }
        router = {
            "route": "tool_action",
            "intent": "search_bill",
            "tool_name": "search_bill",
            "topic": "search_bill",
            "should_cancel_current_flow": False,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {"custnum": "1049621"},
            "reason": "test_web_customer_number_lookup",
        }
        captured_call_memory = {}

        def capture_call_tool(_tool_name, call_memory):
            captured_call_memory.update(json.loads(json.dumps(call_memory, ensure_ascii=False)))
            return {
                "success": False,
                "tool_name": "search_bill",
                "message": "查詢不到您的資料，請先確認客戶編號是否正確。",
                "data": {"missing": ["custnum"]},
            }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch("app.handlers.chat_handler.call_tool", side_effect=capture_call_tool),
        ):
            result = handle_chat_message(
                user_id="web:test-user",
                user_text="查詢帳單",
                memory=memory,
                history=[],
                llm=llm_with_router_response({"route": "unknown"}),
                persist=False,
            )

        called_memory = captured_call_memory
        self.assertEqual(called_memory["known_info"]["custnum"], "1049621")
        self.assertEqual(called_memory["known_info"]["custnum_source"], "web_authenticated")
        self.assertNotIn("戶名與登記電話", result["ai_response"])
        self.assertNotIn("name", result["memory"].get("pending_tool_args", []))
        self.assertNotIn("phone", result["memory"].get("pending_tool_args", []))

    def test_bare_human_handoff_intent_asks_for_issue_before_transfer(self):
        router_llm = llm_with_router_response({
            "route": "direct_reply",
            "intent": "human_handoff_request",
            "tool_name": None,
            "topic": "真人客服",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "此項可由真人文字客服協助處理。",
            "extracted_slots": {},
            "reason": "llm_human_handoff",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我想要請真人客服處理",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "human_handoff_triage")
        self.assertEqual(result["ai_response"], HUMAN_HANDOFF_CONFIRM_REPLY)
        self.assertEqual(result["memory"]["clarify_context"]["type"], "human_handoff_triage")
        self.assertNotIn("請稍候", result["ai_response"])
        self.assertNotIn("【轉真人客服】", result["ai_response"])
        self.assertNotIn("請由真人客服接手", result["ai_response"])

    def test_personal_project_points_status_uses_web_handoff_intent(self):
        router = run_intent_router(
            user_input="辦專案未得到點數",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=llm_with_router_response({
                "route": "direct_reply",
                "intent": "other",
                "topic": "專案點數",
                "reply": "需要依帳戶資料確認。",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
            }),
        )

        self.assertEqual(router["intent"], "human_handoff_request")
        self.assertEqual(router["topic"], "個人專案點數查詢")
        self.assertEqual(router["reply"], WEB_HUMAN_HANDOFF_REPLY)

    def test_paper_to_electronic_bill_change_uses_web_handoff_contract(self):
        router = run_intent_router(
            user_input="把紙本改為電子帳單",
            memory={"company_code": "wctv", "known_info": {}},
            history=[],
            llm=llm_with_router_response({
                "route": "direct_reply",
                "intent": "paper_bill_request",
                "topic": "帳單寄送方式",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "reply": "此類帳單寄送方式變更需由真人客服協助確認並辦理。",
            }),
        )

        self.assertEqual(router["intent"], "human_handoff_request")
        self.assertEqual(router["topic"], "電子帳單變更")
        self.assertEqual(router["reply"], WEB_HUMAN_HANDOFF_REPLY)
        self.assertNotIn("請稍候", router["reply"])

    def test_human_handoff_direct_phrase_archived_rule_expectation(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我要找真人",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "human_handoff_triage")
        self.assertEqual(result["ai_response"], HUMAN_HANDOFF_CONFIRM_REPLY)
        self.assertEqual(result["memory"]["clarify_context"]["type"], "human_handoff_triage")
        self.assertNotIn("【轉真人客服】", result["ai_response"])
        self.assertNotIn("請由真人客服接手", result["ai_response"])

    def test_human_handoff_cancels_pending_contract_lookup_without_collecting_name(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="找真人",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_contract_info",
                    "pending_tool_args": ["name", "phone"],
                },
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "human_handoff_triage")
        self.assertIsNone(result["memory"].get("pending_tool"))
        self.assertEqual(result["memory"].get("pending_tool_args"), [])
        self.assertNotIn("name", result["memory"].get("known_info", {}))
        self.assertEqual(result["memory"]["clarify_context"]["type"], "human_handoff_triage")

    def test_human_handoff_question_asks_for_issue_before_transfer(self):
        router_llm = llm_with_router_response({
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
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="有沒有真人 我想要隱藏優惠",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "human_handoff_triage")
        self.assertEqual(result["ai_response"], HUMAN_HANDOFF_CONFIRM_REPLY)
        self.assertNotIn("服務地址", result["ai_response"])
        self.assertEqual(
            result["memory"]["clarify_context"]["type"],
            "human_handoff_triage",
        )

    def test_human_handoff_confirmation_yes_repeats_issue_question(self):
        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="好",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "clarify_context": {
                        "type": "human_handoff_confirmation",
                        "topic": "human_handoff_confirmation",
                    },
                },
                history=[],
                llm=llm_with_router_response({"route": "unknown"}),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "human_handoff_triage")
        self.assertEqual(result["ai_response"], HUMAN_HANDOFF_CONFIRM_REPLY)
        self.assertEqual(result["memory"]["clarify_context"]["type"], "human_handoff_triage")
        self.assertNotIn("【轉真人客服】", result["ai_response"])
        self.assertNotIn("請由真人客服接手", result["ai_response"])

    def test_human_handoff_confirmation_no_declines(self):
        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="不用",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "clarify_context": {
                        "type": "human_handoff_confirmation",
                        "topic": "human_handoff_confirmation",
                    },
                },
                history=[],
                llm=llm_with_router_response({"route": "unknown"}),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "human_handoff_declined")
        self.assertNotEqual(result["ai_response"], WEB_HUMAN_HANDOFF_REPLY)

    def test_handoff_issue_description_after_triage_transfers(self):
        from app.handlers.chat_handler import resolve_clarify_context

        memory = {
            "known_info": {},
            "clarify_context": {
                "type": "human_handoff_triage",
                "topic": "真人客服問題",
            },
        }

        selection = resolve_clarify_context("家裡網路斷線，無法使用", memory)
        self.assertEqual(memory["known_info"]["human_handoff_issue_described"], "yes")
        self.assertEqual(selection["intent"], "human_handoff_request")
        self.assertEqual(selection["reply"], WEB_HUMAN_HANDOFF_REPLY)

    def test_contact_phone_change_after_handoff_triage_transfers(self):
        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="更改電話",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[
                    {"role": "user", "content": "真人客服"},
                    {"role": "assistant", "content": HUMAN_HANDOFF_CONFIRM_REPLY},
                ],
                llm=llm_with_router_response({"route": "unknown"}),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "human_handoff_request")
        self.assertEqual(result["router"]["topic"], "變更聯絡電話")
        self.assertEqual(result["ai_response"], WEB_HUMAN_HANDOFF_REPLY)

    def test_knowledge_entity_confirmation_yes_continues_with_canonical_query(self):
        from app.handlers.chat_handler import resolve_clarify_context

        memory = {
            "clarify_context": {
                "type": "knowledge_entity_confirmation",
                "topic": "加值產品與服務",
                "name": "熊搭心",
                "knowledge_query": "熊搭心 加值服務 費用 申辦方式",
            }
        }

        selection = resolve_clarify_context("是", memory)

        self.assertEqual(selection["route"], "knowledge_query")
        self.assertEqual(selection["intent"], "value_added_product_query")
        self.assertIn("熊搭心", selection["knowledge_query"])

    def test_knowledge_entity_confirmation_is_created_by_chat_entrypoint(self):
        def fail_if_called(_prompt):
            raise AssertionError("LLM should not be called before entity confirmation")

        memory = {"company_code": "tdtv", "known_info": {}}
        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="熊溫馨",
                memory=memory,
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "clarify")
        self.assertEqual(result["router"]["intent"], "knowledge_entity_confirmation")
        self.assertEqual(result["ai_response"], "請問您指的是「熊搭心」服務嗎？")
        self.assertEqual(memory["clarify_context"]["name"], "熊搭心")

    def test_knowledge_entity_confirmation_new_question_exits_context(self):
        from app.handlers.chat_handler import resolve_clarify_context

        memory = {
            "clarify_context": {
                "type": "knowledge_entity_confirmation",
                "topic": "加值產品與服務",
                "name": "熊搭心",
                "knowledge_query": "熊搭心 加值服務 費用 申辦方式",
            }
        }

        selection = resolve_clarify_context("我想查帳單", memory)

        self.assertIsNone(selection)
        self.assertIsNone(memory["clarify_context"])

    def test_knowledge_entity_confirmation_no_does_not_force_candidate(self):
        from app.handlers.chat_handler import resolve_clarify_context

        memory = {
            "clarify_context": {
                "type": "knowledge_entity_confirmation",
                "topic": "加值產品與服務",
                "name": "熊搭心",
                "knowledge_query": "熊搭心 加值服務 費用 申辦方式",
            }
        }

        selection = resolve_clarify_context("不是", memory)

        self.assertEqual(selection["route"], "direct_reply")
        self.assertEqual(selection["intent"], "knowledge_entity_confirmation_declined")
        self.assertNotIn("熊搭心", selection["reply"])

    def test_value_added_clarification_context_resolves_each_supported_product(self):
        from app.handlers.chat_handler import build_clarify_context, resolve_clarify_context

        router = {
            "route": "clarify",
            "intent": "value_added_service_clarification",
            "topic": "加值服務",
        }
        expected_queries = {
            "LINE TV": "LINE TV",
            "wifi": "WiFi 5",
            "攝影機": "居家智慧攝影機",
            "熊大心": "熊搭心",
            "全部": "各項單品銷售",
        }

        for answer, expected in expected_queries.items():
            with self.subTest(answer=answer):
                memory = {"clarify_context": build_clarify_context(router)}
                selection = resolve_clarify_context(answer, memory)

                self.assertIsNotNone(selection)
                self.assertEqual(selection["route"], "knowledge_query")
                self.assertIn(expected, selection["knowledge_query"])

    def test_company_info_rule_does_not_call_llm(self):
        def fail_if_called(_prompt):
            raise AssertionError("LLM should not be called for company info rule")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="客服電話",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "company_info")
        self.assertEqual(result["router"]["reason"], "company_info_contact_phone_interrupt_rule")
        self.assertIn("大屯有線客服電話", result["ai_response"])

    def test_company_phone_interrupts_tv_troubleshooting(self):
        def fail_if_called(_prompt):
            raise AssertionError("Company phone switch should not need LLM")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="公司電話",
                memory={
                    "company_code": "wctv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "tv",
                        "troubleshooting_step": "tv_power_cycle_reboot",
                    },
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "company_info")
        self.assertEqual(result["router"]["topic"], "contact_phone")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_started"], "no")
        self.assertIn("客服電話", result["ai_response"])
        self.assertNotIn("自己關機再開機", result["ai_response"])

    def test_network_troubleshooting_request_interrupts_tv_troubleshooting(self):
        def fail_if_called(_prompt):
            raise AssertionError("Network troubleshooting switch should not need LLM")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路排除",
                memory={
                    "company_code": "toplight",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "tv",
                        "troubleshooting_step": "tv_check_power",
                    },
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "clarify")
        self.assertEqual(result["router"]["intent"], "network_troubleshooting_clarify")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_started"], "no")
        self.assertIn("無法連線", result["ai_response"])
        self.assertNotIn("機上盒電源燈", result["ai_response"])

    def test_engineer_weekend_question_is_not_business_hours(self):
        router_llm = llm_with_router_response({
            "route": "company_info",
            "intent": "company_info",
            "tool_name": None,
            "topic": "business_hours",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": "business_hours",
            "reply": "大屯有線營業時間：星期一～星期五 08:00-19:00。",
            "extracted_slots": {},
            "reason": "bad_business_hours_route",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="工程師假日有上班嗎?",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertEqual(result["router"]["intent"], "engineer_weekend_service")
        self.assertIn("裝機", result["ai_response"])
        self.assertIn("維修", result["ai_response"])
        self.assertIn("工程量控", result["ai_response"])

    def test_plain_website_issue_does_not_match_archived_company_rule(self):
        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網站打不開",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm_with_router_response({
                    "route": "smalltalk",
                    "intent": "smalltalk",
                    "tool_name": None,
                    "topic": None,
                    "should_cancel_current_flow": False,
                    "should_call_tool": False,
                    "should_retrieve_knowledge": False,
                    "knowledge_query": None,
                    "reply": "我幫您確認。",
                    "extracted_slots": {},
                    "reason": "test_router",
                }),
                persist=False,
            )

        self.assertNotEqual(result["router"]["reason"], "archived_website_rule")

    def test_rag_turn_clears_previous_tool_snapshot(self):
        router_llm = llm_with_router_response({
            "route": "knowledge_query",
            "intent": "faq",
            "tool_name": None,
            "topic": "發票",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "何時拿到發票",
            "reply": "",
            "extracted_slots": {},
            "reason": "test_knowledge_query",
        })

        memory = {
            "company_code": "tdtv",
            "known_info": {},
            "last_tool_result": {
                "success": True,
                "tool_name": "search_channel_no",
                "message": "已查詢到「三立台灣台」相關頻道：\n三立台灣台：第 29 台",
            },
            "last_knowledge_results": [{"question": "舊資料"}],
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=[]),
            patch(
                "app.handlers.chat_handler.compose_knowledge_reply",
                return_value="目前我這邊沒有查到足夠明確的資料，請您換個方式描述想了解的問題。",
            ),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="何時拿到發票",
                memory=memory,
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertIsNone(result["memory"]["last_tool_result"])
        self.assertEqual(result["memory"]["last_knowledge_results"], [])

    def test_company_info_can_interrupt_troubleshooting_flow(self):
        def fail_if_called(_prompt):
            raise AssertionError("LLM should not be called for company info interrupt")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="有區域故障嗎",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                        "troubleshooting_step": "net_all_or_single",
                    },
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "company_info")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_started"], "no")
        self.assertIn("區域故障", result["ai_response"])

    def test_contract_query_interrupts_troubleshooting_and_requires_login(self):
        def fail_if_called(_prompt):
            raise AssertionError("Contract interrupt should not need router LLM")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我的合約",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "tv",
                        "troubleshooting_step": "tv_check_power",
                        "troubleshooting_failed": "no",
                        "retry": 0,
                    },
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertEqual(result["router"]["intent"], "contract_lookup_login_required")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_started"], "no")
        self.assertNotIn("機上盒電源燈", result["ai_response"])
        self.assertIn("登入會員後才能查詢", result["ai_response"])

    def test_paid_reconnection_archived_interrupt_expectation(self):
        def fail_if_called(_prompt):
            raise AssertionError("paid reconnection must not remain in troubleshooting")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我已經繳費了，網路還沒恢復，請幫我復線",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                        "troubleshooting_step": "net_all_or_single",
                    },
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "payment_receipt_image_required")
        self.assertIsNone(result["router"]["tool_name"])
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_started"], "no")
        self.assertIn("上傳清楚、完整", result["ai_response"])

    def test_paid_bill_without_restore_request_keeps_troubleshooting_flow(self):
        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我已經繳費了，但帳單還顯示未繳",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                        "troubleshooting_step": "net_all_or_single",
                    },
                },
                history=[],
                llm=RunnableLambda(lambda _prompt: Response("{}")),
                persist=False,
            )

        self.assertNotEqual(result["router"]["intent"], "payment_receipt_reconnection")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_started"], "yes")

    def test_promotion_query_interrupts_troubleshooting_and_searches_rag(self):
        router_llm = llm_with_router_response({
            "route": "knowledge_query",
            "intent": "promotion_query",
            "tool_name": None,
            "topic": "促銷方案",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "優惠方案",
            "reply": "",
            "extracted_slots": {},
            "reason": "test_active_switch",
        })

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge") as retrieve_knowledge,
        ):
            retrieve_knowledge.return_value = []
            result = handle_chat_message(
                user_id="test-user",
                user_text="有優惠方案嗎",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                        "troubleshooting_step": "net_all_or_single",
                    },
                },
                history=[],
                llm=router_llm,
                persist=False,
            )

        retrieve_knowledge.assert_called_once()
        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertEqual(result["router"]["topic"], "促銷方案")
        self.assertTrue(result["router"]["should_retrieve_knowledge"])
        self.assertTrue(result["router"]["reason"].startswith("active_flow_switch_"))
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_started"], "no")
        self.assertIn("沒有查到足夠明確的資料", result["ai_response"])

    def test_promotion_reply_combines_company_profile_and_rag_results(self):
        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge") as retrieve_knowledge,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我要最新優惠",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm_with_router_response({
                    "route": "clarify",
                    "intent": "promotion_service_scope_clarification",
                    "topic": "優惠方案服務類型",
                    "should_cancel_current_flow": False,
                    "should_call_tool": False,
                    "should_retrieve_knowledge": False,
                    "knowledge_query": None,
                    "reply": "請問您想了解哪一類優惠方案？\n1. 有線電視＋網路\n2. 純網路\n3. 純有線電視",
                    "extracted_slots": {},
                    "reason": "model_promotion_scope_clarification",
                }),
                persist=False,
            )

        retrieve_knowledge.assert_not_called()
        self.assertEqual(result["router"]["route"], "clarify")
        self.assertFalse(result["router"]["should_retrieve_knowledge"])
        self.assertIn("有線電視＋網路", result["ai_response"])
        self.assertIn("純網路", result["ai_response"])
        self.assertIn("純有線電視", result["ai_response"])

    def test_apply_300m_discount_followup_transfers_without_rag(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived promotion rule unexpectedly invoked the model")

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge") as retrieve_knowledge,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="申請300M網路優惠",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[
                    {"role": "user", "content": "網路跟有線電視優惠"},
                    {"role": "assistant", "content": "目前資料有好視成雙NO8與好視成雙NO7。"},
                ],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        retrieve_knowledge.assert_not_called()
        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertEqual(result["router"]["intent"], "human_handoff_request")
        self.assertEqual(result["ai_response"], WEB_HUMAN_HANDOFF_REPLY)
        self.assertNotIn("【轉真人客服】", result["ai_response"])
        self.assertNotIn("請由真人客服接手", result["ai_response"])

    def test_social_discount_question_enters_rag_flow(self):
        def fail_if_called(_prompt):
            raise AssertionError("Social discount query should not need router LLM")

        doc = {
            "id": "low-income-1",
            "company": "大屯",
            "category": "billing",
            "question": "低收入_身心障礙優惠報價AI版",
            "answer": "【方案名稱】低收入戶優惠方案\n【優惠內容】收視服務費優惠後收費金額：0元／年。",
            "_score": 0.9,
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=[doc]) as retrieve_knowledge,
            patch("app.handlers.chat_handler.compose_knowledge_reply", return_value="低收入戶優惠方案：0元／年。"),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="有低收入優惠方案嗎?",
                memory={"company_code": "tdtv", "company": "大屯", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        retrieve_knowledge.assert_called_once()
        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertEqual(result["router"]["intent"], "social_discount_query")
        self.assertEqual(result["ai_response"], "低收入戶優惠方案：0元／年。")

    def test_promotion_rag_query_includes_user_text(self):
        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=[]) as retrieve_knowledge,
        ):
            handle_chat_message(
                user_id="test-user",
                user_text="飆網守護家 和好視成雙 300M多少錢?",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm_with_router_response({
                    "route": "knowledge_query",
                    "intent": "promotion_comparison_query",
                    "topic": "具名方案比較",
                    "should_cancel_current_flow": True,
                    "should_call_tool": False,
                    "should_retrieve_knowledge": True,
                    "knowledge_query": "飆網守護家 和好視成雙 300M 費用 優惠方案",
                    "reply": "",
                    "extracted_slots": {},
                    "reason": "model_named_campaign_comparison",
                }),
                persist=False,
            )

        controller_output = retrieve_knowledge.call_args.args[2]
        self.assertIn("飆網守護家", controller_output["knowledge_query"])
        self.assertIn("優惠方案", controller_output["knowledge_query"])

    def test_renewal_process_query_uses_renewal_terms_not_promotion_only(self):
        docs = [{
            "id": "renewal-doc",
            "question": "好視成雙NO8",
            "answer": (
                "方案名稱：好視成雙NO8\n"
                "五、中途換約或升級：需升級且原剩餘合約需累加新合約週期。\n"
                "售價：\n"
                "500M/500M：月繳$999元、半年繳$5994元、年繳$11988元\n"
                "300M/300M：月繳$899元、半年繳$5394元、年繳$10788元"
            ),
            "company": "大屯",
            "category": "billing",
            "_score": 0.9,
        }]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs) as retrieve_knowledge,
            patch("app.handlers.chat_handler.compose_knowledge_reply", return_value="續約需由客服依目前合約狀態確認可辦理方案。"),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="怎麼重新續約",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm_with_router_response({
                    "route": "knowledge_query",
                    "intent": "renewal_process_query",
                    "topic": "續約流程",
                    "should_cancel_current_flow": True,
                    "should_call_tool": False,
                    "should_retrieve_knowledge": True,
                    "knowledge_query": "續約 重新續約 合約狀態 辦理方式",
                    "reply": "",
                    "extracted_slots": {},
                    "reason": "model_renewal_process",
                }),
                persist=False,
            )

        controller_output = retrieve_knowledge.call_args.args[2]
        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertEqual(result["router"]["intent"], "renewal_process_query")
        self.assertIn("續約", controller_output["knowledge_query"])
        self.assertIn("合約狀態", controller_output["knowledge_query"])
        self.assertNotEqual(controller_output["knowledge_query"], "優惠方案")
        self.assertNotEqual(result["router"].get("topic"), "promotion_activity")

    def test_monthly_price_correction_uses_sale_monthly_lines(self):
        docs = [{
            "question": "好視成雙NO8",
            "answer": (
                "方案名稱：好視成雙NO8\n"
                "售價：\n"
                "500M/500M：月繳$999元、半年繳$5994元、年繳$11988元\n"
                "300M/300M：月繳$899元、半年繳$5394元、年繳$10788元"
            ),
        }]

        reply = apply_customer_reply_policies(
            "怎麼重新續約",
            "【方案名稱】\n好視成雙NO8\n【月租/速率】\n300M/300M 或 500M/500M；資料未提供月租。",
            docs,
        )

        self.assertNotIn("未提供月租", reply)
        self.assertIn("500M/500M：月繳$999元", reply)
        self.assertIn("300M/300M：月繳$899元", reply)

    def test_basic_tv_fee_query_targets_basic_fee_docs_not_campaigns(self):
        router_llm = llm_with_router_response({
            "route": "knowledge_query",
            "intent": "cable_tv_pricing",
            "tool_name": None,
            "topic": "有線電視基本收費",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "只要看有線電視 裝機二台機上盒 半年繳 合計多少錢",
            "reply": "",
            "extracted_slots": {},
            "reason": "test_basic_tv_fee",
        })

        docs = [{
            "id": "basic-tv",
            "question": "大屯_TV_基本收費標準11506",
            "answer": "半年繳 $3,280，裝機費 $1,000，TV 分機費順裝 $500，第1、2台機上盒免押金。",
            "company": "大屯",
            "category": "billing",
            "_score": 0.9,
        }]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs) as retrieve_knowledge,
            patch("app.handlers.chat_handler.compose_knowledge_reply", return_value="半年繳 $3,280 + 裝機費 $1,000 + TV 分機費 $500 = $4,780。"),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="只要看有線電視,裝機一起裝二台機上盒,用半年繳,合計要多少錢",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        controller_output = retrieve_knowledge.call_args.args[2]
        self.assertIn("基本收費", controller_output["knowledge_query"])
        self.assertIn("TV 收視費", controller_output["knowledge_query"])
        self.assertIn("TV 分機費", controller_output["knowledge_query"])
        self.assertIn("STB", controller_output["knowledge_query"])
        self.assertNotIn("好視成雙", controller_output["knowledge_query"])
        self.assertIn("$4,780", result["ai_response"])

    def test_social_discount_ineligible_followup_clarifies_service_scope(self):
        def fail_if_called(_prompt):
            raise AssertionError("Social discount alternative promotion should not need router LLM")

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge") as retrieve_knowledge,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我也沒有中低收~還有其他優惠嗎",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        retrieve_knowledge.assert_not_called()
        self.assertEqual(result["router"]["route"], "clarify")
        self.assertEqual(result["router"]["topic"], "優惠方案服務類型")
        self.assertIn("有線電視＋網路", result["ai_response"])

    def test_promotion_price_question_uses_rag_docs_even_with_amount_terms(self):
        docs = [{
            "id": "promo-amount",
            "question": "最新優惠",
            "answer": "飆網守護家 B2606：主推 100M、300M、500M，免裝機費、免寬頻設備押金。",
            "company": "通用",
            "category": "billing",
            "_score": 0.9,
        }]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="飆網守護家 和好視成雙 300M多少錢?",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm_with_router_response({
                    "route": "knowledge_query",
                    "intent": "promotion_comparison_query",
                    "topic": "具名方案比較",
                    "should_cancel_current_flow": True,
                    "should_call_tool": False,
                    "should_retrieve_knowledge": True,
                    "knowledge_query": "飆網守護家 和好視成雙 300M 費用",
                    "reply": "",
                    "extracted_slots": {},
                    "reason": "model_named_campaign_price",
                }),
                persist=False,
            )

        self.assertIn("沒有查到足夠明確的資料", result["ai_response"])
        self.assertNotIn("免裝機費", result["ai_response"])

    def test_short_followup_knowledge_query_uses_recent_topic(self):
        router_llm = llm_with_router_response({
            "route": "knowledge_query",
            "intent": "faq",
            "tool_name": None,
            "topic": "賽事時間",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "賽事時間 有網站參考嗎",
            "reply": "",
            "extracted_slots": {},
            "reason": "test_knowledge_query",
        })

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=[]) as retrieve_knowledge,
            patch(
                "app.handlers.chat_handler.compose_knowledge_reply",
                return_value="目前我這邊沒有查到足夠明確的資料，請您換個方式描述想了解的問題。",
            ),
        ):
            handle_chat_message(
                user_id="test-user",
                user_text="賽事時間 有網站參考嗎",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[{"role": "user", "content": "世足轉播在哪一台"}],
                llm=router_llm,
                persist=False,
            )

        controller_output = retrieve_knowledge.call_args.args[2]
        self.assertEqual(
            controller_output["knowledge_query"],
            "世足賽 賽事時間 有網站參考嗎",
        )

    def test_promotion_gift_followup_uses_dynamic_recent_campaign(self):
        router_llm = llm_with_router_response({
            "route": "knowledge_query",
            "intent": "promotion_gift_service",
            "tool_name": None,
            "topic": "贈品壁掛服務",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "贈品的電視機有含壁掛服務嗎？",
            "reply": "",
            "extracted_slots": {},
            "reason": "test_knowledge_query",
        })
        memory = {
            "company_code": "tdtv",
            "known_info": {},
            "last_knowledge_results": [
                {
                    "question": "好視成雙NO9-1150901-1151231",
                    "answer": "好視成雙 NO9 提供 300M/300M 與家電贈品。",
                    "company": "大屯",
                    "campaign_name": "好視成雙 NO9",
                }
            ],
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=[]) as retrieve_knowledge,
            patch(
                "app.handlers.chat_handler.compose_knowledge_reply",
                return_value="目前我這邊沒有查到足夠明確的資料，請您換個方式描述想了解的問題。",
            ),
        ):
            handle_chat_message(
                user_id="test-user",
                user_text="贈品的電視機有含壁掛服務嗎？",
                memory=memory,
                history=[{"role": "assistant", "content": "好視成雙 NO9 方案內容如下..."}],
                llm=router_llm,
                persist=False,
        )

        controller_output = retrieve_knowledge.call_args.args[2]
        self.assertNotIn("好視成雙 NO9", controller_output["knowledge_query"])
        self.assertIn("壁掛", controller_output["knowledge_query"])
        self.assertNotIn("NO8", controller_output["knowledge_query"])

    def test_pending_tool_fixed_ip_switch_clears_pending_and_uses_rag(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": "固定 IP",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=[]),
            patch(
                "app.handlers.chat_handler.compose_knowledge_reply",
                return_value="固定 IP 需由客服協助確認。",
            ),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="綁固定ip",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "bill_return_line_tv",
                    "pending_tool_args": ["phone"],
                },
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertIsNone(result["memory"]["pending_tool"])
        self.assertEqual(result["memory"]["pending_tool_args"], [])

    def test_pending_bill_lookup_can_switch_to_installation_fee_question(self):
        router_llm = llm_with_router_response({
            "route": "knowledge_query",
            "intent": "installation_fee_query",
            "tool_name": None,
            "topic": "電視裝機費",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "電視 裝機費 分機費",
            "reply": "",
            "extracted_slots": {},
            "reason": "test_installation_fee_switch",
        })

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=[]),
            patch(
                "app.handlers.chat_handler.compose_knowledge_reply",
                return_value="裝機費與分機費依裝設方式計算。",
            ),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="電視裝機費多少錢？",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["name", "phone"],
                },
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertIsNone(result["memory"].get("pending_tool"))
        self.assertIn("裝機費", result["ai_response"])
        self.assertNotIn("戶名", result["ai_response"])

    def test_invalid_pending_customer_number_returns_format_prompt_without_api_call(self):
        def fail_if_called(_prompt):
            raise AssertionError("customer-number validation unexpectedly invoked the model")

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="-046793",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["name", "phone"],
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        call_tool.assert_not_called()
        self.assertIn("戶名與登記電話", result["ai_response"])
        self.assertEqual(result["memory"].get("pending_tool"), "search_bill")

    def test_zero_prefixed_pending_customer_number_is_rejected_without_api_call(self):
        def fail_if_called(_prompt):
            raise AssertionError("customer-number validation unexpectedly invoked the model")

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="046793",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["name", "phone"],
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        call_tool.assert_not_called()
        self.assertIn("戶名與登記電話", result["ai_response"])
        self.assertEqual(result["memory"].get("pending_tool"), "search_bill")

    def test_generic_network_fault_starts_with_actionable_checks(self):
        memory = {"known_info": {}}
        plan = {"reply": "", "should_call_tool": False, "tool_name": None}

        result = apply_troubleshooting_engine("網路有問題", memory, plan)

        self.assertIn("電源拔除 10 秒", result["reply"])
        self.assertIn("網路線兩端", result["reply"])
        self.assertIn("所有設備", result["reply"])

    def test_tv_unauthorized_does_not_route_to_reconnection_tool(self):
        router_llm = llm_with_router_response({
            "route": "tool_action",
            "intent": "reconnection",
            "tool_name": "bill_return_line_tv",
            "topic": "電視復線",
            "should_cancel_current_flow": False,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "可以，我幫您處理復線申請。",
            "extracted_slots": {},
            "reason": "bad_test_route",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="電視顯示未授權",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertNotEqual(result["router"].get("tool_name"), "bill_return_line_tv")
        self.assertIsNone(result["memory"].get("pending_tool"))
        self.assertIn("一般基本頻道", result["ai_response"])

    def test_network_cannot_connect_is_detected_as_network_fault(self):
        self.assertTrue(is_network_fault("網路不能連線"))
        self.assertTrue(is_network_fault("有線網路未連線"))

    def test_tv_complete_outage_and_signal_search_are_tv_faults(self):
        self.assertTrue(is_tv_fault("電視完全斷訊"))
        self.assertTrue(is_tv_fault("機上盒搜不到訊號"))

    def test_tv_unauthorized_first_checks_paid_channel_range(self):
        memory = {"known_info": {}}
        plan = {"reply": "", "should_call_tool": False, "tool_name": None}

        result = apply_troubleshooting_engine("按 0000 後頻道顯示未授權", memory, plan)

        self.assertIn("付費頻道", result["reply"])
        self.assertIn("200", result["reply"])
        self.assertIn("一般基本頻道", result["reply"])
        self.assertNotIn("繳費方式", result["reply"])

    def test_tv_authorization_expired_asks_channel_not_reconnection(self):
        router_llm = llm_with_router_response({
            "route": "tool_action",
            "intent": "reconnection",
            "tool_name": "bill_return_line_tv",
            "topic": "電視復線",
            "should_cancel_current_flow": False,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "可以，我幫您送出電視復機申請。請提供戶名與聯絡電話。",
            "extracted_slots": {},
            "reason": "bad_authorization_route",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="機上盒怎一直出現授權到期",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertNotEqual(result["router"].get("tool_name"), "bill_return_line_tv")
        self.assertIsNone(result["memory"].get("pending_tool"))
        self.assertIn("確認收視費", result["ai_response"])
        self.assertIn("繳費", result["ai_response"])

    def test_set_top_box_power_cycle_gets_reboot_guidance(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="機上盒看到一半自己關機再開機",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_power_cycle_reboot")
        self.assertIn("重新插上", result["ai_response"])

    def test_all_channels_unavailable_after_reboot_is_not_power_cycle_followup(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="機上盒已重開機過了，全部頻道都無法收視",
                memory={
                    "company_code": "wctv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "tv",
                        "troubleshooting_step": "tv_power_cycle_reboot",
                    },
                },
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_failed"], "yes")
        self.assertIn("全部頻道無法收視", result["ai_response"])
        self.assertIn("真人客服", result["ai_response"])
        self.assertNotIn("自己關機再開機", result["ai_response"])

    def test_no_signal_variant_enters_tv_input_source_troubleshooting(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="無信號",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_check_input_source")
        self.assertIn("訊號源", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_llm_tv_fault_route_enters_tv_input_source_troubleshooting(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "tv_signal_issue",
            "tool_name": None,
            "topic": "電視故障",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_tv_fault_route",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="故障無信號",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_check_input_source")
        self.assertIn("訊號源", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_repair_report_with_user_address_does_not_return_company_address(self):
        router_llm = llm_with_router_response({
            "route": "company_info",
            "intent": "company_info",
            "tool_name": None,
            "topic": "company_address",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": "company_address",
            "reply": "大屯有線地址：台中市大里區國光路一段68號。",
            "extracted_slots": {},
            "reason": "bad_address_route",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="家中機上盒壞掉，無亮燈，需報修。地址：大里市公教街209巷11號",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertNotEqual(result["router"]["route"], "company_info")
        self.assertEqual(result["plan"]["tool_name"], "create_repair_ticket")
        self.assertIn("報修", result["ai_response"])
        self.assertNotIn("國光路一段68號", result["ai_response"])

    def test_payment_reconnection_can_interrupt_network_troubleshooting(self):
        def fail_if_called(_prompt):
            raise AssertionError("LLM should not be called for contextual reconnection switch")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我已經繳費了 快點恢復",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                        "troubleshooting_step": "net_all_or_single",
                    },
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertEqual(result["router"]["intent"], "payment_receipt_image_required")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_started"], "no")
        self.assertIsNone(result["memory"]["pending_tool"])
        self.assertIn("無法接受手動輸入", result["ai_response"])

    def test_unstable_network_enters_troubleshooting(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路連線不穩",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_unstable_scope")
        self.assertIn("連線不穩", result["ai_response"])
        self.assertNotIn("所有設備都不能上網", result["ai_response"])

    def test_slow_network_enters_speed_troubleshooting_not_repair_disabled(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="是很慢不是不能上網",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_slow_scope")
        self.assertIn("重新啟動數據機及分享器", result["ai_response"])
        self.assertIn("約 2 分鐘", result["ai_response"])

    def test_slow_network_video_buffering_uses_slow_speed_guidance(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我家網路最近變慢，影片一直轉圈圈，是不是要換設備？",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_slow_scope")
        self.assertIn("網路變慢", result["ai_response"])
        self.assertIn("重新啟動數據機及分享器", result["ai_response"])
        self.assertNotIn("所有設備都不能上網", result["ai_response"])

    def test_non_promoted_1g_plan_interrupts_troubleshooting_with_special_reply(self):
        router_llm = llm_with_router_response({
            "route": "unsupported_flow",
            "intent": "apply_internet_plan",
            "tool_name": None,
            "topic": "申辦網路",
            "should_cancel_current_flow": True,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "目前線上申辦網路方案服務暫停，請改由真人客服協助您確認與辦理。",
            "extracted_slots": {},
            "reason": "bad_unsupported_flow",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我要申請1G網路方案。",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                        "troubleshooting_step": "net_slow_scope",
                    },
                },
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "non_promoted_1g_plan")
        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertIn("1G 非主推網路方案", result["ai_response"])
        self.assertNotIn("線上申辦網路方案服務暫停", result["ai_response"])

    def test_paid_tv_still_unavailable_requests_convenience_store_receipt(self):
        router_llm = llm_with_router_response({
            "route": "tool_action",
            "intent": "tv_reactivation_after_payment",
            "tool_name": "bill_return_line_tv",
            "topic": "電視復線",
            "should_cancel_current_flow": False,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "可以，我幫您送出電視復機申請。請提供戶名與聯絡電話。",
            "extracted_slots": {},
            "reason": "bad_tv_reconnection",
        })

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="怎麼開通電視我已經繳費完成",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        call_tool.assert_not_called()
        self.assertEqual(result["router"]["intent"], "payment_receipt_image_required")
        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertIsNone(result["router"].get("tool_name"))
        self.assertIsNone(result["memory"].get("pending_tool"))
        self.assertIn("無法接受手動輸入", result["ai_response"])

    def test_general_channel_e004_confirms_temp_restore_before_calling_tv_api(self):
        router_llm = llm_with_router_response({
            "route": "clarify",
            "intent": "general_channel_e004_temp_restore_clarify",
            "tool_name": None,
            "topic": "一般頻道 E004",
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "若一般基本頻道也顯示 E004、授權到期或未授權，請先確認收視費是否已繳清。\n若尚未繳費，我可以先協助您進行電視暫時復線；請問需要我現在協助嗎？",
            "extracted_slots": {},
        })
        first = handle_chat_message(
            user_id="test-user",
            user_text="一般頻道顯示 E004",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=router_llm,
            persist=False,
        )

        self.assertEqual(first["router"]["intent"], "general_channel_e004_temp_restore_clarify")
        self.assertEqual(first["router"]["route"], "clarify")
        self.assertIn("暫時復線", first["ai_response"])

        second = handle_chat_message(
            user_id="test-user",
            user_text="要",
            memory=first["memory"],
            history=[],
            llm=RunnableLambda(lambda _prompt: Response("{}")),
            persist=False,
        )

        self.assertEqual(second["router"]["tool_name"], "bill_return_line_tv")
        self.assertEqual(second["memory"].get("pending_tool"), "bill_return_line_tv")

    def test_personal_monthly_fee_clarifies_bill_or_contract_before_lookup(self):
        router_llm = llm_with_router_response({
            "route": "clarify",
            "intent": "personal_monthly_fee_clarify",
            "tool_name": None,
            "topic": "月租查詢類型",
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "請問您是想查詢目前待繳帳單金額，還是查詢目前合約／服務內容？",
            "extracted_slots": {},
        })
        first = handle_chat_message(
            user_id="test-user",
            user_text="查詢月租",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=router_llm,
            persist=False,
        )

        self.assertEqual(first["router"]["intent"], "personal_monthly_fee_clarify")
        self.assertIn("待繳帳單金額", first["ai_response"])
        self.assertIn("合約／服務內容", first["ai_response"])

        second = handle_chat_message(
            user_id="test-user",
            user_text="合約內容",
            memory=first["memory"],
            history=[],
            llm=RunnableLambda(lambda _prompt: Response("{}")),
            persist=False,
        )

        self.assertEqual(second["router"]["route"], "direct_reply")
        self.assertEqual(second["router"]["intent"], "contract_lookup_login_required")
        self.assertIsNone(second["memory"].get("pending_tool"))
        self.assertIn("登入會員後才能查詢", second["ai_response"])

    def test_restore_before_payment_returns_original_service_clarification(self):
        router_llm = llm_with_router_response({
            "route": "faq",
            "intent": "payment_reconnection_faq",
            "tool_name": None,
            "topic": "復訊",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "復訊 繳費",
            "reply": "復訊通常需先完成繳費；若您有特殊狀況想先復訊，需由客服確認。",
            "extracted_slots": {},
            "reason": "bad_faq_fallback",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我可以先復訊再繳費嗎",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "overdue_reconnection_service_clarify")
        self.assertEqual(result["router"]["route"], "clarify")
        self.assertEqual(result["ai_response"], "請問您要恢復的是「網路」還是「電視」服務？")

    def test_repair_service_hours_are_24h_not_counter_hours(self):
        router_llm = llm_with_router_response({
            "route": "company_info",
            "intent": "company_contact_business_hours",
            "tool_name": None,
            "topic": "business_hours",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "大屯有線營業時間：星期一～星期五 08:00-19:00。",
            "extracted_slots": {},
            "reason": "bad_business_hours",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="電話報修客服時間",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "company_repair_service_hours")
        self.assertEqual(result["router"]["topic"], "電話報修客服時間")
        self.assertIn("24 小時服務", result["ai_response"])
        self.assertIn("櫃台營業時間僅適用於臨櫃辦理", result["ai_response"])

    def test_phone_cannot_connect_asks_wifi_or_mobile_data(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="手機不能上網",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_phone_connection_type")
        self.assertIn("4G/5G", result["ai_response"])

    def test_computer_cannot_connect_asks_wifi_or_cable(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="電腦不能上網",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_computer_connection_type")
        self.assertIn("實體網路線", result["ai_response"])

    def test_wired_wall_port_followup_does_not_escalate_to_handoff(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })
        memory = {"company_code": "tdtv", "known_info": {}}
        history = []

        with patch("app.handlers.chat_handler.log_chat_latency"):
            for user_text in ["網路排除", "速度慢", "我是直接插網路孔"]:
                result = handle_chat_message(
                    user_id="test-user",
                    user_text=user_text,
                    memory=memory,
                    history=history,
                    llm=router_llm,
                    persist=False,
                )
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": result["ai_response"]})
                memory = result["memory"]

        self.assertFalse(result["plan"]["should_call_tool"])
        self.assertIsNone(result["plan"]["tool_name"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_wired_connection_check")
        self.assertEqual(memory["known_info"]["connection_type"], "wired")
        self.assertIn("網路線", result["ai_response"])
        self.assertNotIn("轉真人文字客服", result["ai_response"])
        self.assertNotIn("維修申告", result["ai_response"])

    def test_report_fault_during_network_troubleshooting_escalates(self):
        llm = llm_with_router_response({"label": "refuse"})

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="回報故障",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                        "troubleshooting_step": "net_check_scope",
                        "retry": 0,
                    },
                },
                history=[],
                llm=llm,
                persist=False,
            )

        self.assertTrue(result["plan"]["should_call_tool"])
        self.assertEqual(result["plan"]["tool_name"], "create_repair_ticket")
        self.assertIn("報修", result["ai_response"])

    def test_llm_fault_report_during_network_troubleshooting_continues_diagnosis(self):
        llm = llm_with_router_response({"label": "fault_report"})

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="回報故障",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "network",
                        "troubleshooting_step": "net_check_scope",
                        "issue_description": "家中無網路",
                        "retry": 0,
                    },
                },
                history=[],
                llm=llm,
                persist=False,
            )

        self.assertFalse(result["plan"]["should_call_tool"])
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_check_modem_light")
        self.assertIn("數據機", result["ai_response"])

    def test_bare_fault_report_does_not_cancel_active_network_troubleshooting(self):
        router_llm = llm_with_router_response({"label": "fault_report"})
        memory = {
            "company_code": "tdtv",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_check_scope",
                "issue_description": "家中無網路",
                "retry": 0,
            },
        }

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="回報故障",
                memory=memory,
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertFalse(result["plan"]["should_call_tool"])
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_check_modem_light")

    def test_plain_report_fault_starts_fault_category_question(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="回報故障",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "ask_fault_category")
        self.assertIn("電視、網路", result["ai_response"])

    def test_initial_concrete_fault_cannot_skip_to_repair_ticket(self):
        router_llm = llm_with_router_response({
            "route": "tool_action",
            "intent": "tv_signal_instability_repair",
            "tool_name": "create_repair_ticket",
            "topic": "電視異常報修",
            "should_cancel_current_flow": False,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "了解，我幫您安排報修。",
            "extracted_slots": {},
            "reason": "llm_requested_repair",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="機上盒搜不到訊號，請回報故障",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertFalse(result["plan"]["should_call_tool"])
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_check_input_source")
        self.assertIn("訊號源", result["ai_response"])

    def test_fault_report_wording_cannot_skip_to_repair_ticket(self):
        router = run_intent_router(
            "回傳故障",
            {"company_code": "cnt", "known_info": {}},
            [{"role": "user", "content": "線路不通"}],
            llm_with_router_response({
                "route": "tool_action",
                "intent": "network_repair",
                "tool_name": "create_repair_ticket",
                "should_call_tool": True,
                "should_retrieve_knowledge": False,
                "reply": "了解，我幫您安排報修。",
            }),
        )

        self.assertEqual(router["route"], "troubleshooting")
        self.assertFalse(router["should_call_tool"])

    def test_tv_sound_issue_starts_sound_specific_diagnosis(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "tv_viewing_interruption_issue",
            "tool_name": None,
            "topic": "哈TV 聲音異常",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_tv_sound_issue",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="哈TV沒有聲音",
                memory={"company_code": "cnt", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_check_sound")
        self.assertIn("靜音", result["ai_response"])

    def test_new_question_cancels_pending_identity_collection_before_llm_routing(self):
        router_llm = llm_with_router_response({
            "route": "knowledge_query",
            "intent": "next_tier_plan_fee_guidance",
            "tool_name": None,
            "topic": "寬頻升級方案費用",
            "should_cancel_current_flow": True,
            "should_call_tool": False,
            "should_retrieve_knowledge": True,
            "knowledge_query": "目前速率 60M/6M 升級下一階速率 費用",
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_next_tier_query",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="再高一階多少錢",
                memory={
                    "company_code": "tdtv",
                    "pending_tool": "search_contract_info",
                    "pending_tool_args": ["name", "phone"],
                    "known_info": {"custnum": "115585"},
                },
                history=[{"role": "user", "content": "目前方案資訊"}],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertIsNone(result["memory"]["pending_tool"])

    def test_fault_category_signal_problem_switches_to_tv_without_reasking_category(self):
        router_llm = llm_with_router_response({
            "route": "continue_current_flow",
            "intent": "troubleshooting",
            "tool_name": None,
            "topic": "故障排除",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "state_machine_first",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="訊號不良",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "unknown",
                        "troubleshooting_step": "ask_fault_category",
                        "troubleshooting_failed": "no",
                        "retry": 0,
                    },
                },
                history=[
                    {"role": "user", "content": "回報故障"},
                    {"role": "assistant", "content": "請問目前遇到的是電視、網路，還是其他設備問題？"},
                ],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "tv")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("收訊", result["ai_response"])
        self.assertNotIn("請問目前遇到的是電視、網路", result["ai_response"])

    def test_fault_category_broadband_outage_switches_to_network_without_reasking_category(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "unknown",
                "troubleshooting_step": "ask_fault_category",
                "troubleshooting_failed": "no",
                "retry": 0,
            },
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine("寬頻網路斷訊", memory, plan)

        self.assertEqual(memory["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_check_scope")
        self.assertIn("所有設備", result["reply"])
        self.assertNotIn("請直接回覆", result["reply"])

    def test_tv_playback_pause_enters_tv_signal_flow(self):
        router_llm = llm_with_router_response({
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test_unknown",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="電視播放中會突然停頓，3至5秒後繼續播出",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "tv")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("播放不穩", result["ai_response"])
        self.assertNotIn("請問目前遇到的是電視、網路", result["ai_response"])

    def test_llm_network_problem_route_enters_network_troubleshooting(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "network_problem",
            "tool_name": None,
            "topic": "網路故障",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_network_fault_route",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路有問題",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_reboot_modem")
        self.assertIn("最簡單的重開步驟", result["ai_response"])
        self.assertNotIn("所有設備都不能上網", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_llm_network_no_connection_route_enters_network_troubleshooting(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "network_connection_issue",
            "tool_name": None,
            "topic": "網路故障",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_network_fault_route",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路無連線",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_reboot_modem")
        self.assertIn("最簡單的重開步驟", result["ai_response"])
        self.assertNotIn("所有設備都不能上網", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])
        self.assertNotIn("哪一種網路狀況", result["ai_response"])

    def test_network_lag_enters_network_troubleshooting_not_generic_clarify(self):
        router_llm = llm_with_router_response({
            "route": "clarify",
            "intent": "ambiguous_short_query",
            "tool_name": None,
            "topic": "不明問題",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
            "extracted_slots": {},
            "reason": "bad_llm_clarify",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路卡頓",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_slow_scope")
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_network_troubleshooting_label_does_not_reask_known_outage_type(self):
        def fail_if_called(_prompt):
            raise AssertionError("Known network outage continuation should not need LLM")

        memory = {"company_code": "toplight", "known_info": {}}
        history = []
        with patch("app.handlers.chat_handler.log_chat_latency"):
            first = handle_chat_message(
                user_id="test-user",
                user_text="網路無連線",
                memory=memory,
                history=history,
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )
            history.extend([
                {"role": "user", "content": "網路無連線"},
                {"role": "assistant", "content": first["ai_response"]},
            ])
            second = handle_chat_message(
                user_id="test-user",
                user_text="網路排除",
                memory=first["memory"],
                history=history,
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(second["router"]["route"], "continue_current_flow")
        self.assertEqual(second["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertIn("已在處理網路無法連線", second["ai_response"])
        self.assertNotIn("哪一種網路狀況", second["ai_response"])

    def test_active_network_flow_keeps_step_when_llm_returns_troubleshooting(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "internet_connection_issue",
            "tool_name": None,
            "topic": "網路故障",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "same_network_troubleshooting",
        })
        memory = {
            "company_code": "toplight",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_check_scope",
                "troubleshooting_failed": "no",
                "repair_ready": "no",
            },
        }

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路排除",
                memory=memory,
                history=[{"role": "user", "content": "網路無連線"}],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(
            result["memory"]["known_info"]["troubleshooting_step"],
            "net_reboot_modem",
        )
        self.assertIn("最簡單的重開步驟", result["ai_response"])

    def test_analog_tv_signal_setting_starts_input_source_steps(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "tv_signal_issue",
            "topic": "電視訊號異常",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="電視跳類比訊號設定，掃描完還是不能看",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_check_input_source")
        self.assertIn("訊號源", result["ai_response"])

    def test_set_top_box_selection_keeps_prior_no_light_report(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "tv_set_top_box_unresponsive_issue",
            "topic": "機上盒無亮燈",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="機上盒",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[{"role": "user", "content": "都有插電，但是無亮燈"}],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_check_power_cable")
        self.assertIn("電源線與插座", result["ai_response"])
        self.assertNotIn("電源是否有亮燈", result["ai_response"])

    def test_channel_scope_reply_after_reboot_transfers_to_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_reboot",
                "awaiting_channel_scope_after_reboot": "yes",
            },
        }

        result = apply_troubleshooting_engine(
            "單一",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")

    def test_empty_reply_keeps_disabled_repair_handoff_response(self):
        router_llm = llm_with_router_response({
            "route": "direct_reply",
            "intent": "repair_followup",
            "topic": "報修進度",
            "reply": "",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
        })
        memory = {
            "company_code": "tdtv",
            "known_info": {"repair_flow_status": "disabled"},
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_tool_or_rag_flow", return_value=("", memory)),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="有插電。無亮燈",
                memory=memory,
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertIn("維修申告", result["ai_response"])
        self.assertNotEqual(result["ai_response"], "")

    def test_network_disconnected_overrides_bad_direct_reply(self):
        router_llm = llm_with_router_response({
            "route": "direct_reply",
            "intent": "ambiguous_service_type",
            "tool_name": None,
            "topic": "不明問題",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
            "extracted_slots": {},
            "reason": "bad_llm_direct_reply",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="斷網",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_check_scope")
        self.assertIn("所有設備都不能上網", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_general_signal_outage_asks_fault_category_not_generic_menu(self):
        router_llm = llm_with_router_response({
            "route": "direct_reply",
            "intent": "ambiguous_service_type",
            "tool_name": None,
            "topic": "不明問題",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
            "extracted_slots": {},
            "reason": "bad_llm_direct_reply",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="塗城路斷訊",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "unknown")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "ask_fault_category")
        self.assertIn("電視、網路", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_tv_cannot_watch_overrides_bad_direct_reply(self):
        router_llm = llm_with_router_response({
            "route": "direct_reply",
            "intent": "ambiguous_service_type",
            "tool_name": None,
            "topic": "不明問題",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
            "extracted_slots": {},
            "reason": "bad_llm_direct_reply",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="電視沒辦法看",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "tv")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_check_power")
        self.assertIn("機上盒電源", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_network_signal_check_followup_continues_network_troubleshooting(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_check_scope",
                "troubleshooting_failed": "no",
                "repair_ready": "no",
                "retry": 0,
                "issue_description": "網路沒有連線",
            }
        }
        result = apply_troubleshooting_engine(
            "查訊號",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_check_modem_light")
        self.assertIn("數據機", result["reply"])
        self.assertNotIn("請問您想查詢資料", result["reply"])

    def test_input_source_how_to_repeats_switch_steps(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_input_source",
                "troubleshooting_failed": "no",
                "repair_ready": "no",
                "retry": 0,
                "issue_description": "電視畫面顯示無訊號",
            }
        }
        result = apply_troubleshooting_engine(
            "怎麼切",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_check_input_source")
        self.assertIn("訊號源 / INPUT / SOURCE", result["reply"])
        self.assertIn("HDMI1", result["reply"])
        self.assertNotIn("切換訊號源後，畫面是否已恢復", result["reply"])

    def test_fault_category_followup_network_no_internet_switches_to_network_flow(self):
        router_llm = llm_with_router_response({
            "route": "continue_current_flow",
            "intent": "troubleshooting",
            "tool_name": None,
            "topic": "故障排除",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "state_machine_first",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路有問題，沒有網路",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "troubleshooting_started": "yes",
                        "troubleshooting_type": "unknown",
                        "troubleshooting_step": "ask_fault_category",
                        "troubleshooting_failed": "no",
                        "retry": 0,
                    },
                },
                history=[
                    {"role": "user", "content": "回報故障"},
                    {"role": "assistant", "content": "請問目前遇到的是電視、網路，還是其他設備問題？"},
                ],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_check_scope")
        self.assertIn("所有設備都不能上網", result["ai_response"])
        self.assertNotIn("請問目前遇到的是電視、網路", result["ai_response"])

    def test_troubleshooting_correction_resets_to_fault_category(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_check_scope",
                "retry": 1,
                "category_retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "我剛剛說錯了，不是這個",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_type"], "unknown")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "ask_fault_category")
        self.assertEqual(memory["known_info"]["retry"], 0)
        self.assertIn("重新確認方向", result["reply"])

    def test_troubleshooting_correction_with_clear_network_issue_switches_flow(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power",
                "retry": 1,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "不對，我是網路沒有網路",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_check_scope")
        self.assertIn("所有設備都不能上網", result["reply"])

    def test_fault_category_repeated_unexpected_answers_uses_simpler_prompt(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "unknown",
                "troubleshooting_step": "ask_fault_category",
                "category_retry": 1,
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "我也不知道怎麼講",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "ask_fault_category")
        self.assertEqual(memory["known_info"]["category_retry"], 2)
        self.assertIn("請直接回覆", result["reply"])

    def test_failed_label_at_tv_screen_step_moves_to_reboot(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_screen",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }
        llm = llm_with_router_response({"label": "failed"})

        result = apply_troubleshooting_engine(
            "畫面還是黑的",
            memory,
            plan,
            llm=llm,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("機上盒電源拔掉", result["reply"])

    def test_tv_power_confirmed_uses_existing_screen_description(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power",
                "retry": 0,
                "issue_description": "電視不能收看，畫面出現請洽客服",
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine("有亮", memory, plan)

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("前面描述的畫面狀況", result["reply"])
        self.assertIn("機上盒電源拔掉", result["reply"])
        self.assertNotIn("無訊號", result["reply"])
        self.assertNotIn("黑畫面", result["reply"])
        self.assertNotIn("錯誤代碼", result["reply"])

    def test_tv_power_confirmed_still_asks_screen_when_no_description(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power",
                "retry": 0,
                "issue_description": "電視不能看",
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine("有亮", memory, plan)

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_check_screen")
        self.assertIn("無訊號", result["reply"])
        self.assertIn("黑畫面", result["reply"])
        self.assertIn("錯誤代碼", result["reply"])

    def test_clear_tv_symptoms_skip_redundant_power_or_screen_questions(self):
        cases = [
            {
                "text": "電視有開但沒頻道",
                "step": "tv_rescan_channels",
                "contains": "重新搜頻",
                "not_contains": "電源是否有亮",
            },
            {
                "text": "畫面一直卡住",
                "step": "tv_reboot",
                "contains": "機上盒電源拔掉",
                "not_contains": "電源是否有亮",
            },
            {
                "text": "有聲音沒畫面",
                "step": "tv_check_input_source",
                "contains": "訊號源",
                "not_contains": "電源是否有亮",
            },
            {
                "text": "機上盒一直跑不進去",
                "step": "tv_reboot",
                "contains": "機上盒電源拔掉",
                "not_contains": "無訊號",
            },
        ]

        for case in cases:
            with self.subTest(case["text"]):
                memory = {"known_info": {}}
                result = apply_troubleshooting_engine(
                    case["text"],
                    memory,
                    {"reply": "", "should_call_tool": False, "tool_name": None},
                )

                self.assertFalse(result["should_call_tool"])
                self.assertEqual(memory["known_info"]["troubleshooting_step"], case["step"])
                self.assertIn(case["contains"], result["reply"])
                self.assertNotIn(case["not_contains"], result["reply"])

    def test_tv_troubleshooting_topics_follow_customer_service_sop(self):
        cases = [
            {
                "text": "頻道收視異常",
                "step": "tv_rescan_channels",
                "contains": "重新搜頻",
                "not_contains": "電源是否有亮",
            },
            {
                "text": "畫面顯示未收權",
                "step": "unauthorized_channel_check",
                "contains": "誤切到加購",
                "not_contains": "繳費",
            },
            {
                "text": "機上盒一直出現授權到期",
                "step": "authorization_payment",
                "contains": "是否已完成繳費",
                "not_contains": "誤切到加購",
            },
            {
                "text": "電視無畫面",
                "step": "tv_check_input_source",
                "contains": "訊號源",
                "not_contains": "電源是否有亮",
            },
        ]

        for case in cases:
            with self.subTest(case["text"]):
                memory = {"known_info": {}}
                result = apply_troubleshooting_engine(
                    case["text"],
                    memory,
                    {"reply": "", "should_call_tool": False, "tool_name": None},
                )

                self.assertFalse(result["should_call_tool"])
                self.assertEqual(memory["known_info"]["troubleshooting_step"], case["step"])
                self.assertIn(case["contains"], result["reply"])
                self.assertNotIn(case["not_contains"], result["reply"])

    def test_clear_network_symptoms_skip_redundant_scope_questions(self):
        cases = [
            {
                "text": "數據機亮紅燈不能上網",
                "step": "net_reboot_modem",
                "scope": None,
                "contains": "數據機電源拔掉",
            },
            {
                "text": "網路有線可以用，Wi-Fi不能用",
                "step": "net_single_device",
                "scope": "wifi_only",
                "contains": "Wi-Fi 不能用",
            },
            {
                "text": "手機能上網，電腦不能",
                "step": "net_computer_connection_type",
                "scope": "single_device",
                "contains": "電腦是透過 Wi-Fi",
            },
        ]

        for case in cases:
            with self.subTest(case["text"]):
                memory = {"known_info": {}}
                result = apply_troubleshooting_engine(
                    case["text"],
                    memory,
                    {"reply": "", "should_call_tool": False, "tool_name": None},
                )

                known = memory["known_info"]
                self.assertFalse(result["should_call_tool"])
                self.assertEqual(known["troubleshooting_step"], case["step"])
                if case["scope"]:
                    self.assertEqual(known["affected_scope"], case["scope"])
                self.assertIn(case["contains"], result["reply"])
                self.assertNotIn("所有設備都不能上網", result["reply"])

    def test_signal_source_help_starts_followup_troubleshooting_state(self):
        memory = {
            "known_info": {},
            "pending_tool": None,
            "pending_tool_args": [],
            "conversation_state": {},
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = start_tv_input_source_troubleshooting(
            "訊號源跑掉怎麼辦",
            memory=memory,
            plan=plan,
        )

        self.assertIn("訊號源", result["reply"])
        self.assertEqual(memory["known_info"]["troubleshooting_started"], "yes")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_check_input_source")

    def test_no_after_input_source_check_moves_to_reboot_step(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_input_source",
                "retry": 0,
                "issue_description": "電視畫面顯示無訊號",
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "沒有",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("機上盒電源拔掉", result["reply"])

    def test_partial_channel_issue_starts_channel_rescan_steps(self):
        memory = {
            "known_info": {},
            "pending_tool": None,
            "pending_tool_args": [],
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "有些頻道看得到，有些頻道顯示無訊號",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_rescan_channels")
        self.assertIn("恢復預設", result["reply"])
        self.assertIn("重搜", result["reply"])
        self.assertIn("TOP-006", result["reply"])
        self.assertIn("TOP-007", result["reply"])
        self.assertIn("雙模機且遙控器型號為 TOP-006", result["reply"])
        self.assertIn("雙模機且遙控器型號為 TOP-007", result["reply"])

    def test_bare_mosaic_reply_enters_rescan_without_repeating_screen_question(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_screen",
                "retry": 0,
            }
        }

        result = apply_troubleshooting_engine(
            "馬賽克",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_rescan_channels")
        self.assertIn("重新搜頻", result["reply"])
        self.assertNotIn("畫面目前是什麼狀況", result["reply"])

    def test_outdoor_loose_line_stops_repetitive_diagnosis_and_requests_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power",
            }
        }

        result = apply_troubleshooting_engine(
            "室外的電源線有鬆脫",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertIn("請勿自行碰觸", result["reply"])
        self.assertNotIn("電源燈", result["reply"])

    def test_partial_channel_issue_after_reboot_switches_to_rescan_not_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_reboot",
                "retry": 0,
                "issue_description": "電視黑畫面或沒有畫面",
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "還是有部份頻道看不到",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_rescan_channels")
        self.assertIn("重搜", result["reply"])

    def test_paper_bill_request_cancels_pending_sms_bill_tool(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived paper-bill rule unexpectedly invoked the model")

        memory = {
            "company_code": "tdtv",
            "known_info": {"name": "蘇碧珠"},
            "pending_tool": "send_message",
            "pending_tool_args": ["phone"],
        }

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="如果我要紙本帳單怎麼辦",
                memory=memory,
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(
            result["router"]["reason"],
            "active_flow_switch_paper_bill_request_rule",
        )
        self.assertIsNone(result["memory"]["pending_tool"])
        self.assertEqual(result["memory"]["pending_tool_args"], [])
        self.assertEqual(
            result["ai_response"],
            "您好，請問您需要紙本帳單是有特別需求嗎？若方便，建議先使用簡訊帳單或線上信用卡繳費，快速又便利，謝謝。",
        )

    def test_paper_bill_rule_requires_request_signal(self):
        self.assertTrue(is_paper_bill_request("如果我要紙本帳單怎麼辦"))
        self.assertTrue(is_paper_bill_request("紙本帳單可以補寄嗎"))

        self.assertFalse(is_paper_bill_request("紙本帳單需要由真人客服協助確認寄送或申請方式"))
        self.assertFalse(is_paper_bill_request("用戶編號可在紙本帳單、簡訊帳單或 APP 帳務資料中找到"))

    def test_paper_bill_rule_skips_image_ocr_and_barcode_context(self):
        self.assertFalse(
            is_paper_bill_request(
                "我上傳了一張圖片，辨識內容如下：\n"
                "紙本帳單需要由真人客服協助確認寄送或申請方式。"
            )
        )
        self.assertFalse(
            is_paper_bill_request(
                "這是一張紙本繳費單，上面有第一段條碼、第二段條碼、第三段條碼，想復線。"
            )
        )

    def test_legacy_payment_pending_requires_receipt_image(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {},
            "pending_tool": "payment_bill_batch",
            "pending_tool_args": ["receipt_image_evidence"],
            "pending_tool_missing_repeat_count": 1,
        }
        router = {
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test",
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="等我一下喔",
                memory=memory,
                history=[],
                llm=RunnableLambda(lambda _prompt: None),
                persist=False,
            )

        call_tool.assert_not_called()
        self.assertEqual(result["router"]["intent"], "other")
        self.assertEqual(result["memory"]["pending_tool_missing_repeat_count"], 0)
        self.assertIsNone(result["memory"]["pending_tool"])

    def test_payment_bill_pending_rejects_same_line_three_segment_barcodes(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {},
            "pending_tool": "payment_bill_batch",
            "pending_tool_args": ["receipt_image_evidence"],
        }
        router = {
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test",
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="第一段 150826TCN 第二段 0058072608022007 第三段 150841000000550",
                memory=memory,
                history=[],
                llm=RunnableLambda(lambda _prompt: None),
                persist=False,
            )

        call_tool.assert_not_called()
        self.assertEqual(result["router"]["intent"], "payment_receipt_image_required")
        self.assertNotIn("first_barcode", result["memory"]["known_info"])
        self.assertNotIn("second_barcode", result["memory"]["known_info"])
        self.assertNotIn("third_barcode", result["memory"]["known_info"])
        self.assertIsNone(result["memory"]["pending_tool"])
        self.assertEqual(result["memory"]["pending_tool_args"], [])

    def test_incomplete_receipt_image_requires_a_clear_reupload(self):
        router = {
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test",
        }
        user_text = (
            "我上傳了一張圖片，辨識內容如下：\n"
            "7-ELEVEN 代收收據\n"
            "第一段條碼：150826TCN"
        )

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text=user_text,
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(lambda _prompt: None),
                persist=False,
            )

        call_tool.assert_not_called()
        self.assertEqual(result["router"]["intent"], "payment_receipt_image_required")
        self.assertIn("重新上傳", result["ai_response"])
        self.assertIn("超商名稱", result["ai_response"])

    def test_payment_reconnection_calls_api_only_with_verified_image_evidence(self):
        user_text = (
            "我上傳了一張圖片，辨識內容如下：\n"
            "7-ELEVEN 代收收據 繳費完成\n"
            "第一段條碼：150826TCN\n"
            "第二段條碼：0058072608022007\n"
            "第三段條碼：150841000000550"
        )
        evidence = {
            "verified": True,
            "source": "verified_image_ocr",
            "message_hash": hashlib.sha256(user_text.encode("utf-8")).hexdigest(),
            "bills": [{
                "first_barcode": "150826TCN",
                "second_barcode": "0058072608022007",
                "third_barcode": "150841000000550",
            }],
        }
        router = {
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test",
        }

        def payment_api(tool_name, tool_memory):
            self.assertEqual(tool_name, "payment_bill_batch")
            self.assertEqual(
                tool_memory["known_info"]["active_receipt_image_evidence"], evidence,
            )
            return {"success": True, "message": "已完成復線"}

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch("app.handlers.chat_handler.call_tool", side_effect=payment_api),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text=user_text,
                memory={
                    "company_code": "tdtv",
                    "known_info": {"receipt_image_evidence": evidence},
                },
                history=[],
                llm=RunnableLambda(lambda _prompt: None),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "payment_receipt_reconnection")
        self.assertIn("已完成復線", result["ai_response"])
        self.assertNotIn(
            "active_receipt_image_evidence", result["memory"]["known_info"],
        )

    def test_tv_reactivation_already_temp_restored_result_is_remembered(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {"name": "王仁盛", "phone": "0981639099"},
            "pending_tool": "bill_return_line_tv",
            "pending_tool_args": [],
        }
        router = {
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test",
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            call_tool.return_value = {
                "success": True,
                "tool_name": "bill_return_line_tv",
                "message": "您已暫復過，無法重復暫復，請查閱帳單是否已繳費",
                "data": {"raw": {"code": "0099", "msg": "您已暫復過，無法重復暫復，請查閱帳單是否已繳費"}},
            }
            result = handle_chat_message(
                user_id="test-user",
                user_text="0981639099",
                memory=memory,
                history=[],
                llm=RunnableLambda(lambda _prompt: None),
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["tv_reactivation_status"], "already_temp_restored")
        self.assertIsNone(result["memory"]["pending_tool"])

    def test_tv_reactivation_already_temp_restored_followup_does_not_call_tool(self):
        result = detect_safe_direct_reply(
            "還是不可以看電視",
            {
                "known_info": {
                    "tv_reactivation_status": "already_temp_restored",
                },
            },
        )

        self.assertEqual(result["intent"], "tv_reactivation_already_temp_restored_followup")
        self.assertFalse(result["should_call_tool"])
        self.assertIn("無法重複暫復", result["reply"])
        self.assertIn("真人客服", result["reply"])

    def test_already_temp_restored_followup_blocks_bad_reconnection_tool_route(self):
        router_llm = llm_with_router_response({
            "route": "tool_action",
            "intent": "tv_reactivation_after_payment",
            "tool_name": "bill_return_line_tv",
            "topic": "電視復線",
            "should_cancel_current_flow": False,
            "should_call_tool": True,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "可以，我幫您再次送出電視復機申請。",
            "extracted_slots": {},
            "reason": "bad_already_restored_route",
        })

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="還是不可以看電視",
                memory={
                    "company_code": "tdtv",
                    "known_info": {
                        "tv_reactivation_status": "already_temp_restored",
                        "tv_reactivation_message": "您已暫復過，無法重復暫復，請查閱帳單是否已繳費",
                    },
                },
                history=[],
                llm=router_llm,
                persist=False,
            )

        call_tool.assert_not_called()
        self.assertEqual(result["router"]["intent"], "tv_reactivation_already_temp_restored_followup")
        self.assertFalse(result["router"]["should_call_tool"])
        self.assertIsNone(result["memory"].get("pending_tool"))
        self.assertIn("無法重複暫復", result["ai_response"])
        self.assertIn("真人客服", result["ai_response"])

    def test_sms_bill_redirect_phone_request_does_not_send_message(self):
        def fail_if_called(_prompt):
            raise AssertionError("Registered phone guard should not need LLM")

        memory = {
            "company_code": "tdtv",
            "known_info": {"name": "梁仁澤"},
            "pending_tool": "send_message",
            "pending_tool_args": ["phone"],
        }

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="梁仁澤電話0952959768帳單訊息改傳到0983641649",
                memory=memory,
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "sms_bill_registered_phone_policy")
        self.assertFalse(result["router"]["should_call_tool"])
        self.assertIsNone(result["memory"]["last_tool_result"])
        self.assertIsNone(result["memory"]["pending_tool"])
        self.assertEqual(result["memory"]["pending_tool_args"], [])
        self.assertIn("帳務系統登記的電話", result["ai_response"])
        self.assertIn("無法改寄", result["ai_response"])

    def test_switching_from_tv_troubleshooting_to_remote_control_starts_remote_check(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_input_source",
                "issue_description": "電視畫面顯示無訊號",
                "retry": 0,
            },
            "pending_tool": None,
            "pending_tool_args": [],
        }
        llm = llm_with_router_response({
            "route": "direct_reply",
            "intent": "remote_control_no_response",
            "tool_name": None,
            "topic": "remote_control",
            "should_cancel_current_flow": True,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "請先確認遙控器電池是否有電，並對準機上盒感應位置。",
            "extracted_slots": {},
            "reason": "remote_control_switch",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="請問遙控器無反應?",
                memory=memory,
                history=[],
                llm=llm,
                persist=False,
            )

        known = result["memory"]["known_info"]
        self.assertEqual(known["troubleshooting_started"], "yes")
        self.assertEqual(known["troubleshooting_type"], "remote")
        self.assertEqual(known["troubleshooting_step"], "remote_check_light")
        self.assertIn("遙控器", result["ai_response"])
        self.assertIn("紅燈", result["ai_response"])

    def test_remote_control_issue_during_tv_screen_check_asks_remote_check(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_screen",
                "issue_description": "機上盒故障",
                "retry": 0,
            },
            "pending_tool": None,
            "pending_tool_args": [],
        }
        router_llm = llm_with_router_response({
            "route": "continue_current_flow",
            "intent": "troubleshooting",
            "tool_name": None,
            "topic": "故障排除",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "state_machine_first",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="有畫面 遙控器控制異常",
                memory=memory,
                history=[],
                llm=router_llm,
                persist=False,
            )

        known = result["memory"]["known_info"]
        self.assertEqual(known["troubleshooting_type"], "remote")
        self.assertEqual(known["troubleshooting_step"], "remote_check_light")
        self.assertIn("遙控器", result["ai_response"])
        self.assertIn("紅燈", result["ai_response"])
        self.assertNotIn("無訊號", result["ai_response"])
        self.assertNotIn("錯誤代碼", result["ai_response"])

    def test_network_still_cannot_connect_after_reboot_switches_to_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "還是不能上網",
            memory,
            plan,
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")
        self.assertNotIn("已恢復正常", result["reply"])

    def test_network_can_connect_after_reboot_finishes_troubleshooting(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "可以上網了",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "no")
        self.assertIn("已恢復正常", result["reply"])

    def test_low_download_speed_after_reboot_never_finishes_as_recovered(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "download_speed": 270.0,
                "retry": 0,
            }
        }
        plan = {"reply": "", "should_call_tool": False, "tool_name": None}

        result = apply_troubleshooting_engine(
            "重新開完，下載4Mbps，上傳36Mbps",
            memory,
            plan,
            llm=RunnableLambda(lambda _: Response('{"label":"recovered"}')),
        )

        known = memory["known_info"]
        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertEqual(known["previous_download_speed"], 270.0)
        self.assertEqual(known["download_speed"], 4.0)
        self.assertEqual(known["upload_speed"], 36.0)
        self.assertNotIn("已恢復正常", result["reply"])

    def test_disabled_repair_reply_explains_low_speed_is_not_recovered(self):
        reply = build_repair_ticket_flow_disabled_reply({
            "company_code": "tdtv",
            "known_info": {"download_speed": 4.0},
        })

        self.assertIn("下載速度僅 4 Mbps", reply)
        self.assertIn("尚未恢復正常", reply)
        self.assertIn("［維修申告🔗］http", reply)
        self.assertIn("password=\n送出需求", reply)

    def test_unknown_scope_moves_to_modem_light_check(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_check_scope",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "我不知道",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_check_modem_light")
        self.assertIn("數據機", result["reply"])

    def test_llm_device_replacement_followup_guides_registration(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_check_scope",
                "issue_description": "換新 wifi 機結果沒網路",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }
        llm = llm_with_router_response({"label": "device_replacement"})

        result = apply_troubleshooting_engine(
            "我換舊的那台是正常",
            memory,
            plan,
            llm=llm,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_device_registration")
        self.assertIn("電腦網卡更換註冊", result["reply"])
        self.assertNotIn("所有設備都不能上網", result["reply"])

    def test_llm_partial_channel_route_keeps_semantic_decision_in_tv_flow(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "tv_partial_channel_issue",
            "tool_name": None,
            "topic": "電視部分頻道異常",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_tv_partial_channel_issue",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="哈tv頻道不見",
                memory={"company_code": "cnt", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "tv_rescan_channels")
        self.assertIn("恢復原廠預設或重新搜頻", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_llm_slow_network_route_keeps_semantic_decision_in_network_flow(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "internet_slow_buffering",
            "tool_name": None,
            "topic": "網路速度異常",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_internet_slow_buffering",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網速降了一半，晚上速度更慢",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_slow_scope")
        self.assertIn("www.speedtest.net", result["ai_response"])
        self.assertIn("不透過 Wi-Fi", result["ai_response"])
        self.assertNotIn("所有設備都不能上網", result["ai_response"])

    def test_llm_network_connection_route_keeps_semantic_decision_in_network_flow(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "internet_connection_issue",
            "tool_name": None,
            "topic": "網路故障",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_internet_connection_issue",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="家中無網路",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_check_scope")
        self.assertIn("數據機與分享器", result["ai_response"])

    def test_llm_new_device_registration_route_guides_registration(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "new_device_registration_issue",
            "tool_name": None,
            "topic": "更換分享器後無法上網",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_new_device_registration_issue",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="新增分享器無法連接上網",
                memory={"company_code": "wctv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "net_device_registration")
        self.assertIn("電腦網卡更換註冊", result["ai_response"])

    def test_llm_remote_control_route_starts_remote_troubleshooting(self):
        router_llm = llm_with_router_response({
            "route": "troubleshooting",
            "intent": "remote_control_issue",
            "tool_name": None,
            "topic": "遙控器故障",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "llm_remote_control_issue",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="故障",
                memory={"company_code": "wctv", "known_info": {}},
                history=[{"role": "user", "content": "搖控器無法使用"}],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "remote")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], "remote_check_light")
        self.assertIn("按鍵時是否有亮紅燈", result["ai_response"])
        self.assertNotIn("一般型 300 元、語音型 400 元", result["ai_response"])

    def test_game_disconnect_during_scope_moves_to_specific_check_not_scope_loop(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_check_scope",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "能上網可是玩遊戲會玩到一半網路會不穩直接斷線",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_slow_specific")
        self.assertIn("其他網站或 APP", result["reply"])
        self.assertNotIn("所有設備都不能上網，還是只有", result["reply"])

    def test_multi_device_unstable_during_specific_check_moves_to_modem_check(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_slow_specific",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "手機玩遊戲會不穩，電腦插網路線也一樣不穩",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["affected_scope"], "multiple_devices")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_check_modem_light")
        self.assertIn("手機與電腦都出現網路不穩", result["reply"])

    def test_network_unstable_opening_does_not_overstate_issue_type(self):
        result = apply_troubleshooting_engine(
            "現在網路斷線，是哪裡的問題？",
            {"known_info": {}},
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertIn("請問是所有網站、APP 都會不穩或斷線", result["reply"])
        self.assertNotIn("不是完全不能上網", result["reply"])

    def test_multi_device_unstable_escapes_single_device_loop(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_single_device",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "手機Wi-Fi重開一樣，電腦是插網路線也不穩",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_check_modem_light")
        self.assertIn("數據機", result["reply"])
        self.assertNotIn("該設備是否已可以上網", result["reply"])

    def test_unstable_game_multi_device_dialog_does_not_loop(self):
        memory = {"known_info": {}}
        turns = [
            "網路不穩",
            "能上網可是玩遊戲會玩到一半網路會不穩直接斷線",
            "能上網 手機跟電腦都能上網 只是不穩定",
            "手機Wi-Fi重開一樣 電腦是插網路線的",
            "能上網只是手機打遊戲會顯示網路不穩定 電腦插網路線也一樣顯示不穩定",
            "沒恢復",
        ]

        result = {}
        replies = []
        for text in turns:
            result = apply_troubleshooting_engine(
                text,
                memory,
                {"reply": "", "should_call_tool": False, "tool_name": None},
            )
            replies.append(result.get("reply", ""))

        joined_replies = "\n".join(replies)
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertNotIn("所有設備都不能上網，還是只有", joined_replies)
        self.assertNotIn("其他手機或電腦是否可以正常上網", joined_replies)
        self.assertNotIn("該設備是否已可以上網", joined_replies)

    def test_unknown_modem_light_moves_to_reboot(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_check_modem_light",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "我就不知道",
            memory,
            plan,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_reboot_modem")
        self.assertIn("數據機電源拔掉", result["reply"])

    def test_unknown_after_modem_reboot_switches_to_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "retry": 0,
            }
        }
        plan = {
            "reply": "",
            "should_call_tool": False,
            "tool_name": None,
        }

        result = apply_troubleshooting_engine(
            "不知道",
            memory,
            plan,
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")

    def test_persistent_multi_device_instability_switches_to_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "troubleshooting_failed": "no",
                "repair_ready": "no",
                "retry": 0,
                "issue_description": "舊款 SB6141，網路不穩超過半年且機器容易發熱",
            }
        }

        result = apply_troubleshooting_engine(
            "兩邊都不穩",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")

    def test_abnormal_modem_light_after_reboot_switches_to_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "troubleshooting_failed": "no",
                "repair_ready": "no",
                "retry": 0,
            }
        }

        result = apply_troubleshooting_engine(
            "紅燈有亮，一直閃",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")

    def test_new_network_install_uses_model_selected_plan_query(self):
        docs = [{
            "id": "promo-install",
            "question": "飆網守護家_B2606",
            "answer": (
                "方案名稱：飆網守護家 B2606（網路贈清冰組方案）。"
                "提供 100M/10M、300M/300M 與 500M/500M 方案，免裝機費。"
                "300M/300M：半年繳 3,594 元；500M/500M：半年繳 4,194 元。"
                "清冰組為申裝純網方案客戶額外贈送的電視頻道。"
            ),
            "company": "大屯",
            "category": "billing",
            "document_type": "promotion_campaign",
            "record_type": "campaign_summary",
            "campaign_name": "飆網守護家 B2606",
            "source": {
                "title": "飆網守護家_B2606",
                "document_type": "promotion_campaign",
                "record_type": "campaign_summary",
                "content": (
                    "方案名稱：飆網守護家 B2606（網路贈清冰組方案）。"
                    "提供 100M/10M、300M/300M 與 500M/500M 方案，免裝機費。"
                    "300M/300M：半年繳 3,594 元；500M/500M：半年繳 4,194 元。"
                    "清冰組為申裝純網方案客戶額外贈送的電視頻道。"
                ),
            },
            "_score": 0.9,
        }]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我想安裝網路",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm_with_router_response({
                    "route": "knowledge_query",
                    "intent": "internet_install_application_guidance",
                    "topic": "寬頻網路新申辦",
                    "service_scope": "寬頻網路",
                    "requested_information": "裝機申請與方案",
                    "knowledge_query": "寬頻網路 裝機申請 方案 費用",
                    "reply": "",
                    "should_call_tool": False,
                    "should_retrieve_knowledge": True,
                    "extracted_slots": {},
                    "reason": "model_install_application",
                }),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertTrue(result["router"]["should_retrieve_knowledge"])
        self.assertIn("300M", result["ai_response"])
        self.assertIn("500M", result["ai_response"])
        self.assertNotIn("清冰組", result["ai_response"])
        self.assertNotIn("抽獎", result["ai_response"])

    def test_network_install_application_quotes_before_handoff_when_summary_is_empty_json(self):
        docs = [{
            "id": "pure-network-install",
            "question": "一般寬頻方案：哈 NET1",
            "answer": (
                "方案名稱：哈 NET1。\n"
                "A.60M/6M：月繳 $500 元，季繳 $1,500 元，半年繳 $3,000 元。\n"
                "B.120M/10M：月繳 $600 元，季繳 $1,800 元，半年繳 $3,600 元。\n"
                "裝機費：$500 元；寬頻設備押金：$500 元。"
            ),
            "company": "大屯",
            "category": "billing",
            "document_type": "promotion_campaign",
            "record_type": "campaign_summary",
            "campaign_name": "哈 NET1",
            "service_types": "純網寬頻",
            "_score": 0.92,
        }]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路裝機申請",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[{"role": "assistant", "content": "您好，我是台數科哈寶寶。"}],
                llm=llm_with_router_response({
                    "route": "knowledge_query",
                    "intent": "internet_install_application_guidance",
                    "topic": "寬頻網路新申辦",
                    "service_scope": "寬頻網路",
                    "requested_information": "裝機申請與方案",
                    "knowledge_query": "寬頻網路 裝機申請 方案 費用",
                    "reply": "",
                    "should_call_tool": False,
                    "should_retrieve_knowledge": True,
                    "extracted_slots": {},
                    "reason": "model_install_application",
                }),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertEqual(result["router"]["intent"], "pure_network_install_plan_query")
        self.assertIn("哈 NET1", result["ai_response"])
        self.assertIn("60M/6M", result["ai_response"])
        self.assertIn("月繳 500 元", result["ai_response"])
        self.assertNotIn("{}", result["ai_response"])
        self.assertNotIn("裝機費", result["ai_response"])

    def test_combo_install_full_chat_corrects_model_and_skips_long_summary(self):
        docs = [{
            "id": "combo-install",
            "question": "測試同裝方案",
            "answer": (
                "方案名稱：測試同裝方案。\n"
                "100M/10M、300M/300M 可申辦。\n"
                "裝機費、設備押金、WiFi 設備、機上盒、賠償與其他完整條款。"
            ),
            "document_type": "promotion_campaign",
            "record_type": "campaign_summary",
            "campaign_name": "測試同裝方案",
            "service_types": "電視網路同裝",
            "speeds": "100M/10M | 300M/300M",
            "valid_period": "2026/09/01~2026/09/30",
            "_score": 0.95,
        }]

        class Response:
            content = json.dumps({
                "route": "knowledge_query",
                "intent": "internet_install_application_guidance",
                "tool_name": None,
                "topic": "寬頻網路新申辦",
                "service_scope": "寬頻網路",
                "requested_information": "裝機申請與方案",
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

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="有線電視+網路裝機申請",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fake_llm),
                persist=False,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(result["router"]["intent"], "tv_network_install_plan_query")
        self.assertTrue(result["ai_response"].startswith("目前可參考的電視＋網路同裝方案："))
        self.assertIn("1. 測試同裝方案", result["ai_response"])
        self.assertIn("速率：100M/10M、300M/300M", result["ai_response"])
        self.assertNotIn("歡迎申請網路裝機", result["ai_response"])
        self.assertNotIn("WiFi 設備", result["ai_response"])

    def test_new_network_one_year_contract_uses_approved_concise_reply(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived one-year contract rule unexpectedly invoked the model")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路新裝機，有只綁一年約的方案嗎",
                memory={"company_code": "wctv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "new_network_one_year_contract")
        self.assertIn("主推 24 個月優惠方案", result["ai_response"])
        self.assertNotIn("年繳 $", result["ai_response"])
        self.assertNotIn("地址", result["ai_response"])

    def test_basic_tv_monthly_fee_reply_is_concise_and_prefers_new_install_offer(self):
        docs = [{
            "question": "台灣佳光 TV 基本收費標準",
            "answer": (
                "CATV 基本收視費月繳原價 $600 元。"
                "TV 新裝機優惠：月繳 $550 元；優惠到期恢復原價 $600 元。"
                "裝機費 $1,500 元。"
            ),
        }]

        reply = apply_customer_reply_policies(
            "第四台月租費多少？",
            "基本收視費月繳原價 $600 元，另有新裝優惠與裝機費。",
            docs,
        )

        self.assertEqual(reply, "有線電視基本收視費：月繳 $550 元。")

    def test_multiple_plan_reply_uses_numbered_sections_and_blank_line(self):
        reply = apply_customer_reply_policies(
            "我要辦500M網路，費用是多少？",
            (
                "【方案名稱】\n飆網守護家 B2606\n【月租/速率】\n500M 年繳 $8,388\n"
                "【方案名稱】\n好視成雙 NO8\n【月租/速率】\n500M 月繳 $999"
            ),
            [],
        )

        self.assertIn("【方案 1】", reply)
        self.assertIn("\n\n【方案 2】", reply)

    def test_multiple_plan_reply_does_not_duplicate_existing_numbered_headings(self):
        reply = apply_customer_reply_policies(
            "有第四台加網路的優惠方案嗎？",
            (
                "【方案 1】\n【方案名稱】\n好視成雙 NO8\n"
                "【方案 2】\n【方案名稱】\n好視成雙 NO7"
            ),
            [],
        )

        self.assertEqual(reply.count("【方案 1】"), 1)
        self.assertEqual(reply.count("【方案 2】"), 1)
        self.assertNotIn("【方案名稱】", reply)

    def test_combo_tv_network_query_uses_generic_campaign_terms(self):
        class Response:
            content = json.dumps({
                "route": "knowledge_query",
                "intent": "tv_network_install_plan_query",
                "tool_name": None,
                "topic": "電視+網路方案",
                "should_cancel_current_flow": True,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "電視+網路同裝 優惠方案",
                "reply": "",
                "extracted_slots": {},
                "reason": "llm_combo_promotion_scope",
            }, ensure_ascii=False)

        calls = {"count": 0}

        def fake_llm(_prompt):
            calls["count"] += 1
            return Response()

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="請問電視跟網路一起裝. 有什麼優惠的方案嗎？",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fake_llm),
                persist=False,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertTrue(result["router"]["should_retrieve_knowledge"])
        self.assertNotIn("好視成雙", result["router"]["knowledge_query"])
        self.assertIn("電視+網路同裝", result["router"]["knowledge_query"])

    def test_tv_blurry_gets_channel_and_reboot_guidance(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived blurry-TV rule unexpectedly invoked the model")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="看電視很不清",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertIn("第幾台", result["ai_response"])
        self.assertIn("重新插上", result["ai_response"])

    def test_tv_lag_gets_reboot_guidance(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived TV-lag rule unexpectedly invoked the model")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="有畫面但是會lag",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertIn("機上盒電源", result["ai_response"])

    def test_wifi_router_sale_does_not_start_troubleshooting(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived router-sale rule unexpectedly invoked the model")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="請問公司有在賣ＷＩＦＩ分享器ㄇ",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertIn("租借", result["ai_response"])
        self.assertIn("Mesh WiFi-6", result["ai_response"])

    def test_wifi5_yearly_price_followup_retrieves_addon_knowledge(self):
        docs = [{
            "id": "wifi5-product",
            "question": "WiFi 5 系列分享器費用",
            "answer": "WiFi 5 系列分享器月均價 25 元，半年繳 150 元，年繳 300 元。",
            "company": "通用-中區",
            "category": "network_support",
            "record_type": "product_catalog",
            "product_name": "WiFi 5 系列分享器",
            "product_aliases": "WiFi 5 | Mesh WiFi 5 | 分享器",
            "_score": 0.95,
        }]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs) as retrieve_knowledge,
            patch(
                "app.handlers.chat_handler.compose_knowledge_reply",
                return_value="WiFi 5 系列分享器年繳 300 元。",
            ),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="WiFi 5 分享器一年多少錢？",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[
                    {"role": "user", "content": "WiFi 加值服務有哪些？"},
                    {
                        "role": "assistant",
                        "content": "WiFi 5 系列分享器月均價 25 元，半年繳 150 元，年繳 300 元。",
                    },
                ],
                llm=llm_with_router_response({
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
                }),
                persist=False,
            )

        retrieve_knowledge.assert_called_once()
        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertEqual(result["router"]["intent"], "value_added_product_query")
        self.assertIn("年繳 300 元", result["ai_response"])
        self.assertNotEqual(result["router"]["route"], "troubleshooting")

    def test_remote_power_learning_gets_learning_steps(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived remote-learning rule unexpectedly invoked the model")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="雙模機遙控器如何拷貝電源",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertIn("紅外線", result["ai_response"])
        self.assertIn("電源鍵", result["ai_response"])

    def test_lost_bill_gives_payment_methods_not_sms_tool(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived lost-bill rule unexpectedly invoked the model")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="我帳單不見了 如何繳費",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertIsNone(result["router"]["tool_name"])
        self.assertIn("7-11 ibon", result["ai_response"])

    def test_payment_method_query_does_not_use_rag_installment_docs(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived payment-method rule unexpectedly invoked the model")

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge") as retrieve_knowledge,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="要怎麼付款呢?",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        retrieve_knowledge.assert_not_called()
        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertIn("線上繳費", result["ai_response"])
        self.assertIn("臨櫃繳費", result["ai_response"])
        self.assertIn("APP 繳費", result["ai_response"])
        self.assertNotIn("月繳、半年繳、年繳", result["ai_response"])

    def test_app_and_line_pay_payment_terms_use_payment_method_flow(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived App/Line Pay rule unexpectedly invoked the model")

        history = [
            {"role": "user", "content": "繳費後何時才能觀看"},
            {
                "role": "assistant",
                "content": "繳費後需等帳務入帳及設備授權更新，才會恢復收視。",
            },
            {"role": "user", "content": "Line pay 繳費"},
            {"role": "assistant", "content": "目前可用繳費方式：..."},
            {"role": "user", "content": "不是 是繳費方式"},
            {"role": "assistant", "content": "目前可用繳費方式：..."},
        ]

        for user_text in ["Line pay 繳費", "App繳費"]:
            with self.subTest(user_text=user_text):
                with (
                    patch("app.handlers.chat_handler.log_chat_latency"),
                    patch("app.handlers.chat_handler.retrieve_knowledge") as retrieve_knowledge,
                ):
                    result = handle_chat_message(
                        user_id="test-user",
                        user_text=user_text,
                        memory={"company_code": "wctv", "known_info": {}},
                        history=history,
                        llm=RunnableLambda(fail_if_called),
                        persist=False,
                    )

                retrieve_knowledge.assert_not_called()
                self.assertEqual(result["router"]["route"], "direct_reply")
                self.assertEqual(result["router"]["intent"], "bill_payment_methods")
                self.assertIn("APP 繳費", result["ai_response"])
                self.assertIn("線上繳費", result["ai_response"])
                self.assertNotIn("LINE TV", result["ai_response"])
                self.assertNotIn("哈point", result["ai_response"])
                self.assertNotIn("查不到明確的 App 繳費方式", result["ai_response"])

    def test_hatv_addon_query_retrieves_knowledge(self):
        docs = [{
            "id": "hatv-addon",
            "question": "哈TV數位套餐加購",
            "answer": "哈TV 數位套餐可依方案加購，實際費用與申辦方式需依公告與客服確認。",
            "company": "大屯",
            "category": "billing",
            "_score": 0.9,
        }]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs) as retrieve_knowledge,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="哈tv數位套餐加購",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm_with_router_response({
                    "route": "knowledge_query",
                    "intent": "hatv_addon_knowledge",
                    "topic": "哈TV 數位套餐加購",
                    "should_retrieve_knowledge": True,
                    "knowledge_query": "哈TV 數位套餐 加購 費用 內容 申請方式",
                }),
                persist=False,
            )

        retrieve_knowledge.assert_called_once()
        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertEqual(result["router"]["intent"], "hatv_addon_knowledge")
        self.assertIn("哈TV 數位套餐", result["ai_response"])
        self.assertNotIn("線上服務暫停", result["ai_response"])

    def test_value_added_package_followup_stays_in_rag_context(self):
        docs = [{
            "id": "value-added-sales",
            "question": "各項單品銷售(數位電視)",
            "answer": "數位電視套餐（月繳）：HBO加價購$39、運動套餐B$49、Hi Play/松視全餐$120。",
            "company": "大屯",
            "category": "billing",
            "_score": 0.9,
        }]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", return_value=docs) as retrieve_knowledge,
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="加值數位套餐內容有哪些",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "last_knowledge_results": [
                        {
                            "question": "各項單品銷售(數位電視)",
                            "answer": "各項單品銷售／加值服務-數位電視套餐：HBO加價購、運動套餐、Hi Play。",
                        }
                    ],
                },
                history=[
                    {"role": "user", "content": "更多熱門單品銷售"},
                    {"role": "assistant", "content": "方案名稱：各項單品銷售／加值服務"},
                ],
                llm=llm_with_router_response({
                    "route": "knowledge_query",
                    "intent": "value_added_service_query",
                    "topic": "加值服務",
                    "should_retrieve_knowledge": True,
                    "knowledge_query": "加值數位套餐內容 數位電視套餐 單品銷售",
                }),
                persist=False,
            )

        retrieve_knowledge.assert_called_once()
        self.assertEqual(result["router"]["route"], "knowledge_query")
        self.assertEqual(result["router"]["intent"], "value_added_service_query")
        self.assertNotEqual(result["router"].get("tool_name"), "search_contract_info")
        self.assertIn("數位電視套餐", result["ai_response"])

    def test_pending_contract_lookup_requires_authenticated_web_customer_number(self):
        def fail_if_called(_prompt):
            raise AssertionError("pending contract state unexpectedly invoked the model")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="王大明 0988555666",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_contract_info",
                    "pending_tool_args": ["name", "phone"],
                },
                history=[],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertIsNone(result["memory"].get("pending_tool"))
        self.assertNotIn("裝機地址", result["ai_response"])
        self.assertEqual(
            result["ai_response"],
            "為保障您的個人資料安全，個人帳務及方案等資訊需登入會員後才能查詢，"
            "您可以至官網或行動客服 APP 登入後查看相關資料。",
        )

    def test_troubleshooting_dialog_stress_cases_do_not_loop(self):
        cases = [
            {
                "name": "network_unknown_then_generic_failure_moves_to_reboot",
                "turns": ["網路不能用", "不知道", "就是不能用"],
                "final_step": "net_reboot_modem",
                "final_contains": "數據機電源拔掉",
            },
            {
                "name": "computer_only_network_issue_does_not_return_to_all_device_prompt",
                "turns": ["網路有問題", "手機能上網，電腦不能", "電腦插網路線也不行"],
                "final_not_contains": "所有設備都不能上網",
            },
            {
                "name": "unstable_game_disconnect_keeps_unstable_context",
                "turns": ["網路不穩", "手機遊戲會斷線，電腦正常", "不是不能上網，是會突然斷"],
                "final_not_contains": "所有設備都不能上網",
            },
            {
                "name": "light_status_given_during_scope_moves_forward",
                "turns": ["網路斷了", "有亮燈", "我不知道哪個燈"],
                "final_step": "net_reboot_modem",
                "final_contains": "數據機",
            },
            {
                "name": "already_rebooted_network_failure_escalates",
                "turns": ["不能上網", "剛剛重開過了", "還是不行"],
                "final_tool": "create_repair_ticket",
            },
            {
                "name": "tv_audio_no_picture_then_reboot_failed_escalates",
                "turns": ["電視沒畫面", "有聲音沒畫面", "重開也一樣"],
                "final_tool": "create_repair_ticket",
            },
            {
                "name": "no_signal_user_cannot_change_input_gets_step_by_step_help",
                "turns": ["電視不能看", "顯示無訊號", "我不會調輸入源"],
                "final_step": "tv_check_input_source",
                "final_contains": "一步一步",
            },
            {
                "name": "set_top_box_no_error_code_black_screen_moves_to_reboot",
                "turns": ["機上盒不能用", "沒有錯誤代碼", "只有黑畫面"],
                "final_step": "tv_reboot",
                "final_contains": "機上盒電源拔掉",
            },
            {
                "name": "network_user_cannot_check_moves_to_basic_step",
                "turns": ["網路壞了", "應該吧", "你幫我看"],
                "final_step": "net_reboot_modem",
                "final_contains": "數據機",
            },
            {
                "name": "generic_tv_failure_unknown_moves_to_reboot",
                "turns": ["不能看", "都不行", "我也不知道"],
                "final_step": "tv_reboot",
                "final_contains": "機上盒電源拔掉",
            },
            {
                "name": "repeated_rejection_resets_fault_category",
                "turns": ["網路不能用", "不是", "不是啦"],
                "final_step": "ask_fault_category",
                "final_contains": "重新確認",
            },
            {
                "name": "user_stops_then_requests_repair_escalates",
                "turns": ["網路怪怪的", "算了", "還是幫我報修"],
                "final_tool": "create_repair_ticket",
            },
            {
                "name": "all_tried_network_failure_escalates_without_repeating",
                "turns": ["不能上網", "都試過了", "還是不行", "都試過了"],
                "final_tool": "create_repair_ticket",
            },
            {
                "name": "repeated_unknown_network_answers_escalate",
                "turns": ["網路不穩", "不知道", "不知道", "不知道"],
                "final_tool": "create_repair_ticket",
            },
            {
                "name": "direct_repair_interrupts_tv_no_signal_flow",
                "turns": ["故障無信號", "回報故障", "我要報修"],
                "final_tool": "create_repair_ticket",
            },
        ]

        for case in cases:
            with self.subTest(case["name"]):
                memory = {"known_info": {}}
                replies = []
                result = {}
                for text in case["turns"]:
                    result = apply_troubleshooting_engine(
                        text,
                        memory,
                        {"reply": "", "should_call_tool": False, "tool_name": None},
                    )
                    reply = result.get("reply") or ""
                    if replies and reply:
                        self.assertNotEqual(reply, replies[-1])
                    replies.append(reply)

                known = memory["known_info"]
                if "final_step" in case:
                    self.assertEqual(known.get("troubleshooting_step"), case["final_step"], case["name"])
                if "final_tool" in case:
                    self.assertEqual(result.get("tool_name"), case["final_tool"], case["name"])
                if "final_contains" in case:
                    self.assertIn(case["final_contains"], result.get("reply", ""), case["name"])
                if "final_not_contains" in case:
                    self.assertNotIn(case["final_not_contains"], result.get("reply", ""), case["name"])

    def test_tv_power_still_off_after_cable_check_escalates_without_reasking(self):
        def classify_step(prompt):
            text = str(prompt)
            if "tv_check_power_cable" in text:
                return Response('{"label": "failed"}')
            if "tv_check_power" in text:
                return Response('{"label": "negative"}')
            return Response('{"label": "unknown"}')

        step_llm = RunnableLambda(classify_step)

        for final_reply in ["還是沒有", "還是一樣"]:
            with self.subTest(final_reply):
                memory = {"known_info": {}}
                result = {}
                for text in ["電視不能看", "沒有", final_reply]:
                    result = apply_troubleshooting_engine(
                        text,
                        memory,
                        {"reply": "", "should_call_tool": False, "tool_name": None},
                        llm=step_llm,
                    )

                self.assertTrue(result["should_call_tool"])
                self.assertEqual(result["tool_name"], "create_repair_ticket")
                self.assertNotIn("確認電源線與插座後", result["reply"])
                self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")

    def test_tv_power_followup_keeps_chat_context_and_escalates(self):
        def llm_route_or_classify(prompt):
            text = str(prompt)
            if "目前步驟代碼" in text:
                if "tv_check_power_cable" in text:
                    return Response('{"label": "failed"}')
                if "tv_check_power" in text and "使用者回覆：沒有" in text:
                    return Response('{"label": "negative"}')
                return Response('{"label": "unknown"}')

            if "電視不能看" in text:
                return Response(json.dumps({
                    "route": "troubleshooting",
                    "intent": "troubleshooting",
                    "tool_name": None,
                    "topic": "電視故障",
                    "should_cancel_current_flow": False,
                    "should_call_tool": False,
                    "should_retrieve_knowledge": False,
                    "knowledge_query": None,
                    "reply": "",
                    "extracted_slots": {},
                    "reason": "test_tv_fault",
                }, ensure_ascii=False))

            return Response(json.dumps({
                "route": "clarify",
                "intent": "ambiguous_short_query",
                "tool_name": None,
                "topic": "不明問題",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
                "extracted_slots": {},
                "reason": "bad_router_clarify",
            }, ensure_ascii=False))

        llm = RunnableLambda(llm_route_or_classify)
        memory = {"company_code": "tdtv", "known_info": {}}
        history = []
        result = None

        with patch("app.handlers.chat_handler.log_chat_latency"):
            for text in [
                "電視不能看",
                "我不知道捏 我有重拔插頭 還是一樣 燈怪怪的",
                "沒有",
                "就是沒有啊!",
            ]:
                result = handle_chat_message(
                    user_id="test-user",
                    user_text=text,
                    memory=memory,
                    history=history,
                    llm=llm,
                    persist=False,
                )
                memory = result["memory"]
                history.extend([
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": result["ai_response"]},
                ])

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(result["plan"]["tool_name"], "create_repair_ticket")
        self.assertNotIn("請問您想查詢資料", result["ai_response"])
        self.assertEqual(memory["known_info"]["troubleshooting_failed"], "yes")

    def test_tv_power_followup_recovers_troubleshooting_state_from_history(self):
        def classify_step(prompt):
            text = str(prompt)
            if "目前步驟代碼" in text and "tv_check_power_cable" in text:
                return Response('{"label": "failed"}')
            return Response(json.dumps({
                "route": "clarify",
                "intent": "ambiguous_short_query",
                "tool_name": None,
                "topic": "不明問題",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
                "extracted_slots": {},
                "reason": "bad_router_clarify",
            }, ensure_ascii=False))

        history = [
            {"role": "user", "content": "沒有"},
            {
                "role": "assistant",
                "content": "請先確認機上盒電源線是否插好，插座是否有電。確認後請告訴我電源燈是否有亮。",
            },
        ]

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="就是沒有啊!",
                memory={"company_code": "tdtv", "known_info": {}},
                history=history,
                llm=RunnableLambda(classify_step),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(result["plan"]["tool_name"], "create_repair_ticket")
        self.assertNotIn("請問您想查詢資料", result["ai_response"])
        self.assertEqual(
            result["memory"]["known_info"]["_troubleshooting_restored_from_history"],
            "yes",
        )

    def test_cable_tv_disconnection_enters_tv_troubleshooting(self):
        router_llm = llm_with_router_response({
            "route": "direct_reply",
            "intent": "ambiguous_service_type",
            "tool_name": None,
            "topic": "不明問題",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
            "extracted_slots": {},
            "reason": "bad_llm_direct_reply",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="有線電視一直斷訊",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "tv")
        self.assertIn("有線電視收訊", result["ai_response"])
        self.assertNotIn("網路連線不穩", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_network_repair_request_recovers_fault_type_from_user_history(self):
        def llm_route_or_classify(prompt):
            text = str(prompt)
            if "目前步驟代碼" in text:
                return Response('{"label": "unknown"}')
            return Response(json.dumps({
                "route": "clarify",
                "intent": "ambiguous_short_query",
                "tool_name": None,
                "topic": "不明問題",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
                "extracted_slots": {},
                "reason": "bad_router_clarify",
            }, ensure_ascii=False))

        history = [
            {"role": "user", "content": "又無法連上網路"},
            {"role": "assistant", "content": "請問您想查詢資料、辦理服務，還是回報故障呢？"},
        ]

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="報故障",
                memory={"company_code": "wctv", "known_info": {}},
                history=history,
                llm=RunnableLambda(llm_route_or_classify),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertEqual(result["memory"]["known_info"]["_troubleshooting_restored_source"], "user_history")
        self.assertEqual(result["plan"]["tool_name"], "create_repair_ticket")
        self.assertNotIn("請問您要回報的是電視、網路", result["ai_response"])

    def test_online_troubleshooting_followup_recovers_network_context(self):
        def llm_route_or_classify(prompt):
            text = str(prompt)
            if "目前步驟代碼" in text:
                return Response('{"label": "unknown"}')
            return Response(json.dumps({
                "route": "clarify",
                "intent": "ambiguous_short_query",
                "tool_name": None,
                "topic": "不明問題",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
                "extracted_slots": {},
                "reason": "bad_router_clarify",
            }, ensure_ascii=False))

        history = [
            {"role": "user", "content": "又無法連上網路"},
            {"role": "assistant", "content": "請問您想查詢資料、辦理服務，還是回報故障呢？"},
        ]

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="可以線上教我怎麼排除嗎",
                memory={"company_code": "wctv", "known_info": {}},
                history=history,
                llm=RunnableLambda(llm_route_or_classify),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertIn("數據機", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_recent_slow_followup_recovers_network_context(self):
        def llm_route_or_classify(prompt):
            text = str(prompt)
            if "目前步驟代碼" in text:
                return Response('{"label": "unknown"}')
            return Response(json.dumps({
                "route": "clarify",
                "intent": "ambiguous_short_query",
                "tool_name": None,
                "topic": "不明問題",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
                "extracted_slots": {},
                "reason": "bad_router_clarify",
            }, ensure_ascii=False))

        history = [
            {"role": "user", "content": "網速不夠是要報修嗎"},
            {"role": "assistant", "content": "請問您是「最近變慢」還是「想升級網速」呢？"},
        ]

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="最近變慢",
                memory={"company_code": "tdtv", "known_info": {}},
                history=history,
                llm=RunnableLambda(llm_route_or_classify),
                persist=False,
            )

        self.assertEqual(result["router"]["route"], "continue_current_flow")
        self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], "network")
        self.assertIn("所有網站/APP", result["ai_response"])
        self.assertIn("特定 APP", result["ai_response"])
        self.assertNotIn("請問您想查詢資料", result["ai_response"])

    def test_general_signal_fault_can_end_when_user_says_issue_is_gone(self):
        memory = {"known_info": {}}

        first = apply_troubleshooting_engine(
            "訊號不佳",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )
        second = apply_troubleshooting_engine(
            "沒事了 可能家裡有人在下載東西",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertIn("電視、網路", first["reply"])
        self.assertIn("已恢復正常", second["reply"])
        self.assertFalse(second["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_started"], "no")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "resolved")

    def test_general_signal_fault_stop_request_does_not_create_repair(self):
        memory = {"known_info": {}}

        apply_troubleshooting_engine(
            "訊號不佳",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )
        result = apply_troubleshooting_engine(
            "先不用了",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertIn("已停止這次排錯", result["reply"])
        self.assertFalse(result["should_call_tool"])
        self.assertIsNone(result["tool_name"])
        self.assertEqual(memory["known_info"]["troubleshooting_started"], "no")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "cancelled")

    def test_general_signal_fault_multi_turn_handler_does_not_repeat_category_question(self):
        def fail_if_called(_prompt):
            raise AssertionError("active troubleshooting state unexpectedly invoked the model")

        llm = RunnableLambda(fail_if_called)
        memory = {"company_code": "tdtv", "known_info": {}}
        history = []

        with patch("app.handlers.chat_handler.log_chat_latency"):
            first = handle_chat_message(
                user_id="test-user",
                user_text="訊號不佳",
                memory=memory,
                history=history,
                llm=llm,
                persist=False,
            )
            history.extend([
                {"role": "user", "content": "訊號不佳"},
                {"role": "assistant", "content": first["ai_response"]},
            ])
            second = handle_chat_message(
                user_id="test-user",
                user_text="沒事了 可能家裡有人在下載東西",
                memory=first["memory"],
                history=history,
                llm=llm,
                persist=False,
            )

        self.assertIn("已恢復正常", second["ai_response"])
        self.assertNotIn("目前遇到的是電視、網路", second["ai_response"])
        self.assertEqual(second["memory"]["known_info"]["troubleshooting_started"], "no")
        self.assertFalse(second["plan"]["should_call_tool"])

    def test_basic_tv_fee_prefers_basic_fee_document_over_promotion(self):
        docs = [
            {
                "title": "好視成雙NO7",
                "file_name": "好視成雙NO7.docx",
                "answer": "300M/300M：月繳 790 元。",
            },
            {
                "title": "大屯 TV 基本收費標準11507",
                "file_name": "大屯_TV_基本收費標準11507.docx",
                "answer": (
                    "第 6 台以上需持續加購月繳 100 元以上套餐。\n"
                    "年繳 $6,550、半年繳 $3,280、季繳 $1,650、月繳 $550。"
                ),
            },
        ]

        self.assertEqual(extract_basic_tv_monthly_fee(docs), "550")
        reply = apply_basic_tv_monthly_fee_concision(
            "大屯第四台一個月多少？",
            "原始回答",
            docs,
        )
        self.assertIn("大屯", reply)
        self.assertIn("$550", reply)

    def test_credit_card_payment_method_interrupts_stale_pending_flow(self):
        result = detect_safe_direct_reply(
            "我想用信用卡繳第四台費用。",
            {
                "pending_tool": "search_bill",
                "known_info": {
                    "troubleshooting_started": "yes",
                    "troubleshooting_type": "network",
                },
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["intent"], "credit_card_payment_methods")
        self.assertIn("信用卡", result["reply"])

    def test_value_added_followup_keeps_explicit_product_topic(self):
        memory = {}

        first = infer_recent_topic("熊搭心是什麼？", memory, [])
        second = infer_recent_topic("一年多少？", memory, [])
        third = infer_recent_topic("可以打多久電話？", memory, [])

        self.assertEqual(first, "熊搭心")
        self.assertEqual(second, "熊搭心")
        self.assertEqual(third, "熊搭心")
        self.assertEqual(memory["known_info"]["last_value_added_topic"], "熊搭心")

    def test_tv_only_promotion_followup_keeps_service_scope(self):
        query = build_contextual_knowledge_query(
            "有甚麼優惠",
            "優惠方案",
            {},
            [
                {"role": "user", "content": "我只要裝有線電視"},
                {"role": "assistant", "content": "可以，純有線電視可受理申裝。"},
            ],
        )

        self.assertIn("純有線電視", query)
        self.assertIn("優惠方案", query)

    def test_campaign_fee_followup_keeps_named_campaign_for_retrieval(self):
        query = build_contextual_knowledge_query(
            "如果年繳全部費用多少錢",
            "年繳 全部費用",
            {},
            [
                {"role": "user", "content": "好視成雙 NO7 除了送 LINE TV 有其他贈品嗎？"},
                {"role": "assistant", "content": "我幫您整理好視成雙 NO7 的活動內容。"},
            ],
        )

        self.assertIn("好視成雙 NO7", query)

    def test_english_named_full_package_uses_digital_tv_retrieval(self):
        result = run_intent_router(
            user_input="Sample全餐",
            memory={"known_info": {}},
            history=[],
            llm=llm_with_router_response({"route": "unknown"}),
        )

        self.assertEqual(result["intent"], "digital_tv_package_addon")
        self.assertIn("數位電視套餐", result["knowledge_query"])

    def test_generic_package_purchase_clarify_is_routed_to_digital_tv_knowledge(self):
        result = run_intent_router(
            user_input="套餐如何加購",
            memory={"known_info": {}},
            history=[],
            llm=llm_with_router_response({
                "route": "clarify",
                "intent": "value_added_service_clarification",
                "topic": "加值服務",
                "reply": "請問您想加購哪項服務？",
            }),
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["intent"], "digital_tv_package_addon")
        self.assertIn("數位電視頻道套餐", result["knowledge_query"])
        self.assertIn("聯網機上盒", result["knowledge_query"])

    def test_named_full_package_unknown_is_routed_to_digital_tv_knowledge(self):
        result = run_intent_router(
            user_input="Hi Play全餐",
            memory={"known_info": {}},
            history=[{"role": "user", "content": "套餐如何加購"}],
            llm=llm_with_router_response({"route": "unknown"}),
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["intent"], "digital_tv_package_addon")
        self.assertIn("Hi Play全餐", result["knowledge_query"])
        self.assertIn("非聯網機上盒", result["knowledge_query"])

    def test_convenience_store_payment_unknown_uses_machine_knowledge(self):
        result = run_intent_router(
            user_input="無法在便利商店繳費",
            memory={"known_info": {}},
            history=[],
            llm=llm_with_router_response({"route": "unknown"}),
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["intent"], "convenience_store_payment_machine_guide")
        self.assertIn("IBON", result["knowledge_query"])
        self.assertIn("FamiPort", result["knowledge_query"])

    def test_digital_tv_package_summary_contract_keeps_both_set_top_box_paths(self):
        self.assertIn("數位電視頻道套餐加購", RAG_SUMMARY_PROMPT)
        self.assertIn("VIP會員 → 優惠專區 → 數位電視", RAG_SUMMARY_PROMPT)
        self.assertIn("非聯網機上盒無法自行加購，須洽客服辦理", RAG_SUMMARY_PROMPT)

    def test_convenience_store_machine_summary_contract_separates_each_kiosk(self):
        self.assertIn("【7-Eleven ibon】", RAG_SUMMARY_PROMPT)
        self.assertIn("【全家 FamiPort】", RAG_SUMMARY_PROMPT)
        self.assertIn("不可把兩種機台步驟混在同一段", RAG_SUMMARY_PROMPT)

    def test_convenience_store_machine_reply_groups_source_backed_kiosk_paths(self):
        reply = build_convenience_store_payment_machine_reply(
            "convenience_store_payment_machine_guide",
            [
                {
                    "question": "ibon繳費教學",
                    "answer": (
                        "ibon機台操作 繳費→有線電視繳費→輸入用戶電話→"
                        "列印繳費單→持繳費單至櫃台繳費\n"
                        "貼心提醒：透過 IBON及FAMIPORT繳費方式系統會自動開通。"
                    ),
                },
                {
                    "question": "famiport繳費教學",
                    "answer": (
                        "famiport機台操作 繳費→有線電視→輸入用戶電話→"
                        "列印繳費單→持繳費單至櫃台繳費\n"
                        "貼心提醒：透過 IBON及FAMIPORT繳費方式系統會自動開通。"
                    ),
                },
            ],
        )

        self.assertIn("【7-Eleven ibon】", reply)
        self.assertIn("【全家 FamiPort】", reply)
        self.assertEqual(reply.count("輸入用戶登記電話"), 2)
        self.assertIn("系統會自動開通服務", reply)

    def test_digital_tv_package_addon_sop_keeps_both_set_top_box_paths(self):
        reply = build_digital_tv_package_addon_process_reply("digital_tv_package_addon")

        self.assertIn("VIP會員 → 優惠專區 → 數位電視", reply)
        self.assertIn("非聯網機上盒：無法透過機上盒自行加購", reply)
        self.assertNotIn("LINE TV", reply)
        self.assertEqual(build_digital_tv_package_addon_process_reply("other"), "")

    def test_two_year_basic_tv_fee_is_derived_from_knowledge_document(self):
        reply = apply_basic_tv_two_year_fee_calculation(
            "2年的呢",
            "原始回答",
            [{"answer": "收視費採年繳者，裝機費優惠為600元。\n年繳$6,550、半年繳$3,280"}],
        )

        self.assertIn("13,700 元", reply)

    def test_campaign_fee_followup_with_line_tv_does_not_become_basic_tv_query(self):
        query = expand_targeted_knowledge_query(
            "你剛剛說60M多少錢，如果年繳全部費用多少錢？",
            "客戶前一題詢問某優惠方案除了送 LINE TV 還有其他贈品嗎？ "
            "你剛剛說60M多少錢，如果年繳全部費用多少錢？",
        )

        self.assertNotIn("TV 基本收費標準", query)

    def test_hatv_and_hatnet_request_uses_combo_plan_retrieval(self):
        query = expand_targeted_knowledge_query(
            "本身有哈TV想申請哈NET有什麼優惠",
            "本身有哈TV想申請哈NET有什麼優惠",
        )

        self.assertTrue(is_hatv_hatnet_combo_request("本身有ㄏㄚtv想申請哈net有什麼優惠"))
        self.assertIn("電視網路同裝", query)
        self.assertNotIn("基本收費標準", query)

    def test_hatv_hatnet_overview_uses_current_combo_plan_evidence(self):
        reply = build_hatv_hatnet_combo_overview_reply(
            "本身有ㄏㄚtv想申請哈net有什麼優惠",
            [{
                "campaign_name": "目前電視網路方案",
                "service_types": "電視網路同裝",
                "answer": (
                    "舊戶無合約均可參加。\n"
                    "60M/6M：月繳$790元、年繳$9480。\n"
                    "100M/10M：月繳$890元、年繳$10680。\n"
                    "中途升級須依原剩餘合約辦理。"
                ),
            }],
        )

        self.assertIn("方案名稱：目前電視網路方案", reply)
        self.assertIn("60M/6M：月繳$790元", reply)
        self.assertNotIn("1.60M/6M", reply)
        self.assertIn("舊戶無合約均可參加", reply)

    def test_combo_followup_confirms_services_without_dumping_plan_document(self):
        reply = build_combo_service_inclusion_reply(
            "請問是兩個加起來嗎？",
            [{
                "campaign_name": "目前電視網路方案",
                "service_types": "電視網路同裝",
                "answer": "60M/6M：月繳$790元。",
            }],
        )

        self.assertIn("包含有線電視與寬頻網路服務", reply)
        self.assertNotIn("60M/6M", reply)

    def test_100m_tv_price_question_clarifies_existing_service_or_new_plan(self):
        router = run_intent_router(
            "請問家裡裝上網100M加電視頻道觀看這樣一個月多少錢呢？",
            {"company_code": "tdtv", "known_info": {}},
            [],
            llm_with_router_response({
                "route": "clarify",
                "intent": "existing_service_or_combo_plan_clarification",
                "topic": "100M 電視加網路費用",
                "reply": "請問您是想查詢目前合約的月費，還是想了解 100M 電視加網路的優惠方案？",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
            }),
        )

        self.assertEqual(router["intent"], "existing_service_or_combo_plan_clarification")
        self.assertIn("目前合約", router["reply"])

    def test_next_tier_query_uses_knowledge_flow_without_trusting_prior_assistant_text(self):
        router = run_intent_router(
            "再高一階多少錢",
            {"company_code": "tdtv", "known_info": {}},
            [{"role": "assistant", "content": "速率：下載 60 Mbps / 上傳 6 Mbps"}],
            llm_with_router_response({"route": "knowledge_query", "intent": "other"}),
        )

        self.assertEqual(router["intent"], "next_tier_plan_fee_guidance")
        self.assertIn("升級下一階速率", router["knowledge_query"])
        self.assertNotIn("60M/6M", router["knowledge_query"])

    def test_next_tier_fallback_keeps_only_plan_fee_and_upgrade_condition(self):
        reply = build_next_tier_plan_fallback(
            [
                {
                    "campaign_name": "測試方案",
                    "answer": (
                        "活動期間申辦享有加值服務。\n"
                        "500M/500M：月繳 $1,000、年繳 $12,000。\n"
                        "中途升級或換約須依目前合約資格確認。\n"
                        "其他說明與設備資訊。"
                    ),
                }
            ]
        )

        self.assertIn("方案名稱：測試方案", reply)
        self.assertIn("500M/500M：月繳 $1,000、年繳 $12,000", reply)
        self.assertIn("中途升級或換約", reply)
        self.assertNotIn("其他說明與設備資訊", reply)

    def test_evidence_fallback_selects_relevant_lines_instead_of_raw_document(self):
        reply = build_evidence_compact_fallback(
            "有線電視裝機費用",
            [
                {
                    "answer": (
                        "方案名稱：基本收費標準\n"
                        "有線電視裝機費用為 1,500 元。\n"
                        "年繳可享裝機費優惠。\n"
                        "機上盒遺失或損壞另依規定處理。\n"
                        "其他與本題無關的加值服務說明。"
                    )
                }
            ],
        )

        self.assertIn("有線電視裝機費用為 1,500 元", reply)
        self.assertIn("年繳可享裝機費優惠", reply)
        self.assertNotIn("其他與本題無關", reply)

    def test_knowledge_summary_must_reference_the_customer_question(self):
        self.assertFalse(
            has_knowledge_reply_evidence(
                "有線電視裝機申請",
                "月費保留(暫停機)復機 200 元，限拆機三個月內辦理。",
            )
        )
        self.assertTrue(
            has_knowledge_reply_evidence(
                "有線電視裝機申請",
                "有線電視裝機費用依繳別而有不同優待標準。",
            )
        )

    def test_combo_rate_inclusion_reply_uses_matching_plan_evidence(self):
        reply = build_combo_rate_inclusion_reply(
            "60M/6M 月繳 790 元，是含哈TV費用嗎？",
            [
                {
                    "campaign_name": "測試電視網路方案",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "電視網路同裝",
                    "answer": "60M/6M：月繳 $790 元。",
                }
            ],
        )

        self.assertIn("60M/6M：月繳 $790 元", reply)
        self.assertIn("包含有線電視與寬頻網路服務", reply)

        numbered_reply = build_combo_rate_inclusion_reply(
            "60M/6M 月繳 790 元，是含哈TV費用嗎？",
            [{
                "campaign_name": "測試電視網路方案",
                "service_types": "電視網路同裝",
                "answer": "1.60M/6M：月繳 $790 元。",
            }],
        )
        self.assertIn("60M/6M：月繳 $790 元", numbered_reply)
        self.assertNotIn("1.60M/6M", numbered_reply)

    def test_500m_price_reply_keeps_each_matching_plan_source(self):
        reply = build_multi_plan_broadband_price_reply(
            "500mbps費用",
            [
                {"campaign_name": "一般寬頻方案", "answer": "500M/500M：月繳 $1,000、年繳 $12,000"},
                {"campaign_name": "當期優惠方案", "answer": "500M/500M：季繳 $2,097、年繳 $8,388"},
            ],
        )

        self.assertIn("一般寬頻方案", reply)
        self.assertIn("當期優惠方案", reply)

    def test_broad_promotion_query_returns_a_compact_campaign_list(self):
        reply = build_promotion_catalog_reply(
            "九月優惠方案",
            [
                {
                    "campaign_name": "測試電視網路方案",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "電視網路同裝",
                    "valid_period": "2026/09/01~2026/09/30",
                    "answer": "60M/6M：年繳 $9,480。\n裝機費 $600。\n違約金 $2,400。",
                },
                {
                    "campaign_name": "測試純網方案",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "寬頻",
                    "valid_period": "2026/09/01~2026/09/30",
                    "answer": "500M/500M：年繳 $8,388。\n贈送 LINE TV。",
                },
            ],
        )

        self.assertIn("1. 測試電視網路方案", reply)
        self.assertIn("2. 測試純網方案", reply)
        self.assertIn("類型：電視網路同裝", reply)
        self.assertIn("60M/6M", reply)
        self.assertIn("500M/500M", reply)
        self.assertIn("活動期間：2026/09/01~2026/09/30", reply)
        self.assertNotIn("違約金", reply)
        self.assertNotIn("年繳 $9,480", reply)

        final_reply = append_promotion_referral_code(
            reply,
            {"route": "company_info", "topic": "promotion_activity"},
            {"company_code": "tdtv", "last_knowledge_results": [{"id": "promotion-1"}]},
            user_text="九月優惠方案",
        )
        self.assertNotIn(PROMOTION_REFERRAL_FOOTER, final_reply)

    def test_single_network_query_returns_only_a_compact_pure_network_catalog(self):
        reply = build_promotion_catalog_reply(
            "請問我合約到期，我想問有單一網路的嗎？",
            [
                {
                    "campaign_name": "測試純網方案 A",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "寬頻 | 加值服務",
                    "valid_period": "2026/09/01~2026/09/30",
                    "answer": "500M/500M 年繳 $8,388。裝機費 $0。",
                },
                {
                    "campaign_name": "測試純網方案 B",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "寬頻",
                    "valid_period": "2026/09/01~2026/09/30",
                    "answer": "300M/300M 年繳 $7,188。",
                },
                {
                    "campaign_name": "測試電視網路方案",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "電視網路同裝",
                    "valid_period": "2026/09/01~2026/09/30",
                    "answer": "好視成雙，電視+網路同裝。",
                },
            ],
        )

        self.assertTrue(reply.startswith("目前可參考的純網方案："))
        self.assertIn("測試純網方案 A", reply)
        self.assertIn("測試純網方案 B", reply)
        self.assertIn("500M/500M", reply)
        self.assertIn("300M/300M", reply)
        self.assertNotIn("類型：純網寬頻", reply)
        self.assertIn("速率與費用：", reply)
        self.assertIn("500M/500M：年繳 8,388 元", reply)
        self.assertIn("300M/300M：年繳 7,188 元", reply)
        self.assertIn("活動期間：2026/09/01~2026/09/30", reply)
        self.assertNotIn("測試電視網路方案", reply)
        self.assertNotIn("裝機費", reply)
        self.assertNotIn("違約金", reply)

    def test_network_install_button_uses_router_scope_and_lists_plan_rates_first(self):
        reply = build_promotion_catalog_reply(
            "網路裝機申請",
            [
                {
                    "campaign_name": "測試純網方案 A",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "寬頻",
                    "valid_period": "2026/09/01~2026/09/30",
                    "answer": (
                        "A.100M/10M：月繳 $600、半年繳 $3,000。\n"
                        "B.300M/300M：季繳 $1,797、年繳 $7,188。\n"
                        "裝機費：500 元。\n"
                        "贈哈POINT點數：888 點。"
                    ),
                },
                {
                    "campaign_name": "測試純網方案 B",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "純網寬頻",
                    "answer": "500M/500M：半年繳 $4,194、年繳 $8,388。",
                },
                {
                    "campaign_name": "測試同裝方案",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "電視網路同裝",
                    "answer": "100M/10M：月繳 $790。",
                },
            ],
            intent="pure_network_install_plan_query",
        )

        self.assertTrue(reply.startswith("目前可參考的純網方案："))
        self.assertIn("1. 測試純網方案 A", reply)
        self.assertIn("100M/10M：月繳 600 元、半年繳 3,000 元", reply)
        self.assertIn("300M/300M：季繳 1,797 元、年繳 7,188 元", reply)
        self.assertIn("2. 測試純網方案 B", reply)
        self.assertIn("500M/500M：半年繳 4,194 元、年繳 8,388 元", reply)
        self.assertNotIn("測試同裝方案", reply)
        self.assertNotIn("裝機費", reply)
        self.assertNotIn("POINT", reply)

    def test_network_install_full_chat_skips_rag_summary_and_keeps_plan_boundaries(self):
        docs = [
            {
                "campaign_name": "測試純網方案 A",
                "document_id": "dynamic-plan-a",
                "knowledge_base": "大屯",
                "question": "測試純網方案 A",
                "document_type": "promotion_campaign",
                "record_type": "campaign_summary",
                "service_types": "寬頻",
                "answer": (
                    "方案名稱：測試純網方案 A。\n"
                    "100M/10M：月繳 $600、半年繳 $3,000。\n"
                    "裝機費：500 元。"
                ),
                "company": "大屯",
                "category": "billing",
                "_score": 0.95,
            },
            {
                "campaign_name": "測試純網方案 B",
                "document_id": "dynamic-plan-b",
                "knowledge_base": "大屯",
                "question": "測試純網方案 B",
                "document_type": "promotion_campaign",
                "record_type": "campaign_summary",
                "service_types": "純網寬頻",
                "answer": (
                    "方案名稱：測試純網方案 B。\n"
                    "500M/500M：半年繳 $4,194、年繳 $8,388。\n"
                    "贈哈POINT點數：888 點。"
                ),
                "company": "大屯",
                "category": "billing",
                "_score": 0.94,
            },
        ]
        calls = {"count": 0}

        def fake_llm(_payload):
            calls["count"] += 1
            return Response(json.dumps({
                "route": "knowledge_query",
                "intent": "pure_network_install_plan_query",
                "tool_name": None,
                "topic": "純網方案",
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "單辦寬頻 純網方案 裝機申請 速率 費用 排除電視同裝方案",
                "reply": "",
                "extracted_slots": {},
                "reason": "model_install_application",
            }, ensure_ascii=False))

        retrieval_calls = []

        def fake_retrieve(_user_text, _memory, plan, top_k=5):
            retrieval_calls.append(dict(plan))
            target_document_id = plan.get("target_document_id")
            if target_document_id:
                return [
                    doc for doc in docs
                    if doc.get("document_id") == target_document_id
                ]
            return docs

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", side_effect=fake_retrieve),
        ):
            result = handle_chat_message(
                user_id="test-user",
                user_text="網路裝機申請",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(fake_llm),
                persist=False,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(result["router"]["intent"], "pure_network_install_plan_query")
        self.assertIn("測試純網方案 A", result["ai_response"])
        self.assertIn("100M/10M：月繳 600 元、半年繳 3,000 元", result["ai_response"])
        self.assertIn("測試純網方案 B", result["ai_response"])
        self.assertIn("500M/500M：半年繳 4,194 元、年繳 8,388 元", result["ai_response"])
        self.assertNotIn("裝機費", result["ai_response"])
        self.assertNotIn("POINT", result["ai_response"])
        self.assertEqual(
            list(result["memory"]["clarify_context"]["options"].keys()),
            ["測試純網方案 A", "測試純網方案 B"],
        )

        def select_second_option(_payload):
            calls["count"] += 1
            return Response(json.dumps({
                "route": "knowledge_query",
                "intent": "promotion_named_campaign_selection",
                "topic": "測試純網方案 B",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "測試純網方案 B",
                "selected_option_id": "option_2",
                "reply": "",
                "extracted_slots": {},
                "reason": "model_catalog_option_selection",
            }, ensure_ascii=False))

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", side_effect=fake_retrieve),
        ):
            selected = handle_chat_message(
                user_id="test-user",
                user_text="2",
                memory=result["memory"],
                history=[
                    {"role": "user", "content": "網路裝機申請"},
                    {"role": "assistant", "content": result["ai_response"]},
                ],
                llm=RunnableLambda(select_second_option),
                persist=False,
            )

        self.assertEqual(calls["count"], 2)
        self.assertEqual(selected["router"]["reason"], "model_selected_context_validated")
        self.assertEqual(selected["router"]["topic"], "測試純網方案 B")
        self.assertEqual(selected["router"]["selected_option_id"], "option_2")
        self.assertEqual(selected["plan"]["target_document_id"], "dynamic-plan-b")
        self.assertEqual(retrieval_calls[-1]["target_document_id"], "dynamic-plan-b")
        self.assertIn("測試純網方案 B", retrieval_calls[-1]["knowledge_query"])
        self.assertNotIn("優惠活動 節慶", retrieval_calls[-1]["knowledge_query"])
        self.assertIn("方案名稱：測試純網方案 B", selected["ai_response"])
        self.assertNotIn("測試純網方案 A", selected["ai_response"])
        self.assertNotIn("無法理解", selected["ai_response"])

    def test_promotion_catalog_excludes_faq_titles_and_limits_speed_preview(self):
        reply = build_promotion_catalog_reply(
            "純網路",
            [
                {
                    "campaign_name": "正式純網活動",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "純網寬頻",
                    "speeds": "100M/10M | 300M/300M | 500M/500M | 1G/1G",
                },
                {
                    "question": "LINE TV 新裝機首期贈送",
                    "document_type": "faq",
                    "service_types": "寬頻",
                    "answer": "LINE TV 服務說明與 100M/10M 參考資訊。",
                },
            ],
        )

        self.assertIn("正式純網活動", reply)
        self.assertIn("速率：100M/10M、300M/300M、500M/500M 等", reply)
        self.assertNotIn("1G/1G", reply)
        self.assertNotIn("LINE TV 新裝機首期贈送", reply)
        self.assertNotIn("；", reply)

    def test_named_campaign_initial_reply_keeps_the_four_required_sections(self):
        docs = [{
            "campaign_name": "好視成雙NO7",
            "campaign_aliases": "好視成雙 NO7 | 好視成雙NO7",
            "answer": (
                "方案名稱：好視成雙NO7\n"
                "一、裝機費：年繳用戶優待為 $600。\n"
                "二、半年繳(含)以上免押。\n"
                "六、違約：提前解約需支付違約金 2,400 元。\n"
                "七、贈加值服務 LINE TV：首期贈送半年。\n"
                "八、可加價租用 WiFi 設備。\n"
                "十、售價：\n"
                "1.60M/6M：月繳 $790、年繳 $9,480。"
            ),
        }]

        reply = build_named_campaign_overview_reply("好視成雙 NO7", docs)

        self.assertIn("寬頻費用：", reply)
        self.assertIn("60M/6M：月繳 790 元", reply)
        self.assertIn("贈送內容：", reply)
        self.assertIn("裝機費：", reply)
        self.assertIn("違約金：", reply)
        self.assertNotIn("可加價租用 WiFi", reply)
        self.assertNotIn("年繳 $9,480", reply)

        gift_reply = build_campaign_gift_followup_reply(
            "好視成雙 NO7除了送LINE TV有其他贈品嗎？",
            docs,
        )
        self.assertIn("未列其他贈品", gift_reply)

    def test_named_campaign_timing_query_returns_only_its_valid_period(self):
        docs = [{
            "campaign_name": "好視成雙NO7 (電視+網路同裝方案)",
            "campaign_aliases": "好視成雙NO7|大屯好視成雙NO7-AI版",
            "valid_period": "115.01.01至115.12.31",
            "answer": (
                "裝機費：500元。\n"
                "售價：500M/500M 月繳 1,000元。\n"
                "違約金：2,400元。"
            ),
        }]

        reply = build_campaign_valid_period_reply("好視成雙方案何時？", docs)

        self.assertEqual(
            reply,
            "好視成雙NO7 (電視+網路同裝方案)活動期間：115.01.01至115.12.31。",
        )
        self.assertNotIn("裝機費", reply)
        self.assertNotIn("違約金", reply)

    def test_campaign_annual_total_uses_rate_install_fee_and_waived_deposit(self):
        reply = build_campaign_total_fee_reply(
            "60M 年繳全部費用多少錢？",
            [{
                "campaign_name": "好視成雙NO7",
                "answer": (
                    "一、裝機費：採用月繳、季繳用戶 $1,500；"
                    "半年繳用戶優待為 $1,000；年繳用戶優待為 $600；"
                    "300M(含)以上收裝機費500元。\n"
                    "二、網路設備押金：1000 元，半年繳(含)以上免押。\n"
                    "十、售價：\n"
                    "1.60M/6M：月繳 $790、季繳 $2,370、半年繳 $4,740、年繳 $9,480。"
                ),
            }],
        )

        self.assertIn("年繳費用 9,480 元", reply)
        self.assertIn("裝機費 600 元", reply)
        self.assertIn("設備押金 0 元", reply)
        self.assertIn("10,080 元", reply)

    def test_campaign_fee_followup_stays_with_explicitly_named_campaign(self):
        named_campaign = {
            "campaign_name": "好視成雙NO7",
            "answer": (
                "一、裝機費：年繳用戶優待為 $600。\n"
                "二、網路設備押金：1000 元，半年繳(含)以上免押。\n"
                "十、售價：60M/6M：月繳 $790、年繳 $9,480。"
            ),
        }
        unrelated_campaign = {
            "campaign_name": "哈 NET1",
            "answer": (
                "一、裝機費：年繳用戶優待為 $500。\n"
                "二、網路設備押金：1000 元，半年繳(含)以上免押。\n"
                "十、售價：60M/6M：月繳 $500、年繳 $6,000。"
            ),
        }

        reply = build_campaign_total_fee_reply(
            "60M 年繳全部費用多少錢？",
            [unrelated_campaign],
            memory={
                "last_campaign_topic": "好視成雙NO7",
                "last_knowledge_results": [named_campaign],
            },
        )

        self.assertIn("好視成雙NO7", reply)
        self.assertIn("年繳費用 9,480 元", reply)
        self.assertIn("裝機費 600 元", reply)
        self.assertIn("10,080 元", reply)
        self.assertNotIn("哈 NET1", reply)

    def test_named_full_package_leaves_generic_addon_menu_for_llm_routing(self):
        memory = {
            "clarify_context": get_clarify_context("加值服務"),
            "known_info": {},
        }

        result = resolve_clarify_context("Hi Play全餐", memory)

        self.assertIsNone(result)
        self.assertIsNone(memory["clarify_context"])

    def test_capability_followup_keeps_recent_customer_device_for_retrieval(self):
        query = build_contextual_knowledge_query(
            "哈TV可以使用YouTube嗎？",
            "哈TV YouTube 是否支援",
            {},
            [
                {"role": "user", "content": "請問怎麼獲取無線網路"},
                {"role": "assistant", "content": "請選擇加值服務"},
                {"role": "user", "content": "聯網機上盒"},
            ],
        )

        self.assertIn("聯網機上盒", query)
        self.assertIn("YouTube", query)

    def test_generic_value_added_followups_do_not_create_a_new_topic(self):
        self.assertIsNone(exact_value_added_topic("一年多少？"))
        self.assertIsNone(exact_value_added_topic("可以打多久電話？"))
        self.assertEqual(exact_value_added_topic("熊搭心可以打多久電話？"), "熊搭心")

    def test_contextual_query_ignores_child_plan_terms_added_by_query_rewrite(self):
        memory = {
            "last_value_added_topic": "熊搭心",
            "known_info": {"last_value_added_topic": "熊搭心"},
        }

        query = build_contextual_knowledge_query(
            "一年多少？",
            "瑪帛用戶 原價49元/月 一年多少？",
            memory,
            [
                {"role": "user", "content": "熊搭心是什麼？"},
                {"role": "assistant", "content": "熊搭心包含瑪帛用戶、瑪帛好友與瑪帛夥伴。"},
            ],
        )

        self.assertTrue(query.startswith("熊搭心 "))
        self.assertEqual(memory["last_value_added_topic"], "熊搭心")

    def test_memory_summary_exposes_remembered_value_added_topic(self):
        summary = json.loads(
            build_memory_summary(
                {"known_info": {"last_value_added_topic": "熊搭心"}}
            )
        )

        self.assertEqual(summary["last_value_added_topic"], "熊搭心")
        self.assertEqual(summary["known_info"]["last_value_added_topic"], "熊搭心")

    def test_memory_summary_exposes_tv_reactivation_status(self):
        summary = json.loads(
            build_memory_summary(
                {
                    "known_info": {
                        "tv_reactivation_status": "already_temp_restored",
                        "tv_reactivation_message": "您已暫復過，無法重復暫復",
                    }
                }
            )
        )

        self.assertEqual(summary["known_info"]["tv_reactivation_status"], "already_temp_restored")
        self.assertIn("已暫復過", summary["known_info"]["tv_reactivation_message"])

    def test_remembered_value_added_topic_resolves_short_price_followup(self):
        result = resolve_remembered_value_added_followup(
            "一年多少？",
            {"known_info": {"last_value_added_topic": "熊搭心"}},
            {
                "route": "clarify",
                "intent": "value_added_service_clarification",
                "topic": "加值服務",
                "knowledge_query": "",
                "reason": "unspecified_value_added_service",
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["topic"], "熊搭心")
        self.assertIn("熊搭心", result["knowledge_query"])
        self.assertIn("年繳", result["knowledge_query"])
        self.assertNotIn("瑪帛好友", result["knowledge_query"])
        self.assertNotIn("申辦方式", result["knowledge_query"])

    def test_remembered_value_added_topic_resolves_generic_short_price_followup(self):
        result = resolve_remembered_value_added_followup(
            "一年多少？",
            {"known_info": {"last_value_added_topic": "熊搭心"}},
            {
                "route": "clarify",
                "intent": "unclear_request",
                "topic": "",
                "knowledge_query": "",
                "reason": "insufficient_context",
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["route"], "knowledge_query")
        self.assertIn("熊搭心", result["knowledge_query"])
        self.assertIn("年費", result["knowledge_query"])

    def test_remembered_value_added_topic_resolves_short_call_duration_followup(self):
        result = resolve_remembered_value_added_followup(
            "可以打多久電話？",
            {"known_info": {"last_value_added_topic": "熊搭心"}},
            {
                "route": "unknown",
                "intent": "other",
                "topic": "",
                "knowledge_query": "",
                "reason": "unknown",
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["topic"], "熊搭心")
        self.assertIn("通話分鐘", result["knowledge_query"])
        self.assertIn("使用時間", result["knowledge_query"])
        self.assertNotIn("瑪帛好友", result["knowledge_query"])

    def test_remembered_value_added_topic_does_not_override_tool_flow(self):
        result = resolve_remembered_value_added_followup(
            "帳單一年多少？",
            {"known_info": {"last_value_added_topic": "熊搭心"}},
            {
                "route": "tool_action",
                "intent": "bill_query",
                "topic": "帳單",
                "knowledge_query": "",
                "reason": "bill_lookup",
            },
        )

        self.assertIsNone(result)

    def test_remembered_value_added_topic_does_not_override_explicit_topic_switch(self):
        for message in ("我的帳單一年多少？", "網路不能用怎麼辦？"):
            with self.subTest(message=message):
                result = resolve_remembered_value_added_followup(
                    message,
                    {"known_info": {"last_value_added_topic": "熊搭心"}},
                    {
                        "route": "clarify",
                        "intent": "unclear_request",
                        "topic": "",
                        "knowledge_query": "",
                        "reason": "insufficient_context",
                    },
                )

                self.assertIsNone(result)

    def test_network_reboot_followup_switches_to_repair_without_repeating_reboot(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "retry": 0,
            }
        }

        result = apply_troubleshooting_engine(
            "數據機重開後還是一樣",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertTrue(result["should_call_tool"])
        self.assertEqual(result["tool_name"], "create_repair_ticket")
        self.assertNotIn("重新開機", result["reply"])

    def test_fault_category_plain_tv_selection_uses_previous_signal_context(self):
        memory = {
            "known_info": {
                "issue_description": "反應訊號不好",
                "troubleshooting_started": "yes",
                "troubleshooting_type": "unknown",
                "troubleshooting_step": "ask_fault_category",
                "troubleshooting_failed": "no",
                "repair_ready": "no",
                "retry": 0,
            }
        }

        result = apply_troubleshooting_engine(
            "電視",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_type"], "tv")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("收訊", result["reply"])
        self.assertNotIn("請直接回覆", result["reply"])
        self.assertNotIn("請問目前遇到的是電視、網路", result["reply"])

    def test_fault_category_semantic_llm_handles_colloquial_fault_wording(self):
        memory = {
            "known_info": {
                "issue_description": "反應訊號不好",
                "troubleshooting_started": "yes",
                "troubleshooting_type": "unknown",
                "troubleshooting_step": "ask_fault_category",
                "troubleshooting_failed": "no",
                "repair_ready": "no",
                "retry": 0,
            }
        }
        llm = llm_with_router_response({"type": "tv", "confidence": 0.91})

        result = apply_troubleshooting_engine(
            "4/27後完全不好看的",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
            llm=llm,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_type"], "tv")
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")
        self.assertIn("收訊", result["reply"])
        self.assertNotIn("請問目前遇到的是電視、網路", result["reply"])

    def test_virtual_hosting_website_page_followup_stays_unsupported(self):
        router = build_contextual_website_page_switch_router(
            "官網哪裡可以看到介紹?",
            [
                {"role": "user", "content": "虛擬主機"},
                {"role": "assistant", "content": "目前未提供「虛擬主機」服務。"},
                {"role": "user", "content": "服務內容"},
                {"role": "assistant", "content": "目前未提供「虛擬主機」服務。"},
            ],
        )

        self.assertIsNotNone(router)
        self.assertEqual(router["route"], "direct_reply")
        self.assertEqual(router["intent"], "unsupported_virtual_hosting_service")
        self.assertTrue(router["should_cancel_current_flow"])
        self.assertFalse(router["should_retrieve_knowledge"])
        self.assertIn("未提供", router["reply"])
        self.assertIn("虛擬主機", router["reply"])

    def test_feedback_virtual_hosting_service_content_is_not_contract_lookup(self):
        def fail_if_called(_prompt):
            raise AssertionError("virtual hosting should be handled by deterministic rules")

        memory = {"company_code": "tdtv", "known_info": {}}
        history = []

        first = handle_chat_message(
            "test:feedback-case-21",
            "虛擬主機",
            memory,
            history,
            llm=RunnableLambda(fail_if_called),
            persist=False,
        )
        self.assertEqual(first["router"]["intent"], "unsupported_virtual_hosting_service")
        self.assertEqual(
            first["ai_response"],
            "您好，目前本公司未提供「虛擬主機」服務，抱歉無法協助辦理。",
        )
        self.assertNotEqual(first["router"].get("tool_name"), "search_contract_info")

        history.extend([
            {"role": "user", "content": "虛擬主機"},
            {"role": "assistant", "content": first["ai_response"]},
        ])

        second = handle_chat_message(
            "test:feedback-case-21",
            "服務內容",
            first["memory"],
            history,
            llm=RunnableLambda(fail_if_called),
            persist=False,
        )

        self.assertEqual(second["router"]["intent"], "unsupported_virtual_hosting_service")
        self.assertEqual(
            second["ai_response"],
            "您好，目前本公司未提供「虛擬主機」服務，抱歉無法協助辦理。",
        )
        self.assertNotEqual(second["router"].get("tool_name"), "search_contract_info")
        self.assertFalse(second["plan"]["should_call_tool"])

    def test_tv_screen_check_accepts_lag_description_without_repeating_choices(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_screen",
            }
        }

        result = apply_troubleshooting_engine(
            "觀看畫面正常，但中途會轉圈lag",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertIn("卡頓", result["reply"])
        self.assertIn("機上盒電源", result["reply"])
        self.assertNotIn("無訊號", result["reply"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_reboot")

    def test_tv_no_program_flow_goes_to_rescan(self):
        memory = {"known_info": {}}

        result = apply_troubleshooting_engine(
            "顯示沒有節目卡住",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertIn("重新搜頻", result["reply"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_rescan_channels")

    def test_remote_button_fault_starts_remote_flow(self):
        result = detect_safe_direct_reply(
            "2台遙控器數字按鈕壞掉，其他功能鍵正常",
            {"known_info": {}},
        )

        self.assertEqual(result["intent"], "remote_control_issue")
        self.assertIn("遙控器", result["reply"])
        self.assertIn("300 元", result["reply"])
        self.assertIn("400 元", result["reply"])

    def test_clarify_numeric_reply_selects_matching_option(self):
        context = get_clarify_context("加值服務")

        selection = match_clarify_option("2", context)

        self.assertIsNotNone(selection)
        self.assertEqual(selection["matched_option"], "WiFi 加值服務")
        self.assertEqual(selection["route"], "knowledge_query")
        self.assertIn("WiFi", selection["knowledge_query"])

    def test_value_added_clarify_intent_uses_choices_despite_descriptive_topic(self):
        context = build_clarify_context(
            {
                "intent": "value_added_service_clarification",
                "topic": "加值產品與服務",
                "reply": "請選擇想了解的項目。",
            },
            original_query="想加購服務",
        )

        self.assertIsNotNone(context)
        self.assertEqual(context["topic"], "加值服務")
        self.assertEqual(match_clarify_option("2", context)["matched_option"], "WiFi 加值服務")

    def test_promotion_scope_clarification_retains_original_period_and_routes_each_choice(self):
        router = {
            "intent": "promotion_service_scope_clarification",
            "topic": "優惠方案服務類型",
            "reply": "請問您想了解哪一類優惠方案？",
        }
        context = build_clarify_context(router, original_query="九月有什麼優惠方案")

        expected = {
            "1": ("tv_network_install_plan_query", "電視+網路方案"),
            "純網": ("pure_network_install_plan_query", "純網方案"),
            "純有線": ("pure_tv_promotion_query", "單辦有線電視優惠"),
        }
        for answer, (intent, topic) in expected.items():
            with self.subTest(answer=answer):
                selection = resolve_clarify_context(answer, {"clarify_context": dict(context)})
                self.assertEqual(selection["route"], "knowledge_query")
                self.assertEqual(selection["intent"], intent)
                self.assertEqual(selection["topic"], topic)
                self.assertIn("九月有什麼優惠方案", selection["knowledge_query"])

    def test_wifi_value_added_youtube_clarify_reply_uses_original_question(self):
        router = {
            "intent": "value_added_service_clarification",
            "topic": "加值服務",
            "reply": "請問您想了解哪一項加值服務？",
        }
        memory = {"clarify_context": build_clarify_context(router, original_query="加值後可以用YouTube嗎？")}

        selection = resolve_clarify_context("2", memory)

        self.assertIsNotNone(selection)
        self.assertEqual(selection["route"], "direct_reply")
        self.assertEqual(selection["intent"], "wifi_value_added_youtube_scope")
        self.assertIn("WiFi 加值服務", selection["topic"])
        self.assertIn("YouTube", selection["reply"])
        self.assertIn("數位機上盒", selection["reply"])

    def test_wifi_value_added_youtube_followup_uses_remembered_topic(self):
        result = resolve_remembered_value_added_followup(
            "加值後可以用YouTube嗎？",
            {"known_info": {"last_value_added_topic": "WiFi 加值服務"}},
            {"route": "clarify", "intent": "value_added_service_clarification", "topic": "加值服務"},
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["route"], "direct_reply")
        self.assertEqual(result["intent"], "wifi_value_added_youtube_scope")
        self.assertIn("YouTube", result["reply"])
        self.assertIn("數位機上盒", result["reply"])

    def test_tatung_pure_tv_install_application_quotes_basic_install_fee(self):
        result = detect_safe_direct_reply(
            "有線電視裝機申請",
            {"company_code": "tdtv", "known_info": {}},
        )

        self.assertEqual(result["route"], "direct_reply")
        self.assertEqual(result["intent"], "pure_tv_install_query")
        self.assertIn("基本收視費", result["reply"])
        self.assertIn("月繳 550 元", result["reply"])
        self.assertIn("半年繳 3,280 元", result["reply"])
        self.assertIn("月繳／季繳", result["reply"])
        self.assertIn("1,500 元", result["reply"])
        self.assertIn("未滿 1 年", result["reply"])
        self.assertNotIn("有申裝意願", result["reply"])
        self.assertNotIn("裝機申告表單", result["reply"])

    def test_install_option_buttons_route_to_expected_plan_categories(self):
        network = detect_safe_direct_reply(
            "網路裝機申請",
            {"company_code": "tdtv", "known_info": {}},
        )

        self.assertEqual(network["route"], "knowledge_query")
        self.assertEqual(network["topic"], "純網方案")
        self.assertTrue(network["should_retrieve_knowledge"])
        self.assertIn("純網方案", network["knowledge_query"])
        self.assertIn("一般寬頻方案", network["knowledge_query"])
        self.assertIn("單辦寬頻", network["knowledge_query"])
        self.assertNotIn("清冰組", network["knowledge_query"])
        self.assertNotIn("有申裝意願", network["knowledge_query"])
        self.assertNotIn("裝機申告表單", network["knowledge_query"])

        for user_text in (
            "同時申裝有線網路",
            "有線電視+網路裝機申請",
            "有線電視＋網路裝機申請",
            "有線電視與網路裝機申請",
        ):
            with self.subTest(user_text=user_text):
                combo = detect_safe_direct_reply(
                    user_text,
                    {"company_code": "tdtv", "known_info": {}},
                )

                self.assertEqual(combo["route"], "knowledge_query")
                self.assertEqual(combo["topic"], "電視+網路方案")
                self.assertTrue(combo["should_retrieve_knowledge"])
                self.assertIn("電視+網路方案", combo["knowledge_query"])
                self.assertIn("電視網路同裝方案", combo["knowledge_query"])
                self.assertNotIn("好視成雙", combo["knowledge_query"])
                self.assertIn("不要回答純網方案", combo["knowledge_query"])

    def test_combo_install_query_returns_only_a_compact_combo_catalog(self):
        reply = build_promotion_catalog_reply(
            "有線電視+網路裝機申請",
            [
                {
                    "campaign_name": "測試同裝方案",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "電視網路同裝",
                    "speeds": "100M/10M | 300M/300M",
                    "valid_period": "2026/09/01~2026/09/30",
                },
                {
                    "campaign_name": "測試純網方案",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "純網寬頻",
                    "speeds": "500M/500M",
                },
                {
                    "campaign_name": "測試社福同裝方案",
                    "document_type": "promotion_campaign",
                    "record_type": "campaign_summary",
                    "service_types": "電視網路同裝",
                    "answer": "限低收入戶申請。",
                },
            ],
        )

        self.assertTrue(reply.startswith("目前可參考的電視＋網路同裝方案："))
        self.assertIn("1. 測試同裝方案", reply)
        self.assertIn("類型：電視網路同裝", reply)
        self.assertNotIn("測試純網方案", reply)
        self.assertNotIn("測試社福同裝方案", reply)

    def test_pure_network_natural_fee_query_routes_to_plan_knowledge(self):
        result = detect_safe_direct_reply(
            "可以只上網，不用第四台嗎",
            {"company_code": "tdtv", "known_info": {}},
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["topic"], "純網方案")
        self.assertIn("純網方案", result["knowledge_query"])
        self.assertIn("單辦寬頻", result["knowledge_query"])

    def test_single_network_query_routes_to_pure_network_catalog_knowledge(self):
        result = detect_safe_direct_reply(
            "請問我合約到期，我想問有單一網路的嗎？",
            {"company_code": "tdtv", "known_info": {}},
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["intent"], "pure_network_install_plan_query")
        self.assertEqual(result["topic"], "純網方案")
        self.assertIn("目前有效的純網方案總覽", result["knowledge_query"])
        self.assertIn("只找純網方案，排除電視同裝", result["knowledge_query"])

    def test_contract_termination_beats_contract_lookup(self):
        result = detect_safe_direct_reply(
            "想要提前終止合約",
            {"known_info": {"custnum": "1267177"}},
        )

        self.assertEqual(result["intent"], "contract_termination_guidance")
        self.assertIn("違約金", result["reply"])
        self.assertIn("辦理流程如下", result["reply"])
        self.assertFalse(result["should_call_tool"])

    def test_contract_termination_interrupts_unrelated_value_added_history(self):
        history = [
            {"role": "user", "content": "想要提前終止合約"},
            {"role": "assistant", "content": "目前方案含 WiFi 加值服務。"},
        ]
        result = run_intent_router(
            "合約終止",
            {"company_code": "tdtv", "known_info": {"custnum": "1267177"}},
            history,
            llm_with_router_response(
                {
                    "route": "knowledge_query",
                    "intent": "service_termination_process",
                    "topic": "退租流程",
                    "should_call_tool": False,
                    "should_retrieve_knowledge": True,
                    "knowledge_query": "WiFi 加值服務 提前終止合約",
                    "reply": "",
                }
            ),
        )

        self.assertEqual(result["intent"], "contract_termination_guidance")
        self.assertEqual(result["route"], "direct_reply")
        self.assertIn("向客服提出退租申請", result["reply"])
        self.assertIn("違約金", result["reply"])

    def test_billing_mailing_address_is_not_company_address(self):
        result = detect_safe_direct_reply(
            "目前帳單寄送地址",
            {"known_info": {}},
        )

        self.assertEqual(result["intent"], "personal_billing_address_handoff")
        self.assertIn("無法直接提供", result["reply"])

    def test_autopay_definition_does_not_become_binding_status_lookup(self):
        result = detect_safe_direct_reply(
            "綁定循環扣款是什麼意思",
            {"known_info": {}},
        )

        self.assertEqual(result["intent"], "card_autopay_definition")
        self.assertIn("自動扣款", result["reply"])

    def test_line_tv_opening_uses_customer_service_steps(self):
        result = detect_safe_direct_reply(
            "如何開通line tv",
            {"known_info": {}},
        )

        self.assertEqual(result["intent"], "line_tv_opening_query")
        self.assertFalse(result["should_retrieve_knowledge"])
        self.assertIn("雙模機", result["reply"])
        self.assertIn("VIP會員", result["reply"])
        self.assertIn("QR code", result["reply"])

    def test_app_online_payment_receipt_includes_invoice_lookup_and_carrier_binding(self):
        result = detect_safe_direct_reply(
            "如果在app，線上繳完費，會去實體收據，到家嗎",
            {"company_code": "tdtv", "known_info": {}},
        )

        self.assertEqual(result["intent"], "app_payment_receipt_lookup")
        self.assertIn("不會另外寄送實體收據到府", result["reply"])
        self.assertIn("發票號碼會於營業日以簡訊通知", result["reply"])
        self.assertIn("客戶服務 → 發票查詢", result["reply"])
        self.assertIn("哈TV行動客服 APP", result["reply"])
        self.assertIn("用戶資訊", result["reply"])
        self.assertIn("用戶歸戶", result["reply"])
        self.assertIn("財政部網站", result["reply"])

    def test_app_payment_receipt_llm_intent_uses_customer_service_sop(self):
        result = run_intent_router(
            "如果在app，線上繳完費，會寄實體收據到家嗎？",
            {"company_code": "tdtv", "known_info": {}},
            [],
            llm_with_router_response({
                "route": "knowledge_query",
                "intent": "app_payment_receipt_lookup",
                "topic": "APP 線上繳費收據與發票查詢",
                "should_retrieve_knowledge": True,
                "knowledge_query": "繳費入帳 營業日 簡訊發票號碼 客戶服務 發票查詢",
            }),
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["intent"], "app_payment_receipt_lookup")

        reply = build_app_payment_receipt_lookup_reply(result["intent"])
        self.assertIn("不會另外寄送實體收據到府", reply)
        self.assertIn("發票號碼會於營業日以簡訊通知用戶", reply)
        self.assertIn("客戶服務 → 發票查詢 → 輸入客編及密碼", reply)
        self.assertIn("用戶資訊", reply)
        self.assertNotIn("紙本", reply)

    def test_invoice_issue_timing_keeps_full_customer_service_guidance(self):
        result = run_intent_router(
            "繳費後發票何時有",
            {"company_code": "tdtv", "known_info": {}},
            [],
            llm_with_router_response({
                "route": "knowledge_query",
                "intent": "invoice_issue_timing",
                "topic": "發票開立與寄送時程",
                "should_retrieve_knowledge": True,
                "knowledge_query": "電子發票 入帳後第二天 簡訊 紙本發票 16天 發票號碼載具 用戶歸戶",
            }),
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["intent"], "invoice_issue_timing")
        self.assertIn("入帳後第二天", result["knowledge_query"])
        self.assertIn("紙本發票", result["knowledge_query"])

        reply = build_invoice_issue_timing_reply(result["intent"])
        self.assertIn("入帳後的第二天", reply)
        self.assertIn("16 天內寄出", reply)
        self.assertIn("客戶服務 → 發票查詢", reply)
        self.assertIn("用戶歸戶", reply)
        self.assertIn("財政部網站", reply)

    def test_invoice_mobile_barcode_uses_llm_confirmation_then_official_sop(self):
        confirmation = run_intent_router(
            "發票加入手機條碼",
            {"company_code": "tdtv", "known_info": {}},
            [],
            llm_with_router_response({
                "route": "clarify",
                "intent": "invoice_carrier_binding_confirmation",
                "topic": "手機條碼載具歸戶",
                "should_retrieve_knowledge": False,
                "reply": "任意的模型措辭不應直接顯示",
            }),
        )
        self.assertEqual(confirmation["route"], "clarify")
        self.assertEqual(confirmation["intent"], "invoice_carrier_binding_confirmation")
        confirmation_plan = build_plan_from_router(confirmation)
        self.assertEqual(confirmation_plan["reply"], "請問您是想將發票歸戶到手機條碼載具嗎？")

        binding = run_intent_router(
            "是",
            {"company_code": "tdtv", "known_info": {}},
            [{"role": "user", "content": "發票加入手機條碼"}],
            llm_with_router_response({
                "route": "knowledge_query",
                "intent": "invoice_carrier_binding",
                "topic": "手機條碼載具歸戶",
                "should_retrieve_knowledge": True,
                "knowledge_query": "手機條碼載具 發票歸戶 官網 線上繳費 用戶歸戶 用戶歸戶2 財政部網站",
            }),
        )
        self.assertEqual(binding["route"], "knowledge_query")
        self.assertEqual(binding["intent"], "invoice_carrier_binding")
        self.assertIn("用戶歸戶2", binding["knowledge_query"])

        reply = build_invoice_carrier_binding_reply(binding["intent"])
        self.assertIn("線上繳費", reply)
        self.assertIn("用戶歸戶2", reply)
        self.assertIn("財政部網站", reply)
        self.assertIn("手機號碼及驗證碼", reply)
        self.assertNotIn("真人客服", reply)

    def test_short_invoice_carrier_question_bypasses_unknown_model_route(self):
        def fail_if_called(_payload):
            raise AssertionError("short invoice carrier question must not depend on the model")

        for user_text in ("發票可以載具嗎", "發票可以載具"):
            with self.subTest(user_text=user_text):
                result = run_intent_router(
                    user_text,
                    {"company_code": "wctv", "known_info": {}},
                    [],
                    RunnableLambda(fail_if_called),
                )

                self.assertEqual(result["route"], "direct_reply")
                self.assertEqual(result["intent"], "invoice_carrier_binding")
                self.assertIn("用戶歸戶2", result["reply"])

    def test_cable_tv_termination_and_contract_change_followups_use_llm_sops(self):
        termination = run_intent_router(
            "有線電視退租計算",
            {"company_code": "tdtv", "known_info": {}},
            [],
            llm_with_router_response({
                "route": "knowledge_query",
                "intent": "cable_tv_termination_calculation",
                "topic": "有線電視退租費用與辦理",
                "should_retrieve_knowledge": True,
                "knowledge_query": "有線電視 退租 退費計算 合約 繳別 機上盒 配件 櫃檯辦理",
            }),
        )
        self.assertEqual(termination["intent"], "cable_tv_termination_calculation")
        termination_reply = build_cable_tv_termination_calculation_reply(termination["intent"])
        self.assertIn("沒有固定公式", termination_reply)
        self.assertIn("機上盒及所有配件", termination_reply)
        self.assertIn("代辦人與用戶雙方證件正本", termination_reply)

        contract_change = run_intent_router(
            "需退約再重新約定嗎",
            {"company_code": "tdtv", "known_info": {}},
            [{"role": "user", "content": "有線電視退租計算"}],
            llm_with_router_response({
                "route": "knowledge_query",
                "intent": "contract_change_after_termination",
                "topic": "退租後換約",
                "should_retrieve_knowledge": True,
                "knowledge_query": "有線電視 退租後 換約 原剩餘合約期 新合約期 違約金",
            }),
        )
        self.assertEqual(contract_change["intent"], "contract_change_after_termination")
        contract_reply = build_contract_change_after_termination_reply(contract_change["intent"])
        self.assertIn("不一定需要先退約再重新約定", contract_reply)
        self.assertIn("原剩餘合約期間加上新方案合約期間", contract_reply)
        self.assertIn("違約金", contract_reply)

    def test_cloud_account_followup_uses_app_sop_not_broadband_plan(self):
        result = run_intent_router(
            "協助登入或使用雲端帳號",
            {"company_code": "cnt", "known_info": {}},
            [{
                "role": "user",
                "content": "哈NET寬頻用戶權益通知：系統已為您開通雲端帳號",
            }],
            llm_with_router_response({
                "route": "knowledge_query",
                "intent": "cloud_account_app_usage",
                "topic": "雲端帳號與行動客服 APP",
                "should_retrieve_knowledge": True,
                "knowledge_query": "雲端帳號 行動客服 APP 登入 使用功能",
            }),
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["intent"], "cloud_account_app_usage")
        self.assertNotIn("寬頻方案", result["knowledge_query"])

        reply = build_cloud_account_app_usage_reply(result["intent"])
        self.assertIn("下載並安裝行動客服 APP", reply)
        self.assertIn("雲端帳號與密碼登入", reply)
        self.assertIn("線上報修、帳單查詢、紅利點數查詢及繳費", reply)

    def test_basic_channel_query_uses_official_channel_table_link(self):
        result = run_intent_router(
            "基本頻道可以看哪幾台？",
            {"company_code": "wctv", "known_info": {}},
            [],
            llm_with_router_response({
                "route": "knowledge_query",
                "intent": "basic_channel_table_query",
                "topic": "基本頻道表",
                "should_retrieve_knowledge": True,
                "knowledge_query": "基本頻道 有線電視頻道 頻道表 官網查詢",
            }),
        )

        self.assertEqual(result["route"], "knowledge_query")
        self.assertEqual(result["intent"], "basic_channel_table_query")
        self.assertNotIn("方案", result["knowledge_query"])

        reply = ensure_known_link_mentions(
            build_basic_channel_table_reply(result["intent"]),
            {"company_code": "wctv"},
        )
        self.assertIn("基本頻道就是有線電視頻道", reply)
        self.assertIn("頻道查詢頁面", reply)
        self.assertIn("https://wctv.com.tw/", reply)

    def test_feedback_direct_replies_follow_customer_service_suggestions(self):
        examples = [
            ("我要更換網路分享器", "router_replacement_clarify", "電腦網卡更換註冊"),
            ("DS 燈閃爍是正常嗎？", "ds_light_blinking", "持續閃爍"),
            ("我想線上繳費半年，要怎麼做", "half_year_online_payment", "無法直接協助更改繳別"),
            ("如何註冊會員", "member_registration_policy", "無須另外註冊"),
            ("60M/6M：月繳 790 元、，是含哈tv費用嗎", "hatv_hanet_790_includes_tv", "包含有線電視與寬頻網路"),
            ("哈tv+哈net990", "hatv_hanet_990_price", "月繳 990 元"),
            ("爸氣有禮月繳需綁定循環扣款嗎", "dad_gift_autopay_requirement", "一律需綁定循環扣款"),
            ("ㄏㄚtv是自行繳費的，為啥這個就要綁定循環扣款？", "hatv_combo_autopay_explanation", "單獨申裝有線電視不需綁約"),
            ("機上盒同地址移動，如何付費", "set_top_box_relocation_payment", "現場收取現金"),
            ("請問怎麼獲取無線網路", "wireless_network_acquisition_clarify", "新申請寬頻網路"),
            ("如果在app，線上繳完費，會去實體收據，到家嗎", "app_payment_receipt_lookup", "發票號碼會於營業日以簡訊通知"),
            ("協助登入或使用雲端帳號", "cloud_account_app_usage", "行動客服 APP"),
            ("沒有節目", "tv_no_program_clarify", "部分頻道無法收視"),
            ("是可以上網，但是一樓電視常訊號不穩", "tv_signal_instability_repair", "維修申告流程"),
            ("預繳方式", "prepay_bill_lookup", "是否有待繳帳單"),
        ]

        for text, intent, expected in examples:
            with self.subTest(text=text):
                result = detect_safe_direct_reply(text, {"company_code": "cnt", "known_info": {}})
                self.assertEqual(result["intent"], intent)
                self.assertIn(expected, result["reply"])

    def test_contextual_feedback_followups_do_not_use_stale_topics(self):
        def fail_if_called(_input):
            raise AssertionError("feedback history rule should route before the LLM")

        cases = [
            (
                "查詢",
                [
                    {"role": "user", "content": "最近網路很不穩，發生什麼事了。"},
                    {"role": "assistant", "content": "目前佳光電訊-台中市區沒有區域故障公告。若您家中網路仍持續不穩，我先帶您做簡單排除。"},
                ],
                "direct_reply",
                "history_network_outage_instability_followup_rule",
            ),
            (
                "如何執行",
                [
                    {"role": "user", "content": "最近網路很不穩，發生什麼事了。"},
                    {"role": "assistant", "content": "佳光電訊-台中市區資訊：區域故障：目前無公告"},
                ],
                "direct_reply",
                "history_network_troubleshooting_execution_followup",
            ),
            (
                "回報故障",
                [
                    {"role": "user", "content": "遙控器開關接觸不良"},
                    {"role": "assistant", "content": "遙控器沒有反應時，請先確認遙控器按鍵時是否有亮紅燈。"},
                ],
                "direct_reply",
                "history_remote_repair_followup_rule",
            ),
            (
                "如何申請",
                [
                    {"role": "assistant", "content": "【方案名稱】爸氣獻禮\n【活動期間】115.08.01～115.09.30"},
                    {"role": "user", "content": "爸氣有禮"},
                ],
                "direct_reply",
                "history_promotion_application_followup_rule",
            ),
            (
                "聯網機上盒",
                [
                    {"role": "user", "content": "哈TV可以使用YouTube嗎？"},
                    {"role": "assistant", "content": "建議確認是否需改用支援的聯網設備。"},
                ],
                "direct_reply",
                "history_connected_stb_youtube_followup_rule",
            ),
            (
                "2",
                [
                    {"role": "assistant", "content": "請問您想了解哪一項加值服務？\n1. LINE TV\n2. WiFi 加值服務\n3. 居家智慧攝影機\n4. 熊搭心"},
                ],
                "direct_reply",
                "history_value_added_option_2_wifi_rule",
            ),
        ]

        for text, history, route, reason in cases:
            with self.subTest(text=text):
                result = run_intent_router(
                    user_input=text,
                    memory={"company_code": "cnt", "known_info": {}},
                    history=history,
                    llm=RunnableLambda(fail_if_called),
                )
                self.assertEqual(result["route"], route)
                self.assertEqual(result["reason"], reason)

    def test_llm_stop_watching_interrupts_pending_bill_lookup(self):
        router_llm = llm_with_router_response({
            "route": "clarify",
            "intent": "stop_watching_clarify",
            "tool_name": None,
            "topic": "退租或暫停收看",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "了解，請問您是想辦理退租／終止服務，還是想暫停收看一段時間？",
            "extracted_slots": {},
            "reason": "llm_stop_watching_clarify",
        })

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="不想看了",
                memory={
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["name", "phone"],
                    "known_info": {
                        "_identity_lookup_failure_count": 1,
                        "_identity_lookup_failure_tool": "search_bill",
                    },
                },
                history=[
                    {"role": "user", "content": "本期帳單金額查詢"},
                    {"role": "assistant", "content": "可以，我幫您查詢帳單。請提供戶名與聯絡電話。"},
                    {"role": "user", "content": "康通益 0910510278"},
                    {"role": "assistant", "content": "查詢不到您的資料，請確認戶名與電話是否與帳務資料一致。"},
                ],
                llm=router_llm,
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "stop_watching_clarify")
        self.assertIn("退租", result["ai_response"])
        self.assertNotEqual(result["memory"].get("known_info", {}).get("name"), "不想看了")

    def test_feedback_general_channel_followup_after_e004_uses_authorization_reply(self):
        result = detect_contextual_feedback_direct_reply(
            "一般頻道的",
            [
                {"role": "user", "content": "E004錯誤碼"},
                {"role": "assistant", "content": "請先切到 200 頻道以下的一般基本頻道確認是否可以收看。如果一般基本頻道也顯示未授權，再請客服協助確認授權狀態。"},
            ],
            {"company_code": "cnt", "known_info": {}},
        )

        self.assertEqual(result["intent"], "general_channel_e004_temp_restore_clarify")
        self.assertIn("收視費是否已繳清", result["reply"])

    def test_feedback_cnt_609741_authorization_followup_uses_paid_seasonal_reply(self):
        def fail_if_called(_prompt):
            raise AssertionError("CNT authorization feedback rule should route before LLM")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="test-user",
                user_text="沒辦法收視，顯示授權過期",
                memory={"company_code": "cnt", "known_info": {}},
                history=[
                    {"role": "user", "content": "想詢問一下，目前我第四台用季繳，是不是有贈送HBO頻道？"},
                    {"role": "assistant", "content": "可以，我幫您查詢目前服務內容與合約資訊。請提供戶名與聯絡電話。"},
                    {"role": "user", "content": "609741"},
                    {"role": "assistant", "content": "查詢不到您的資料，請先確認客戶編號是否正確。"},
                ],
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "cnt_seasonal_authorization_paid")
        self.assertIn("目前無費用需繳納", result["ai_response"])
        self.assertIn("HBO 頻道 CH221", result["ai_response"])

    def test_feedback_numeric_value_added_followup_uses_remembered_wifi_topic(self):
        result = detect_safe_direct_reply(
            "2",
            {"known_info": {"last_value_added_topic": "WiFi 加值服務"}},
        )

        self.assertEqual(result["intent"], "wifi_value_added_service")
        self.assertIn("WiFi 5 系列分享器", result["reply"])
        self.assertIn("WiFi 6 系列分享器", result["reply"])

    def test_feedback_network_instability_question_checks_outage_before_clarifying(self):
        def fail_if_called(_prompt):
            raise AssertionError("network outage instability rule should route before LLM")

        memory = {"company_code": "toplight", "known_info": {}}
        history = []

        with patch("app.handlers.chat_handler.log_chat_latency"):
            first = handle_chat_message(
                user_id="test-user",
                user_text="最近網路很不穩，發生什麼事了。",
                memory=memory,
                history=history,
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )
            history.extend([
                {"role": "user", "content": "最近網路很不穩，發生什麼事了。"},
                {"role": "assistant", "content": first["ai_response"]},
            ])
            second = handle_chat_message(
                user_id="test-user",
                user_text="查詢",
                memory=first["memory"],
                history=history,
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(first["router"]["intent"], "network_outage_instability_check")
        self.assertIn("佳光電訊-台中市區沒有區域故障公告", first["ai_response"])
        self.assertIn("數據機電源", first["ai_response"])
        self.assertEqual(second["router"]["intent"], "network_outage_instability_check")
        self.assertIn("佳光電訊-台中市區沒有區域故障公告", second["ai_response"])

    def test_feedback_clarify_option_two_maps_to_wifi_value_added_service(self):
        memory = {
            "clarify_context": {
                "topic": "加值服務",
                "intent": "value_added_service_clarification",
                "options": get_clarify_context("加值服務")["options"],
            },
            "known_info": {},
        }

        result = resolve_clarify_context("2", memory)

        self.assertEqual(result["intent"], "wifi_value_added_service")
        self.assertIn("WiFi 5 系列分享器", result["reply"])

    def test_modem_ds_light_blinking_is_network_troubleshooting(self):
        memory = {"known_info": {}}

        result = apply_troubleshooting_engine(
            "DS 燈閃爍是正常嗎？",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )

        self.assertEqual(memory["known_info"]["troubleshooting_type"], "network")
        self.assertIn("燈號異常", result["reply"])

    def test_feedback_sep_1_2_direct_router_rules(self):
        cases = [
            ("網路是獨立的還是區域共用？", "network_line_ownership", "學舍"),
            ("app沒有超商繳費條碼嗎", "app_convenience_store_barcode", "待繳帳單"),
            ("請問有打電話給我有什麼事？", "outbound_call_lookup_handoff", "無法查詢是否有客服人員外撥"),
            ("無法在便利商店繳費", "convenience_store_payment_failed", "補發簡訊帳單"),
            ("請問基本頻道跟數位頻道是什麼區別？", "basic_vs_digital_channel", "額外的數位付費套餐"),
            ("手機條碼載具設定電子發票", "invoice_carrier_binding", "用戶歸戶2"),
            ("可以依地址來查網路速率嗎", "address_service_plan_lookup_handoff", "無法依地址查詢"),
            ("電視一直卡在機上盒教學", "stb_tutorial_stuck", "恢復原廠預設"),
            ("能夠轉換合約嗎？", "contract_change_guidance", "想改成哪一個方案"),
            ("費用查詢", "generic_fee_lookup_clarification", "哪一類費用"),
            ("我只要裝有線電視", "pure_tv_install_query", "真人客服協助確認"),
            ("再高一階多少錢", "next_tier_plan_fee_guidance", "實際月費差額"),
        ]

        for text, intent, expected in cases:
            with self.subTest(text=text):
                result = detect_safe_direct_reply(text, {"company_code": "cnt", "known_info": {}})
                self.assertEqual(result["intent"], intent)
                self.assertIn(expected, result["reply"])

        tv_promotion = detect_safe_direct_reply(
            "有線電視有甚麼優惠",
            {"company_code": "cnt", "known_info": {}},
        )
        self.assertEqual(tv_promotion["intent"], "pure_tv_promotion_query")
        self.assertTrue(tv_promotion["should_retrieve_knowledge"])
        self.assertIn("基本收費標準", tv_promotion["knowledge_query"])

        address_result = detect_safe_direct_reply(
            "可以依地址來查網路速率嗎",
            {"company_code": "tdtv", "known_info": {}},
        )
        self.assertNotIn("服務地址核對", address_result["reply"])
        self.assertIn("客戶編號", address_result["reply"])

    def test_feedback_direct_router_rules_preserve_rule_ids(self):
        def fail_if_called(_prompt):
            raise AssertionError("golden direct-router cases should route before LLM")

        cases = [
            (
                "app沒有超商繳費條碼嗎",
                {"company_code": "cnt", "known_info": {}},
                "direct_reply",
                "app_convenience_store_barcode",
                "direct_app_convenience_store_barcode_rule",
            ),
            (
                "費用查詢",
                {"company_code": "cnt", "known_info": {}},
                "clarify",
                "generic_fee_lookup_clarification",
                "direct_generic_fee_lookup_clarification_rule",
            ),
            (
                "LINE TV",
                {"company_code": "tdtv", "known_info": {}},
                "clarify",
                "line_tv_topic_clarification",
                "direct_line_tv_topic_clarification_rule",
            ),
            (
                "我只要裝有線電視",
                {"company_code": "cnt", "known_info": {}},
                "direct_reply",
                "pure_tv_install_query",
                "direct_pure_tv_install_handoff_rule",
            ),
            (
                "再高一階多少錢",
                {"company_code": "cnt", "known_info": {}},
                "direct_reply",
                "next_tier_plan_fee_guidance",
                "direct_next_tier_plan_fee_guidance_rule",
            ),
            (
                "手機條碼載具設定電子發票",
                {"company_code": "wctv", "known_info": {}},
                "direct_reply",
                "invoice_carrier_binding",
                "direct_invoice_carrier_knowledge_rule",
            ),
            (
                "網路是獨立的還是區域共用？",
                {"company_code": "toplight", "known_info": {}},
                "direct_reply",
                "network_line_ownership",
                "direct_network_line_ownership_rule",
            ),
        ]

        for text, memory, route, intent, rule_id in cases:
            with self.subTest(text=text):
                result = run_intent_router(
                    user_input=text,
                    memory=memory,
                    history=[],
                    llm=RunnableLambda(fail_if_called),
                )

                self.assertEqual(result["route"], route)
                self.assertEqual(result["intent"], intent)
                self.assertEqual(result["matched_rule_id"], rule_id)

    def test_router_decision_does_not_treat_llm_reason_as_rule_id(self):
        result = RouterDecision.from_raw(
            {
                "route": "knowledge_query",
                "intent": "billing_question",
                "reason": "使用者詢問帳務內容，需查詢知識庫。",
            },
            supported_tools=[],
        ).to_router_dict()

        self.assertIsNone(result["matched_rule_id"])

    def test_feedback_sep_1_2_sms_and_payment_followups(self):
        sms = detect_safe_direct_reply(
            "1310815",
            {"pending_tool": "send_message", "known_info": {}},
        )
        self.assertEqual(sms["intent"], "sms_bill_registered_phone_policy")
        self.assertIn("帳務系統登記的電話", sms["reply"])

        paid = detect_safe_direct_reply("線上繳費的", {"known_info": {}})
        self.assertEqual(paid["intent"], "online_payment_done_activation")
        self.assertIn("重啟數據機或機上盒", paid["reply"])

    def test_feedback_sep_1_2_contextual_tv_only_promotion(self):
        result = run_intent_router(
            user_input="有甚麼優惠",
            memory={"company_code": "cnt", "known_info": {}},
            history=[
                {"role": "user", "content": "有線電視有甚麼優惠"},
                {"role": "assistant", "content": "請問是只裝有線電視，還是有線電視加網路？"},
                {"role": "user", "content": "我只要裝有線電視"},
            ],
            llm=llm_with_router_response({
                "route": "knowledge_query",
                "intent": "pure_tv_promotion_query",
                "topic": "純有線電視優惠",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "純有線電視 基本收費標準 優惠",
                "reply": "",
                "extracted_slots": {},
                "reason": "model_tv_only_promotion_followup",
            }),
        )

        self.assertEqual(result["intent"], "pure_tv_promotion_query")
        self.assertTrue(result["should_retrieve_knowledge"])
        self.assertIn("基本收費標準", result["knowledge_query"])

    def test_feedback_payment_clarify_option_one_shows_payment_methods(self):
        result = run_intent_router(
            user_input="1",
            memory={"company_code": "cnt", "known_info": {}},
            history=[
                {"role": "user", "content": "繳費"},
                {"role": "assistant", "content": "請問您是想查詢繳費方式、確認是否繳費成功，還是申請繳費後復線呢？"},
            ],
            llm=RunnableLambda(lambda _: (_ for _ in ()).throw(AssertionError("active state unexpectedly invoked the model"))),
        )

        self.assertEqual(result["intent"], "bill_payment_methods")
        self.assertIn("超商繳費", result["reply"])

    def test_feedback_sep_1_2_contract_lookup_is_deterministic(self):
        def fail_if_called(_prompt):
            raise AssertionError("contract lookup should route before LLM")

        result = run_intent_router(
            user_input="我的合約到什麼時候",
            memory={"company_code": "cnt", "known_info": {}},
            history=[],
            llm=RunnableLambda(fail_if_called),
        )

        self.assertEqual(result["intent"], "service_content_query")
        self.assertEqual(result["tool_name"], "search_contract_info")

    def test_feedback_sep_1_2_active_flow_switches_to_line_tv_and_fee(self):
        def fail_if_called(_prompt):
            raise AssertionError("archived active-flow rule unexpectedly invoked the model")

        base_memory = {
            "company_code": "cnt",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_input_source",
            },
        }
        history = [
            {"role": "user", "content": "機上盒排除"},
            {"role": "assistant", "content": "請先確認訊號源是否正確。"},
        ]

        with patch("app.handlers.chat_handler.log_chat_latency"):
            line_tv = handle_chat_message(
                user_id="test-user",
                user_text="LINE TV",
                memory=json.loads(json.dumps(base_memory)),
                history=history,
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )
            fee = handle_chat_message(
                user_id="test-user",
                user_text="費用查詢",
                memory=json.loads(json.dumps(base_memory)),
                history=history,
                llm=RunnableLambda(fail_if_called),
                persist=False,
            )

        self.assertEqual(line_tv["router"]["intent"], "line_tv_topic_clarification")
        self.assertIn("LINE TV 的哪一種問題", line_tv["ai_response"])
        self.assertEqual(fee["router"]["intent"], "generic_fee_lookup_clarification")
        self.assertIn("哪一類費用", fee["ai_response"])

    def test_feedback_sep_1_2_troubleshooting_terms(self):
        self.assertTrue(is_network_fault("網路無訊號"))
        self.assertFalse(is_tv_fault("網路無訊號"))
        self.assertTrue(is_network_fault("線路不通"))
        self.assertTrue(is_network_fault("網路掛了"))
        self.assertTrue(is_network_fault("無法連網"))
        self.assertTrue(is_tv_fault("哈tv没有聲音"))
        self.assertTrue(is_tv_fault("有線電視訊息看到一半會中斷"))

        slow = apply_troubleshooting_engine(
            "網路速度300Kbps 請人員來維修",
            {"known_info": {}},
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )
        self.assertIn("重新啟動數據機", slow["reply"])
        self.assertIn("安排工程人員協助", slow["reply"])

        partial = apply_troubleshooting_engine(
            "都不是，就是特定幾台不見了",
            {"known_info": {}},
            {"reply": "", "should_call_tool": False, "tool_name": None},
        )
        self.assertIn("重新搜頻", partial["reply"])

    def test_feedback_fault_phrases_continue_after_llm_troubleshooting_route(self):
        scenarios = (
            ("網路掛了", "network", "net_check_scope"),
            ("無法連網", "network", "net_check_scope"),
            ("有線電視訊息看到一半會中斷", "tv", "tv_check_power"),
        )
        for user_text, expected_type, expected_step in scenarios:
            router_llm = llm_with_router_response({
                "route": "troubleshooting",
                "intent": "feedback_fault_test",
                "tool_name": None,
                "topic": "故障",
                "should_cancel_current_flow": False,
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "reply": "",
                "extracted_slots": {},
                "reason": "llm_troubleshooting_route",
            })
            with self.subTest(user_text=user_text), patch("app.handlers.chat_handler.log_chat_latency"):
                result = handle_chat_message(
                    user_id="test-user",
                    user_text=user_text,
                    memory={"company_code": "tdtv", "known_info": {}},
                    history=[],
                    llm=router_llm,
                    persist=False,
                )

            self.assertEqual(result["router"]["route"], "troubleshooting")
            self.assertEqual(result["memory"]["known_info"]["troubleshooting_type"], expected_type)
            self.assertEqual(result["memory"]["known_info"]["troubleshooting_step"], expected_step)

if __name__ == "__main__":
    unittest.main()
