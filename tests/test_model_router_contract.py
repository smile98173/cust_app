import json
import unittest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import (
    build_clarify_context,
    build_plan_from_router,
    handle_chat_message,
    is_likely_slot_answer,
    resolve_model_selected_context,
)
from app.schemas.router import RouterDecision
from app.services.intent_router import build_memory_summary, router_guard, run_intent_router
from app.services.router_catalog import get_clarify_context
from app.services.router_prompt import build_contextual_runtime_intent_router_rules


class Response:
    def __init__(self, content: str):
        self.content = content


def model_response(**overrides):
    payload = {
        "route": "knowledge_query",
        "intent": "model_owned_intent",
        "tool_name": None,
        "topic": "model-owned-topic",
        "should_cancel_current_flow": False,
        "should_call_tool": False,
        "should_retrieve_knowledge": True,
        "knowledge_query": "model-owned-query",
        "reply": "",
        "extracted_slots": {},
        "reason": "model_semantic_decision",
    }
    payload.update(overrides)
    return Response(json.dumps(payload, ensure_ascii=False))


class ModelRouterContractTest(unittest.TestCase):
    def test_pending_tool_rule_is_only_sent_while_collecting_fields(self):
        ordinary = build_contextual_runtime_intent_router_rules(
            "如何登入會員", {"company_code": "tdtv", "known_info": {}}, []
        )
        pending = build_contextual_runtime_intent_router_rules(
            "王大明",
            {
                "company_code": "tdtv",
                "known_info": {},
                "pending_tool": "search_bill",
                "pending_tool_args": ["identity_pair"],
            },
            [],
        )
        self.assertNotIn("目前正在補工具欄位", ordinary)
        self.assertIn("目前正在補工具欄位", pending)

    def test_pending_invalid_customer_number_does_not_preempt_new_intent(self):
        calls = {"count": 0}

        def classify(_prompt):
            calls["count"] += 1
            return model_response(
                route="direct_reply",
                intent="personal_contract_info_lookup",
                should_call_tool=False,
                should_retrieve_knowledge=False,
                knowledge_query=None,
                reply="請登入會員後查詢合約。",
            )

        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool"
        ) as call_tool:
            result = handle_chat_message(
                user_id="pending-invalid-custnum-new-intent-test",
                user_text="查詢合約 客編 -046793",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["identity_pair"],
                },
                history=[],
                llm=RunnableLambda(classify),
                persist=False,
            )

        self.assertEqual(calls["count"], 1)
        self.assertIsNone(result["memory"]["pending_tool"])
        self.assertEqual(result["router"]["intent"], "personal_contract_info_lookup")
        self.assertIn("登入會員後才能查詢", result["ai_response"])
        self.assertNotIn("有效的客戶編號", result["ai_response"])
        call_tool.assert_not_called()

    def test_pending_invalid_customer_number_is_rejected_after_model_continues(self):
        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool"
        ) as call_tool:
            result = handle_chat_message(
                user_id="pending-invalid-custnum-continuation-test",
                user_text="客編 -046793",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["identity_pair"],
                },
                history=[],
                llm=RunnableLambda(lambda _: model_response(
                    route="continue_current_flow",
                    intent="pending_tool_args",
                    should_call_tool=False,
                    should_retrieve_knowledge=False,
                    knowledge_query=None,
                )),
                persist=False,
            )

        self.assertEqual(result["router"]["reason"], "invalid_pending_customer_number_format")
        self.assertIn("有效的客戶編號", result["ai_response"])
        self.assertEqual(result["memory"]["pending_tool"], "search_bill")
        call_tool.assert_not_called()

    def test_bill_clarification_rejects_invalid_customer_number_after_model_continues(self):
        for route in ("continue_current_flow", "clarify"):
            with self.subTest(route=route), patch(
                "app.handlers.chat_handler.log_chat_latency"
            ), patch("app.handlers.chat_handler.call_tool") as call_tool:
                result = handle_chat_message(
                    user_id=f"bill-clarification-invalid-custnum-{route}",
                    user_text="客編 -046793",
                    memory={"company_code": "tdtv", "known_info": {}},
                    history=[
                        {"role": "user", "content": "查詢帳單"},
                        {"role": "assistant", "content": "請提供客戶編號、戶名、登記電話任兩項。"},
                    ],
                    llm=RunnableLambda(lambda _: model_response(
                        route=route,
                        intent="bill_query",
                        should_call_tool=False,
                        should_retrieve_knowledge=False,
                        knowledge_query=None,
                        reply="請再提供戶名或登記電話。",
                    )),
                    persist=False,
                )

                self.assertEqual(result["router"]["reason"], "invalid_bill_customer_number_format")
                self.assertIn("有效的客戶編號", result["ai_response"])
                self.assertIsNone(result["memory"].get("known_info", {}).get("custnum"))
                call_tool.assert_not_called()

    def test_pending_identity_name_like_new_intent_follows_model_switch(self):
        calls = {"count": 0}

        def classify(_prompt):
            calls["count"] += 1
            return model_response(
                route="clarify",
                intent="relocation_guidance",
                tool_name=None,
                topic="移機",
                should_call_tool=False,
                should_retrieve_knowledge=False,
                knowledge_query=None,
                reply="請問您要辦理移機嗎？",
            )

        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool"
        ) as call_tool:
            result = handle_chat_message(
                user_id="pending-bill-to-relocation-test",
                user_text="我想搬家",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["identity_pair"],
                },
                history=[
                    {"role": "user", "content": "查詢帳單"},
                    {"role": "assistant", "content": "請提供客戶編號、戶名、登記電話任兩項。"},
                ],
                llm=RunnableLambda(classify),
                persist=False,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(result["router"]["intent"], "relocation_guidance")
        self.assertIsNone(result["memory"].get("pending_tool"))
        self.assertIn("移機", result["ai_response"])
        self.assertNotIn("查詢帳單", result["ai_response"])
        call_tool.assert_not_called()

    def test_pending_identity_name_follows_model_continuation(self):
        calls = {"count": 0}

        def classify(_prompt):
            calls["count"] += 1
            return model_response(
                route="continue_current_flow",
                intent="pending_tool_args",
                tool_name=None,
                should_call_tool=False,
                should_retrieve_knowledge=False,
                knowledge_query=None,
            )

        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool"
        ) as call_tool:
            result = handle_chat_message(
                user_id="pending-bill-name-test",
                user_text="王大明",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["identity_pair"],
                },
                history=[
                    {"role": "assistant", "content": "請提供客戶編號、戶名、登記電話任兩項。"},
                ],
                llm=RunnableLambda(classify),
                persist=False,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(result["memory"]["known_info"]["name"], "王大明")
        self.assertEqual(result["memory"]["pending_tool"], "search_bill")
        call_tool.assert_not_called()

    def test_pending_identity_model_failure_does_not_repeat_stale_bill_question(self):
        def unavailable(_prompt):
            raise RuntimeError("model unavailable")

        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool"
        ) as call_tool:
            result = handle_chat_message(
                user_id="pending-bill-router-failure-test",
                user_text="我想搬家",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "pending_tool": "search_bill",
                    "pending_tool_args": ["identity_pair"],
                },
                history=[],
                llm=RunnableLambda(unavailable),
                persist=False,
            )

        self.assertEqual(result["router"]["reason"], "model_router_unavailable")
        self.assertEqual(result["memory"]["pending_tool"], "search_bill")
        self.assertIn("暫時無法判讀", result["ai_response"])
        self.assertNotIn("客戶編號、戶名", result["ai_response"])
        call_tool.assert_not_called()

    def test_guest_bill_identity_prompt_switches_to_contract_lookup(self):
        self.assertFalse(is_likely_slot_answer("查詢合約"))
        self.assertFalse(is_likely_slot_answer("查詢帳單"))
        self.assertTrue(is_likely_slot_answer("王大明"))

        decisions = iter((
            model_response(
                route="tool_action",
                intent="bill_query",
                tool_name="search_bill",
                topic="帳單查詢",
                should_call_tool=True,
                should_retrieve_knowledge=False,
                knowledge_query=None,
            ),
            model_response(
                route="tool_action",
                intent="personal_contract_info_lookup",
                tool_name="search_contract_info",
                topic="本人合約資訊查詢",
                should_call_tool=True,
                should_retrieve_knowledge=False,
                knowledge_query=None,
            ),
        ))
        llm = RunnableLambda(lambda _: next(decisions))

        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool"
        ) as call_tool:
            first = handle_chat_message(
                user_id="guest-bill-to-contract-test",
                user_text="查詢帳單",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=llm,
                persist=False,
            )
            self.assertEqual(first["memory"]["pending_tool"], "search_bill")
            self.assertIn("客戶編號、戶名、登記電話任兩項", first["ai_response"])
            second = handle_chat_message(
                user_id="guest-bill-to-contract-test",
                user_text="查詢合約",
                memory=first["memory"],
                history=[
                    {"role": "user", "content": "查詢帳單"},
                    {"role": "assistant", "content": first["ai_response"]},
                ],
                llm=llm,
                persist=False,
            )

        self.assertIsNone(second["memory"].get("pending_tool"))
        self.assertIn("登入會員後才能查詢", second["ai_response"])
        self.assertNotIn("幫您查詢帳單", second["ai_response"])
        self.assertEqual(second["router"]["intent"], "personal_contract_info_lookup")
        call_tool.assert_not_called()

    def test_authenticated_contract_lookup_uses_contract_tool_not_bill_tool(self):
        memory = {
            "company_code": "tdtv",
            "is_logged_in": True,
            "known_info": {
                "custnum": "905397",
                "custnum_source": "web_authenticated",
                "is_logged_in": True,
            },
        }
        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool",
            return_value={
                "success": True,
                "tool_name": "search_contract_info",
                "message": "目前合約到期日：2026-12-31",
                "data": {},
            },
        ) as call_tool:
            result = handle_chat_message(
                user_id="authenticated-contract-lookup-test",
                user_text="查詢合約",
                memory=memory,
                history=[],
                llm=RunnableLambda(lambda _: model_response(
                    route="tool_action",
                    intent="personal_contract_info_lookup",
                    tool_name="search_contract_info",
                    topic="本人合約資訊查詢",
                    should_call_tool=True,
                    should_retrieve_knowledge=False,
                    knowledge_query=None,
                )),
                persist=False,
            )

        call_tool.assert_called_once()
        self.assertEqual(call_tool.call_args.args[0], "search_contract_info")
        self.assertIn("2026-12-31", result["ai_response"])
        self.assertNotIn("查詢帳單", result["ai_response"])

    def test_authenticated_bill_due_date_uses_trusted_customer_number(self):
        memory = {
            "company_code": "tdtv",
            "is_logged_in": True,
            "known_info": {
                "custnum": "905397",
                "custnum_source": "web_authenticated",
                "is_logged_in": True,
            },
        }
        self.assertIn('"authenticated_web_custnum":true', build_memory_summary(memory))

        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool",
            return_value={
                "success": True,
                "tool_name": "search_bill",
                "message": "本期帳單繳費截止日：2026-10-15",
                "data": {},
            },
        ) as call_tool:
            result = handle_chat_message(
                user_id="authenticated-bill-deadline-test",
                user_text="查詢帳單繳費截止日期",
                memory=memory,
                history=[],
                llm=RunnableLambda(lambda _: model_response(
                    route="clarify",
                    intent="bill_query",
                    tool_name=None,
                    topic="帳單查詢",
                    should_call_tool=False,
                    should_retrieve_knowledge=False,
                    knowledge_query=None,
                    reply="請提供戶名或登記電話其中一項。",
                )),
                persist=False,
            )

        call_tool.assert_called_once()
        self.assertEqual(result["router"]["tool_name"], "search_bill")
        self.assertIn("2026-10-15", result["ai_response"])
        self.assertNotIn("請提供戶名", result["ai_response"])

    def test_untrusted_customer_number_is_not_authenticated_in_router_context(self):
        memory = {
            "known_info": {
                "custnum": "905397",
                "custnum_source": "user_provided",
            },
        }
        self.assertIn('"authenticated_web_custnum":false', build_memory_summary(memory))
        decision = router_guard(
            "查詢帳單繳費截止日期",
            memory,
            {"route": "clarify", "intent": "bill_query", "reply": "請補充核對資料。"},
        )
        self.assertEqual(decision["route"], "clarify")

    def test_router_prompt_requests_structured_clarification_options(self):
        rules = build_contextual_runtime_intent_router_rules(
            "有線電視還是網路？",
            {"company_code": "tdtv", "known_info": {}},
            [],
        )

        self.assertIn("clarification_question", rules)
        self.assertIn("clarification_options", rules)
        self.assertIn("依順序填完整純文字選項", rules)

    def test_structured_clarification_options_render_as_complete_numbered_list(self):
        router = RouterDecision.from_raw(
            {
                "route": "clarify",
                "intent": "plan_change_scope_clarification",
                "clarification_question": "請問您想更換哪一類服務？",
                "clarification_options": [
                    "1. 純網路",
                    "純有線電視",
                    "有線電視＋網路",
                    "已有指定方案想更換",
                ],
                "reply": "模型的非結構化回覆",
            },
            supported_tools=(),
        ).to_router_dict()

        reply = build_plan_from_router(router)["reply"]

        self.assertEqual(
            reply,
            "請問您想更換哪一類服務？\n"
            "1. 純網路\n"
            "2. 純有線電視\n"
            "3. 有線電視＋網路\n"
            "4. 已有指定方案想更換",
        )

    def test_contract_change_clarification_uses_catalog_options_when_model_omits_structure(self):
        router = RouterDecision.from_raw(
            {
                "route": "clarify",
                "intent": "contract_expired_plan_change_clarify",
                "reply": (
                    "請問您想轉換成哪一類新方案？\n"
                    "1. 純網路\n2. 純有線電視\n3.有線電視＋網路\n已有指定方案"
                ),
            },
            supported_tools=(),
        ).to_router_dict()

        plan = build_plan_from_router(router)
        context = build_clarify_context(router)

        self.assertEqual(
            plan["reply"],
            "請問您想轉換成哪一類新方案？\n"
            "1. 純網路\n"
            "2. 純有線電視\n"
            "3. 有線電視＋網路\n"
            "4. 已有指定方案",
        )
        self.assertEqual(context["topic"], "方案轉換目標")
        self.assertEqual(list(context["options"]), [
            "純網路",
            "純有線電視",
            "有線電視＋網路",
            "已有指定方案",
        ])

    def test_chat_entrypoint_repairs_incomplete_contract_change_option_list(self):
        def incomplete_clarification(_prompt):
            return model_response(
                route="clarify",
                intent="contract_expired_plan_change_clarify",
                should_retrieve_knowledge=False,
                knowledge_query=None,
                reply=(
                    "請問您想轉換成哪一類新方案？\n"
                    "1. 純網路\n2. 有線電視\n3.有線電視＋網路\n已有指定方案"
                ),
            )

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="contract-change-clarify-layout-test",
                user_text="原本合約已到期要轉換新方案如何辦理",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(incomplete_clarification),
                persist=False,
            )

        self.assertEqual(
            result["ai_response"],
            "請問您想轉換成哪一類新方案？\n"
            "1. 純網路\n"
            "2. 純有線電視\n"
            "3. 有線電視＋網路\n"
            "4. 已有指定方案",
        )

    def test_representative_semantic_turns_always_invoke_model(self):
        cases = (
            "請幫我轉真人客服",
            "客服電話多少",
            "發票可以載具嗎",
            "清冰組可以借幾台機上盒",
            "網路裝機申請",
            "無法在便利商店繳費",
        )

        for text in cases:
            with self.subTest(text=text):
                calls = {"count": 0}

                def fake_model(_prompt):
                    calls["count"] += 1
                    return model_response()

                decision = run_intent_router(
                    user_input=text,
                    memory={"company_code": "tdtv", "known_info": {}},
                    history=[],
                    llm=RunnableLambda(fake_model),
                )

                self.assertEqual(calls["count"], 1)
                self.assertEqual(decision["intent"], "model_owned_intent")
                self.assertEqual(decision["knowledge_query"], "model-owned-query")

    def test_model_failure_never_uses_legacy_semantic_rules(self):
        cases = (
            "請幫我轉真人客服",
            "客服電話多少",
            "發票可以載具嗎",
            "清冰組是什麼",
            "現在有優惠方案嗎",
        )

        def unavailable(_prompt):
            raise RuntimeError("model unavailable")

        for text in cases:
            with self.subTest(text=text):
                decision = run_intent_router(
                    user_input=text,
                    memory={"company_code": "tdtv", "known_info": {}},
                    history=[],
                    llm=RunnableLambda(unavailable),
                )

                self.assertEqual(decision["route"], "unknown")
                self.assertEqual(decision["reason"], "model_router_unavailable")

    def test_post_model_guard_does_not_call_semantic_detectors(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("semantic detector must not run after the model")

        detectors = (
            "detect_company_info_interrupt_query",
            "is_clear_channel_group_query",
            "is_personal_project_points_status_query",
            "is_paper_to_electronic_bill_change_query",
            "is_counter_service_account_transfer_hours_query",
            "is_existing_customer_speed_upgrade_eligibility_query",
            "is_next_tier_plan_fee_query",
        )

        patches = [
            patch(f"app.services.intent_router.{name}", side_effect=forbidden)
            for name in detectors
        ]
        for active_patch in patches:
            active_patch.start()
        try:
            decision = run_intent_router(
                user_input="清冰組可以借幾台機上盒",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(lambda _prompt: model_response()),
            )
        finally:
            for active_patch in reversed(patches):
                active_patch.stop()

        self.assertEqual(decision["intent"], "model_owned_intent")

    def test_post_model_guard_keeps_decision_without_keyword_reroute(self):
        decision = router_guard(
            user_input="客服電話多少",
            memory={"company_code": "tdtv", "known_info": {}},
            router={
                "route": "continue_current_flow",
                "intent": "existing_state",
                "topic": "existing-state-topic",
                "reply": "",
                "should_call_tool": False,
                "should_retrieve_knowledge": False,
            },
        )

        self.assertEqual(decision["route"], "continue_current_flow")
        self.assertEqual(decision["intent"], "existing_state")
        self.assertEqual(decision["topic"], "existing-state-topic")

    def test_all_catalog_clarifications_receive_stable_option_ids(self):
        context = get_clarify_context("帳單")

        self.assertIsNotNone(context)
        self.assertEqual(
            [option["option_id"] for option in context["options"].values()],
            ["option_1", "option_2", "option_3"],
        )

    def test_model_selected_generic_option_is_validated_by_backend(self):
        context = get_clarify_context("帳單")
        router = {
            "route": "knowledge_query",
            "intent": "model_selection",
            "selected_option_id": "option_2",
            "target_document_id": "model-must-not-control-this",
            "target_knowledge_base": "model-must-not-control-this",
        }

        decision, selected = resolve_model_selected_context(
            {"clarify_context": context},
            router,
        )

        self.assertTrue(selected)
        self.assertEqual(decision["route"], "tool_action")
        self.assertEqual(decision["tool_name"], "send_message")
        self.assertTrue(decision["should_call_tool"])
        self.assertIsNone(decision["target_document_id"])
        self.assertIsNone(decision["target_knowledge_base"])

    def test_unknown_option_id_cannot_select_a_route(self):
        context = get_clarify_context("帳單")

        decision, selected = resolve_model_selected_context(
            {"clarify_context": context},
            {
                "route": "tool_action",
                "tool_name": "search_bill",
                "selected_option_id": "option_999",
            },
        )

        self.assertFalse(selected)
        self.assertEqual(decision["route"], "clarify")
        self.assertIsNone(decision["tool_name"])

    def test_chat_entrypoint_sends_generic_clarify_selection_to_model(self):
        calls = {"count": 0}
        context = get_clarify_context("一般頻道 E004 暫復確認")

        def select_second_option(_prompt):
            calls["count"] += 1
            return model_response(
                route="clarify",
                intent="model_option_selection",
                should_retrieve_knowledge=False,
                knowledge_query=None,
                selected_option_id="option_2",
            )

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="model-selection-test",
                user_text="先不用",
                memory={
                    "company_code": "tdtv",
                    "known_info": {},
                    "clarify_context": context,
                },
                history=[],
                llm=RunnableLambda(select_second_option),
                persist=False,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(result["router"]["route"], "direct_reply")
        self.assertEqual(result["router"]["reason"], "model_selected_context_validated")
        self.assertIn("完成繳費後若仍無法收看", result["ai_response"])

    def test_guest_unpaid_reconnection_waits_for_identity(self):
        cases = (
            ("我還沒繳費，想先辦理網路復線", "bill_return_line_internet"),
            ("我還沒繳費，想先辦理電視復線", "bill_return_line_tv"),
        )
        for user_text, tool_name in cases:
            with self.subTest(user_text=user_text), patch(
                "app.handlers.chat_handler.log_chat_latency"
            ), patch("app.handlers.chat_handler.call_tool") as call_tool:
                result = handle_chat_message(
                    user_id="guest-reconnection-contract-test",
                    user_text=user_text,
                    memory={"company_code": "tdtv", "known_info": {}},
                    history=[],
                    llm=RunnableLambda(lambda _: model_response(
                        route="tool_action",
                        intent="reconnection",
                        tool_name=tool_name,
                        should_call_tool=True,
                        should_retrieve_knowledge=False,
                        knowledge_query=None,
                    )),
                    persist=False,
                )

                self.assertEqual(result["router"]["route"], "tool_action")
                self.assertEqual(result["memory"]["pending_tool"], tool_name)
                self.assertIn("客戶編號、戶名、登記電話任兩項", result["ai_response"])
                call_tool.assert_not_called()

    def test_paid_reconnection_requires_receipt_even_if_model_selects_reconnection_tool(self):
        with patch("app.handlers.chat_handler.log_chat_latency"), patch(
            "app.handlers.chat_handler.call_tool"
        ) as call_tool:
            result = handle_chat_message(
                user_id="paid-reconnection-contract-test",
                user_text="我已繳費，想辦理電視復線",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(lambda _: model_response(
                    route="tool_action",
                    intent="reconnection",
                    tool_name="bill_return_line_tv",
                    should_call_tool=True,
                    should_retrieve_knowledge=False,
                    knowledge_query=None,
                )),
                persist=False,
            )

        self.assertEqual(result["router"]["intent"], "payment_receipt_image_required")
        self.assertIn("請上傳清楚、完整的超商繳費收據圖片", result["ai_response"])
        self.assertIsNone(result["memory"].get("pending_tool"))
        call_tool.assert_not_called()

    def test_chat_entrypoint_does_not_answer_semantic_query_when_model_fails(self):
        calls = {"count": 0}

        def unavailable(_prompt):
            calls["count"] += 1
            raise RuntimeError("model unavailable")

        with patch("app.handlers.chat_handler.log_chat_latency"):
            result = handle_chat_message(
                user_id="model-failure-test",
                user_text="客服電話多少",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(unavailable),
                persist=False,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(result["router"]["route"], "unknown")
        self.assertEqual(result["router"]["reason"], "model_router_unavailable")


if __name__ == "__main__":
    unittest.main()
