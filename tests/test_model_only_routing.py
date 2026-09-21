import json
import unittest

from langchain_core.runnables import RunnableLambda

from app.services.intent_router import run_intent_router


class Response:
    def __init__(self, payload):
        self.content = json.dumps(payload, ensure_ascii=False)


def model_response(payload, calls):
    def invoke(_prompt):
        calls.append(True)
        return Response(payload)

    return RunnableLambda(invoke)


class ModelOnlyRoutingTest(unittest.TestCase):
    def test_fixed_business_topics_use_the_model_decision(self):
        cases = (
            ("如果我要紙本帳單怎麼辦", "direct_reply", "paper_bill_request"),
            ("有區域故障嗎", "company_info", "company_info"),
            ("你好", "smalltalk", "smalltalk"),
        )

        for text, route, intent in cases:
            with self.subTest(text=text):
                calls = []
                result = run_intent_router(
                    user_input=text,
                    memory={"company_code": "tdtv", "known_info": {}},
                    history=[],
                    llm=model_response(
                        {
                            "route": route,
                            "intent": intent,
                            "tool_name": None,
                            "topic": text,
                            "should_cancel_current_flow": False,
                            "should_call_tool": False,
                            "should_retrieve_knowledge": False,
                            "knowledge_query": None,
                            "reply": "模型判斷結果。",
                            "extracted_slots": {},
                            "reason": "model_test",
                        },
                        calls,
                    ),
                )

                self.assertEqual(calls, [True])
                self.assertEqual(result["route"], route)
                self.assertEqual(result["intent"], intent)

    def test_model_unavailable_returns_a_generic_unknown_route(self):
        def fail(_prompt):
            raise RuntimeError("model unavailable")

        result = run_intent_router(
            user_input="如果我要紙本帳單怎麼辦",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=RunnableLambda(fail),
        )

        self.assertEqual(result["route"], "unknown")
        self.assertEqual(result["reason"], "model_router_unavailable")

    def test_model_unavailable_does_not_fall_back_to_install_keyword_routing(self):
        def fail(_prompt):
            raise RuntimeError("model unavailable")

        result = run_intent_router(
            user_input="網路裝機申請",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=RunnableLambda(fail),
        )

        self.assertEqual(result["route"], "unknown")
        self.assertEqual(result["reason"], "model_router_unavailable")
        self.assertFalse(result["should_retrieve_knowledge"])

    def test_model_semantic_contract_is_preserved_for_retrieval(self):
        result = run_intent_router(
            user_input="線上繳費",
            memory={"company_code": "tdtv", "known_info": {}},
            history=[],
            llm=model_response(
                {
                    "route": "knowledge_query",
                    "intent": "online_payment_guidance",
                    "topic": "線上繳費",
                    "should_cancel_current_flow": True,
                    "should_retrieve_knowledge": True,
                    "knowledge_query": "線上繳費流程",
                    "service_scope": "線上繳費",
                    "requested_information": "官方網站與行動客服 APP 的繳費步驟",
                    "target_document_id": "model-invented-document",
                    "target_knowledge_base": "model-invented-base",
                },
                [],
            ),
        )

        self.assertEqual(result["service_scope"], "線上繳費")
        self.assertIn("行動客服 APP", result["requested_information"])
        self.assertIsNone(result["target_document_id"])
        self.assertIsNone(result["target_knowledge_base"])
