import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import cust_api_diagnostic_logging


class CustApiDiagnosticLoggingTest(unittest.TestCase):
    def test_cust_api_diagnostic_log_excludes_identity_values(self):
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "cust_api_diagnostic.log"
            cust_api_diagnostic_logging._LOGGER = None
            cust_api_diagnostic_logging._LOGGER_PATH = None

            with patch.object(cust_api_diagnostic_logging, "CUST_API_DIAGNOSTIC_LOG_PATH", str(log_path)), patch.object(
                cust_api_diagnostic_logging,
                "CUST_API_DIAGNOSTIC_LOG_DAILY",
                False,
            ):
                with cust_api_diagnostic_logging.cust_api_diagnostic_context(
                    request_id="request-123",
                    user_id="test_web:user-1",
                    channel="test_web",
                    company_code="tdtv",
                ):
                    cust_api_diagnostic_logging.log_cust_api_diagnostic(
                        tool_name="search_bill",
                        url="https://example.test/cust/getCustBill",
                        payload={
                            "token": "secret-token",
                            "custNo": "905397",
                            "custTel": "0988555666",
                            "custCName": "王大明",
                        },
                        http_status=200,
                        response_data={"code": "0000", "msg": "查無客戶未繳帳單"},
                    )

            for handler in list(cust_api_diagnostic_logging._LOGGER.handlers):
                handler.flush()

            content = log_path.read_text(encoding="utf-8")
            record = json.loads(content)
            self.assertEqual(record["tool_name"], "search_bill")
            self.assertEqual(record["endpoint"], "getCustBill")
            self.assertEqual(record["api_code"], "0000")
            self.assertEqual(record["api_msg"], "查無客戶未繳帳單")
            self.assertEqual(record["identity_mode"], "custNo")
            self.assertEqual(record["request_id"], "request-123")
            self.assertEqual(record["user_id"], "test_web:user-1")
            self.assertEqual(record["channel"], "test_web")
            self.assertEqual(record["company_code"], "tdtv")
            self.assertEqual(record["identity_hint"], "custNo:***397")
            self.assertEqual(
                record["payload"],
                {
                    "token": "***",
                    "custNo": "***397",
                    "custTel": "*******666",
                    "custCName": "王**",
                },
            )
            self.assertNotIn("secret-token", content)
            self.assertNotIn("905397", content)
            self.assertNotIn("0988555666", content)
            self.assertNotIn("王大明", content)
            cust_api_diagnostic_logging.close_cust_api_diagnostic_logger()


if __name__ == "__main__":
    unittest.main()
