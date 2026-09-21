from __future__ import annotations

import contextlib
import io

from app.services.kb_service import retrieve_knowledge_from_keyword_fallback


CASES = (
    "紅利點數",
    "台數科紅利點數是什麼？",
    "哈Point可以做什麼？",
)

POINTS_QUERY = (
    "台數科紅利點數哈Point說明 紅利點數是什麼 "
    "優惠積點回饋機制 如何獲得 如何使用 有效期限 查詢點數"
)


def main() -> None:
    memory = {"company_code": "tdtv", "company": "大屯有線"}
    for user_input in CASES:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            docs = retrieve_knowledge_from_keyword_fallback(
                POINTS_QUERY,
                memory,
                top_k=20,
            )

        print(f"\nQUERY: {user_input} / COUNT: {len(docs)}")
        for index, doc in enumerate(docs[:8], start=1):
            source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
            title = doc.get("title") or doc.get("question") or ""
            content = str(doc.get("answer") or doc.get("content") or "")
            print(
                index,
                f"title={title!r}",
                f"source={source.get('source')!r}",
                f"knowledge_base={(source.get('knowledge_base') or doc.get('company'))!r}",
                f"facet={doc.get('_query_facet_evidence_score')!r}",
                f"relevance={doc.get('_query_relevance_score')!r}",
            )
            print(" ", content[:240].replace("\n", " / "))


if __name__ == "__main__":
    main()
