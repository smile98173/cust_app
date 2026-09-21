import unittest

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.services.general_knowledge_fallback import (
    build_general_knowledge_reply,
    is_general_knowledge_fallback_allowed,
)


class GeneralKnowledgeFallbackTest(unittest.TestCase):
    def test_allows_low_risk_definition_question(self):
        self.assertTrue(is_general_knowledge_fallback_allowed("雙模機是什麼?"))
        self.assertTrue(is_general_knowledge_fallback_allowed("什麼是固定 IP?"))

    def test_rejects_operation_and_policy_questions(self):
        blocked = [
            "雙模機怎麼設定?",
            "雙模機可以網路分享嗎?",
            "固定 IP 怎麼申請?",
            "固定 IP 多少錢?",
            "我要辦理移機",
            "網路不能用怎麼辦?",
        ]

        for query in blocked:
            with self.subTest(query=query):
                self.assertFalse(is_general_knowledge_fallback_allowed(query))

    def test_rejects_non_definition_question(self):
        self.assertFalse(is_general_knowledge_fallback_allowed("雙模機設定選項"))

    def test_rejects_model_guess_for_possible_proprietary_name(self):
        llm = RunnableLambda(lambda _payload: AIMessage(content=(
            "依一般理解，這可能是以名稱諧音設計的公司服務。"
            "這不是公司官方服務承諾。"
        )))

        reply = build_general_knowledge_reply(
            "某某心是什麼？",
            llm,
            memory={"company_code": "tdtv"},
        )

        self.assertIsNone(reply)


if __name__ == "__main__":
    unittest.main()
