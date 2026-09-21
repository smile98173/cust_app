import unittest

from app.services.customer_validation import (
    CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY,
    normalize_customer_number,
    normalize_tel,
    valid_name_tel,
    validate_name,
    validate_tel,
)
from app.services.controller_service import normalize_phone_value
from app.services.slot_manager import (
    extract_channel_name,
    extract_customer_number,
    extract_explicit_customer_number,
    extract_explicit_person_name,
    build_missing_args_question,
    get_missing_tool_args,
    has_invalid_customer_number_format,
    is_valid_person_name,
    merge_slots_into_memory,
    normalize_pending_tool_args,
    rule_extract_slots_from_text,
)


class CustomerValidationTest(unittest.TestCase):
    def test_explicit_customer_number_requires_a_customer_number_label(self):
        self.assertEqual(extract_explicit_customer_number("客編 1082281"), "1082281")
        self.assertEqual(
            extract_explicit_customer_number("客戶編號：1082281"),
            "1082281",
        )
        self.assertEqual(extract_explicit_customer_number("1082281客編"), "1082281")
        self.assertEqual(
            extract_explicit_customer_number("1082281 客戶編號"),
            "1082281",
        )
        self.assertIsNone(extract_explicit_customer_number("1082281"))

    def test_validate_name_matches_update_info_rules(self):
        self.assertTrue(validate_name("王大明"))
        self.assertTrue(validate_name("John Smith"))
        self.assertTrue(validate_name("阿布都·拉曼"))
        self.assertFalse(validate_name("王1明"))
        self.assertFalse(validate_name("A"))

    def test_validate_tel_matches_update_info_rules(self):
        self.assertTrue(validate_tel("0912345678"))
        self.assertTrue(validate_tel("02-2345-6789"))
        self.assertTrue(validate_tel("22345678"))
        self.assertFalse(validate_tel("12345"))
        self.assertFalse(validate_tel("0100123456"))

    def test_normalize_phone_value_returns_only_valid_digits(self):
        self.assertEqual(normalize_tel("09-1234-5678"), "0912345678")
        self.assertEqual(normalize_phone_value("09-1234-5678"), "0912345678")
        self.assertIsNone(normalize_phone_value("12345"))

    def test_valid_name_tel(self):
        self.assertTrue(valid_name_tel({"name": "王大明", "phone": "0912345678"}))
        self.assertFalse(valid_name_tel({"name": "王1明", "phone": "0912345678"}))

    def test_slot_name_validation_keeps_intent_words_blocked(self):
        self.assertTrue(is_valid_person_name("王大明"))
        self.assertFalse(is_valid_person_name("網路不能用"))
        self.assertFalse(is_valid_person_name("本期帳單金額查詢"))
        self.assertFalse(is_valid_person_name("會出現"))
        self.assertFalse(is_valid_person_name("系統繁忙"))
        self.assertFalse(is_valid_person_name("忘了繳費已被斷訊"))
        self.assertFalse(is_valid_person_name("一樣"))
        self.assertFalse(is_valid_person_name("還是一樣"))
        self.assertFalse(is_valid_person_name("沒改善"))

    def test_repair_transition_status_reply_is_not_contact_name(self):
        memory = {
            "known_info": {
                "repair_ready": "yes",
                "troubleshooting_started": "no",
                "troubleshooting_failed": "yes",
            },
            "pending_tool": None,
            "pending_tool_args": [],
        }

        slots = rule_extract_slots_from_text("一樣", memory, "create_repair_ticket")
        self.assertNotIn("contact_name", slots)

        updated = merge_slots_into_memory(
            memory,
            {"contact_name": "一樣"},
        )
        self.assertNotIn("contact_name", updated["known_info"])

    def test_repair_contact_name_is_extracted_when_requested(self):
        memory = {
            "known_info": {},
            "pending_tool": "create_repair_ticket",
            "pending_tool_args": ["contact_name", "contact_phone"],
        }

        slots = rule_extract_slots_from_text(
            "王大明 0912345678",
            memory,
            "create_repair_ticket",
        )

        self.assertEqual(slots["contact_name"], "王大明")
        self.assertEqual(slots["contact_phone"], "0912345678")

    def test_name_phone_with_punctuation_is_extracted_when_requested(self):
        memory = {
            "known_info": {},
            "pending_tool": "bill_return_line_tv",
            "pending_tool_args": ["name", "phone"],
        }

        slots = rule_extract_slots_from_text(
            "王大明，0988555666",
            memory,
            "bill_return_line_tv",
        )

        self.assertEqual(slots["name"], "王大明")
        self.assertEqual(slots["phone"], "0988555666")

    def test_bill_error_description_is_not_extracted_as_name(self):
        memory = {
            "known_info": {},
            "pending_tool": "search_bill",
            "pending_tool_args": ["name", "phone"],
        }

        slots = rule_extract_slots_from_text(
            "本期帳單金額查詢 會出現 系統繁忙",
            memory,
            "search_bill",
        )

        self.assertNotIn("name", slots)

        updated = merge_slots_into_memory(
            memory,
            {"name": "會出現"},
        )
        self.assertNotIn("name", updated["known_info"])

    def test_human_handoff_words_are_not_extracted_as_name(self):
        memory = {
            "known_info": {},
            "pending_tool": "search_contract_info",
            "pending_tool_args": ["name", "phone"],
        }

        for text in ["找真人", "轉真人", "找真人客服"]:
            with self.subTest(text=text):
                slots = rule_extract_slots_from_text(
                    text,
                    memory,
                    "search_contract_info",
                )

                self.assertNotIn("name", slots)

    def test_customer_number_label_is_extracted_for_bill_lookup(self):
        memory = {
            "known_info": {},
            "pending_tool": "search_bill",
            "pending_tool_args": ["name", "phone"],
        }

        slots = rule_extract_slots_from_text(
            "客戶編號 1071272",
            memory,
            "search_bill",
        )

        self.assertEqual(slots["custnum"], "1071272")
        self.assertNotIn("name", slots)
        self.assertNotIn("phone", slots)
        self.assertNotIn("service_address", slots)

    def test_customer_number_with_trailing_label_is_extracted_for_bill_lookup(self):
        memory = {
            "known_info": {},
            "pending_tool": "search_bill",
            "pending_tool_args": ["name", "phone"],
        }

        slots = rule_extract_slots_from_text(
            "1071272客編",
            memory,
            "search_bill",
        )

        self.assertEqual(slots["custnum"], "1071272")

    def test_plain_customer_number_is_extracted_when_identity_tool_is_pending(self):
        memory = {
            "known_info": {},
            "pending_tool": "search_bill",
            "pending_tool_args": ["name", "phone"],
        }

        slots = rule_extract_slots_from_text(
            "1071272",
            memory,
            "search_bill",
        )

        self.assertEqual(slots["custnum"], "1071272")

    def test_customer_number_with_symbol_is_rejected(self):
        self.assertIsNone(extract_customer_number("-046793"))
        self.assertIsNone(extract_customer_number("客編 -046793"))
        self.assertTrue(has_invalid_customer_number_format("-046793"))
        self.assertTrue(has_invalid_customer_number_format("客編 -046793"))
        self.assertFalse(has_invalid_customer_number_format("客編 905397"))

        memory = {
            "known_info": {},
            "pending_tool": "search_bill",
            "pending_tool_args": ["name", "phone"],
        }
        slots = rule_extract_slots_from_text("-046793", memory, "search_bill")
        self.assertNotIn("custnum", slots)

    def test_customer_number_must_not_start_with_zero(self):
        self.assertIsNone(normalize_customer_number("046793"))
        self.assertIsNone(extract_customer_number("046793"))
        self.assertIsNone(extract_customer_number("客編 046793"))
        self.assertTrue(has_invalid_customer_number_format("046793"))
        self.assertTrue(has_invalid_customer_number_format("客編 046793"))
        self.assertEqual(normalize_customer_number("905397"), "905397")
        self.assertEqual(extract_customer_number("客編 905397"), "905397")

        memory = {
            "known_info": {},
            "pending_tool": "search_bill",
            "pending_tool_args": ["name", "phone"],
        }
        slots = rule_extract_slots_from_text("046793", memory, "search_bill")
        self.assertNotIn("custnum", slots)

    def test_phone_is_not_extracted_as_customer_number(self):
        self.assertIsNone(extract_customer_number("0988555333"))

        memory = {
            "known_info": {},
            "pending_tool": "search_bill",
            "pending_tool_args": ["name", "phone"],
        }

        slots = rule_extract_slots_from_text(
            "0988555333",
            memory,
            "search_bill",
        )

        self.assertEqual(slots["phone"], "0988555333")
        self.assertNotIn("custnum", slots)

    def test_search_bill_does_not_require_service_address(self):
        self.assertEqual(
            get_missing_tool_args("search_bill", {"known_info": {}}),
            ["identity_pair"],
        )

    def test_search_bill_accepts_authenticated_web_customer_number_without_name_or_phone(self):
        memory = {
            "is_logged_in": True,
            "known_info": {
                "custnum": " 905397 ",
                "custnum_source": "web_authenticated",
                "is_logged_in": True,
            },
        }

        self.assertEqual(get_missing_tool_args("search_bill", memory), [])
        self.assertEqual(memory["known_info"]["custnum"], "905397")

    def test_all_customer_api_tools_accept_authenticated_web_customer_number_without_name_or_phone(self):
        for tool_name in [
            "search_bill",
            "search_contract_info",
            "bill_return_line_tv",
            "bill_return_line_internet",
        ]:
            with self.subTest(tool_name=tool_name):
                memory = {
                    "is_logged_in": True,
                    "known_info": {
                        "custnum": " 1082281 ",
                        "custnum_source": "web_authenticated",
                        "is_logged_in": True,
                    },
                }
                self.assertEqual(get_missing_tool_args(tool_name, memory), [])
                self.assertEqual(memory["known_info"]["custnum"], "1082281")

    def test_contract_lookup_rejects_chat_entered_identity(self):
        for memory in [
            {"known_info": {"name": "王大明", "phone": "0988555666"}},
            {
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "user_provided",
                    "name": "王大明",
                    "phone": "0988555666",
                }
            },
            {
                "channel_context": {"channel": "line"},
                "known_info": {
                    "custnum": "1082281",
                    "custnum_source": "user_provided",
                },
            },
        ]:
            with self.subTest(memory=memory):
                missing = get_missing_tool_args("search_contract_info", memory)
                self.assertEqual(missing, ["authenticated_web_custnum"])
                self.assertEqual(
                    build_missing_args_question("search_contract_info", missing, memory),
                    CONTRACT_LOOKUP_LOGIN_REQUIRED_REPLY,
                )

    def test_search_bill_accepts_any_two_valid_identity_fields(self):
        self.assertEqual(
            get_missing_tool_args(
                "search_bill",
                {"known_info": {"name": "王大明"}},
            ),
            ["identity_pair"],
        )
        self.assertEqual(
            get_missing_tool_args(
                "search_bill",
                {"known_info": {"phone": "0988555666"}},
            ),
            ["identity_pair"],
        )
        self.assertEqual(
            get_missing_tool_args(
                "search_bill",
                {"known_info": {"name": "王大明", "phone": "0988555666"}},
            ),
            [],
        )

    def test_unverified_customer_number_still_requires_one_more_identity_field(self):
        memory = {
            "known_info": {"custnum": "905397"},
            "pending_tool": "search_bill",
            "pending_tool_args": ["name", "phone"],
        }

        normalized = normalize_pending_tool_args(memory)

        self.assertEqual(normalized["pending_tool_args"], ["identity_pair"])

    def test_user_provided_customer_number_requires_one_more_identity_field(self):
        memory = {
            "known_info": {
                "custnum": "905397",
                "custnum_source": "user_provided",
            },
        }

        self.assertEqual(get_missing_tool_args("search_bill", memory), ["identity_pair"])

        memory["known_info"]["phone"] = "0988555666"
        self.assertEqual(get_missing_tool_args("search_bill", memory), [])

        memory["known_info"]["name"] = "王大明"
        self.assertEqual(get_missing_tool_args("search_bill", memory), [])

    def test_authenticated_web_customer_number_requires_no_extra_identity(self):
        memory = {
            "is_logged_in": True,
            "known_info": {
                "custnum": "905397",
                "custnum_source": "web_authenticated",
                "is_logged_in": True,
            },
        }

        for tool_name in [
            "search_bill",
            "search_contract_info",
            "bill_return_line_internet",
            "bill_return_line_tv",
        ]:
            self.assertEqual(get_missing_tool_args(tool_name, memory), [], tool_name)

    def test_reconnection_tools_do_not_require_service_address(self):
        memory = {"known_info": {}}

        self.assertEqual(
            get_missing_tool_args("bill_return_line_internet", memory),
            ["identity_pair"],
        )
        self.assertEqual(
            get_missing_tool_args("bill_return_line_tv", memory),
            ["identity_pair"],
        )

    def test_invalid_pending_identity_is_still_missing(self):
        memory = {
            "known_info": {
                "name": "查帳單",
                "phone": "12345",
            },
        }

        self.assertEqual(
            get_missing_tool_args("bill_return_line_tv", memory),
            ["identity_pair"],
        )

    def test_explicit_contact_name_label_is_cleaned(self):
        self.assertEqual(extract_explicit_person_name("聯絡人 王大明 電話 0912345678"), "王大明")

    def test_cancel_repair_extracts_ticket_id_and_phone_from_same_message(self):
        memory = {
            "known_info": {},
            "pending_tool": "cancel_repair_ticket",
            "pending_tool_args": ["repair_ticket_id", "contact_phone"],
        }

        slots = rule_extract_slots_from_text(
            "NT20260513-ABC123 0912345678",
            memory,
            "cancel_repair_ticket",
        )

        self.assertEqual(slots["repair_ticket_id"], "NT20260513-ABC123")
        self.assertEqual(slots["contact_phone"], "0912345678")

    def test_channel_name_strips_which_channel_suffix(self):
        self.assertEqual(extract_channel_name("東森電影台在哪一台"), "東森電影台")
        self.assertEqual(extract_channel_name("我想知道HBO在哪個頻道"), "HBO")
        self.assertEqual(extract_channel_name("找不到霹靂台"), "霹靂台灣台")
        self.assertEqual(extract_channel_name("霹靂台在第幾台"), "霹靂台灣台")

    def test_payment_receipt_barcodes_are_not_extracted_from_chat_text(self):
        memory = {
            "known_info": {},
            "pending_tool": "payment_bill_batch",
            "pending_tool_args": ["receipt_image_evidence"],
        }

        slots = rule_extract_slots_from_text(
            "代收項目: 123 有線電視\n"
            "第一段條碼: 1234567890\n"
            "第二段條碼: ABC1234567\n"
            "第三段條碼: 9999999999",
            memory,
            "payment_bill_batch",
        )

        self.assertNotIn("first_barcode", slots)
        self.assertNotIn("second_barcode", slots)
        self.assertNotIn("third_barcode", slots)

    def test_payment_receipt_barcodes_without_label_are_not_extracted_from_chat_text(self):
        memory = {
            "known_info": {},
            "pending_tool": "payment_bill_batch",
            "pending_tool_args": ["receipt_image_evidence"],
        }

        slots = rule_extract_slots_from_text(
            "第一段 150826TCN 第二段 0058072608022007 第三段 150841000000550",
            memory,
            "payment_bill_batch",
        )

        self.assertNotIn("first_barcode", slots)
        self.assertNotIn("second_barcode", slots)
        self.assertNotIn("third_barcode", slots)

    def test_payment_receipt_multiple_barcodes_are_not_extracted_from_chat_text(self):
        memory = {
            "known_info": {},
            "pending_tool": "payment_bill_batch",
            "pending_tool_args": ["receipt_image_evidence"],
        }

        slots = rule_extract_slots_from_text(
            "第1筆帳單\n"
            "第一段條碼: 1111111111\n"
            "第二段條碼: 2222222222\n"
            "第三段條碼: 3333333333\n"
            "第2筆帳單\n"
            "第一段條碼: 4444444444\n"
            "第二段條碼: 5555555555\n"
            "第三段條碼: 6666666666",
            memory,
            "payment_bill_batch",
        )

        self.assertNotIn("bills", slots)
        self.assertNotIn("first_barcode", slots)


if __name__ == "__main__":
    unittest.main()
