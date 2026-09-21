"""Semantic quality review for externally rerun feedback cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


PROMPT = """你是客服品質驗收審核員，只輸出 JSON。

請比對「客服建議」與「本次 API 實測對話」，判斷最後 AI 回覆是否符合客服期待。
不可因語氣不同判失敗；但若答非所問、改答其他服務、漏掉客服建議的核心處理方向、錯誤承諾，必須判 FAIL。
若客服建議本身需要知識庫尚未提供的事實，且 AI 因此無法正確答覆，判 NEED_KB。
帳務 API 題若只是不方便直接辦理，不要推測要改 API 規則；依客服建議判斷回覆方向。

客服建議：
{suggestion}

本次 API 實測對話：
{conversation}

輸出：
{{"verdict":"PASS|FAIL|NEED_KB|REVIEW","reason":"不超過80字","missing_or_wrong":"不超過120字"}}
"""


def parse_json(text: str) -> dict[str, str]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model did not return JSON")
    data = json.loads(text[start:end + 1])
    verdict = str(data.get("verdict") or "REVIEW").upper()
    if verdict not in {"PASS", "FAIL", "NEED_KB", "REVIEW"}:
        verdict = "REVIEW"
    return {
        "verdict": verdict,
        "reason": str(data.get("reason") or "").strip(),
        "missing_or_wrong": str(data.get("missing_or_wrong") or "").strip(),
    }


def review_case(case: dict[str, Any], llm) -> dict[str, Any]:
    conversation = "\n".join(
        f"{item.get('role')}: {item.get('content')}"
        for item in case.get("rerun_messages") or []
    )
    try:
        response = llm.invoke(PROMPT.format(
            suggestion=case.get("suggestion") or "未提供",
            conversation=conversation or "未取得測試回答",
        ))
        result = parse_json(str(getattr(response, "content", response) or ""))
    except Exception as exc:
        result = {"verdict": "REVIEW", "reason": "審核模型失敗", "missing_or_wrong": str(exc)[:120]}
    return {
        "feedback_id": case.get("feedback_id"),
        "company_code": case.get("company_code"),
        "feedback_type": case.get("feedback_type"),
        "suggestion": case.get("suggestion"),
        "final_reply": (case.get("rerun_messages") or [{}])[-1].get("content", ""),
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    os.environ["CUST_APP_ENV_FILE"] = args.env_file
    from app.services.model_manager import ModelManager

    cases = json.loads(Path(args.report).read_text(encoding="utf-8"))
    llm = ModelManager().get_llm()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(review_case, case, llm): case for case in cases if case.get("status") == "RAN"}
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            print(f"[{index}/{len(futures)}] {results[-1]['feedback_id']} {results[-1]['verdict']}", flush=True)
    results.sort(key=lambda item: str(item["feedback_id"]))
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={args.output}", flush=True)


if __name__ == "__main__":
    main()
