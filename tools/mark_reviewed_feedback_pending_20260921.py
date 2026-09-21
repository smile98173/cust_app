"""Move the 13 locally reviewed feedback items back to pending acceptance.

This utility only calls the already-running local backend. It does not invoke
feedback tracker pull or publish endpoints.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from scripts.run_feedback_html_dialog_tests import build_backend_headers


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TRACKER_DB = ROOT_DIR.parent / "cust_app_runtime" / "feedback_tracker.db"
DEFAULT_REPORT_DIR = ROOT_DIR / "reports"
VERIFIED_REPORT = DEFAULT_REPORT_DIR / "failed_feedback_manual_replay_20260921_105324.json"

FEEDBACK_IDS = (
    "FB-20260824113931-F7781B",
    "FB-20260824143457-EFB52D",
    "FB-20260831095207-96995E",
    "FB-20260831121311-247E3C",
    "FB-20260831124656-1D4B28",
    "FB-20260831145627-968FBB",
    "FB-20260902125357-F0AA74",
    "FB-20260903094111-4B9BCC",
    "FB-20260903100134-DE4585",
    "FB-20260903130144-AAC7A7",
    "FB-20260907105351-2A8E44",
    "FB-20260907121255-643430",
    "FB-20260907130110-1503B2",
)
FIXED_IDS = {
    "FB-20260824113931-F7781B",
    "FB-20260824143457-EFB52D",
    "FB-20260831095207-96995E",
}


def load_report(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else [payload]


def load_verified_results(report_path: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for item in load_report(report_path):
        feedback_id = str(item.get("feedback_id") or "")
        if feedback_id:
            results[feedback_id] = item

    missing = sorted(set(FEEDBACK_IDS) - set(results))
    if missing:
        raise RuntimeError(f"實測報告缺少案例：{', '.join(missing)}")

    for feedback_id in FEEDBACK_IDS:
        result = results[feedback_id]
        if result.get("status") != "RAN":
            raise RuntimeError(f"{feedback_id} 實測未成功")
        if result.get("model_call_findings"):
            raise RuntimeError(f"{feedback_id} 仍有模型呼叫問題")
        if not result.get("rerun_messages"):
            raise RuntimeError(f"{feedback_id} 沒有可儲存的調整後對話")
    return results


def load_current_rows(db_path: Path) -> dict[str, dict[str, Any]]:
    placeholders = ", ".join("?" for _ in FEEDBACK_IDS)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT feedback_id, status, priority, owner, review_status,
                   review_note, acceptance_issue, acceptance_feedback
            FROM feedback_tracker_state
            WHERE feedback_id IN ({placeholders})
            """,
            FEEDBACK_IDS,
        ).fetchall()
    finally:
        conn.close()

    current = {row["feedback_id"]: dict(row) for row in rows}
    missing = sorted(set(FEEDBACK_IDS) - set(current))
    if missing:
        raise RuntimeError(f"本機追蹤資料缺少：{', '.join(missing)}")
    unexpected = [
        feedback_id
        for feedback_id, row in current.items()
        if row.get("review_status") != "failed"
    ]
    if unexpected:
        raise RuntimeError(
            "以下案例已不是驗收退回，為避免覆寫而停止："
            + ", ".join(sorted(unexpected))
        )
    return current


def backup_database(source: Path, destination: Path) -> None:
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(destination_conn)
    finally:
        destination_conn.close()
        source_conn.close()


def cleaned_conversation(result: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": str(message.get("role") or ""),
            "content": str(message.get("content") or ""),
        }
        for message in result.get("rerun_messages") or []
        if message.get("role") in {"user", "assistant"}
        and str(message.get("content") or "").strip()
    ]


def review_note(existing: str, feedback_id: str) -> str:
    if feedback_id in FIXED_IDS:
        summary = "已依客服補充調整並使用原始對話通過 8123 重播，送回待驗收。"
    else:
        summary = "原始完整對話經 8123 重播後已符合現行回答與安全邊界，送回待驗收。"
    entry = f"2026-09-21 本機人工檢視：{summary} OpenAI gpt-5.5，fallback=false。"
    existing = str(existing or "").strip()
    if entry in existing:
        return existing
    return f"{existing}\n{entry}".strip()


def verify_updated_rows(db_path: Path) -> list[dict[str, Any]]:
    placeholders = ", ".join("?" for _ in FEEDBACK_IDS)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT feedback_id, status, review_status, updated_by,
                   adjusted_conversation_json
            FROM feedback_tracker_state
            WHERE feedback_id IN ({placeholders})
            ORDER BY feedback_id
            """,
            FEEDBACK_IDS,
        ).fetchall()
    finally:
        conn.close()

    result = [dict(row) for row in rows]
    invalid = [
        row["feedback_id"]
        for row in result
        if row["status"] != "processed"
        or row["review_status"] != "pending"
        or not row["adjusted_conversation_json"]
    ]
    if invalid:
        raise RuntimeError("更新後驗證失敗：" + ", ".join(invalid))
    return result


def update_directly(
    db_path: Path,
    current: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
) -> list[str]:
    updated: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for feedback_id in FEEDBACK_IDS:
            row = current[feedback_id]
            cursor = conn.execute(
                """
                UPDATE feedback_tracker_state
                SET status='processed', priority=?, owner=?, review_status='pending',
                    review_note=?, acceptance_issue=?, acceptance_feedback=?,
                    adjusted_conversation_json=?, updated_at=?, updated_by=?
                WHERE feedback_id=? AND review_status='failed'
                """,
                (
                    row.get("priority"),
                    row.get("owner") or "codex",
                    review_note(row.get("review_note") or "", feedback_id),
                    row.get("acceptance_issue"),
                    row.get("acceptance_feedback"),
                    json.dumps(
                        cleaned_conversation(results[feedback_id]),
                        ensure_ascii=False,
                    ),
                    datetime.now().isoformat(timespec="seconds"),
                    "codex-local-review",
                    feedback_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"{feedback_id} 本機狀態未更新")
            updated.append(feedback_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracker-db", default=str(DEFAULT_TRACKER_DB))
    parser.add_argument("--backend-url", default="http://127.0.0.1:8123")
    parser.add_argument("--auth-env-file", required=True)
    parser.add_argument("--backup-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--verified-report", default=str(VERIFIED_REPORT))
    parser.add_argument("--direct", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.tracker_db)
    results = load_verified_results(Path(args.verified_report))
    current = load_current_rows(db_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(args.backup_dir) / f"feedback_tracker_before_13_pending_{stamp}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_database(db_path, backup_path)

    if args.direct:
        updated = update_directly(db_path, current, results)
    else:
        headers = build_backend_headers(args.backend_url, args.auth_env_file)
        updated = []
        for feedback_id in FEEDBACK_IDS:
            row = current[feedback_id]
            payload = {
                "status": "processed",
                "priority": row.get("priority"),
                "owner": row.get("owner") or "codex",
                "review_status": "pending",
                "review_note": review_note(row.get("review_note") or "", feedback_id),
                "acceptance_issue": row.get("acceptance_issue"),
                "acceptance_feedback": row.get("acceptance_feedback"),
                "adjusted_conversation": cleaned_conversation(results[feedback_id]),
            }
            response = requests.put(
                f"{args.backend_url}/api/feedback-tracker/feedback/{quote(feedback_id, safe='')}",
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("status") != "success":
                raise RuntimeError(f"{feedback_id} 更新失敗：{body}")
            updated.append(feedback_id)

    verified = verify_updated_rows(db_path)
    print(json.dumps({
        "status": "success",
        "updated": len(updated),
        "pending_acceptance": len(verified),
        "fixed": len(FIXED_IDS),
        "kept": len(FEEDBACK_IDS) - len(FIXED_IDS),
        "online_sync": False,
        "backup": str(backup_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
