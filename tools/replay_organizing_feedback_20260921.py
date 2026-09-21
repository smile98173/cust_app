"""Replay the visible organizing feedback backlog through the running 8123 API.

The tracker is opened read-only. This tool mirrors the tracker page's duplicate
collapse, excludes merged sources, and never changes review state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.run_feedback_html_dialog_tests import (
    build_backend_headers,
    run_case_backend,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TRACKER_DB = ROOT_DIR.parent / "cust_app_runtime" / "feedback_tracker.db"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "reports"
EXPECTED_VISIBLE_CASES = 42


def decode_json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def collapse_recent_identical_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    kept: list[sqlite3.Row] = []
    latest_by_content: dict[str, datetime] = {}
    for row in rows:
        item = dict(row)
        fingerprint_fields = (
            item.get("company_code"),
            item.get("feedback_type"),
            item.get("suggestion"),
            item.get("conversation_json"),
            item.get("status"),
            item.get("review_status"),
            item.get("adjusted_conversation_json"),
        )
        fingerprint = hashlib.sha256(
            "\x1f".join(
                str(value or "").strip() for value in fingerprint_fields
            ).encode("utf-8")
        ).hexdigest()
        try:
            created_at = datetime.fromisoformat(str(item.get("created_at") or ""))
        except ValueError:
            kept.append(row)
            continue
        previous = latest_by_content.get(fingerprint)
        if previous and previous - created_at <= timedelta(minutes=10):
            continue
        latest_by_content[fingerprint] = created_at
        kept.append(row)
    return kept


def original_user_turns(row: sqlite3.Row) -> list[str]:
    messages = decode_json(row["conversation_json"], [])
    turns = [
        str(message.get("content") or message.get("message") or "").strip()
        for message in messages
        if isinstance(message, dict)
        and str(message.get("role") or "").lower() == "user"
        and str(message.get("content") or message.get("message") or "").strip()
    ]
    fallback = str(row["user_message"] or "").strip()
    return turns or ([fallback] if fallback else [])


def load_organized_case_map(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT case_id, suite, priority, group_name, company_codes, case_kind,
               script, expected_behavior, must_include, must_not_include,
               dependency, focus, source_feedback_ids_json, review_note
        FROM regression_cases
        WHERE case_id LIKE 'ORG-202609-%'
        ORDER BY case_id
        """
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        source_ids = decode_json(item.pop("source_feedback_ids_json"), [])
        item["source_feedback_ids"] = source_ids
        for feedback_id in source_ids:
            result[str(feedback_id)] = item
    return result


def load_visible_cases(
    tracker_db: Path,
    feedback_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{tracker_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT f.feedback_id, f.created_at, f.company_code, f.company,
                   f.feedback_type, f.suggestion, f.user_message,
                   f.conversation_json, t.status, t.review_status,
                   t.review_note, t.adjusted_conversation_json
            FROM feedback_records AS f
            JOIN feedback_tracker_state AS t ON t.feedback_id = f.feedback_id
            WHERE substr(f.created_at, 1, 10) >= '2026-08-24'
              AND t.status = 'processed'
              AND t.review_status = 'organizing'
            ORDER BY f.created_at DESC, f.feedback_id DESC
            """
        ).fetchall()
        rows = collapse_recent_identical_rows(rows)
        organized_by_source = load_organized_case_map(conn)
    finally:
        conn.close()

    if feedback_ids:
        rows = [row for row in rows if row["feedback_id"] in feedback_ids]

    cases: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        feedback_id = str(row["feedback_id"])
        organized_case = organized_by_source.get(feedback_id) or {}
        cases.append({
            "case_no": index,
            "feedback_id": feedback_id,
            "created_at": row["created_at"],
            "company_code": row["company_code"] or "tdtv",
            "company": row["company"] or "",
            "feedback_type": row["feedback_type"] or "",
            "suggestion": row["suggestion"] or "",
            "review_note": row["review_note"] or "",
            "user_turns": original_user_turns(row),
            "organized_case": organized_case,
        })
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
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    selected_ids = {value.strip() for value in args.feedback_id if value.strip()}
    cases = load_visible_cases(Path(args.tracker_db), selected_ids or None)
    if not selected_ids and not args.limit and len(cases) != EXPECTED_VISIBLE_CASES:
        raise RuntimeError(
            f"待整理代表案例應為 {EXPECTED_VISIBLE_CASES} 筆，實際為 {len(cases)} 筆"
        )
    if selected_ids and len(cases) != len(selected_ids):
        found = {case["feedback_id"] for case in cases}
        missing = sorted(selected_ids - found)
        raise RuntimeError(f"找不到待整理案例：{', '.join(missing)}")
    if args.limit:
        cases = cases[: args.limit]

    if args.dry_run:
        print(json.dumps({
            "mode": "dry_run",
            "total": len(cases),
            "cases": [
                {
                    "feedback_id": case["feedback_id"],
                    "company_code": case["company_code"],
                    "organized_case_id": case["organized_case"].get("case_id"),
                    "group_name": case["organized_case"].get("group_name"),
                    "turns": len(case["user_turns"]),
                }
                for case in cases
            ],
        }, ensure_ascii=False, indent=2))
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"organizing_feedback_replay_{stamp}.json"
    results: list[dict[str, Any]] = []

    print(
        f"RUNNING={len(cases)} MODE=visible_organizing_original_conversation "
        "TRACKER_WRITE=false",
        flush=True,
    )
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
            result = {
                **case,
                "status": "ERROR",
                "error": str(exc),
                "duration_sec": 0,
            }
        result["latency_records"] = load_latency_records(
            str(result.get("user_id") or "")
        )
        result["model_call_findings"] = model_call_findings(result)
        results.append(result)
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"[{index}/{len(cases)}] {case['feedback_id']} "
            f"{case['organized_case'].get('case_id') or '-'} => "
            f"{result.get('status')} | {result.get('duration_sec')} sec | "
            f"model_findings={len(result['model_call_findings'])}",
            flush=True,
        )

    summary = {
        "total": len(results),
        "ran": sum(result.get("status") == "RAN" for result in results),
        "errors": sum(result.get("status") != "RAN" for result in results),
        "model_findings": sum(
            len(result.get("model_call_findings") or []) for result in results
        ),
        "turns": sum(len(result.get("user_turns") or []) for result in results),
        "tracker_updated": 0,
        "report": str(output_path),
    }
    print("SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
