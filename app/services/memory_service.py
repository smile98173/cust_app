import sqlite3
from typing import Dict, Any, List

from app.config.settings import DB_PATH
from app.services.company_profile import DEFAULT_TV_CABLE, get_company_profile
from app.services.state_repository import get_state_repository


def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def infer_customer_key_from_user_id(user_id: str) -> str | None:
    value = (user_id or "").strip()
    parts = value.split(":")
    if len(parts) >= 3 and parts[0] == "line":
        raw_line_user_id = parts[-1]
        if raw_line_user_id:
            return f"line:{raw_line_user_id}"
    if value.startswith("test_web:"):
        return value
    if value.startswith("web:"):
        return value
    return None


def init_db():
    get_state_repository().init_schema()

    conn = db_conn()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS tickets")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS feedback_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feedback_id TEXT UNIQUE NOT NULL,
        user_id TEXT NOT NULL,
        company_code TEXT,
        company TEXT,
        tv_cable TEXT,
        feedback_type TEXT,
        suggestion TEXT NOT NULL,
        user_message TEXT,
        ai_response TEXT,
        conversation_json TEXT,
        memory_json TEXT,
        csv_path TEXT,
        created_at TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()


def default_memory() -> Dict[str, Any]:
    profile = get_company_profile(DEFAULT_TV_CABLE)
    return {
        "conversation_state": {
            "mode": "idle",   # idle / waiting_tool_args / waiting_schedule / waiting_confirmation
        },
        "service": None,
        "issue_type": None,
        "company_code": DEFAULT_TV_CABLE,
        "company": profile["company_name"],
        "company_profile": profile,
        "known_info": {},
        "next_goal": None,
        "need_dispatch": None,
        "available_slots": [],
        "last_knowledge_results": [],
        "last_knowledge_intent": None,
        "decision_type": None,
        "pending_tool": None,
        "pending_tool_args": [],
        "last_tool_result": None,
        "last_extracted_fields": None,
        "customer_key": None,
    }


def get_session_memory(user_id: str) -> Dict[str, Any]:
    document = get_state_repository().get_session_document(user_id)
    if not document:
        return default_memory()

    try:
        data = document.get("memory") or {}
        base = default_memory()
        base.update(data)

        # 防止舊資料沒有 conversation_state
        if "conversation_state" not in base or not isinstance(base["conversation_state"], dict):
            base["conversation_state"] = {"mode": "idle"}

        return base
    except Exception:
        return default_memory()


def save_session_memory(user_id: str, memory: Dict[str, Any]):
    customer_key = memory.get("customer_key") or infer_customer_key_from_user_id(user_id)
    if customer_key:
        memory["customer_key"] = customer_key
        memory.setdefault("channel_context", {})["customer_key"] = customer_key

    get_state_repository().save_session_document(user_id, memory, customer_key)


def save_chat_log(user_id: str, role: str, message: str, customer_key: str | None = None):
    customer_key = customer_key or infer_customer_key_from_user_id(user_id)
    get_state_repository().append_chat_log(user_id, role, message, customer_key)


def reset_user_session(user_id: str) -> Dict[str, Any]:
    """
    重置指定 user_id 的後端對話狀態。

    目前只清：
    - sessions
    - chat_logs
    """
    get_state_repository().delete_user_state(user_id)

    return {
        "conversation_state": "reset",
        "memory": default_memory(),
    }


def get_recent_chat_history(user_id: str, limit: int = 12) -> List[Dict[str, str]]:
    return get_state_repository().get_recent_chat_history(user_id, limit)


def list_chat_logs_since(
    start_date: str, limit: int = 20000, after: str | None = None,
) -> List[Dict[str, Any]]:
    return get_state_repository().list_chat_logs_since(start_date, limit, after)


def get_customer_profile(customer_key: str | None) -> Dict[str, Any] | None:
    if not customer_key:
        return None
    return get_state_repository().get_customer_profile(customer_key)


def save_customer_profile(profile: Dict[str, Any]) -> None:
    get_state_repository().save_customer_profile(profile)
