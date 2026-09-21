import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config.settings import DB_PATH
from app.services.memory_service import infer_customer_key_from_user_id


def connect_readonly(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def build_user_id_candidates(raw_user_id: str) -> List[str]:
    user_id = raw_user_id.strip()
    candidates = [user_id]
    if ":" not in user_id:
        candidates.append(f"web:{user_id}")
    return list(dict.fromkeys([item for item in candidates if item]))


def find_sessions(conn: sqlite3.Connection, raw_user_id: str) -> List[Dict[str, Any]]:
    if not table_exists(conn, "sessions"):
        return []

    candidates = build_user_id_candidates(raw_user_id)
    rows: List[sqlite3.Row] = []
    for candidate in candidates:
        rows.extend(
            conn.execute(
                """
                SELECT user_id, customer_key, memory_json, updated_at
                FROM sessions
                WHERE user_id = ?
                """,
                (candidate,),
            ).fetchall()
        )

    if ":" not in raw_user_id and raw_user_id.strip().startswith("U"):
        rows.extend(
            conn.execute(
                """
                SELECT user_id, customer_key, memory_json, updated_at
                FROM sessions
                WHERE user_id LIKE ?
                ORDER BY updated_at DESC
                """,
                (f"line:%:{raw_user_id.strip()}",),
            ).fetchall()
        )

    seen = set()
    sessions = []
    for row in rows:
        if row["user_id"] in seen:
            continue
        seen.add(row["user_id"])
        memory = {}
        try:
            memory = json.loads(row["memory_json"] or "{}")
        except Exception:
            memory = {"_parse_error": True, "raw": row["memory_json"]}

        sessions.append({
            "user_id": row["user_id"],
            "customer_key": row["customer_key"],
            "updated_at": row["updated_at"],
            "memory": memory,
        })

    return sessions


def find_chat_logs(
    conn: sqlite3.Connection,
    user_ids: List[str],
    limit: int,
) -> Dict[str, List[Dict[str, Any]]]:
    if not table_exists(conn, "chat_logs"):
        return {}

    result = {}
    for user_id in user_ids:
        rows = conn.execute(
            """
            SELECT id, user_id, customer_key, role, message, created_at
            FROM chat_logs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        result[user_id] = [dict(row) for row in reversed(rows)]
    return result


def find_matched_user_ids(
    conn: sqlite3.Connection,
    raw_user_id: str,
    sessions: List[Dict[str, Any]],
) -> List[str]:
    user_ids = build_user_id_candidates(raw_user_id)
    user_ids.extend(session["user_id"] for session in sessions)

    if ":" not in raw_user_id and raw_user_id.strip().startswith("U"):
        pattern = f"line:%:{raw_user_id.strip()}"
        for table_name in ("sessions", "chat_logs"):
            if not table_exists(conn, table_name):
                continue
            rows = conn.execute(
                f"""
                SELECT DISTINCT user_id
                FROM {table_name}
                WHERE user_id LIKE ?
                """,
                (pattern,),
            ).fetchall()
            user_ids.extend(row["user_id"] for row in rows)

    return list(dict.fromkeys([user_id for user_id in user_ids if user_id]))


def find_customer_profiles(
    conn: sqlite3.Connection,
    raw_user_id: str,
    sessions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not table_exists(conn, "customer_profiles"):
        return []

    customer_keys = []
    inferred = infer_customer_key_from_user_id(raw_user_id)
    if inferred:
        customer_keys.append(inferred)
    if raw_user_id.startswith("U"):
        customer_keys.append(f"line:{raw_user_id}")
    for session in sessions:
        if session.get("customer_key"):
            customer_keys.append(session["customer_key"])
        memory = session.get("memory") or {}
        if memory.get("customer_key"):
            customer_keys.append(memory["customer_key"])

    profiles = []
    for customer_key in dict.fromkeys(customer_keys):
        row = conn.execute(
            """
            SELECT customer_key, last_company_code, last_company, last_area,
                   last_user_id, last_line_bot_code, resolution_source, updated_at
            FROM customer_profiles
            WHERE customer_key = ?
            """,
            (customer_key,),
        ).fetchone()
        if row:
            profiles.append(dict(row))

    return profiles


def query_user_state(db_path: str, raw_user_id: str, limit: int) -> Dict[str, Any]:
    with connect_readonly(db_path) as conn:
        sessions = find_sessions(conn, raw_user_id)
        user_ids = find_matched_user_ids(conn, raw_user_id, sessions)
        chat_logs = find_chat_logs(conn, user_ids, limit)
        customer_profiles = find_customer_profiles(conn, raw_user_id, sessions)

    return {
        "db_path": str(Path(db_path).resolve()),
        "input_user_id": raw_user_id,
        "matched_user_ids": user_ids,
        "sessions": sessions,
        "chat_logs": chat_logs,
        "customer_profiles": customer_profiles,
    }


def print_summary(result: Dict[str, Any]) -> None:
    print(f"DB: {result['db_path']}")
    print(f"Input user_id: {result['input_user_id']}")
    print()

    print("Matched user_ids:")
    for user_id in result["matched_user_ids"]:
        print(f"  - {user_id}")
    if not result["matched_user_ids"]:
        print("  (none)")
    print()

    print("Sessions:")
    if not result["sessions"]:
        print("  (no session found)")
    for session in result["sessions"]:
        memory = session.get("memory") or {}
        print(f"  - user_id: {session['user_id']}")
        print(f"    customer_key: {session.get('customer_key')}")
        print(f"    updated_at: {session.get('updated_at')}")
        print(f"    company_code: {memory.get('company_code')}")
        print(f"    company: {memory.get('company')}")
        print(f"    decision_type: {memory.get('decision_type')}")
        print(f"    pending_tool: {memory.get('pending_tool')}")
        print(f"    pending_tool_args: {memory.get('pending_tool_args')}")
        print(f"    known_info: {json.dumps(memory.get('known_info', {}), ensure_ascii=False)}")
        print(f"    channel_context: {json.dumps(memory.get('channel_context', {}), ensure_ascii=False)}")
    print()

    print("Customer profiles:")
    if not result["customer_profiles"]:
        print("  (no customer profile found)")
    for profile in result["customer_profiles"]:
        print(f"  - {json.dumps(profile, ensure_ascii=False)}")
    print()

    print("Recent chat logs:")
    if not result["chat_logs"]:
        print("  (no chat logs found)")
    for user_id, logs in result["chat_logs"].items():
        print(f"  [{user_id}]")
        if not logs:
            print("    (no chat logs)")
        for log in logs:
            print(f"    {log.get('created_at')} {log.get('role')}: {log.get('message')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query local SQLite session, chat logs, and customer profile by user_id.",
    )
    parser.add_argument("user_id", nargs="?", help="Stored user_id, member id, or raw LINE U id.")
    parser.add_argument("--db", default=DB_PATH, help=f"SQLite DB path. Default: {DB_PATH}")
    parser.add_argument("--limit", type=int, default=20, help="Chat log limit per matched user_id.")
    parser.add_argument("--json", action="store_true", help="Print full result as JSON.")
    args = parser.parse_args()

    user_id = args.user_id or input("請輸入 user_id：").strip()
    if not user_id:
        print("user_id 不可空白。", file=sys.stderr)
        return 2

    result = query_user_state(args.db, user_id, args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
