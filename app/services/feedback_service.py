import csv
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.settings import FEEDBACK_CSV_DAILY, FEEDBACK_CSV_PATH, FEEDBACK_DIR
from app.services.memory_service import db_conn, get_recent_chat_history
from app.services.error_logging import log_exception
from app.services.regional_policy import resolve_policy_context


CSV_FIELDS = [
    "feedback_id",
    "created_at",
    "user_id",
    "company_code",
    "company",
    "tv_cable",
    "region_code",
    "regional_knowledge_base",
    "station_knowledge_base",
    "policy_resolution_status",
    "resolved_knowledge_bases_json",
    "applied_policy_rules_json",
    "feedback_type",
    "suggestion",
    "user_message",
    "ai_response",
    "decision_type",
    "pending_tool",
    "pending_tool_args_json",
    "known_info_json",
    "last_tool_result_json",
    "last_knowledge_results_json",
    "conversation_json",
]


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def dated_csv_path(csv_path: Optional[str] = None, enabled: bool = FEEDBACK_CSV_DAILY) -> Path:
    base_path = csv_path if csv_path and str(csv_path).strip() else FEEDBACK_CSV_PATH
    path = Path(base_path if str(base_path or "").strip() else FEEDBACK_DIR / "ai_feedback.csv")
    if not path.name:
        path = FEEDBACK_DIR / "ai_feedback.csv"
    if not enabled:
        return path
    date_suffix = datetime.now().strftime("%Y-%m-%d")
    return path.with_name(f"{path.stem}_{date_suffix}{path.suffix}")


def get_last_turn(conversation: List[Dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
    last_user = None
    last_assistant = None

    for message in conversation or []:
        role = message.get("role")
        content = message.get("content")
        if role == "user":
            last_user = str(content or "")
        elif role == "assistant":
            last_assistant = str(content or "")

    return last_user, last_assistant


def build_feedback_record(
    *,
    user_id: str,
    tv_cable: str,
    feedback_type: str,
    suggestion: str,
    memory: Dict[str, Any],
    conversation: Optional[List[Dict[str, Any]]] = None,
    user_message: Optional[str] = None,
    ai_response: Optional[str] = None,
) -> Dict[str, Any]:
    conversation = conversation or get_recent_chat_history(user_id, limit=30)
    last_user, last_assistant = get_last_turn(conversation)
    known_info = memory.get("known_info", {})
    policy_context = memory.get("policy_context")
    if not isinstance(policy_context, dict):
        policy_context = resolve_policy_context(memory)

    return {
        "feedback_id": "FB-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6].upper(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "user_id": user_id,
        "company_code": memory.get("company_code"),
        "company": memory.get("company"),
        "tv_cable": tv_cable,
        "region_code": policy_context.get("region_code"),
        "regional_knowledge_base": policy_context.get("regional_knowledge_base"),
        "station_knowledge_base": policy_context.get("station_knowledge_base"),
        "policy_resolution_status": policy_context.get("policy_resolution_status"),
        "resolved_knowledge_bases_json": json_dumps(memory.get("resolved_knowledge_bases", [])),
        "applied_policy_rules_json": json_dumps(memory.get("applied_policy_rules", [])),
        "feedback_type": feedback_type or "bad_answer",
        "suggestion": (suggestion or "").strip(),
        "user_message": user_message or last_user or "",
        "ai_response": ai_response or last_assistant or "",
        "decision_type": memory.get("decision_type"),
        "pending_tool": memory.get("pending_tool"),
        "pending_tool_args_json": json_dumps(memory.get("pending_tool_args", [])),
        "known_info_json": json_dumps(known_info),
        "last_tool_result_json": json_dumps(memory.get("last_tool_result")),
        "last_knowledge_results_json": json_dumps(memory.get("last_knowledge_results", [])),
        "conversation_json": json_dumps(conversation),
        "memory_json": json_dumps(memory),
    }


def ensure_feedback_csv_schema(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return

    try:
        with path.open("r", newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames == CSV_FIELDS:
                return
            rows = list(reader)
    except Exception:
        return

    temp_path = path.with_suffix(path.suffix + ".schema.tmp")
    with temp_path.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
    temp_path.replace(path)


def append_feedback_csv(record: Dict[str, Any], csv_path: Optional[str] = None) -> str:
    path = Path(csv_path) if csv_path and str(csv_path).strip() else dated_csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_feedback_csv_schema(path)
    file_exists = path.exists() and path.stat().st_size > 0

    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({field: record.get(field, "") for field in CSV_FIELDS})

    return str(path)


def insert_feedback_record(record: Dict[str, Any], csv_path: str) -> None:
    conn = db_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO feedback_records (
            feedback_id, user_id, company_code, company, tv_cable,
            feedback_type, suggestion, user_message, ai_response,
            conversation_json, memory_json, csv_path, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["feedback_id"],
            record["user_id"],
            record.get("company_code"),
            record.get("company"),
            record.get("tv_cable"),
            record.get("feedback_type"),
            record.get("suggestion"),
            record.get("user_message"),
            record.get("ai_response"),
            record.get("conversation_json"),
            record.get("memory_json"),
            csv_path,
            record["created_at"],
        ),
    )
    conn.commit()
    conn.close()


def feedback_duplicate_key(record: Dict[str, Any]) -> str:
    """Identify an accidental repeat without conflating separate feedback."""
    fields = (
        record.get("user_id"),
        record.get("company_code"),
        record.get("feedback_type"),
        record.get("suggestion"),
        record.get("conversation_json"),
    )
    normalized = "\x1f".join(str(value or "").strip() for value in fields)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def find_recent_duplicate_feedback(record: Dict[str, Any], window_minutes: int = 10) -> str | None:
    """Return an identical recent submission, if the feedback button was repeated."""
    created_at = datetime.fromisoformat(str(record["created_at"]))
    cutoff = (created_at - timedelta(minutes=window_minutes)).isoformat(timespec="seconds")
    target_key = feedback_duplicate_key(record)
    conn = db_conn()
    try:
        rows = conn.execute(
            """
            SELECT feedback_id, user_id, company_code, feedback_type, suggestion,
                   conversation_json
            FROM feedback_records
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at DESC
            """,
            (cutoff, record["created_at"]),
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        if feedback_duplicate_key(dict(row)) == target_key:
            return str(row["feedback_id"])
    return None


def save_feedback(
    *,
    user_id: str,
    tv_cable: str,
    feedback_type: str,
    suggestion: str,
    memory: Dict[str, Any],
    conversation: Optional[List[Dict[str, Any]]] = None,
    user_message: Optional[str] = None,
    ai_response: Optional[str] = None,
) -> Dict[str, Any]:
    record = build_feedback_record(
        user_id=user_id,
        tv_cable=tv_cable,
        feedback_type=feedback_type,
        suggestion=suggestion,
        memory=memory,
        conversation=conversation,
        user_message=user_message,
        ai_response=ai_response,
    )

    if not record["suggestion"]:
        raise ValueError("feedback suggestion is required")

    duplicate_feedback_id = find_recent_duplicate_feedback(record)
    if duplicate_feedback_id:
        return {
            "feedback_id": duplicate_feedback_id,
            "csv_path": None,
            "created_at": record["created_at"],
            "db_saved": True,
            "duplicate": True,
        }

    csv_path = append_feedback_csv(record)
    db_saved = True
    try:
        insert_feedback_record(record, csv_path)
    except Exception as exc:
        db_saved = False
        log_exception(
            "feedback.insert_feedback_record",
            exc,
            user_id=user_id,
            extra={"feedback_id": record["feedback_id"], "csv_path": csv_path},
        )

    return {
        "feedback_id": record["feedback_id"],
        "csv_path": csv_path,
        "created_at": record["created_at"],
        "db_saved": db_saved,
        "duplicate": False,
    }


def get_feedback_csv_path() -> str:
    path = dated_csv_path(FEEDBACK_CSV_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
    return str(path)
