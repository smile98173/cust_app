"""Replay failed feedback cases through the already-running 8123 API.

The tracker is opened read-only. Only original user turns are replayed, and
the resulting report is written locally without changing review state.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.run_feedback_html_dialog_tests import (
    build_backend_headers,
    run_case_backend,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TRACKER_DB = ROOT_DIR.parent / "cust_app_runtime" / "feedback_tracker.db"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "reports"


def decode_original_user_turns(value: Any, fallback: Any) -> list[str]:
    try:
        messages = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        messages = []
    turns = [
        str(message.get("content") or "").strip()
        for message in messages
        if isinstance(message, dict)
        and str(message.get("role") or "").lower() == "user"
        and str(message.get("content") or "").strip()
    ]
    if not turns and str(fallback or "").strip():
        turns = [str(fallback).strip()]
    return turns


def load_failed_cases(
    tracker_db: Path,
    feedback_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{tracker_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        clauses = ["t.review_status = 'failed'"]
        parameters: list[str] = []
        if feedback_ids:
            placeholders = ", ".join("?" for _ in feedback_ids)
            clauses.append(f"f.feedback_id IN ({placeholders})")
            parameters.extend(sorted(feedback_ids))
        rows = conn.execute(
            f"""
            SELECT f.feedback_id, f.created_at, f.company_code, f.feedback_type,
                   f.suggestion, f.user_message, f.conversation_json,
                   t.acceptance_issue, t.acceptance_feedback, t.review_note,
                   t.updated_at, t.updated_by
            FROM feedback_records AS f
            JOIN feedback_tracker_state AS t ON t.feedback_id = f.feedback_id
            WHERE {' AND '.join(clauses)}
            ORDER BY t.updated_at, f.feedback_id
            """,
            parameters,
        ).fetchall()
    finally:
        conn.close()

    cases: list[dict[str, Any]] = []
    for case_no, row in enumerate(rows, start=1):
        cases.append(
            {
                "case_no": case_no,
                "feedback_id": row["feedback_id"],
                "created_at": row["created_at"],
                "company_code": row["company_code"] or "tdtv",
                "feedback_type": row["feedback_type"] or "",
                "suggestion": row["suggestion"] or "",
                "acceptance_issue": row["acceptance_issue"] or "",
                "acceptance_feedback": row["acceptance_feedback"] or "",
                "review_note": row["review_note"] or "",
                "reviewed_at": row["updated_at"] or "",
                "reviewed_by": row["updated_by"] or "",
                "user_turns": decode_original_user_turns(
                    row["conversation_json"], row["user_message"]
                ),
            }
        )
    return cases


def load_latency_records(user_id: str) -> list[dict[str, Any]]:
    from app.config.settings import CHAT_LATENCY_LOG_DAILY, CHAT_LATENCY_LOG_PATH
    from app.services.error_logging import dated_path

    path = dated_path(Path(CHAT_LATENCY_LOG_PATH), CHAT_LATENCY_LOG_DAILY)
    if not path.exists():
        return []
    target_user_id = f"web:{user_id}"
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "chat_latency" and record.get("user_id") == target_user_id:
            records.append(record)
    return records


def model_call_findings(result: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    records = result.get("latency_records") or []
    expected_turns = len(result.get("user_turns") or [])
    if len(records) != expected_turns:
        findings.append(
            f"latency log 輪數不符：預期 {expected_turns}，實際 {len(records)}"
        )
    for turn_no, latency in enumerate(records, start=1):
        primary_events = [
            event
            for event in latency.get("llm_events") or []
            if event.get("task") == "primary"
        ]
        if not primary_events:
            findings.append(f"第 {turn_no} 輪沒有 primary LLM 紀錄")
            continue
        for event in primary_events:
            if not event.get("success"):
                findings.append(f"第 {turn_no} 輪 primary LLM 呼叫失敗")
            if event.get("fallback"):
                findings.append(f"第 {turn_no} 輪發生模型 fallback")
    return findings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracker-db", default=str(DEFAULT_TRACKER_DB))
    parser.add_argument("--backend-url", default="http://127.0.0.1:8123")
    parser.add_argument("--auth-env-file", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--chat-timeout", type=int, default=180)
    parser.add_argument("--feedback-id", action="append", default=[])
    args = parser.parse_args()

    selected_ids = {value.strip() for value in args.feedback_id if value.strip()}
    cases = load_failed_cases(Path(args.tracker_db), selected_ids or None)
    if selected_ids and len(cases) != len(selected_ids):
        found = {str(case["feedback_id"]) for case in cases}
        missing = sorted(selected_ids - found)
        raise RuntimeError(f"找不到驗收退回案例：{', '.join(missing)}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"failed_feedback_manual_replay_{stamp}.json"

    results: list[dict[str, Any]] = []
    print(f"RUNNING={len(cases)} MODE=original_conversation TRACKER_WRITE=false", flush=True)
    for index, case in enumerate(cases, start=1):
        try:
            headers = build_backend_headers(args.backend_url, args.auth_env_file)
            result = run_case_backend(
                case,
                args.backend_url,
                chat_timeout=args.chat_timeout,
                headers=headers,
                api_mode="external",
            )
        except Exception as exc:
            result = {**case, "status": "ERROR", "error": str(exc), "duration_sec": 0}
        result["latency_records"] = load_latency_records(str(result.get("user_id") or ""))
        result["model_call_findings"] = model_call_findings(result)
        results.append(result)
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"[{index}/{len(cases)}] {case['feedback_id']} => "
            f"{result.get('status')} | {result.get('duration_sec')} sec | "
            f"model_findings={len(result['model_call_findings'])}",
            flush=True,
        )

    summary = {
        "total": len(results),
        "ran": sum(result.get("status") == "RAN" for result in results),
        "errors": sum(result.get("status") != "RAN" for result in results),
        "model_findings": sum(len(result["model_call_findings"]) for result in results),
        "tracker_updated": 0,
        "report": str(output_path),
    }
    print("SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
