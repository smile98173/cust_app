import json
import unittest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import (
    build_campaign_rate_followup_reply,
    constrain_promotion_documents,
    handle_chat_message,
)


class Response:
    def __init__(self, content: str):
        self.content = content


def json_response(payload: dict) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False))


def campaign_doc(
    name: str,
    service_types: str,
    answer: str,
    document_id: str,
) -> dict:
    return {
        "document_id": document_id,
        "knowledge_base": "大屯",
        "question": name,
        "campaign_name": name,
        "document_type": "promotion_campaign",
        "record_type": "campaign_summary",
        "service_types": service_types,
        "valid_period": "2026/09/01~2026/09/30",
        "answer": answer,
    }


class PromotionConversationContractTest(unittest.TestCase):
    def test_unspecified_promotion_asks_for_the_three_service_scopes(self):
        calls = {"router": 0, "retrieval": 0}

        def route(_prompt):
            calls["router"] += 1
            return json_response({
                "route": "clarify",
                "intent": "promotion_service_scope_clarification",
                "topic": "優惠方案服務類型",
                "should_cancel_current_flow": True,
                "should_retrieve_knowledge": False,
                "knowledge_query": None,
                "service_scope": "優惠方案",
                "requested_information": "可選擇的服務類型",
                "promotion_scope": "unspecified",
                "promotion_query_kind": "scope_clarification",
                "social_discount_requested": False,
                "reply": (
                    "請問您想了解哪一類優惠方案？\n"
                    "1. 有線電視＋網路\n"
                    "2. 純網路\n"
                    "3. 純有線電視"
                ),
            })

        def forbidden_retrieval(*_args, **_kwargs):
            calls["retrieval"] += 1
            raise AssertionError("clarification must not retrieve knowledge")

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch(
                "app.handlers.chat_handler.retrieve_knowledge",
                side_effect=forbidden_retrieval,
            ),
        ):
            result = handle_chat_message(
                user_id="promotion-scope-test",
                user_text="現在有優惠方案嗎",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(route),
                persist=False,
            )

        self.assertEqual(calls, {"router": 1, "retrieval": 0})
        self.assertEqual(result["router"]["promotion_scope"], "unspecified")
        self.assertIn("有線電視＋網路", result["ai_response"])
        self.assertIn("純網路", result["ai_response"])
        self.assertIn("純有線電視", result["ai_response"])

        pure_network = campaign_doc(
            "知識庫動態純網方案",
            "純網寬頻",
            "300M/300M：月繳 $799、年繳 $8,388。",
            "dynamic-pure-network",
        )
        retrieval_plans = []

        def select_pure_network(_prompt):
            return json_response({
                "route": "knowledge_query",
                "intent": "promotion_scope_selection",
                "topic": "純網路",
                "should_cancel_current_flow": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "純網路優惠方案",
                "selected_option_id": "option_2",
                "reply": "",
            })

        def retrieve(_user_text, _memory, plan, top_k=5):
            retrieval_plans.append({**plan, "top_k": top_k})
            return [pure_network]

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", side_effect=retrieve),
        ):
            selected = handle_chat_message(
                user_id="promotion-scope-test",
                user_text="2",
                memory=result["memory"],
                history=[
                    {"role": "user", "content": "現在有優惠方案嗎"},
                    {"role": "assistant", "content": result["ai_response"]},
                ],
                llm=RunnableLambda(select_pure_network),
                persist=False,
            )

        self.assertEqual(selected["router"]["reason"], "model_selected_context_validated")
        self.assertEqual(selected["plan"]["promotion_scope"], "pure_network")
        self.assertEqual(selected["plan"]["promotion_query_kind"], "catalog")
        self.assertEqual(retrieval_plans[0]["top_k"], 12)
        self.assertIn("純網路", retrieval_plans[0]["knowledge_query"])
        self.assertIn("知識庫動態純網方案", selected["ai_response"])

    def test_model_scope_enforces_a_dynamic_pure_network_catalog(self):
        pure_a = campaign_doc(
            "動態純網方案 A",
            "純網寬頻",
            "100M/10M：月繳 $600、半年繳 $3,000。",
            "pure-a",
        )
        pure_b = campaign_doc(
            "動態純網方案 B",
            "寬頻",
            "500M/500M：半年繳 $4,194、年繳 $8,388。",
            "pure-b",
        )
        combo = campaign_doc(
            "不應出現的同裝方案",
            "電視網路同裝",
            "100M/10M：月繳 $790。",
            "combo",
        )
        social = campaign_doc(
            "不應主動出現的低收入方案",
            "純網寬頻",
            "限低收入戶申請，100M/10M：月繳 $100。",
            "social",
        )
        all_docs = [pure_a, pure_b, combo, social]
        calls = {"router": 0}
        retrieval_plans = []

        def route(_prompt):
            calls["router"] += 1
            return json_response({
                "route": "knowledge_query",
                # The downstream contract must not depend on this intent name.
                "intent": "internet_install_application_guidance",
                "topic": "寬頻網路新申辦",
                "should_cancel_current_flow": True,
                "should_retrieve_knowledge": True,
                "knowledge_query": "網路裝機申請方案",
                "service_scope": "純網路",
                "requested_information": "目前方案名稱、速率、費用與期間",
                "promotion_scope": "pure_network",
                "promotion_query_kind": "catalog",
                "social_discount_requested": False,
                "reply": "",
            })

        def retrieve(_user_text, _memory, plan, top_k=5):
            retrieval_plans.append({**plan, "top_k": top_k})
            target_id = plan.get("target_document_id")
            if target_id:
                return [doc for doc in all_docs if doc["document_id"] == target_id]
            return list(all_docs)

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", side_effect=retrieve),
        ):
            first = handle_chat_message(
                user_id="pure-network-catalog-test",
                user_text="網路裝機申請",
                memory={"company_code": "tdtv", "known_info": {}},
                history=[],
                llm=RunnableLambda(route),
                rag_summary_llm=RunnableLambda(
                    lambda _prompt: (_ for _ in ()).throw(
                        AssertionError("compact catalog must not call the summary model")
                    )
                ),
                persist=False,
            )

        self.assertEqual(calls["router"], 1)
        self.assertEqual(first["router"]["intent"], "internet_install_application_guidance")
        self.assertEqual(first["plan"]["promotion_scope"], "pure_network")
        self.assertEqual(retrieval_plans[0]["top_k"], 12)
        self.assertIn("純網路", retrieval_plans[0]["knowledge_query"])
        self.assertNotIn("動態純網方案 A", retrieval_plans[0]["knowledge_query"])
        self.assertTrue(first["ai_response"].startswith("目前可參考的純網方案："))
        self.assertIn("動態純網方案 A", first["ai_response"])
        self.assertIn("100M/10M：月繳 600 元、半年繳 3,000 元", first["ai_response"])
        self.assertIn("動態純網方案 B", first["ai_response"])
        self.assertNotIn("不應出現的同裝方案", first["ai_response"])
        self.assertNotIn("不應主動出現的低收入方案", first["ai_response"])
        self.assertNotIn("歡迎申請網路裝機", first["ai_response"])
        self.assertNotIn(";", first["ai_response"])

        def select_second(_prompt):
            return json_response({
                "route": "knowledge_query",
                "intent": "promotion_named_campaign_selection",
                "topic": "動態純網方案 B",
                "should_cancel_current_flow": False,
                "should_retrieve_knowledge": True,
                "knowledge_query": "動態純網方案 B",
                "selected_option_id": "option_2",
                "reply": "",
            })

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.retrieve_knowledge", side_effect=retrieve),
        ):
            selected = handle_chat_message(
                user_id="pure-network-catalog-test",
                user_text="2",
                memory=first["memory"],
                history=[
                    {"role": "user", "content": "網路裝機申請"},
                    {"role": "assistant", "content": first["ai_response"]},
                ],
                llm=RunnableLambda(select_second),
                persist=False,
            )

        self.assertEqual(selected["router"]["reason"], "model_selected_context_validated")
        self.assertEqual(selected["plan"]["target_document_id"], "pure-b")
        self.assertEqual(selected["plan"]["promotion_query_kind"], "campaign_detail")
        self.assertIn("方案名稱：動態純網方案 B", selected["ai_response"])
        self.assertNotIn("動態純網方案 A", selected["ai_response"])

    def test_service_scope_filters_combo_and_pure_tv_documents(self):
        pure = campaign_doc(
            "純網方案",
            "純網寬頻",
            "100M/10M：月繳 $600。",
            "pure",
        )
        combo = campaign_doc(
            "電視網路同裝方案",
            "電視網路同裝",
            "100M/10M：月繳 $790。",
            "combo",
        )
        pure_tv = {
            "question": "有線電視基本收費標準",
            "answer": "有線電視月繳 550 元，首次裝機費 1,500 元。",
            "service_types": "純有線電視",
        }
        social = campaign_doc(
            "低收入戶優惠",
            "純網寬頻",
            "限低收入戶申請。",
            "social",
        )
        docs = [pure, combo, pure_tv, social]

        combo_docs = constrain_promotion_documents(
            docs,
            "tv_network",
            "catalog",
            social_discount_requested=False,
        )
        tv_docs = constrain_promotion_documents(
            docs,
            "pure_tv",
            "catalog",
            social_discount_requested=False,
        )
        explicit_social_docs = constrain_promotion_documents(
            [social],
            "pure_network",
            "campaign_detail",
            social_discount_requested=True,
        )

        self.assertEqual([doc["document_id"] for doc in combo_docs], ["combo"])
        self.assertEqual(tv_docs, [pure_tv])
        self.assertEqual(explicit_social_docs, [social])

    def test_campaign_detail_uses_remembered_dynamic_campaign(self):
        first = campaign_doc(
            "動態方案 A",
            "純網寬頻",
            "100M/10M：年繳 7,200 元。",
            "dynamic-a",
        )
        selected = campaign_doc(
            "動態方案 B",
            "純網寬頻",
            "100M/100M：年繳 5,400 元。",
            "dynamic-b",
        )

        detail_docs = constrain_promotion_documents(
            [first, selected],
            "pure_network",
            "campaign_detail",
            memory={"known_info": {"last_campaign_topic": "動態方案 B"}},
        )

        self.assertEqual(
            [doc["document_id"] for doc in detail_docs],
            ["dynamic-b"],
        )

        reply = build_campaign_rate_followup_reply(
            "100M/100M年繳",
            detail_docs,
            memory={"known_info": {"last_campaign_topic": "動態方案 B"}},
        )

        self.assertEqual(reply, "動態方案 B\n100M/100M：年繳 5,400 元")
        self.assertNotIn("月繳", reply)


if __name__ == "__main__":
    unittest.main()
