import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import error_logging


def test_log_exception_writes_json_line():
    with TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "app_errors.log"
        error_logging._LOGGER = None

        with patch.object(error_logging, "APP_ERROR_LOG_PATH", str(log_path)), \
                patch.object(error_logging, "APP_ERROR_LOG_DAILY", False):
            try:
                raise RuntimeError("mongo failed")
            except RuntimeError as exc:
                error_logging.log_exception(
                    "mongodb.append_chat_log",
                    exc,
                    user_id="web:member_1",
                    request_path="/api/v1/chat",
                    extra={"role": "user"},
                )

        record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
        assert record["operation"] == "mongodb.append_chat_log"
        assert record["user_id"] == "web:member_1"
        assert record["request_path"] == "/api/v1/chat"
        assert record["exception_type"] == "RuntimeError"
        assert record["error"] == "mongo failed"
        assert record["extra"]["role"] == "user"
        error_logging.close_error_logger()


def test_public_error_response_does_not_expose_private_detail():
    response = error_logging.public_error_response()

    assert response["status"] == "error"
    assert "Mongo" not in response["msg"]
    assert "DB" not in response["msg"]


def test_dated_path_adds_date_suffix():
    path = error_logging.dated_path(Path("logs/app_errors.log"), enabled=True)

    assert path.name.startswith("app_errors_")
    assert path.suffix == ".log"
