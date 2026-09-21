import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import app_backend
from app.services.knowledge_base_policy import (
    CENTRAL_COMMON_KNOWLEDGE_BASE,
    JIANNAN_COMMON_KNOWLEDGE_BASE,
)
from app.services.web_account_service import (
    ROLE_DEVELOPER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
)


class KnowledgeBaseAccessControlTest(unittest.TestCase):
    def require_as(self, account, knowledge_base, *, write=False):
        with patch.object(
            app_backend,
            "get_web_account_from_request",
            return_value=account,
        ):
            return app_backend.require_kb_permission(
                object(),
                knowledge_base,
                write=write,
            )

    def test_supervisor_can_view_every_knowledge_base(self):
        supervisor = {
            "role": ROLE_SUPERVISOR,
            "managed_knowledge_bases": ["大屯"],
        }

        self.assertIs(
            self.require_as(supervisor, "佳聯"),
            supervisor,
        )
        self.assertIs(
            self.require_as(supervisor, CENTRAL_COMMON_KNOWLEDGE_BASE),
            supervisor,
        )

    def test_supervisor_can_only_write_assigned_knowledge_bases(self):
        supervisor = {
            "role": ROLE_SUPERVISOR,
            "managed_knowledge_bases": [
                "台灣佳光",
                "大屯",
                CENTRAL_COMMON_KNOWLEDGE_BASE,
            ],
        }

        self.assertIs(
            self.require_as(supervisor, "西海岸", write=True),
            supervisor,
        )
        with self.assertRaises(HTTPException) as denied:
            self.require_as(supervisor, "佳聯", write=True)
        self.assertEqual(denied.exception.status_code, 403)

        self.assertIs(
            self.require_as(supervisor, CENTRAL_COMMON_KNOWLEDGE_BASE, write=True),
            supervisor,
        )
        self.assertIs(
            self.require_as(supervisor, "通用", write=True),
            supervisor,
        )
        with self.assertRaises(HTTPException):
            self.require_as(
                supervisor,
                JIANNAN_COMMON_KNOWLEDGE_BASE,
                write=True,
            )

    def test_developer_can_write_all_knowledge_bases(self):
        developer = {
            "role": ROLE_DEVELOPER,
            "managed_knowledge_bases": [],
        }

        for knowledge_base in (
            "大屯",
            "新永安",
            CENTRAL_COMMON_KNOWLEDGE_BASE,
            JIANNAN_COMMON_KNOWLEDGE_BASE,
        ):
            with self.subTest(knowledge_base=knowledge_base):
                self.assertIs(
                    self.require_as(developer, knowledge_base, write=True),
                    developer,
                )

    def test_staff_cannot_read_knowledge_bases(self):
        staff = {
            "role": ROLE_STAFF,
            "managed_knowledge_bases": ["大屯"],
        }

        with self.assertRaises(HTTPException) as denied:
            self.require_as(staff, "大屯")
        self.assertEqual(denied.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
