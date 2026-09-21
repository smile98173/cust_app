import json
import logging
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from app.config.settings import APP_ERROR_LOG_DAILY, APP_ERROR_LOG_PATH, PUBLIC_ERROR_MESSAGE


_LOGGER: Optional[logging.Logger] = None
_LOGGER_PATH: Optional[Path] = None


def dated_path(path: Path, enabled: bool = True) -> Path:
    if not enabled:
        return path
    date_suffix = datetime.now().strftime("%Y-%m-%d")
    return path.with_name(f"{path.stem}_{date_suffix}{path.suffix}")


def get_error_logger() -> logging.Logger:
    global _LOGGER, _LOGGER_PATH
    path = dated_path(Path(APP_ERROR_LOG_PATH), APP_ERROR_LOG_DAILY)
    if _LOGGER is not None and _LOGGER_PATH == path:
        return _LOGGER

    if _LOGGER is not None:
        close_error_logger()

    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("cust_app.error")
    logger.setLevel(logging.ERROR)
    logger.propagate = False

    if not logger.handlers:
        handler = RotatingFileHandler(
            path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    _LOGGER = logger
    _LOGGER_PATH = path
    return logger


def close_error_logger() -> None:
    global _LOGGER, _LOGGER_PATH
    logger = _LOGGER or logging.getLogger("cust_app.error")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    _LOGGER = None
    _LOGGER_PATH = None


def log_exception(
    operation: str,
    exc: BaseException,
    *,
    user_id: Optional[str] = None,
    request_path: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    record = {
        "timestamp": datetime.now().isoformat(),
        "level": "ERROR",
        "operation": operation,
        "user_id": user_id,
        "request_path": request_path,
        "exception_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exc(),
        "extra": extra or {},
    }
    try:
        get_error_logger().error(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass


def public_error_response() -> Dict[str, str]:
    return {
        "status": "error",
        "msg": PUBLIC_ERROR_MESSAGE,
    }
