"""Publish externally rerun conversations to the local feedback tracker UI.

The tracker update schema applies default status values, so this script first
reads the existing state and sends those values back with each conversation.
Existing tracking state is preserved. Newly imported feedback records without
a state row are initialized as processed and pending review before their
adjusted conversation is stored.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from run_feedback_html_dialog_tests import build_backend_headers


DEFAULT_TRACKER_DB = Path(r"D:\AI智能客服\cust_app_runtime\feedback_tracker.db")


def load_tracker_states(path: Path) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT feedback_id, status, priority, owner, review_status, review_note,
                   acceptance_issue, acceptance_feedback
            FROM feedback_tracker_state
            """
        ).fetchall()
    finally:
        conn.close()
    return {str(row["feedback_id"]): dict(row) for row in rows}


def build_payload(result: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": state.get("status") or "processed",
        "priority": state.get("priority"),
        "owner": state.get("owner"),
        "review_status": state.get("review_status") or "pending",
        "review_note": state.get("review_note"),
        "acceptance_issue": state.get("acceptance_issue"),
        "acceptance_feedback": state.get("acceptance_feedback"),
        "adjusted_conversation": result.get("rerun_messages") or [],
    }


def publish_directly_to_local_tracker(
    results: list[dict[str, Any]],
    tracker_db: Path,
    dry_run: bool,
) -> int:
    updates = [
        (str(item.get("feedback_id") or ""), item.get("rerun_messages") or [])
        for item in results
        if item.get("status") == "RAN" and item.get("feedback_id") and item.get("rerun_messages")
    ]
    if not updates:
        return 0
    conn = sqlite3.connect(tracker_db)
    try:
        if not dry_run:
            now = datetime.now(timezone.utc).isoformat()
            conn.executemany(
                """
                INSERT INTO feedback_tracker_state (
                    feedback_id, status, review_status, adjusted_conversation_json,
                    updated_at, updated_by
                ) VALUES (?, 'processed', 'pending', ?, ?, ?)
                ON CONFLICT(feedback_id) DO UPDATE SET
                    adjusted_conversation_json=excluded.adjusted_conversation_json,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                [
                    (feedback_id, json.dumps(messages, ensure_ascii=False), now, "api-rerun-publisher")
                    for feedback_id, messages in updates
                ],
            )
            conn.commit()
    finally:
        conn.close()
    return len(updates)


def put_with_token_retry(
    backend_url: str,
    feedback_id: str,
    payload: dict[str, Any],
    auth_env_file: str,
    headers: dict[str, str],
    web_auth_token: str,
) -> dict[str, str]:
    url = f"{backend_url.rstrip('/')}/api/feedback-tracker/feedback/{feedback_id}"
    request_headers = {**headers, "X-Web-Auth-Token": web_auth_token}
    response = requests.put(url, headers=request_headers, json=payload, timeout=30)
    if response.status_code == 401:
        headers.clear()
        headers.update(build_backend_headers(backend_url, auth_env_file))
        request_headers = {**headers, "X-Web-Auth-Token": web_auth_token}
        response = requests.put(url, headers=request_headers, json=payload, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
    return response.json()


def create_web_auth_token(auth_env_file: str) -> str:
    # Settings must load the same test environment as Streamlit before these
    # imports, otherwise the local session token would be signed differently.
    os.environ["CUST_APP_ENV_FILE"] = auth_env_file
    from app.config.settings import WEB_AUTH_BOOTSTRAP_PASSWORD, WEB_AUTH_BOOTSTRAP_USERNAME
    from app.services.web_account_service import WebAccountService

    service = WebAccountService()
    service.init_schema()
    # ``authenticate`` writes a login audit row. The account store can be
    # read-only for this maintenance task, so use the configured local account
    # only to mint the same signed session token that Streamlit would send.
    account = service.get_account_by_username(WEB_AUTH_BOOTSTRAP_USERNAME)
    if not account:
        raise RuntimeError("無法使用測試環境的後台帳號建立回饋追蹤 session。")
    return service.create_session_token(account)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--auth-env-file", required=True)
    parser.add_argument("--tracker-db", default=str(DEFAULT_TRACKER_DB))
    parser.add_argument("--backend-url", default="http://127.0.0.1:8123")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--direct-local-tracker", action="store_true")
    args = parser.parse_args()

    results = json.loads(Path(args.report).read_text(encoding="utf-8"))
    if args.direct_local_tracker:
        published = publish_directly_to_local_tracker(
            results,
            Path(args.tracker_db),
            args.dry_run,
        )
        print(f"PUBLISHED={published}", flush=True)
        return
    states = load_tracker_states(Path(args.tracker_db))
    headers = build_backend_headers(args.backend_url, args.auth_env_file)
    web_auth_token = create_web_auth_token(args.auth_env_file)
    published = 0
    for index, result in enumerate(results, start=1):
        feedback_id = str(result.get("feedback_id") or "")
        messages = result.get("rerun_messages") or []
        if result.get("status") != "RAN" or not feedback_id or not messages:
            continue
        payload = build_payload(result, states.get(feedback_id, {}))
        if not args.dry_run:
            put_with_token_retry(
                args.backend_url,
                feedback_id,
                payload,
                args.auth_env_file,
                headers,
                web_auth_token,
            )
        published += 1
        print(f"[{index}/{len(results)}] {feedback_id}", flush=True)
    print(f"PUBLISHED={published}", flush=True)


if __name__ == "__main__":
    main()
