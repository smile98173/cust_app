import unittest
from unittest.mock import patch

from scripts import run_common_kb_retrieval_tests as report


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "retrieval_pipeline_version": "faq-fallback-v3",
            "sources": [
                {
                    "document_id": "bear-care-doc",
                    "title": "台數科能提供給年長者的服務有那些",
                    "answer": "熊搭心包含電視電話、家庭相簿與生活提醒。",
                }
            ],
        }


class CommonKBRetrievalReportTest(unittest.TestCase):
    def test_clarification_candidate_is_a_retrieval_pass(self):
        item = {
            "id": "C25",
            "group": "中區／加值服務",
            "station": "大屯",
            "category": "value_added",
            "question": "熊溫馨是什麼？",
            "expected_any": ["熊搭心", "電視電話"],
            "variant": "名稱差距較大",
            "negative": False,
            "knowledge_gap": False,
            "expected_mode": "clarification",
            "expected_document_id": "bear-care-doc",
            "expected_source": "各項單品銷售_加值服務_.docx",
            "expected_title": "台數科能提供給年長者的服務有那些",
        }

        with patch.object(report.requests, "post", return_value=_FakeResponse()):
            result = report.run_case(item, headers={})

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["hit_rank"], 1)
        self.assertEqual(result["content_hit_rank"], 1)
        self.assertEqual(result["missing_terms"], [])


if __name__ == "__main__":
    unittest.main()
