import json
import unittest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import (
    handle_chat_message,
    remember_internet_reactivation_status,
)
from app.services.intent_router import build_memory_summary
from app.services.router_prompt import build_contextual_runtime_intent_router_rules


REACTIVATION_NOT_REQUIRED_MESSAGE = (
    "經查詢，您的網路服務狀態正常，無需進行復線處理。"
)


class Response:
    def __init__(self, content):
        self.content = content


def llm_response(payload):
    return RunnableLambda(
        lambda _prompt: Response(json.dumps(payload, ensure_ascii=False))
    )


class InternetReactivationFollowupTest(unittest.TestCase):
    def test_not_required_tool_result_is_remembered_as_account_side_status(self):
        memory = {"known_info": {}}
        tool_result = {
            "success": True,
            "tool_name": "bill_return_line_internet",
            "message": REACTIVATION_NOT_REQUIRED_MESSAGE,
            "data": {
                "raw": {
                    "code": "0099",
                    "msg": REACTIVATION_NOT_REQUIRED_MESSAGE,
                }
            },
        }

        updated = remember_internet_reactivation_status(memory, tool_result)

        self.assertEqual(
            updated["known_info"]["internet_reactivation_status"],
            "not_required",
        )
        self.assertEqual(
            updated["known_info"]["internet_reactivation_message"],
            REACTIVATION_NOT_REQUIRED_MESSAGE,
        )

    def test_chat_flow_saves_not_required_reactivation_result(self):
        memory = {
            "company_code": "tdtv",
            "known_info": {"name": "王仁盛", "phone": "0981639099"},
            "pending_tool": "bill_return_line_internet",
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
            "reason": "test_pending_tool_completion",
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            call_tool.return_value = {
                "success": True,
                "tool_name": "bill_return_line_internet",
                "message": REACTIVATION_NOT_REQUIRED_MESSAGE,
                "data": {
                    "raw": {
                        "code": "0099",
                        "msg": REACTIVATION_NOT_REQUIRED_MESSAGE,
                    }
                },
            }
            result = handle_chat_message(
                user_id="internet-reactivation-status-test",
                user_text="0981639099",
                memory=memory,
                history=[],
                llm=RunnableLambda(lambda _prompt: None),
                persist=False,
            )

        self.assertEqual(
            result["memory"]["known_info"]["internet_reactivation_status"],
            "not_required",
        )
        self.assertIsNone(result["memory"]["pending_tool"])

    def test_router_memory_exposes_status_without_claiming_connection_works(self):
        summary = json.loads(
            build_memory_summary(
                {
                    "known_info": {
                        "internet_reactivation_status": "not_required",
                        "internet_reactivation_message": REACTIVATION_NOT_REQUIRED_MESSAGE,
                    }
                }
            )
        )

        self.assertEqual(
            summary["known_info"]["internet_reactivation_status"],
            "not_required",
        )
        self.assertEqual(
            summary["known_info"]["internet_reactivation_message"],
            REACTIVATION_NOT_REQUIRED_MESSAGE,
        )

    def test_router_contract_distinguishes_reactivation_from_connectivity(self):
        rules = build_contextual_runtime_intent_router_rules(
            "目前沒有網路",
            {"company_code": "tdtv", "known_info": {"internet_reactivation_status": "not_required"}},
            [{"role": "user", "content": "忘了繳費已被斷訊"}],
        )

        self.assertIn('internet_reactivation_status = "not_required"', rules)
        self.assertIn("不代表實際連線正常", rules)
        self.assertIn("internet_connection_issue", rules)
        self.assertIn("不可重呼復線", rules)

    def test_model_selected_troubleshooting_does_not_repeat_reactivation_tool(self):
        router = {
            "route": "troubleshooting",
            "intent": "internet_connection_issue",
            "tool_name": None,
            "topic": "網路無法連線",
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "account_side_reactivation_not_required_but_connection_still_down",
        }
        memory = {
            "company_code": "tdtv",
            "known_info": {
                "internet_reactivation_status": "not_required",
                "internet_reactivation_message": REACTIVATION_NOT_REQUIRED_MESSAGE,
            },
        }
        history = [
            {"role": "user", "content": "忘了繳費已被斷訊"},
            {"role": "assistant", "content": REACTIVATION_NOT_REQUIRED_MESSAGE},
        ]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.call_tool") as call_tool,
        ):
            result = handle_chat_message(
                user_id="internet-reactivation-followup-test",
                user_text="目前沒有網路",
                memory=memory,
                history=history,
                llm=llm_response(router),
                persist=False,
            )

        call_tool.assert_not_called()
        self.assertEqual(result["router"]["route"], "troubleshooting")
        self.assertEqual(result["router"]["intent"], "internet_connection_issue")
        self.assertNotEqual(result["ai_response"], REACTIVATION_NOT_REQUIRED_MESSAGE)
        self.assertNotIn("先完成繳費", result["ai_response"])


if __name__ == "__main__":
    unittest.main()
