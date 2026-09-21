import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import web_account_service
from app.services.web_account_service import (
    PERMISSION_ACCOUNT_MANAGEMENT,
    PERMISSION_COMPANY_PROFILES,
    PERMISSION_FEEDBACK,
    PERMISSION_KNOWLEDGE_BASE,
    ROLE_DEVELOPER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    WebAccountError,
    WebAccountService,
    can_manage_knowledge_base,
    can_view_knowledge_base,
    has_permission,
)
from app.services.knowledge_base_policy import (
    CENTRAL_COMMON_KNOWLEDGE_BASE,
    JIANNAN_COMMON_KNOWLEDGE_BASE,
)


class WebAccountServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "web_accounts.db")
        self.service = WebAccountService(self.db_path, secret="test-secret")
        self.service.init_schema()
        self.iteration_patch = patch.object(web_account_service, "PASSWORD_ITERATIONS", 1_000)
        self.iteration_patch.start()

    def tearDown(self):
        self.iteration_patch.stop()
        self.temp_dir.cleanup()

    def test_bootstrap_from_env_creates_first_developer_only_once(self):
        with patch.object(web_account_service, "WEB_AUTH_BOOTSTRAP_USERNAME", "Admin"), \
                patch.object(web_account_service, "WEB_AUTH_BOOTSTRAP_PASSWORD", "secret"):
            created = self.service.bootstrap_from_env()
            created_again = self.service.bootstrap_from_env()

        self.assertTrue(created)
        self.assertFalse(created_again)
        account = self.service.authenticate("admin", "secret")
        self.assertIsNotNone(account)
        self.assertEqual(account["role"], ROLE_DEVELOPER)

    def test_authenticate_rejects_bad_password_and_inactive_account(self):
        self.service.create_account(
            username="agent",
            password="secret",
            role=ROLE_STAFF,
            actor_username="admin",
        )

        self.assertIsNone(self.service.authenticate("agent", "wrong"))
        self.assertIsNotNone(self.service.authenticate("agent", "secret"))

        self.service.update_account(
            "agent",
            is_active=False,
            actor_username="admin",
        )

        self.assertIsNone(self.service.authenticate("agent", "secret"))

    def test_cannot_disable_or_demote_last_active_developer(self):
        self.service.create_account(
            username="admin",
            password="secret",
            role=ROLE_DEVELOPER,
            actor_username="system",
        )

        with self.assertRaises(WebAccountError):
            self.service.update_account("admin", is_active=False, actor_username="admin")

        with self.assertRaises(WebAccountError):
            self.service.update_account("admin", role=ROLE_SUPERVISOR, actor_username="admin")

        self.service.create_account(
            username="dev2",
            password="secret",
            role=ROLE_DEVELOPER,
            actor_username="admin",
        )
        updated = self.service.update_account(
            "admin",
            is_active=False,
            actor_username="admin",
        )

        self.assertFalse(updated["is_active"])

    def test_session_token_requires_active_account(self):
        account = self.service.create_account(
            username="supervisor",
            password="secret",
            role=ROLE_SUPERVISOR,
            actor_username="admin",
        )
        token = self.service.create_session_token(account)

        self.assertEqual(self.service.validate_session_token(token)["username"], "supervisor")

        self.service.update_account("supervisor", is_active=False, actor_username="admin")

        self.assertIsNone(self.service.validate_session_token(token))

    def test_role_permissions_match_ui_policy(self):
        developer = {"role": ROLE_DEVELOPER}
        supervisor = {"role": ROLE_SUPERVISOR}
        staff = {"role": ROLE_STAFF}

        self.assertTrue(has_permission(developer, PERMISSION_ACCOUNT_MANAGEMENT))
        self.assertTrue(has_permission(supervisor, PERMISSION_COMPANY_PROFILES))
        self.assertTrue(has_permission(supervisor, PERMISSION_KNOWLEDGE_BASE))
        self.assertFalse(has_permission(supervisor, PERMISSION_ACCOUNT_MANAGEMENT))
        self.assertTrue(has_permission(staff, PERMISSION_FEEDBACK))
        self.assertFalse(has_permission(staff, PERMISSION_COMPANY_PROFILES))
        self.assertFalse(has_permission(staff, PERMISSION_KNOWLEDGE_BASE))

    def test_supervisor_can_only_manage_selected_knowledge_bases(self):
        supervisor = self.service.create_account(
            username="north-lead",
            password="secret",
            role=ROLE_SUPERVISOR,
            managed_knowledge_bases=[
                "台灣佳光",
                "佳光市區",
                "大屯",
                "中投",
                CENTRAL_COMMON_KNOWLEDGE_BASE,
            ],
            actor_username="admin",
        )

        self.assertEqual(
            supervisor["managed_knowledge_bases"],
            [
                "西海岸",
                "佳光市區",
                "大屯",
                "中投",
                CENTRAL_COMMON_KNOWLEDGE_BASE,
            ],
        )
        self.assertTrue(can_manage_knowledge_base(supervisor, "台灣佳光"))
        self.assertTrue(can_manage_knowledge_base(supervisor, "西海岸"))
        self.assertTrue(can_manage_knowledge_base(supervisor, "大屯"))
        self.assertFalse(can_manage_knowledge_base(supervisor, "佳聯"))
        self.assertTrue(can_manage_knowledge_base(supervisor, "通用"))
        self.assertTrue(
            can_manage_knowledge_base(supervisor, CENTRAL_COMMON_KNOWLEDGE_BASE)
        )
        self.assertFalse(
            can_manage_knowledge_base(supervisor, JIANNAN_COMMON_KNOWLEDGE_BASE)
        )
        self.assertTrue(can_view_knowledge_base(supervisor, "佳聯"))
        self.assertTrue(
            can_view_knowledge_base(supervisor, CENTRAL_COMMON_KNOWLEDGE_BASE)
        )

    def test_legacy_common_scope_is_normalized_to_central_common(self):
        supervisor = self.service.create_account(
            username="legacy-common-lead",
            password="secret",
            role=ROLE_SUPERVISOR,
            managed_knowledge_bases=["通用"],
            actor_username="admin",
        )

        self.assertEqual(
            supervisor["managed_knowledge_bases"],
            [CENTRAL_COMMON_KNOWLEDGE_BASE],
        )
        self.assertTrue(can_manage_knowledge_base(supervisor, "通用"))
        self.assertTrue(
            can_manage_knowledge_base(supervisor, CENTRAL_COMMON_KNOWLEDGE_BASE)
        )

    def test_managed_knowledge_bases_can_be_changed_without_changing_role(self):
        account = self.service.create_account(
            username="south-lead",
            password="secret",
            role=ROLE_SUPERVISOR,
            managed_knowledge_bases=["新永安", "大揚"],
            actor_username="admin",
        )
        updated = self.service.update_account(
            "south-lead",
            managed_knowledge_bases=["新永安", "大揚", "佳聯", "北港"],
            actor_username="admin",
        )

        self.assertEqual(
            updated["managed_knowledge_bases"],
            ["新永安", "大揚", "佳聯", "北港"],
        )
        self.assertEqual(account["role"], updated["role"])

    def test_common_knowledge_base_scopes_are_configurable_and_persisted(self):
        defaults = self.service.get_common_knowledge_base_scopes()
        self.assertIn("大屯", defaults[CENTRAL_COMMON_KNOWLEDGE_BASE])
        self.assertIn("新永安", defaults[JIANNAN_COMMON_KNOWLEDGE_BASE])

        updated = self.service.update_common_knowledge_base_scopes(
            {
                CENTRAL_COMMON_KNOWLEDGE_BASE: ["大揚", "台灣佳光"],
                JIANNAN_COMMON_KNOWLEDGE_BASE: ["新永安"],
            },
            actor_username="admin",
        )

        self.assertEqual(
            updated[CENTRAL_COMMON_KNOWLEDGE_BASE],
            ["大揚", "西海岸"],
        )
        self.assertEqual(
            updated[JIANNAN_COMMON_KNOWLEDGE_BASE],
            ["新永安"],
        )
        reloaded = WebAccountService(self.db_path, secret="test-secret")
        self.assertEqual(
            reloaded.get_common_knowledge_base_scopes(),
            updated,
        )
        audit = self.service.list_audit_logs(
            action="update_common_knowledge_base_scopes",
        )
        self.assertEqual(audit[0]["actor_username"], "admin")
        self.assertEqual(audit[0]["detail"]["scopes"], updated)

    def test_common_knowledge_base_scope_rejects_non_common_target(self):
        with self.assertRaises(WebAccountError):
            self.service.update_common_knowledge_base_scopes(
                {"大屯": ["佳聯"]},
                actor_username="admin",
            )

    def test_common_knowledge_base_scope_rejects_cross_region_overlap(self):
        with self.assertRaisesRegex(WebAccountError, "不可同時套用中區與嘉南區"):
            self.service.update_common_knowledge_base_scopes(
                {
                    CENTRAL_COMMON_KNOWLEDGE_BASE: ["大屯"],
                    JIANNAN_COMMON_KNOWLEDGE_BASE: ["大屯"],
                },
                actor_username="admin",
            )

    def test_developer_can_manage_all_knowledge_bases(self):
        developer = {"role": ROLE_DEVELOPER, "managed_knowledge_bases": []}

        self.assertTrue(can_manage_knowledge_base(developer, "通用"))
        self.assertTrue(can_manage_knowledge_base(developer, "北港"))
        self.assertTrue(
            can_manage_knowledge_base(developer, CENTRAL_COMMON_KNOWLEDGE_BASE)
        )
        self.assertTrue(
            can_manage_knowledge_base(developer, JIANNAN_COMMON_KNOWLEDGE_BASE)
        )
        self.assertTrue(can_view_knowledge_base(developer, "新永安"))

    def test_staff_cannot_view_or_manage_knowledge_bases(self):
        staff = {"role": ROLE_STAFF, "managed_knowledge_bases": ["大屯"]}

        self.assertFalse(can_view_knowledge_base(staff, "大屯"))
        self.assertFalse(can_manage_knowledge_base(staff, "大屯"))

    def test_audit_logs_can_query_kb_deletions(self):
        self.service.log_audit(
            "north-lead",
            "delete_kb_document",
            "doc-1",
            {
                "title": "優惠方案",
                "file_name": "offer.docx",
                "knowledge_base": "大屯",
            },
        )
        self.service.log_audit("admin", "update_account", "north-lead", {})

        records = self.service.list_audit_logs(action="delete_kb_document")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["actor_username"], "north-lead")
        self.assertEqual(records[0]["detail"]["knowledge_base"], "大屯")


if __name__ == "__main__":
    unittest.main()
