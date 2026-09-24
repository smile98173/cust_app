import unittest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from app.handlers.chat_handler import handle_chat_message

from app.services.receipt_image_evidence import (
    RECEIPT_IMAGE_REUPLOAD_REPLY,
    build_line_receipt_image_attempt,
    evaluate_store_receipt_ocr,
    is_receipt_image_submission,
    issue_receipt_image_evidence_token,
    verify_receipt_image_evidence_token,
)


VALID_RECEIPT_OCR = (
    "收據來源: 超商繳費收據\n"
    "超商名稱: 7-11\n"
    "繳費狀態: 已繳\n"
    "收據完整性: 完整\n"
    "代收項目: 大屯有線電視\n"
    "第一段條碼: 150826TCN\n"
    "第二段條碼: 0058072608022007\n"
    "第三段條碼: 150841000000550"
)

SEVEN_ELEVEN_RECEIPT_OCR = (
    "收據來源: 超商繳費收據\n"
    "超商名稱: 7-ELEVEN\n"
    "繳費狀態: 已繳\n"
    "收據完整性: 完整\n"
    "代收項目: ibon有線繳費台灣佳光\n"
    "第一段條碼: 1509235Y8\n"
    "第二段條碼: 060923TEZHXQ6101\n"
    "第三段條碼: 642300930003097"
)


class ReceiptImageEvidenceTest(unittest.TestCase):
    def test_complete_store_receipt_ocr_is_verified(self):
        evidence = evaluate_store_receipt_ocr(VALID_RECEIPT_OCR)

        self.assertTrue(evidence["verified"])
        self.assertEqual(evidence["bills"][0]["second_barcode"], "0058072608022007")

    def test_standard_seven_eleven_name_is_verified(self):
        evidence = evaluate_store_receipt_ocr(SEVEN_ELEVEN_RECEIPT_OCR)

        self.assertTrue(evidence["store_receipt"])
        self.assertTrue(evidence["paid"])
        self.assertTrue(evidence["complete"])
        self.assertTrue(evidence["verified"])
        self.assertEqual(evidence["bills"], [{
            "first_barcode": "1509235Y8",
            "second_barcode": "060923TEZHXQ6101",
            "third_barcode": "642300930003097",
        }])

    def test_standard_seven_eleven_name_issues_bound_evidence_token(self):
        user_id = "web:seven-eleven-customer"
        token = issue_receipt_image_evidence_token(SEVEN_ELEVEN_RECEIPT_OCR, user_id)
        user_message = (
            "我上傳了一張圖片，辨識內容如下："
            f"{SEVEN_ELEVEN_RECEIPT_OCR}"
        )

        self.assertIsNotNone(token)
        self.assertIsNotNone(
            verify_receipt_image_evidence_token(token, user_id, user_message)
        )

    def test_standard_seven_eleven_receipt_reaches_payment_tool(self):
        user_id = "web:seven-eleven-customer"
        user_message = (
            "我上傳了一張圖片，辨識內容如下："
            f"{SEVEN_ELEVEN_RECEIPT_OCR}"
        )
        token = issue_receipt_image_evidence_token(SEVEN_ELEVEN_RECEIPT_OCR, user_id)
        evidence = verify_receipt_image_evidence_token(token, user_id, user_message)
        router = {
            "route": "unknown",
            "intent": "other",
            "tool_name": None,
            "topic": None,
            "should_cancel_current_flow": False,
            "should_call_tool": False,
            "should_retrieve_knowledge": False,
            "knowledge_query": None,
            "reply": "",
            "extracted_slots": {},
            "reason": "test",
        }

        with (
            patch("app.handlers.chat_handler.log_chat_latency"),
            patch("app.handlers.chat_handler.run_intent_router", return_value=router),
            patch(
                "app.handlers.chat_handler.call_tool",
                return_value={"success": True, "message": "測試復線完成"},
            ) as call_tool,
        ):
            result = handle_chat_message(
                user_id=user_id,
                user_text=user_message,
                memory={
                    "company_code": "tdtv",
                    "known_info": {"receipt_image_evidence": evidence},
                },
                history=[],
                llm=RunnableLambda(lambda _prompt: None),
                persist=False,
            )

        call_tool.assert_called_once()
        self.assertEqual(call_tool.call_args.args[0], "payment_bill_batch")
        self.assertEqual(result["router"]["intent"], "payment_receipt_reconnection")
        self.assertIn("測試復線完成", result["ai_response"])
        self.assertNotIn("重新上傳", result["ai_response"])

    def test_barcodes_without_store_receipt_evidence_are_rejected(self):
        evidence = evaluate_store_receipt_ocr(
            "第一段條碼: 150826TCN\n"
            "第二段條碼: 0058072608022007\n"
            "第三段條碼: 150841000000550"
        )

        self.assertFalse(evidence["verified"])
        self.assertIn("重新上傳", RECEIPT_IMAGE_REUPLOAD_REPLY)

    def test_incomplete_receipt_ocr_is_still_recognized_for_reupload(self):
        user_message = (
            "我上傳了一張圖片，辨識內容如下：\n"
            "7-ELEVEN 代收收據\n"
            "第一段條碼: 150826TCN"
        )

        self.assertTrue(is_receipt_image_submission(user_message))
        self.assertFalse(evaluate_store_receipt_ocr(user_message)["verified"])

    def test_line_receipt_ocr_attempt_is_bound_to_the_image_turn(self):
        ocr_text = "7-ELEVEN 代收收據\n第一段條碼: 150826TCN"
        memory = {
            "known_info": {
                "receipt_image_ocr_attempt": build_line_receipt_image_attempt(ocr_text),
            }
        }

        self.assertTrue(is_receipt_image_submission(ocr_text, memory))
        self.assertFalse(is_receipt_image_submission("7-ELEVEN 代收收據", memory))

    def test_evidence_token_is_bound_to_user_and_exact_ocr_message(self):
        token = issue_receipt_image_evidence_token(VALID_RECEIPT_OCR, "web:customer-1")
        user_message = f"我上傳了一張圖片，辨識內容如下：\n{VALID_RECEIPT_OCR}"

        self.assertIsNotNone(
            verify_receipt_image_evidence_token(token, "web:customer-1", user_message)
        )
        self.assertIsNone(
            verify_receipt_image_evidence_token(token, "web:customer-2", user_message)
        )
        self.assertIsNone(
            verify_receipt_image_evidence_token(
                token,
                "web:customer-1",
                "第一段條碼: 150826TCN\n第二段條碼: 0058072608022007\n第三段條碼: 150841000000550",
            )
        )
