import json
import logging
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from app.config.settings import CHAT_LATENCY_LOG_DAILY, CHAT_LATENCY_LOG_PATH
from app.services.error_logging import dated_path


_LOGGER: Optional[logging.Logger] = None
_LOGGER_PATH: Optional[Path] = None


def get_latency_logger() -> logging.Logger:
    global _LOGGER, _LOGGER_PATH
    path = dated_path(Path(CHAT_LATENCY_LOG_PATH), CHAT_LATENCY_LOG_DAILY)
    if _LOGGER is not None and _LOGGER_PATH == path:
        return _LOGGER

    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("cust_app.chat_latency")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    handler = RotatingFileHandler(
        path,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    _LOGGER = logger
    _LOGGER_PATH = path
    return logger


def log_chat_latency(
    *,
    user_id: str,
    user_text: str,
    memory: Dict[str, Any],
    router: Dict[str, Any],
    plan: Dict[str, Any],
    latency: Dict[str, Any],
    request_id: Optional[str] = None,
) -> None:
    channel_context = memory.get("channel_context") or {}
    matched_rule_id = router.get("matched_rule_id")
    if not matched_rule_id:
        reason = router.get("reason")
        if isinstance(reason, str) and re.fullmatch(r"[A-Za-z0-9_:-]+", reason.strip()):
            matched_rule_id = reason.strip()
    record = {
        "timestamp": datetime.now().isoformat(),
        "level": "INFO",
        "event": "chat_latency",
        "request_id": request_id,
        "user_id": user_id,
        "channel": channel_context.get("channel") or ("line" if str(user_id).startswith("line:") else "web"),
        "line_bot_code": channel_context.get("line_bot_code"),
        "company_code": memory.get("company_code"),
        "company": memory.get("company"),
        "route": router.get("route"),
        "intent": router.get("intent"),
        "promotion_scope": router.get("promotion_scope") or plan.get("promotion_scope"),
        "promotion_query_kind": (
            router.get("promotion_query_kind") or plan.get("promotion_query_kind")
        ),
        "reason": router.get("reason"),
        "matched_rule_id": matched_rule_id,
        "tool_name": router.get("tool_name") or plan.get("tool_name"),
        "decision_type": memory.get("decision_type") or plan.get("decision_type"),
        "message_length": len(user_text or ""),
        "latency": {
            key: round(float(value), 3)
            for key, value in latency.items()
            if key != "llm_events" and isinstance(value, (int, float))
        },
        "llm_calls": latency.get("llm_calls", 0),
        "llm_total": latency.get("llm_total", 0),
        "llm_events": latency.get("llm_events", []),
    }

    try:
        get_latency_logger().info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass
