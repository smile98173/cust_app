"""Evaluate organizing-feedback replays without changing tracker state."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT_DIR / "reports"
EXPECTED_CASES = 42
VALID_VERDICTS = {"pass", "partial", "fail", "needs_evidence"}


def parse_json_array(text: str) -> list[dict[str, Any]]:
    cleaned = str(text or "").replace("```json", "").replace("```", "").strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def invoke_with_timeout(llm, prompt: str, timeout: int) -> str:
    queue: Queue[object] = Queue(maxsize=1)

    def invoke() -> None:
        try:
            queue.put(getattr(llm.invoke(prompt), "content", ""))
        except Exception as exc:
            queue.put(exc)

    Thread(target=invoke, daemon=True).start()
    try:
        result = queue.get(timeout=timeout)
    except Empty as exc:
        raise TimeoutError(f"品質評審逾時（{timeout} 秒）") from exc
    if isinstance(result, Exception):
        raise result
    return str(result or "")


def compact_case(item: dict[str, Any]) -> dict[str, Any]:
    organized = item.get("organized_case") or {}
    return {
        "feedback_id": item.get("feedback_id"),
        "company_code": item.get("company_code"),
        "original_csr_suggestion": item.get("suggestion"),
        "organized_case_id": organized.get("case_id"),
        "group_name": organized.get("group_name"),
        "expected_behavior": organized.get("expected_behavior"),
        "must_include": organized.get("must_include"),
        "must_not_include": organized.get("must_not_include"),
        "dependency": organized.get("dependency"),
        "focus": organized.get("focus"),
        "actual_conversation": [
            {"role": message.get("role"), "content": message.get("content")}
            for message in item.get("rerun_messages") or []
        ],
    }


def evaluation_prompt(batch: list[dict[str, Any]]) -> str:
    return f"""你是有線電視與寬頻客服 AI 的資深品質審核員。
請逐筆檢查「實際完整對話」是否符合客服需求。

判定規則：
1. 原客服建議是這筆原始情境的主要依據；整理後需求用來補足專業邊界。
2. 整理案例可能包含其他變體，不得因本次原始對話並未詢到的變體內容而扣分。
3. 必須檢查每一輪回答與上下文，不可只看最後一輪。
4. 與個人帳務、合約、地址、繳費狀態有關時，未登入對話應引導官方登入或安全真人轉接；不要因為沒有在公開對話收集個資就判為失敗。
5. 優惠與方案只能根據當次知識證據，不得猜測或要求寫死方案。
6. 回答讀起來流暢不等於正確；要檢查是否答非所問、過早轉人工、重複詢問已知資訊、過度回答或有無證據事實。

判定值：
- pass：對當前原始對話已充分正確，沒有實質問題。
- partial：主方向正確，但缺少客服明確要求的重要資訊，或有明顯多餘、重複、流程結束過早。
- fail：意圖、業務事實、多輪上下文、安全邊界或操作流程有關鍵錯誤。
- needs_evidence：回答是否正確取決於目前未提供的業務 SOP、產品目錄或工具狀態，不應猜測。

只輸出 JSON 陣列，每個 feedback_id 正好一筆，不可遺漏：
[
  {{
    "feedback_id": "...",
    "verdict": "pass|partial|fail|needs_evidence",
    "reason": "具體指出符合處或問題，不超過120字",
    "recommended_change": "若需調整，說明最小必要修正；通過則留空字串"
  }}
]

待審核案例：
{json.dumps(batch, ensure_ascii=False, indent=2)}
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    load_dotenv(args.env_file, override=True)
    from app.config.settings import OPENAI_MODEL
    from app.services.model_manager import ModelManager

    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(source, list) or len(source) != EXPECTED_CASES:
        raise RuntimeError(
            f"品質審核預期 {EXPECTED_CASES} 筆，實際為 "
            f"{len(source) if isinstance(source, list) else 0} 筆"
        )
    invalid_runs = [
        item.get("feedback_id")
        for item in source
        if item.get("status") != "RAN"
        or item.get("model_call_findings")
    ]
    if invalid_runs:
        raise RuntimeError("實測報告仍有失敗案例：" + ", ".join(invalid_runs))

    manager = ModelManager(
        provider="openai",
        fallback_provider="openai",
        enable_fallback=False,
    )
    llm = manager.get_llm()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"organizing_feedback_quality_{stamp}.json"

    evaluations: list[dict[str, Any]] = []
    for start in range(0, len(source), args.batch_size):
        items = source[start : start + args.batch_size]
        batch = [compact_case(item) for item in items]
        expected_ids = [str(item["feedback_id"]) for item in batch]
        raw = invoke_with_timeout(llm, evaluation_prompt(batch), args.timeout)
        parsed = parse_json_array(raw)
        by_id = {
            str(item.get("feedback_id") or ""): item
            for item in parsed
            if isinstance(item, dict)
        }
        for feedback_id in expected_ids:
            item = by_id.get(feedback_id) or {
                "feedback_id": feedback_id,
                "verdict": "needs_evidence",
                "reason": "評審模型未回傳這筆案例的有效結果",
                "recommended_change": "需人工複核完整對話",
            }
            if item.get("verdict") not in VALID_VERDICTS:
                item["verdict"] = "needs_evidence"
                item["reason"] = "評審模型回傳的判定值無效"
            item["judge_provider"] = manager.last_provider
            item["judge_model"] = OPENAI_MODEL
            evaluations.append(item)
        output_path.write_text(
            json.dumps(evaluations, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        counts = {
            verdict: sum(item.get("verdict") == verdict for item in evaluations)
            for verdict in sorted(VALID_VERDICTS)
        }
        print(
            json.dumps({
                "reviewed": len(evaluations),
                "total": len(source),
                "counts": counts,
                "provider": manager.last_provider,
                "model": OPENAI_MODEL,
            }, ensure_ascii=False),
            flush=True,
        )

    final_counts = {
        verdict: sum(item.get("verdict") == verdict for item in evaluations)
        for verdict in sorted(VALID_VERDICTS)
    }
    print("SUMMARY=" + json.dumps({
        "total": len(evaluations),
        "counts": final_counts,
        "provider": manager.last_provider,
        "model": OPENAI_MODEL,
        "fallback": False,
        "tracker_updated": 0,
        "report": str(output_path),
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
