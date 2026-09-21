from __future__ import annotations

import io
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env.production", override=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.kb_service import (  # noqa: E402
    build_keyword_terms,
    retrieve_knowledge_from_keyword_fallback,
)


QUERIES = (
    ("複製遙控器要怎麼設定？", "大屯"),
    ("固定 IP 要怎麼申請？", "大屯"),
    ("台數科紅利點數哈 Point 是什麼？", "大屯"),
)


for query, knowledge_base in QUERIES:
    original_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        docs = retrieve_knowledge_from_keyword_fallback(
            query,
            {"knowledge_base": knowledge_base, "company": knowledge_base},
            10,
        )
    finally:
        sys.stdout = original_stdout

    print(f"\nQUERY: {query}")
    print(f"TERMS: {build_keyword_terms(query)}")
    for index, doc in enumerate(docs, 1):
        print(
            index,
            doc.get("source"),
            doc.get("title"),
            f"kw={doc.get('_keyword_score')}",
            f"rel={doc.get('_query_relevance_score')}",
            f"question={(doc.get('question') or '')[:80]}",
        )
