import json
import re
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.services.intent_router import build_memory_summary
from app.services.model_manager import ModelManager, finish_llm_trace, start_llm_trace
from app.services.router_prompt import (
    RUNTIME_INTENT_INDEX,
    RUNTIME_PROMPT_CORE_INTENTS,
    RUNTIME_PROMPT_INTENT_MODULES,
    build_contextual_runtime_intent_router_rules,
    build_runtime_intent_router_rules,
    select_runtime_policy_keys,
    select_runtime_prompt_modules,
)
from app.services.regional_policy import build_policy_prompt


class UsageChatModel:
    def invoke(self, input_value, config=None, **kwargs):
        return AIMessage(
            content="ok",
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 15,
                "total_tokens": 135,
                "input_token_details": {"cache_read": 80},
            },
        )


class PromptUsageOptimizationTest(unittest.TestCase):
    def test_repair_form_choice_after_guidance_is_in_support_module(self):
        scoped = build_contextual_runtime_intent_router_rules(
            "登記維修",
            {"company_code": "tdtv", "known_info": {
                "troubleshooting_started": "yes",
                "troubleshooting_type": "remote",
                "troubleshooting_step": "remote_check_light",
            }},
            [],
        )
        self.assertIn("已給排錯指引", scoped)
        self.assertIn("自行申告", scoped)
        self.assertIn("repair_form_guidance", scoped)

        active = build_contextual_runtime_intent_router_rules(
            "登記維修",
            {"company_code": "tdtv", "known_info": {"repair_form_available": "yes"}},
            [],
        )
        self.assertIn("提供表單連結不是建立工單", active)
        self.assertNotIn("提供表單連結不是建立工單", scoped)

    def test_remote_pairing_contract_preserves_controller_and_target(self):
        scoped = build_contextual_runtime_intent_router_rules(
            "Panasonic遙控器配對哈TV機上盒",
            {"company_code": "tdtv", "known_info": {}},
            [],
        )

        self.assertIn("主控遙控器", scoped)
        self.assertIn("受控設備", scoped)
        self.assertIn("機上盒遙控器", scoped)
        self.assertIn("學習端", scoped)
        self.assertIn("電視遙控器", scoped)
        self.assertIn("訊號來源", scoped)
        self.assertIn("預設", scoped)
        self.assertIn("不反問", scoped)
        self.assertIn("remote_power_learning", scoped)

    def test_fixed_ip_allocation_statement_continues_to_binding(self):
        scoped = build_contextual_runtime_intent_router_rules(
            "已有固定 IP 數量",
            {"company_code": "tdtv", "last_knowledge_intent": "fixed_ip_binding_guidance", "known_info": {}},
            [],
        )
        self.assertIn("已核配的陳述", scoped)
        self.assertIn("固定 IP 綁定", scoped)
        self.assertIn("未詢問本人核配幾組", scoped)
        self.assertIn("即使提到數量", scoped)
        self.assertIn("direct_reply、intent = fixed_ip_existing_binding_steps", scoped)

    def test_transfer_general_process_contract_is_loaded_without_billing_module(self):
        scoped = build_contextual_runtime_intent_router_rules(
            "了解過戶流程",
            {"company_code": "wctv", "known_info": {}},
            [],
        )
        self.assertIn("過戶共通流程免問服務", scoped)
        self.assertIn("account_holder_change_required_documents", scoped)

    def test_device_troubleshooting_request_loads_support_contract(self):
        modules = select_runtime_prompt_modules(
            "機上盒排除", {"company_code": "tdtv", "known_info": {}}, []
        )
        scoped = build_contextual_runtime_intent_router_rules(
            "機上盒排除", {"company_code": "tdtv", "known_info": {}}, []
        )

        self.assertIn("support", modules)
        self.assertIn("repair_troubleshooting_intake", scoped)

    def test_passed_contracts_remain_in_scoped_prompt(self):
        campaign = build_contextual_runtime_intent_router_rules(
            "2026/08/01裝機~2026/12/31退租要繳多少違約金",
            {"company_code": "tdtv", "last_campaign_topic": "飆網守護家", "known_info": {}},
            [],
        )
        sms = build_contextual_runtime_intent_router_rules(
            "手機沒有收到繳費簡訊",
            {"company_code": "tdtv", "known_info": {}},
            [],
        )

        self.assertIn("promotion_query_kind = campaign_detail", campaign)
        self.assertIn("730 天", campaign)
        self.assertIn("勿答一般退租", campaign)
        self.assertIn("補發簡訊帳單：tool_action、send_message", sms)
        self.assertIn("須戶名與登記電話", sms)

    def test_runtime_router_contract_is_compact_and_keeps_safety_boundaries(self):
        runtime = build_runtime_intent_router_rules()
        contextual = build_contextual_runtime_intent_router_rules(
            "如何登入會員", {"company_code": "tdtv", "known_info": {}}, []
        )

        self.assertLess(len(runtime), 17_500)
        self.assertLess(len(contextual), len(runtime))
        self.assertIn("每輪由你依語意判斷", runtime)
        self.assertIn("不可直接 create_repair_ticket", runtime)
        self.assertIn('internet_reactivation_status = "not_required"', runtime)
        self.assertIn("clarification_options", runtime)
        self.assertIn("selected_option_id", runtime)
        self.assertIn("modem_dual_router_dhcp_guidance", runtime)
        self.assertIn("不可混入網路分機線施工或費用", runtime)
        self.assertIn("company_info 必須輸出精確 topic", runtime)
        self.assertIn("direct_reply 必須輸出 reply", runtime)
        self.assertIn("intent = external_line_loose_repair_request", runtime)
        self.assertIn("intent = remote_control_symptom_clarify", runtime)
        self.assertIn("intent = router_replacement_connection_clarify", runtime)
        self.assertIn("intent = area_outage_inquiry", runtime)
        self.assertIn("intent = payment_suspension_service_clarify", runtime)
        self.assertIn("intent = broadband_suspend_or_termination_guidance", runtime)
        self.assertIn("intent = service_signal_type_clarify", runtime)
        self.assertIn("personal_contract_info_lookup", runtime)
        self.assertIn("不是 member_login_guidance", runtime)
        self.assertIn("intent = broadband_termination_guidance", runtime)
        self.assertIn("intent = human_handoff_request", runtime)
        self.assertIn("兩項服務都斷訊", runtime)
        self.assertIn("報修需求不等於同意轉真人", runtime)

    def test_full_runtime_prompt_includes_every_registered_intent(self):
        runtime = build_runtime_intent_router_rules()
        for intent in RUNTIME_INTENT_INDEX:
            with self.subTest(intent=intent):
                self.assertIn(f"- {intent}：", runtime)

    def test_contextual_modules_cover_every_runtime_intent(self):
        covered = set(RUNTIME_PROMPT_CORE_INTENTS)
        for intents in RUNTIME_PROMPT_INTENT_MODULES.values():
            covered.update(intents)

        self.assertEqual(set(RUNTIME_INTENT_INDEX) - covered, set())
        self.assertEqual(covered - set(RUNTIME_INTENT_INDEX), set())

    def test_contextual_prompt_loads_only_relevant_rule_sections(self):
        billing = build_contextual_runtime_intent_router_rules(
            "如何登入會員",
            {"company_code": "tdtv", "known_info": {}},
            [],
        )
        termination = build_contextual_runtime_intent_router_rules(
            "我要取消寬頻網路",
            {"company_code": "tdtv", "known_info": {}},
            [],
        )
        network = build_contextual_runtime_intent_router_rules(
            "數據機 LAN1 跟 LAN2 可以接不同路由器嗎",
            {"company_code": "tdtv", "known_info": {}},
            [],
        )

        self.assertIn("【帳務、復線與工具】", billing)
        self.assertNotIn("【優惠、方案與裝機】", billing)
        self.assertNotIn("【退租、停機與方案變更】", billing)
        self.assertNotIn("【網路與設備】", billing)
        self.assertNotIn("【影音與服務】", billing)
        self.assertIn("personal_contract_info_lookup", billing)
        self.assertIn("bill_query", billing)
        self.assertIn("tool_name = search_bill", billing)
        self.assertIn("客戶編號、戶名、登記電話任兩項", billing)
        self.assertNotIn("帳單金額／待繳狀態／本人合約只能", billing)
        self.assertIn("intent = reconnection", billing)
        self.assertIn("未繳費且明確要求復線", billing)
        self.assertIn("已繳費並要求網路／電視復線", billing)
        self.assertIn("先請上傳完整超商收據", billing)
        self.assertIn("tool_name = bill_return_line_internet", billing)
        self.assertIn("bill_return_line_tv", billing)
        self.assertNotIn("尚未繳費不得執行復線", billing)
        self.assertNotIn("router_path_slow_issue", billing)

        self.assertIn("【退租、停機與方案變更】", termination)
        self.assertIn("broadband_termination_guidance", termination)
        self.assertNotIn("【帳務、復線與工具】", termination)

        self.assertIn("【故障、報修與真人】", network)
        self.assertIn("【網路與設備】", network)
        self.assertIn("modem_dual_router_dhcp_guidance", network)
        self.assertNotIn("【帳務、復線與工具】", network)

    def test_contextual_prompt_selection_covers_active_feedback_domains(self):
        cases = {
            "本期帳單金額查詢": {"billing"},
            "我要辦理網路復線": {"billing"},
            "我要辦理電視復線": {"billing", "services"},
            "解約要繳回什麼東西呢": {"termination"},
            "請提供500M網路活動的電視和冰箱型號": {"promotion"},
            "能取消寬頻網路嗎": {"termination"},
            "網路升級方案": {"promotion"},
            "路由器被限速": {"network"},
            "如何登入會員": {"billing"},
            "哈TV機上盒網路連線有問題": {"support", "services"},
            "變更使用者需要費用嗎": {"termination"},
            "電視節目有些頻道會抖動": {"support", "services"},
            "想停止 不繳費": {"termination", "billing"},
            "哈net可以使用小米網路路由器AX3000T嗎": {"network"},
            "數據機LAN1跟LAN2可以接不同路由器嗎": {"network"},
            "登記維修": {"support"},
            "遙控器壞掉": {"support", "services"},
            "LINE TV 要取消": {"termination", "services"},
            "幫我查合約內容": {"billing"},
        }

        for user_input, expected in cases.items():
            with self.subTest(user_input=user_input):
                selected = set(select_runtime_prompt_modules(user_input, {}, []))
                self.assertTrue(expected.issubset(selected), selected)

    def test_accepted_feedback_intents_survive_contextual_prompt_selection(self):
        cases = {
            "電視出現安全模式需要排除": ("support", "tv_safe_mode_guidance"),
            "哈tv頻道不見": ("support", "tv_partial_channel_issue"),
            "頻道跑掉了": ("support", "tv_partial_channel_issue"),
            "自動扣款": ("billing", "auto_payment_guidance"),
            "網路合約": ("billing", "network_contract_scope_clarify"),
            "我要詢問PPPOE帳號密碼": ("network", "pppoe_connection_type_guidance"),
            "基本頻道跟數位頻道是什麼區別": ("services", "basic_vs_digital_channels_comparison"),
            "我想知道發票中獎會不會通知": ("billing", "invoice_win_notification"),
            "我的帳號密碼忘記了": ("billing", "member_login_scope_clarify"),
            "有沒有加值YouTube": ("services", "youtube_on_tv_guidance"),
            "我要停機": ("termination", "service_suspension_process"),
            "你好我的LINE TV不續訂": ("termination", "line_tv_cancellation_guidance"),
        }
        for user_input, (module, intent) in cases.items():
            with self.subTest(user_input=user_input):
                self.assertIn(module, select_runtime_prompt_modules(user_input))
                self.assertIn(
                    f"- {intent}：",
                    build_contextual_runtime_intent_router_rules(user_input),
                )

    def test_recovered_intents_are_present_in_their_runtime_modules(self):
        cases = (
            ("會員怎麼註冊？", "member_registration_guidance", "帳務、復線與工具"),
            ("電視沒節目", "tv_no_program_clarify", "故障、報修與真人"),
            ("電視沒有台", "tv_no_program_clarify", "故障、報修與真人"),
            ("畫面顯示沒有節目", "tv_no_program_display_issue", "故障、報修與真人"),
            ("換路由器後無法上網", "router_replacement_registration_issue", "網路與設備"),
        )
        for user_input, intent, section in cases:
            with self.subTest(user_input=user_input):
                self.assertIn(intent, RUNTIME_INTENT_INDEX)
                prompt = build_contextual_runtime_intent_router_rules(user_input)
                self.assertIn(f"- {intent}：", prompt)
                self.assertIn(f"【{section}】", prompt)

    def test_short_followup_uses_user_context_not_assistant_reply_topics(self):
        history = [
            {"role": "user", "content": "自動扣款"},
            {"role": "assistant", "content": "您可以退租或移機。"},
        ]
        selected = select_runtime_prompt_modules("了解", history=history)
        self.assertIn("billing", selected)
        self.assertNotIn("termination", selected)

    def test_contextual_prompt_reduces_common_turn_size(self):
        full_size = len(build_runtime_intent_router_rules())
        expected_limits = {
            "你好": 6_000,
            "如何登入會員": 8_000,
            "我要取消寬頻網路": 7_500,
            "數據機LAN1跟LAN2可以接不同路由器嗎": 9_000,
            "哈TV機上盒網路連線有問題": 9_500,
        }

        for user_input, limit in expected_limits.items():
            with self.subTest(user_input=user_input):
                contextual = build_contextual_runtime_intent_router_rules(
                    user_input,
                    {"company_code": "tdtv", "known_info": {}},
                    [],
                )
                self.assertLess(len(contextual), limit)
                self.assertLess(len(contextual), full_size)

    def test_contextual_policy_keys_follow_selected_modules(self):
        self.assertEqual(
            select_runtime_policy_keys(("network",)),
            (),
        )
        self.assertIn(
            "billing.payment_not_posted",
            select_runtime_policy_keys(("billing",)),
        )
        self.assertIn(
            "support.remote_control_price",
            select_runtime_policy_keys(("support", "services")),
        )

    def test_remote_price_question_loads_intent_and_policy_facts(self):
        modules = select_runtime_prompt_modules("遙控器多少錢")
        self.assertIn("services", modules)
        rules = build_contextual_runtime_intent_router_rules(
            "遙控器多少錢", {"company_code": "cnt", "known_info": {}}, []
        )
        self.assertIn("remote_control_price_inquiry", rules)
        policy = build_policy_prompt(
            {"company_code": "cnt"}, select_runtime_policy_keys(modules)
        )
        self.assertIn("一般型遙控器 300 元", policy)
        self.assertIn("語音遙控器 400 元", policy)

    def test_combined_tv_network_monthly_fee_loads_scope_clarification(self):
        text = "第四台再加 Wi-Fi 網路月費要多少？"
        modules = select_runtime_prompt_modules(text)
        self.assertIn("promotion", modules)
        rules = build_contextual_runtime_intent_router_rules(
            text, {"company_code": "tdtv", "known_info": {}}, []
        )
        self.assertIn("existing_vs_new_tv_network_clarify", rules)

    def test_runtime_contract_covers_all_fifteen_active_feedback_cases(self):
        runtime = build_runtime_intent_router_rules()
        required_contracts = {
            "FB-20260921124915-8CDE77": 'internet_reactivation_status = "not_required"',
            "FB-20260921125756-D6E554": "termination_service_scope",
            "FB-20260921130742-09B7B0": "活動贈品的實際品牌",
            "FB-20260921131921-51B303": "合約到期日、合約日期、目前方案或申辦速率",
            "FB-20260921132824-7EE349": "速率、繳別、價格或贈品承接前輪方案",
            "FB-20260922121241-CB6856": "intent = router_path_slow_issue",
            "FB-20260922122536-C9F5A7": "intent = member_login_guidance",
            "FB-20260922123354-C128FB": "tv_set_top_box_app_network_issue",
            "FB-20260922124501-872314": "intent = account_holder_change_fee_query",
            "FB-20260922125421-53899E": "排除失敗或客戶明確無法操作後",
            "FB-20260922133650-B68A37": "不可重問業務意圖",
            "FB-20260922134117-2374C2": "self_owned_router_compatibility_guidance",
            "FB-20260922134701-33EC89": "modem_dual_router_dhcp_guidance",
            "FB-20260922135346-8F09DD": "intent = repair_troubleshooting_intake",
            "FB-20260922140917-06D381": "intent = remote_control_issue",
        }

        missing = {
            feedback_id: marker
            for feedback_id, marker in required_contracts.items()
            if marker not in runtime
        }
        self.assertEqual(missing, {})

    def test_memory_summary_omits_empty_fields_but_keeps_active_context(self):
        empty_summary = json.loads(build_memory_summary({
            "company_code": "tdtv",
            "known_info": {},
        }))
        active_summary = json.loads(build_memory_summary({
            "company_code": "tdtv",
            "known_info": {
                "internet_reactivation_status": "not_required",
                "contact_phone": None,
            },
        }))

        self.assertEqual(empty_summary, {"company_code": "tdtv"})
        self.assertEqual(
            active_summary,
            {
                "company_code": "tdtv",
                "known_info": {"internet_reactivation_status": "not_required"},
            },
        )

    def test_model_trace_records_reported_token_usage(self):
        manager = ModelManager(
            provider="openai",
            fallback_provider="ollama",
            enable_fallback=False,
        )

        token = start_llm_trace()
        with patch.object(manager, "_build_model", return_value=UsageChatModel()):
            manager.invoke("hello")
        events = finish_llm_trace(token)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["input_tokens"], 120)
        self.assertEqual(events[0]["output_tokens"], 15)
        self.assertEqual(events[0]["total_tokens"], 135)
        self.assertEqual(events[0]["cached_input_tokens"], 80)


if __name__ == "__main__":
    unittest.main()
