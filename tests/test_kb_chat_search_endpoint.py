import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from app.app_backend import kb_chat_search, kb_search
from app.schemas.chat import KnowledgeSearchRequest


class KBChatSearchEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_station_is_passed_to_chat_retrieval_memory(self):
        captured = {}

        def fake_retrieve(query, memory, intent, top_k):
            captured.update(
                query=query,
                memory=dict(memory),
                intent=dict(intent),
                top_k=top_k,
            )
            return []

        request = KnowledgeSearchRequest(
            plan_name="家裡長輩有適合的加值服務嗎？",
            knowledge_base="西海岸",
            limit=10,
        )
        with patch("app.services.kb_service.retrieve_knowledge", side_effect=fake_retrieve), patch(
            "app.services.kb_answer_guard.filter_answerable_docs",
            return_value=[],
        ), patch(
            "app.services.kb_service.match_active_campaign_alias",
            return_value=None,
        ):
            response = await kb_chat_search(request)

        self.assertEqual(captured["memory"]["knowledge_base"], "西海岸")
        self.assertEqual(captured["memory"]["company"], "西海岸")
        self.assertEqual(response["knowledge_base"], "西海岸")
        self.assertEqual(response["retrieval_pipeline_version"], "faq-fallback-v3")

    async def test_kb_search_filters_stale_chroma_document_ids_against_manifest(self):
        class FakeSearcher:
            def search(self, query, top_k, knowledge_base=None, category=None):
                return [
                    {
                        "id": "deleted-doc:1",
                        "document_id": "deleted-doc",
                        "question": "已刪 QA",
                        "answer": "不該再出現",
                        "company": knowledge_base,
                        "category": "billing",
                        "source": "deleted.csv",
                        "title": "已刪 QA",
                        "_score": 0.9,
                    },
                    {
                        "id": "active-doc:1",
                        "document_id": "active-doc",
                        "question": "有效 QA",
                        "answer": "可以出現",
                        "company": knowledge_base,
                        "category": "billing",
                        "source": "active.csv",
                        "title": "有效 QA",
                        "_score": 0.8,
                    },
                ]

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "documents.json"
            manifest_path.write_text(json.dumps({
                "documents": [
                    {
                        "id": "deleted-doc",
                        "status": "deleted",
                        "processing_status": "deleted",
                        "knowledge_base": "通用",
                    },
                    {
                        "id": "active-doc",
                        "status": "active",
                        "processing_status": "indexed",
                        "knowledge_base": "通用",
                    },
                ],
            }, ensure_ascii=False), encoding="utf-8")

            request = KnowledgeSearchRequest(
                plan_name="測試",
                knowledge_base="通用",
                limit=10,
            )
            with patch("app.services.kb_service.load_local_searcher", return_value=FakeSearcher()), \
                    patch("app.services.kb_service.RAG_LOCAL_MANIFEST_PATH", str(manifest_path)):
                response = await kb_search(request)

        self.assertEqual(response["count"], 1)
        self.assertEqual(response["sources"][0]["answer"], "可以出現")


if __name__ == "__main__":
    unittest.main()
