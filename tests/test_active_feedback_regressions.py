import json
import unittest

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import (
    build_app_payment_receipt_lookup_reply,
    build_fixed_ip_binding_knowledge_fallback,
    build_next_tier_plan_fallback,
    build_promotion_catalog_reply,
    build_knowledge_summary,
    build_payment_cycle_evidence_fallback,
    carry_forward_same_intent_evidence,
    build_unpaid_partial_payment_router,
    build_plan_from_router,
    disable_repair_ticket_flow,
    detect_active_flow_switch,
    ensure_known_link_mentions,
    format_customer_reply_text,
    is_likely_slot_answer,
    is_unpaid_partial_payment_question,
    is_unpaid_reactivation_request,
)
from app.services.troubleshooting_engine import apply_troubleshooting_engine
from app.services.troubleshooting_engine import record_declared_speed_gap
from app.services.slot_manager import (
    build_missing_args_question,
    extract_slots_from_text,
    get_missing_tool_args,
    merge_slots_into_memory,
)
from app.app_backend import clean_external_link_url
from app.services.company_profile import build_company_info_reply


class ActiveFeedbackRegressionTest(unittest.TestCase):
    def test_declared_speed_gap_survives_a_followup_with_only_measured_speed(self):
        known = {}

        declared, measured = record_declared_speed_gap(
            known,
            "申請300M，測速只有30M",
        )
        followup_declared, followup_measured = record_declared_speed_gap(
            known,
            "有線單機重測還是只有30M",
        )

        self.assertEqual((declared, measured), (300.0, 30.0))
        self.assertEqual((followup_declared, followup_measured), (300.0, 30.0))

    def test_declared_speed_gap_moves_from_single_retest_to_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_slow_scope",
                "retry": 2,
            }
        }
        plan = {"reply": "", "should_call_tool": False, "tool_name": None}

        first = apply_troubleshooting_engine(
            "申請300M，測速只有30M",
            memory,
            dict(plan),
        )
        second = apply_troubleshooting_engine(
            "有線單機重測還是只有30M",
            memory,
            dict(plan),
        )

        self.assertFalse(first["should_call_tool"])
        self.assertIn("300 Mbps", first["reply"])
        self.assertIn("30 Mbps", first["reply"])
        self.assertFalse(second["should_call_tool"])
        self.assertIsNone(second["tool_name"])
        self.assertEqual(second["intent"], "human_handoff_offer")
        self.assertIn("是否需要", second["reply"])

    def test_new_customer_number_replaces_prior_pending_value(self):
        memory = {
            "pending_tool": "search_bill",
            "pending_tool_args": ["identity_pair"],
            "known_info": {"custnum": "1145934"},
        }

        slots = extract_slots_from_text("59889", memory, "search_bill", llm=None)
        merge_slots_into_memory(memory, slots)
        missing = get_missing_tool_args("search_bill", memory)
        question = build_missing_args_question("search_bill", missing, memory)

        self.assertEqual(memory["known_info"]["custnum"], "59889")
        self.assertEqual(missing, ["identity_pair"])
        self.assertIn("已更新客戶編號", question)
        self.assertIn("戶名或登記電話", question)

    def test_repeated_customer_number_is_received_without_claiming_an_update(self):
        memory = {
            "pending_tool": "search_bill",
            "pending_tool_args": ["identity_pair"],
            "known_info": {"custnum": "59889"},
        }

        slots = extract_slots_from_text("59889", memory, "search_bill", llm=None)
        merge_slots_into_memory(memory, slots)
        missing = get_missing_tool_args("search_bill", memory)
        question = build_missing_args_question("search_bill", missing, memory)

        self.assertIn("已收到這個客戶編號", question)
        self.assertNotIn("已更新客戶編號", question)

    def test_network_install_request_is_not_mistaken_for_an_address_slot(self):
        self.assertFalse(is_likely_slot_answer("同時申裝有線網路"))

    def test_tv_playback_interruption_reboots_before_channel_rescan(self):
        result = apply_troubleshooting_engine(
            "有線電視訊息看到一半會中斷",
            {"known_info": {}},
            {
                "intent": "tv_picture_quality_issue",
                "reply": "",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        self.assertIn("電源拔掉約 10 秒", result["reply"])
        self.assertNotIn("重新搜頻", result["reply"])
        self.assertEqual(
            result.get("tool_name"),
            None,
        )

    def test_tv_no_sound_checks_audio_connection_before_reboot(self):
        result = apply_troubleshooting_engine(
            "哈tv沒有聲音",
            {"known_info": {}},
            {
                "intent": "tv_audio_issue",
                "reply": "",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        self.assertIn("靜音", result["reply"])
        self.assertIn("音量", result["reply"])
        self.assertIn("HDMI 或 AV", result["reply"])
        self.assertIn("電源拔掉約 10 秒", result["reply"])

    def test_next_tier_reply_uses_dynamic_rate_lines_before_contract_details(self):
        reply = build_next_tier_plan_fallback(
            [
                {
                    "campaign_name": "動態升級方案",
                    "answer": (
                        "1.100M/10M：月繳 880 元、年繳 10,560 元\n"
                        "2.300M/300M：月繳 980 元、年繳 11,760 元\n"
                        "3.500M/500M：月繳 1,080 元、年繳 12,960 元\n"
                        "四、舊戶是否可參加：舊戶無合約可參加。\n"
                        "五、中途升級資格需依目前合約確認。"
                    ),
                }
            ],
            user_text="原用戶想從100M升級，下一階有什麼方案？",
        )

        self.assertIn("動態升級方案", reply)
        self.assertIn("300M/300M", reply)
        self.assertIn("中途升級資格需依目前合約確認", reply)
        self.assertNotIn("100M/10M", reply)
        self.assertNotIn("500M/500M", reply)
        self.assertNotIn("四、", reply)
        self.assertNotIn("五、", reply)
        formatted_reply = format_customer_reply_text(reply)
        self.assertNotIn("\n是否可\n", formatted_reply)
        self.assertIn("中途升級資格需依目前合約確認", formatted_reply)

    def test_installation_address_guidance_uses_current_company_profile(self):
        reply = build_company_info_reply("installation_address_guidance", "tdtv")

        self.assertIn("服務地區", reply)
        self.assertIn("完整裝機地址", reply)
        self.assertIn("線路與施工條件", reply)
        self.assertNotIn("優惠方案", reply)

    def test_boot_screen_after_repair_handoff_does_not_repeat_reboot(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_reboot",
                "repair_followup_active": "yes",
                "repair_ready": "no",
                "issue_description": "機上盒持續重複開機或停在開機畫面",
            }
        }

        result = apply_troubleshooting_engine(
            "開機中請稍後的畫面",
            memory,
            {
                "intent": "tv_set_top_box_boot_issue",
                "reply": "",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        self.assertIn("轉接真人文字客服", result["reply"])
        self.assertIn("不需要再重複重新插電", result["reply"])
        self.assertFalse(result["should_call_tool"])

    def test_targeted_catalog_only_renders_requested_speed_and_cycle(self):
        docs = [
            {
                "campaign_name": "動態方案甲",
                "document_type": "promotion_campaign",
                "record_type": "campaign_rate",
                "service_types": "電視網路同裝",
                "answer": (
                    "60M/6M：月繳 790 元、年繳 9,480 元\n"
                    "100M/10M：月繳 890 元、年繳 10,680 元"
                ),
            },
            {
                "campaign_name": "動態方案乙",
                "document_type": "promotion_campaign",
                "record_type": "campaign_rate",
                "service_types": "電視網路同裝",
                "answer": "500M/500M：月繳 1,299 元、年繳 15,588 元",
            },
        ]

        reply = build_promotion_catalog_reply(
            "新申裝100M電視加網路一個月多少錢？",
            docs,
            intent="tv_network_install_plan_query",
            promotion_scope="tv_network",
            promotion_query_kind="catalog",
        )

        self.assertIn("動態方案甲", reply)
        self.assertIn("100M/10M：月繳 890 元", reply)
        self.assertIn("包含有線電視與寬頻網路服務", reply)
        self.assertNotIn("60M/6M", reply)
        self.assertNotIn("500M/500M", reply)
        self.assertNotIn("年繳", reply)
        self.assertNotIn("請輸入想了解的方案名稱", reply)

    def test_no_power_followup_without_light_moves_to_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power_cable",
                "issue_description": "機上盒已插電但沒有亮燈",
                "retry": 0,
            }
        }
        llm = RunnableLambda(lambda _prompt: AIMessage(content='{"label":"unknown"}'))

        result = apply_troubleshooting_engine(
            "沒有",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
            llm=llm,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIsNone(result["tool_name"])
        self.assertEqual(result["intent"], "human_handoff_offer")
        self.assertIn("是否需要", result["reply"])
        self.assertNotIn("電源是否有亮燈", result["reply"])

    def test_speed_gap_repair_followup_does_not_restart_retest(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_speed_retest",
                "repair_followup_active": "yes",
                "repair_ready": "no",
                "declared_plan_speed_mbps": 300.0,
                "download_speed": 30.0,
            }
        }

        result = apply_troubleshooting_engine(
            "就跟你說測速不達，是聽不懂嗎",
            memory,
            {
                "intent": "internet_slow_buffering",
                "reply": "",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIn("不需要再重複測速", result["reply"])
        self.assertNotIn("網路線直接連接", result["reply"])

    def test_no_power_repair_followup_does_not_restart_light_check(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power_cable",
                "repair_followup_active": "yes",
                "repair_ready": "no",
                "issue_description": "機上盒已插電但沒有亮燈",
            }
        }

        result = apply_troubleshooting_engine(
            "有插電。無亮燈",
            memory,
            {
                "intent": "tv_set_top_box_unresponsive_issue",
                "reply": "",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIn("不需要再重複確認燈號", result["reply"])
        self.assertNotIn("請先確認機上盒電源", result["reply"])

    def test_disabling_repair_tool_preserves_confirmed_issue_context(self):
        memory = {
            "known_info": {
                "issue_description": "機上盒電源燈不亮",
                "service_address": "測試地址",
            }
        }

        disable_repair_ticket_flow(memory, "create_repair_ticket")

        self.assertEqual(
            memory["known_info"]["issue_description"],
            "機上盒電源燈不亮",
        )
        self.assertNotIn("service_address", memory["known_info"])
        self.assertEqual(memory["known_info"]["repair_followup_active"], "yes")

    def test_explicit_unpaid_partial_payment_blocks_reactivation(self):
        self.assertTrue(
            is_unpaid_partial_payment_question("我費用沒繳，可以先繳電視就好嗎")
        )

        router = build_unpaid_partial_payment_router()

        self.assertEqual(router["route"], "direct_reply")
        self.assertFalse(router["should_call_tool"])
        self.assertIsNone(router["tool_name"])
        self.assertIn("不會直接執行復線", router["reply"])
        self.assertIn("官網或哈TV行動客服 APP", router["reply"])

    def test_future_payment_cannot_start_reactivation(self):
        self.assertTrue(
            is_unpaid_reactivation_request("可以先幫我恢復嗎？我晚點去繳")
        )
        self.assertFalse(
            is_unpaid_reactivation_request("我已經繳費了，可以幫我恢復嗎？")
        )

    def test_app_invoice_followup_uses_history_bill_only(self):
        reply = build_app_payment_receipt_lookup_reply(
            "app_payment_receipt_lookup",
            "行動客服可以查發票嗎",
        )

        self.assertIn("歷史帳單", reply)
        self.assertNotIn("用戶資訊", reply)
        self.assertNotIn("載具歸戶", reply)

    def test_fixed_ip_missing_fee_data_still_uses_answer_model_for_process(self):
        captured = {}

        def answer(prompt):
            captured["prompt"] = str(prompt)
            return AIMessage(
                content=(
                    "請先由真人客服確認當期可申請 9 個固定 IP、追加費用 321 元；"
                    "申請完成後，到［台基科官網🔗］https://www.tinp.net.tw/ "
                    "依序進入會員登入、綁定固定 IP，選擇設備設定，完成後重新啟動設備。"
                )
            )

        reply = build_fixed_ip_binding_knowledge_fallback(
            "我要綁定固定IP",
            "fixed_ip_binding_guidance",
            docs=[{
                "question": "當期固定 IP 規則",
                "answer": "當期可申請 9 個固定 IP，追加費用 321 元。",
            }],
            llm=RunnableLambda(answer),
            memory={"company_code": "tdtv"},
        )

        self.assertIn("真人客服", reply)
        self.assertIn("確認當期可申請 9 個固定 IP", reply)
        self.assertIn("重新啟動", reply)
        self.assertIn("https://www.tinp.net.tw/", reply)
        self.assertIn("321 元", reply)
        self.assertIn("當期可申請 9 個固定 IP", captured["prompt"])
        self.assertIn("不可自行補數量或價格", captured["prompt"])

    def test_external_url_stops_before_chinese_prose(self):
        value = "https://www.tinp.net.tw/，依序選擇「會員登入」"

        self.assertEqual(clean_external_link_url(value), "https://www.tinp.net.tw/")

    def test_named_external_website_link_does_not_append_company_homepage(self):
        reply = (
            "台基科官網：https://www.tinp.net.tw/ "
            "進入「網速推薦工具」→「網速測試」。"
        )

        result = ensure_known_link_mentions(reply, {"company_code": "tdtv"})

        self.assertEqual(result, reply)
        self.assertNotIn("https://www.tdtv.com.tw/", result)

    def test_unlinked_company_website_mention_still_gets_company_homepage(self):
        reply = "請至官網查看最新公告。"

        result = ensure_known_link_mentions(reply, {"company_code": "tdtv"})

        self.assertIn("官網：［官網\U0001f517］https://www.tdtv.com.tw/", result)

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

    def test_repeated_mosaic_description_does_not_become_repair_handoff(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_rescan_channels",
                "retry": 0,
            }
        }
        llm = RunnableLambda(lambda _prompt: AIMessage(content='{"label":"failed"}'))

        result = apply_troubleshooting_engine(
            "畫面馬賽克",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
            llm=llm,
        )

        self.assertEqual(memory["known_info"]["troubleshooting_step"], "tv_rescan_channels")
        self.assertFalse(result["should_call_tool"])
        self.assertIn("重新搜頻", result["reply"])
        self.assertNotIn("真人客服", result["reply"])

    def test_active_flow_keeps_same_service_model_intent(self):
        router_payload = {
            "route": "troubleshooting",
            "intent": "tv_picture_quality_issue",
            "topic": "電視畫質異常",
            "service_scope": "有線電視",
            "requested_information": "畫質排錯",
            "reply": "",
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "extracted_slots": {},
            "reason": "model_tv_picture_issue",
        }
        llm = RunnableLambda(
            lambda _prompt: AIMessage(content=json.dumps(router_payload, ensure_ascii=False))
        )
        memory = {
            "company_code": "tdtv",
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_check_power",
            },
        }

        result = detect_active_flow_switch("電視收訊差", memory, [], llm, {})

        self.assertIsNotNone(result)
        self.assertFalse(result["should_cancel_current_flow"])
        self.assertEqual(result["intent"], "tv_picture_quality_issue")

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

        self.assertFalse(result["should_call_tool"])
        self.assertIsNone(result["tool_name"])
        self.assertEqual(result["intent"], "human_handoff_offer")
        self.assertIn("是否需要", result["reply"])
        self.assertIn("請勿自行碰觸", result["reply"])
        self.assertNotIn("電源燈", result["reply"])

    def test_outdoor_line_repair_followup_does_not_fall_back_to_generic_menu(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "no",
                "troubleshooting_type": "tv",
                "troubleshooting_step": "tv_rescan_channels",
                "repair_followup_active": "yes",
                "repair_ready": "no",
                "issue_description": "室外的電源線有鬆脫",
            }
        }

        result = apply_troubleshooting_engine(
            "有",
            memory,
            {
                "intent": "repair_ticket_request",
                "reply": "請問您想查詢資料、辦理服務，還是回報故障呢？",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIsNone(result["tool_name"])
        self.assertEqual(result["intent"], "human_handoff_offer")
        self.assertIn("是否需要", result["reply"])
        self.assertIn("請勿自行碰觸", result["reply"])
        self.assertNotIn("請問您想查詢資料", result["reply"])

    def test_relocation_summary_receives_a_strict_topic_focus(self):
        captured = {}

        def answer(prompt):
            captured["prompt"] = str(prompt)
            return AIMessage(content="移機費用：室內 500 元。")

        reply = build_knowledge_summary(
            "我要移機，請問流程和可能收費",
            [
                {
                    "question": "移機費與分機費",
                    "answer": "優惠到期恢復原價。移機費：室內 500 元。",
                }
            ],
            llm=RunnableLambda(answer),
            intent="relocation_guidance",
        )

        self.assertEqual(reply, "移機費用：室內 500 元。")
        self.assertIn("只整理移機流程、移機本身的費用與必要條件", captured["prompt"])
        self.assertIn("忽略候選文件中不屬於移機段落", captured["prompt"])
        self.assertIn("不要列分機費、機上盒押金", captured["prompt"])

    def test_channel_rescan_wording_matches_customer_service_guidance(self):
        result = apply_troubleshooting_engine(
            "頻道跑掉了",
            {"known_info": {}},
            {
                "intent": "tv_partial_channel_issue",
                "reply": "",
                "should_call_tool": False,
                "tool_name": None,
            },
        )

        self.assertIn("雙模機且遙控器型號為 TOP-006", result["reply"])
        self.assertIn("雙模機且遙控器型號為 TOP-007", result["reply"])

    def test_repeated_outage_does_not_imply_modem_reboot_was_completed(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "retry": 0,
            }
        }
        llm = RunnableLambda(lambda _prompt: AIMessage(content='{"label":"failed"}'))

        result = apply_troubleshooting_engine(
            "沒有網際網路連線",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
            llm=llm,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertEqual(memory["known_info"]["troubleshooting_step"], "net_reboot_modem")
        self.assertIn("無法確認是否已完成數據機重開", result["reply"])

    def test_explicit_post_reboot_failure_can_move_to_repair(self):
        memory = {
            "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "network",
                "troubleshooting_step": "net_reboot_modem",
                "retry": 0,
            }
        }
        llm = RunnableLambda(lambda _prompt: AIMessage(content='{"label":"failed"}'))

        result = apply_troubleshooting_engine(
            "已經重開數據機了，還是沒有網路",
            memory,
            {"reply": "", "should_call_tool": False, "tool_name": None},
            llm=llm,
        )

        self.assertFalse(result["should_call_tool"])
        self.assertIsNone(result["tool_name"])
        self.assertEqual(result["intent"], "human_handoff_offer")
        self.assertIn("是否需要", result["reply"])

    def test_model_selected_customer_service_intents_use_approved_replies(self):
        repair = build_plan_from_router({
            "route": "direct_reply",
            "intent": "repair_visit_expectation",
            "reply": "立即轉真人",
        })["reply"]
        installation = build_plan_from_router({
            "route": "direct_reply",
            "intent": "installation_visit_expectation",
            "reply": "立即轉真人",
        })["reply"]
        termination = build_plan_from_router({
            "route": "direct_reply",
            "intent": "broadband_termination_guidance",
            "reply": "請撥客服電話",
        })["reply"]
        points = build_plan_from_router({
            "route": "direct_reply",
            "intent": "points_account_merge_policy",
            "reply": "介紹點數用途",
        })["reply"]

        self.assertIn("排程或預約時段", repair)
        self.assertNotIn("真人", repair)
        self.assertEqual(installation, repair)
        self.assertNotIn("維修申告", repair)
        self.assertIn("數據機", termination)
        self.assertNotIn("電話", termination)
        self.assertIn("無法合併或轉移", points)

    def test_fee_summary_prompt_requires_amounts_and_difference(self):
        captured = {}

        def answer(prompt):
            captured["prompt"] = str(prompt)
            return AIMessage(content="月繳 550 元；年繳 6,550 元，月繳 12 個月比年繳多 50 元。")

        reply = build_knowledge_summary(
            "金額呢？月繳跟年繳差多少？",
            [{
                "question": "有線電視基本收視費",
                "answer": "月繳 550 元、年繳 6,550 元。",
            }],
            llm=RunnableLambda(answer),
            intent="cable_tv_payment_cycle_comparison",
        )

        self.assertIn("多 50 元", reply)
        self.assertIn("不可只留下", captured["prompt"])
        self.assertIn("列式計算差額", captured["prompt"])

    def test_relocation_focus_requires_every_explicit_fee(self):
        captured = {}

        def answer(prompt):
            captured["prompt"] = str(prompt)
            return AIMessage(content="有線電視室外移機 800 元；室內移機 500 元。")

        build_knowledge_summary(
            "移機流程和費用",
            [{"question": "移機費", "answer": "室外 800 元；室內 500 元。"}],
            llm=RunnableLambda(answer),
            intent="relocation_guidance",
        )

        self.assertIn("逐項列出所有室內／室外及各服務費用", captured["prompt"])
        self.assertIn("客服電話或服務地區", captured["prompt"])

    def test_same_llm_intent_keeps_previous_relocation_evidence(self):
        previous = {
            "id": "fee-doc",
            "question": "移機費用",
            "answer": "有線電視室外 800 元，室內 500 元。",
        }
        current = {
            "id": "process-doc",
            "question": "移機流程",
            "answer": "完工後收取施工費。",
        }

        merged = carry_forward_same_intent_evidence(
            [current],
            {
                "last_knowledge_intent": "relocation_guidance",
                "last_knowledge_results": [previous],
            },
            "relocation_guidance",
        )

        self.assertEqual([doc["id"] for doc in merged], ["fee-doc", "process-doc"])

    def test_different_llm_intent_does_not_reuse_previous_evidence(self):
        current = {"id": "remote-doc", "answer": "長按學習鍵。"}
        merged = carry_forward_same_intent_evidence(
            [current],
            {
                "last_knowledge_intent": "relocation_guidance",
                "last_knowledge_results": [{"id": "fee-doc", "answer": "800 元"}],
            },
            "remote_power_learning",
        )

        self.assertEqual(merged, [current])

    def test_payment_cycle_fallback_uses_dynamic_document_amounts(self):
        reply = build_payment_cycle_evidence_fallback([
            {
                "answer": (
                    "收視費採年繳$7,100、半年繳$3,570、"
                    "季繳$1,800、月繳$600"
                )
            }
        ])

        self.assertIn("月繳：600 元", reply)
        self.assertIn("年繳：7,100 元", reply)
        self.assertIn("比同期月繳省 100 元", reply)


if __name__ == "__main__":
    unittest.main()
