import unittest

from app.schemas.chat import ExternalChatRequest
from app.services.memory_service import init_db, reset_user_session


class ExternalChatSchemaTest(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_simple_member_request_uses_web_defaults(self):
        request = ExternalChatRequest(
            user_id="member_123456",
            is_logged_in=True,
            company_code="tdtv",
            msg="我想知道HBO在哪個頻道",
        )

        self.assertEqual(request.channel, "web")
        self.assertEqual(request.user_id, "member_123456")
        self.assertIsNone(request.member_id)
        self.assertTrue(request.is_logged_in)
        self.assertEqual(request.company_code, "tdtv")
        self.assertEqual(request.msg, "我想知道HBO在哪個頻道")
        self.assertIsNone(request.user)
        self.assertIsNone(request.message)
        self.assertIsNone(request.custnum)

    def test_custnum_is_explicit_customer_number_not_user_id(self):
        request = ExternalChatRequest(
            user_id="member_123456",
            custnum="A000001",
            phone="0988555666",
            is_logged_in=True,
            company_code="tdtv",
            msg="本期帳單金額查詢",
        )

        self.assertEqual(request.user_id, "member_123456")
        self.assertEqual(request.custnum, "A000001")
        self.assertEqual(request.phone, "0988555666")

    def test_top_level_cust_no_alias_is_accepted(self):
        request = ExternalChatRequest(
            user_id="member_123456",
            custNo="905397",
            is_logged_in=True,
            company_code="tdtv",
            msg="本期帳單金額查詢",
        )

        self.assertEqual(request.custNo, "905397")

    def test_external_memory_uses_cust_no_alias_as_authenticated_customer_number(self):
        try:
            from app.app_backend import apply_external_user_context
        except ModuleNotFoundError as exc:
            if exc.name == "fastapi":
                self.skipTest("fastapi is not installed")
            raise

        memory = apply_external_user_context(
            {},
            ExternalChatRequest(
                user_id="member_123456",
                custNo="905397",
                is_logged_in=True,
                msg="查帳單",
            ),
            "member_123456",
            "web:member_123456",
        )

        self.assertEqual(memory["known_info"]["custnum"], "905397")
        self.assertEqual(memory["known_info"]["custnum_source"], "web_authenticated")

    def test_legacy_nested_user_can_pass_custnum_and_phone(self):
        request = ExternalChatRequest(
            user={
                "user_id": "member_123456",
                "member_id": "member_123456",
                "custnum": "A000001",
                "phone": "0988555666",
                "is_logged_in": True,
            },
            company={
                "company_code": "tdtv",
            },
            message={
                "type": "text",
                "text": "本期帳單金額查詢",
            },
        )

        self.assertEqual(request.user.user_id, "member_123456")
        self.assertEqual(request.user.member_id, "member_123456")
        self.assertEqual(request.user.custnum, "A000001")
        self.assertEqual(request.user.phone, "0988555666")

    def test_simple_guest_request_can_use_temporary_user_id(self):
        request = ExternalChatRequest(
            user_id="guest_000001",
            is_logged_in=False,
            company_code="toplight",
            msg="網路不能用",
        )

        self.assertEqual(request.user_id, "guest_000001")
        self.assertFalse(request.is_logged_in)
        self.assertIsNone(request.member_id)
        self.assertEqual(request.company_code, "toplight")
        self.assertEqual(request.msg, "網路不能用")

    def test_legacy_nested_request_still_parses_for_transition(self):
        request = ExternalChatRequest(
            request_id="req_001",
            channel="web",
            user={
                "user_id": "member_123456",
            },
            company={
                "company_code": "tdtv",
            },
            message={
                "type": "text",
                "text": "那帳單呢",
            },
            ai_state={
                "company_code": "tdtv",
            },
            history=[
                {
                    "role": "user",
                    "content": "我想知道HBO在哪個頻道",
                },
                {
                    "role": "assistant",
                    "content": "HBO 是第 65 台。",
                },
            ],
            metadata={
                "page": "customer-service",
            },
        )

        self.assertEqual(request.request_id, "req_001")
        self.assertEqual(request.user.user_id, "member_123456")
        self.assertEqual(request.company.company_code, "tdtv")
        self.assertEqual(request.message.text, "那帳單呢")
        self.assertEqual(request.ai_state["company_code"], "tdtv")
        self.assertEqual(len(request.history), 2)
        self.assertEqual(request.metadata["page"], "customer-service")

    def test_external_memory_uses_explicit_company_in_message(self):
        try:
            from app.app_backend import memory_from_external_state, normalize_channel_user_id
        except ModuleNotFoundError as exc:
            if exc.name == "fastapi":
                self.skipTest("fastapi is not installed")
            raise

        request = ExternalChatRequest(
            user_id="UTEST_EXTERNAL_COMPANY",
            is_logged_in=False,
            company_code="tdtv",
            msg="新永安客服電話是多少？",
        )
        user_id = normalize_channel_user_id(request.channel or "web", request.user_id)
        reset_user_session(user_id)

        memory = memory_from_external_state(request, user_id)

        self.assertEqual(memory["company_code"], "hya")
        self.assertEqual(memory["company"], "新永安有線")
        self.assertEqual(memory["channel_context"]["resolution_source"], "company_name")
        self.assertEqual(
            memory["channel_context"]["conversation_company_override_code"],
            "hya",
        )

    def test_external_memory_marks_web_customer_number_by_login_state(self):
        try:
            from app.app_backend import apply_external_user_context
        except ModuleNotFoundError as exc:
            if exc.name == "fastapi":
                self.skipTest("fastapi is not installed")
            raise

        member_memory = apply_external_user_context(
            {},
            ExternalChatRequest(
                user_id="member_123456",
                custnum="905397",
                is_logged_in=True,
                msg="查帳單",
            ),
            "member_123456",
            "web:member_123456",
        )
        guest_memory = apply_external_user_context(
            {},
            ExternalChatRequest(
                user_id="guest_123456",
                custnum="905397",
                is_logged_in=False,
                msg="查帳單",
            ),
            "guest_123456",
            "web:guest_123456",
        )

        self.assertEqual(member_memory["known_info"]["custnum_source"], "web_authenticated")
        self.assertNotIn("custnum", guest_memory["known_info"])
        self.assertNotIn("custnum_source", guest_memory["known_info"])

    def test_external_install_location_keeps_request_company_as_account_scope(self):
        try:
            from app.app_backend import memory_from_external_state, normalize_channel_user_id
        except ModuleNotFoundError as exc:
            if exc.name == "fastapi":
                self.skipTest("fastapi is not installed")
            raise

        request = ExternalChatRequest(
            user_id="UTEST_EXTERNAL_INSTALL",
            is_logged_in=False,
            company_code="tdtv",
            msg="永康區可以裝網路嗎？",
        )
        user_id = normalize_channel_user_id(request.channel or "web", request.user_id)
        reset_user_session(user_id)

        memory = memory_from_external_state(request, user_id)

        self.assertEqual(memory["company_code"], "tdtv")
        self.assertEqual(memory["company"], "大屯有線")
        self.assertEqual(memory["channel_context"]["resolution_source"], "web_request")
        self.assertEqual(
            memory["service_availability_context"]["target"]["company_code"],
            "hya",
        )
        self.assertEqual(
            memory["service_availability_context"]["target"]["area"],
            "永康區",
        )


if __name__ == "__main__":
    unittest.main()
