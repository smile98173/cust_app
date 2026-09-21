import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.kb_service import (
    dedupe_retrieved_docs,
    filter_docs_for_query_intent,
    finalize_docs_for_query,
    retrieve_knowledge,
    retrieve_knowledge_from_keyword_fallback,
    retrieve_knowledge_from_local_chroma,
    should_merge_keyword_fallback_for_results,
    sort_docs_by_company_priority,
)


CASES = [
    (
        "C12",
        "網路最近一直斷斷續續，很不穩",
        "大屯",
        "612c7c09feb64593b71d83fdfa33e9c3",
    ),
    (
        "C14",
        "數據機燈完全沒亮怎麼辦？",
        "大屯",
        "612c7c09feb64593b71d83fdfa33e9c3",
    ),
    (
        "C21",
        "我不想續用 LINE TV，要怎麼取消？",
        "大屯",
        "7e7f5f3fe3b64f48a80e28993d261a5e",
    ),
]


for case_id, query, knowledge_base, expected_document_id in CASES:
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        documents = retrieve_knowledge_from_keyword_fallback(
            query,
            {"knowledge_base": knowledge_base},
            top_k=100,
        )

    matches = []
    for rank, document in enumerate(documents, 1):
        source = document.get("source") or {}
        metadata = document.get("metadata") or {}
        document_id = (
            document.get("document_id")
            or source.get("document_id")
            or metadata.get("document_id")
        )
        if str(document_id) == expected_document_id:
            matches.append(
                {
                    "rank": rank,
                    "question": (document.get("question") or "")[:160],
                    "answer": (document.get("answer") or "")[:240],
                    "keyword_score": document.get("_keyword_score"),
                    "direct_score": document.get("_query_direct_evidence_score"),
                    "relevance_score": document.get("_query_relevance_score"),
                    "anchor_score": document.get("_query_anchor_score"),
                }
            )

    top_three = [
        {
            "keys": sorted(document.keys()),
            "title": document.get("title"),
            "content": (document.get("content") or "")[:100],
            "text": (document.get("text") or "")[:100],
            "question": (document.get("question") or "")[:100],
            "answer": (document.get("answer") or "")[:100],
            "keyword_score": document.get("_keyword_score"),
            "direct_score": document.get("_query_direct_evidence_score"),
            "relevance_score": document.get("_query_relevance_score"),
        }
        for document in documents[:3]
    ]
    print(case_id, "count=", len(documents), "matches=", matches[:5])
    print("top3=", top_three)

    memory = {"knowledge_base": knowledge_base, "company": knowledge_base}
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        semantic_docs = retrieve_knowledge_from_local_chroma(
            query,
            memory,
            top_k=10,
            max_distance=0.55,
        )
        merged_docs = dedupe_retrieved_docs([*semantic_docs, *documents])
        filtered_docs = filter_docs_for_query_intent(query, merged_docs)
        sorted_docs = sort_docs_by_company_priority(filtered_docs, memory, query)
        final_docs = finalize_docs_for_query(query, sorted_docs, 10)
        retrieved_docs = retrieve_knowledge(
            query,
            memory,
            {"knowledge_query": query},
            top_k=10,
            max_distance=0.55,
        )

    def summarize(items):
        return [
            (
                str((item.get("source") or {}).get("document_id") or ""),
                str(item.get("question") or "")[:70],
                item.get("_query_question_evidence_score"),
                item.get("_query_direct_evidence_score"),
                item.get("_keyword_score"),
            )
            for item in items[:10]
        ]

    print("should_merge=", should_merge_keyword_fallback_for_results(query, semantic_docs))
    print("semantic=", summarize(semantic_docs))
    print("manual_final=", summarize(final_docs))
    print("retrieve_final=", summarize(retrieved_docs))
