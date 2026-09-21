from __future__ import annotations

import contextlib
import io

from app.services.kb_service import (
    build_keyword_terms,
    retrieve_knowledge,
    retrieve_knowledge_from_keyword_fallback,
)


QUESTIONS = [
    ("機上盒能不能錄節目？", "佳光市區", "機上盒.csv", "機上盒可以錄影嗎"),
    ("為什麼頻道超過 200 台就不能看？", "佳聯", "機上盒.csv", "第四台無法觀看200台之後"),
    ("固定 IP 最多能申請幾組？", "大屯", "網路寬頻_1150624.csv", "申請固定IP"),
    ("LINE TV 要怎麼掃 QR Code 登入電視？", "佳聯", "加值服務.csv", "掃描 QR Code 登入"),
    ("有沒有適合家中長輩使用的服務？", "北港", "加值服務.csv", "年長者的服務"),
    ("有線電視費可以分期付款嗎？", "北港", "帳務.csv", "可繳費分期嗎"),
]


for question, company, expected_source, expected_question in QUESTIONS:
    print(f"\n### {question} [{company}]")
    print("terms:", build_keyword_terms(question))
    with contextlib.redirect_stdout(io.StringIO()):
        docs = retrieve_knowledge_from_keyword_fallback(
            question,
            {"knowledge_base": company, "company": company},
            100,
        )
    expected_matches = []
    for index, doc in enumerate(docs, start=1):
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        source_name = str(source.get("source") or "")
        source_question = str(doc.get("question") or "")
        if expected_source in source_name and expected_question in source_question:
            expected_matches.append((index, doc))
    if expected_matches:
        for index, doc in expected_matches:
            print(
                "EXPECTED rank=", index,
                "question=", repr(doc.get("question")),
                "keyword=", doc.get("_keyword_score"),
                "relevance=", doc.get("_query_relevance_score"),
                "question_evidence=", doc.get("_query_question_evidence_score"),
                "direct_evidence=", doc.get("_query_direct_evidence_score"),
            )
    else:
        print("EXPECTED MISSING")
    with contextlib.redirect_stdout(io.StringIO()):
        final_docs = retrieve_knowledge(
            question,
            {"company": company},
            {"knowledge_query": question},
            top_k=10,
        )
    final_expected_rank = next(
        (
            index
            for index, doc in enumerate(final_docs, start=1)
            if expected_source in str((doc.get("source") or {}).get("source") or "")
            and expected_question in str(doc.get("question") or "")
        ),
        None,
    )
    print("FINAL count=", len(final_docs), "expected_rank=", final_expected_rank)
    for index, doc in enumerate(docs[:10], start=1):
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        answer = str(doc.get("answer") or "").replace("\n", " / ")[:220]
        print(
            index,
            source.get("source"),
            repr(doc.get("question")),
            "keyword=", doc.get("_keyword_score"),
            "relevance=", doc.get("_query_relevance_score"),
            "answer=", answer,
        )
