import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.config.settings import (
    CUST_API_DIAGNOSTIC_LOG_DAILY,
    CUST_API_DIAGNOSTIC_LOG_PATH,
)
from app.services.error_logging import dated_path


_LOGGER: Optional[logging.Logger] = None
_LOGGER_PATH: Optional[Path] = None
_DIAGNOSTIC_CONTEXT: ContextVar[Dict[str, Any]] = ContextVar(
    "cust_api_diagnostic_context",
    default={},
)


def get_cust_api_diagnostic_logger() -> logging.Logger:
    global _LOGGER, _LOGGER_PATH
    path = dated_path(Path(CUST_API_DIAGNOSTIC_LOG_PATH), CUST_API_DIAGNOSTIC_LOG_DAILY)
    if _LOGGER is not None and _LOGGER_PATH == path:
        return _LOGGER

    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("cust_app.cust_api_diagnostic")
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


def close_cust_api_diagnostic_logger() -> None:
    global _LOGGER, _LOGGER_PATH
    logger = _LOGGER or logging.getLogger("cust_app.cust_api_diagnostic")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    _LOGGER = None
    _LOGGER_PATH = None


def endpoint_name(url: str) -> str:
    parsed = urlparse(str(url or ""))
    path = parsed.path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else "unknown"


def identity_mode(payload: Dict[str, Any]) -> str:
    payload = payload or {}
    if str(payload.get("custNo") or "").strip():
        return "custNo"
    if str(payload.get("custCName") or "").strip() or str(payload.get("custTel") or "").strip():
        return "name_phone"
    return "none"


def _masked(value: Any, *, visible: int = 3) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) <= visible:
        return "*" * len(text)
    return f"{'*' * (len(text) - visible)}{text[-visible:]}"


def identity_hint(payload: Dict[str, Any]) -> Optional[str]:
    payload = payload or {}
    cust_no = _masked(payload.get("custNo"), visible=3)
    if cust_no:
        return f"custNo:{cust_no}"

    phone = _masked(payload.get("custTel"), visible=3)
    name = str(payload.get("custCName") or "").strip()
    parts = []
    if name:
        parts.append(f"name:{name[0]}{'*' * max(len(name) - 1, 1)}")
    if phone:
        parts.append(f"phone:{phone}")
    return ",".join(parts) or None


def _masked_name(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    return f"{text[0]}{'*' * max(len(text) - 1, 1)}"


def masked_payload_value(key: str, value: Any) -> Any:
    lowered = str(key or "").lower()
    if isinstance(value, dict):
        return masked_payload(value)
    if isinstance(value, list):
        return [masked_payload_value(key, item) for item in value]
    if value is None:
        return None

    if any(secret in lowered for secret in ("token", "password", "authorization")):
        return "***"
    if lowered in {"custno", "cust_no", "custnum", "customernumber", "accountno"}:
        return _masked(value, visible=3)
    if lowered in {"custtel", "cust_tel", "phone", "tel", "contactphone", "contact_phone"}:
        return _masked(value, visible=3)
    if lowered in {"custcname", "cust_cname", "name", "contactname", "contact_name"}:
        return _masked_name(value)

    return safe_preview(value)


def masked_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {str(key): masked_payload_value(str(key), value) for key, value in payload.items()}


def safe_preview(value: Any, *, limit: int = 300) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"(?i)(token|password|authorization)(\s*[:=]\s*)[^\s,&]+", r"\1\2***", text)
    text = re.sub(r"(?<!\d)\d{6,}(?!\d)", lambda match: _masked(match.group(0), visible=3) or "***", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


@contextmanager
def cust_api_diagnostic_context(**values: Any):
    current = dict(_DIAGNOSTIC_CONTEXT.get() or {})
    current.update({key: value for key, value in values.items() if value not in (None, "")})
    token = _DIAGNOSTIC_CONTEXT.set(current)
    try:
        yield
    finally:
        _DIAGNOSTIC_CONTEXT.reset(token)


def log_cust_api_diagnostic(
    *,
    tool_name: Optional[str] = None,
    url: str = "",
    payload: Optional[Dict[str, Any]] = None,
    http_status: Optional[int] = None,
    response_data: Optional[Dict[str, Any]] = None,
    error_type: Optional[str] = None,
    stage: str = "endpoint",
    elapsed_sec: Optional[float] = None,
    success: Optional[bool] = None,
    error_detail: Optional[str] = None,
    final_message: Optional[str] = None,
    attempt: Optional[int] = None,
    max_attempts: Optional[int] = None,
) -> None:
    context = dict(_DIAGNOSTIC_CONTEXT.get() or {})
    payload = payload or {}
    data = response_data if isinstance(response_data, dict) else {}
    resolved_success = success if success is not None else http_status == 200
    record = {
        "timestamp": datetime.now().isoformat(),
        "level": "INFO" if resolved_success else "WARNING",
        "event": "cust_api_response",
        "stage": stage,
        "request_id": context.get("request_id"),
        "user_id": context.get("user_id"),
        "channel": context.get("channel"),
        "company_code": context.get("company_code"),
        "tool_name": tool_name or context.get("tool_name") or "unknown",
        "endpoint": endpoint_name(url),
        "http_status": http_status,
        "api_code": data.get("code"),
        "api_msg": safe_preview(data.get("msg")),
        "identity_mode": identity_mode(payload),
        "identity_hint": identity_hint(payload),
        "payload": masked_payload(payload),
        "success": bool(resolved_success),
    }
    if elapsed_sec is not None:
        record["elapsed_sec"] = round(float(elapsed_sec), 3)
    if error_type:
        record["error_type"] = error_type
    if error_detail:
        record["error_detail"] = safe_preview(error_detail)
    if final_message:
        record["final_message"] = safe_preview(final_message)
    if attempt is not None:
        record["attempt"] = int(attempt)
    if max_attempts is not None:
        record["max_attempts"] = int(max_attempts)

    record = {key: value for key, value in record.items() if value is not None}

    try:
        get_cust_api_diagnostic_logger().info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass


def log_cust_api_tool_result(tool_result: Dict[str, Any]) -> None:
    result = tool_result if isinstance(tool_result, dict) else {}
    raw = (result.get("data") or {}).get("raw")
    raw_data = raw if isinstance(raw, dict) else {}
    log_cust_api_diagnostic(
        stage="tool_result",
        response_data=raw_data,
        success=bool(result.get("success")),
        error_type=(result.get("data") or {}).get("error_type"),
        final_message=result.get("message"),
    )
