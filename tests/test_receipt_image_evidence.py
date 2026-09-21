import unittest

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


class ReceiptImageEvidenceTest(unittest.TestCase):
    def test_complete_store_receipt_ocr_is_verified(self):
        evidence = evaluate_store_receipt_ocr(VALID_RECEIPT_OCR)

        self.assertTrue(evidence["verified"])
        self.assertEqual(evidence["bills"][0]["second_barcode"], "0058072608022007")

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
