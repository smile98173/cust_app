"""Replay pending-acceptance feedback through the external chat API only.

This reads tracker data in SQLite read-only mode and never updates tracker
status.  A checkpoint JSON is written after each case so a long API run can
be resumed without repeating completed customer conversations.

Cases marked ``review_status=organizing`` are intentionally excluded. They
are paused for knowledge or answer-contract consolidation and must be moved
back to ``pending`` only when a new verification run is explicitly approved.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from run_feedback_html_dialog_tests import build_backend_headers, run_case_backend


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TRACKER_DB = ROOT_DIR.parent / "cust_app_runtime" / "feedback_tracker.db"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "reports"


def decode_messages(value: Any) -> list[dict[str, str]]:
    try:
        items = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [
        {"role": str(item.get("role") or ""), "content": str(item.get("content") or "").strip()}
        for item in items
        if isinstance(item, dict)
        and str(item.get("role") or "") in {"user", "assistant"}
        and str(item.get("content") or "").strip()
    ]


def load_pending_cases(
    tracker_db: Path,
    feedback_ids: set[str] | None = None,
    include_all_open: bool = False,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{tracker_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        where_clause = """
            COALESCE(t.status, 'pending') = 'processed'
            AND COALESCE(t.review_status, 'pending') = 'pending'
        """
        parameters: list[str] = []
        if feedback_ids:
            placeholders = ", ".join("?" for _ in feedback_ids)
            # An explicit case ID is a request to inspect the current live
            # behaviour, regardless of where that feedback sits in the queue.
            where_clause = f"f.feedback_id IN ({placeholders})"
            parameters = sorted(feedback_ids)
        elif include_all_open:
            where_clause = """
                COALESCE(t.status, 'pending') IN ('pending', 'processed')
                AND COALESCE(t.review_status, 'pending') = 'pending'
            """

        rows = conn.execute(
            f"""
            SELECT f.feedback_id, f.created_at, f.company_code, f.feedback_type,
                   f.suggestion, f.user_message, f.conversation_json,
                   t.adjusted_conversation_json
            FROM feedback_records AS f
            LEFT JOIN feedback_tracker_state AS t ON t.feedback_id = f.feedback_id
            WHERE {where_clause}
            ORDER BY f.created_at, f.feedback_id
            """,
            parameters,
        ).fetchall()
    finally:
        conn.close()

    cases = []
    for number, row in enumerate(rows, start=1):
        adjusted = decode_messages(row["adjusted_conversation_json"])
        messages = adjusted or decode_messages(row["conversation_json"])
        user_turns = [item["content"] for item in messages if item["role"] == "user"]
        if not user_turns and row["user_message"]:
            user_turns = [str(row["user_message"])]
        cases.append({
            "case_no": number,
            "feedback_id": row["feedback_id"],
            "created_at": row["created_at"],
            "company_code": row["company_code"] or "tdtv",
            "feedback_type": row["feedback_type"] or "",
            "suggestion": row["suggestion"] or "",
            "original_messages": messages,
            "user_turns": user_turns,
        })
    return cases


def write_checkpoint(path: Path, results: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def run_case_with_fresh_token(
    case: dict[str, Any],
    backend_url: str,
    auth_env_file: str,
    chat_timeout: int,
) -> dict[str, Any]:
    # Tokens are intentionally short-lived in the AI test environment. A
    # fresh token per independent case prevents a long batch from turning its
    # remaining cases into false 401 failures.
    headers = build_backend_headers(backend_url, auth_env_file)
    return run_case_backend(
        case,
        backend_url,
        chat_timeout=chat_timeout,
        headers=headers,
        api_mode="external",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracker-db", default=str(DEFAULT_TRACKER_DB))
    parser.add_argument("--backend-url", default="http://127.0.0.1:8123")
    parser.add_argument("--auth-env-file", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--chat-timeout", type=int, default=120)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--feedback-id",
        action="append",
        default=[],
        help="Only rerun the specified feedback id. May be supplied more than once.",
    )
    parser.add_argument("--resume-json", default="")
    parser.add_argument(
        "--all-open",
        action="store_true",
        help="Rerun both pending fixes and pending-acceptance cases; excludes paused organizing cases.",
    )
    args = parser.parse_args()

    selected_ids = set(args.feedback_id)
    cases = load_pending_cases(
        Path(args.tracker_db),
        selected_ids or None,
        include_all_open=args.all_open,
    )
    if args.limit:
        cases = cases[:args.limit]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"pending_acceptance_api_rerun_{stamp}.json"

    results: list[dict[str, Any]] = []
    completed: set[str] = set()
    if args.resume_json:
        output_path = Path(args.resume_json)
        results = json.loads(output_path.read_text(encoding="utf-8"))
        completed = {
            str(item.get("feedback_id") or "")
            for item in results
            if item.get("status") == "RAN"
        }
        # A transient API error is retried on resume. Keep only the later
        # result for that feedback id, so the final report has one outcome.
        results = [
            item for item in results
            if item.get("status") == "RAN"
        ]

    started = time.perf_counter()
    pending_cases = [case for case in cases if case["feedback_id"] not in completed]
    print(f"RUNNING={len(pending_cases)} WORKERS={max(1, args.workers)}", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                run_case_with_fresh_token,
                case,
                args.backend_url,
                args.auth_env_file,
                chat_timeout=args.chat_timeout,
            ): case
            for case in pending_cases
        }
        for completed_count, future in enumerate(as_completed(futures), start=1):
            case = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {**case, "status": "ERROR", "error": str(exc), "duration_sec": 0}
            results.append(result)
            results.sort(key=lambda item: int(item.get("case_no") or 0))
            write_checkpoint(output_path, results)
            print(
                f"[{completed_count}/{len(pending_cases)}] {case['feedback_id']} "
                f"=> {result['status']} | {result.get('duration_sec')} sec",
                flush=True,
            )

    elapsed = round(time.perf_counter() - started, 3)
    print(f"TOTAL={len(results)} ELAPSED_SEC={elapsed}", flush=True)
    print(f"JSON={output_path}", flush=True)


if __name__ == "__main__":
    main()
