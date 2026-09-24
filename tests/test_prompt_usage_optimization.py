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
    def test_runtime_router_contract_is_compact_and_keeps_safety_boundaries(self):
        runtime = build_runtime_intent_router_rules()
        contextual = build_contextual_runtime_intent_router_rules(
            "如何登入會員", {"company_code": "tdtv", "known_info": {}}, []
        )

        self.assertLess(len(runtime), 15_000)
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
        self.assertIn("personal_contract_info_lookup", billing)
        self.assertNotIn("router_path_slow_issue", billing)

        self.assertIn("【退租、停機與方案變更】", termination)
        self.assertIn("broadband_termination_guidance", termination)
        self.assertNotIn("【帳務、復線與工具】", termination)

        self.assertIn("【故障、報修與真人】", network)
        self.assertIn("modem_dual_router_dhcp_guidance", network)
        self.assertNotIn("【帳務、復線與工具】", network)

    def test_contextual_prompt_selection_covers_active_feedback_domains(self):
        cases = {
            "本期帳單金額查詢": {"billing"},
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
