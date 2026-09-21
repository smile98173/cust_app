import json
import unittest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import handle_chat_message, resolve_model_selected_context
from app.services.intent_router import router_guard, run_intent_router
from app.services.router_catalog import get_clarify_context


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
                with patch(
                    "app.services.intent_router.fallback_router",
                    side_effect=AssertionError("retired fallback was invoked"),
                ):
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
            "detect_safe_direct_reply",
            "detect_company_info_query",
            "detect_company_info_interrupt_query",
            "is_clear_channel_group_query",
            "detect_digital_tv_package_knowledge_guard",
            "detect_convenience_store_payment_machine_guard",
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

    def test_guard_without_model_ownership_only_normalizes_schema(self):
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
            llm_first=False,
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
