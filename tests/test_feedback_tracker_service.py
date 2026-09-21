import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services import feedback_tracker_service


class FeedbackTrackerConversationLogTest(unittest.TestCase):
    def test_legacy_ai_verdicts_become_processing_statuses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"):
                feedback_tracker_service.init_tracker_schema()
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    conn.executemany(
                        """
                        INSERT INTO feedback_tracker_state (
                            feedback_id, status, review_status, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        [
                            ("FB-PASS", "passed", "pending", "2026-09-07T10:00:00"),
                            ("FB-FAIL", "failed", "pending", "2026-09-07T10:00:00"),
                            ("FB-CSR", "closed", "passed", "2026-09-07T10:00:00"),
                        ],
                    )
                    conn.commit()
                finally:
                    conn.close()

                feedback_tracker_service.init_tracker_schema()
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    rows = {
                        row["feedback_id"]: (row["status"], row["review_status"])
                        for row in conn.execute(
                            "SELECT feedback_id, status, review_status FROM feedback_tracker_state"
                        )
                    }
                finally:
                    conn.close()

        self.assertEqual(rows["FB-PASS"], ("processed", "pending"))
        self.assertEqual(rows["FB-FAIL"], ("pending", "pending"))
        self.assertEqual(rows["FB-CSR"], ("processed", "passed"))

    def test_organizing_review_status_is_preserved_for_paused_cases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"):
                result = feedback_tracker_service.update_feedback_item(
                    "FB-ORGANIZING",
                    {"status": "processed", "review_status": "organizing"},
                    actor="test",
                )
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    row = conn.execute(
                        "SELECT status, review_status FROM feedback_tracker_state WHERE feedback_id=?",
                        ("FB-ORGANIZING",),
                    ).fetchone()
                finally:
                    conn.close()

        self.assertEqual(result["status"], "success")
        self.assertEqual((row["status"], row["review_status"]), ("processed", "organizing"))

    def test_merged_review_status_preserves_source_without_pending_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"):
                result = feedback_tracker_service.update_feedback_item(
                    "FB-MERGED",
                    {
                        "status": "processed",
                        "review_status": "merged",
                        "review_note": "已合併至代表案例 FB-PRIMARY。",
                    },
                    actor="test",
                )
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    row = conn.execute(
                        "SELECT status, review_status, review_note "
                        "FROM feedback_tracker_state WHERE feedback_id=?",
                        ("FB-MERGED",),
                    ).fetchone()
                finally:
                    conn.close()

        self.assertEqual(result["status"], "success")
        self.assertEqual((row["status"], row["review_status"]), ("processed", "merged"))
        self.assertIn("FB-PRIMARY", row["review_note"])

    def test_tracker_overview_can_exclude_merged_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"):
                feedback_tracker_service.init_tracker_schema()
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    conn.executemany(
                        """
                        INSERT INTO feedback_records (
                            feedback_id, user_id, suggestion, created_at
                        ) VALUES (?, 'test-user', 'test', '2026-09-18T10:00:00')
                        """,
                        [("FB-PRIMARY",), ("FB-MERGED",)],
                    )
                    conn.executemany(
                        """
                        INSERT INTO feedback_tracker_state (
                            feedback_id, status, review_status, updated_at
                        ) VALUES (?, 'processed', ?, '2026-09-18T11:00:00')
                        """,
                        [("FB-PRIMARY", "organizing"), ("FB-MERGED", "merged")],
                    )
                    conn.commit()
                finally:
                    conn.close()

                visible = feedback_tracker_service.list_feedback_items(
                    start_date="2026-09-18",
                    include_merged=False,
                )
                complete = feedback_tracker_service.list_feedback_items(
                    start_date="2026-09-18",
                    include_merged=True,
                )

        self.assertEqual([item["feedback_id"] for item in visible], ["FB-PRIMARY"])
        self.assertEqual(
            {item["feedback_id"] for item in complete},
            {"FB-PRIMARY", "FB-MERGED"},
        )

    def test_import_conversation_logs_deduplicates_repeated_sync(self):
        records = [
            {
                "id": 1,
                "user_id": "line:tdtv:U123",
                "customer_key": "line:U123",
                "role": "user",
                "message": "帳單怎麼看？",
                "created_at": "2026-08-24T10:00:00",
            },
            {
                "id": 2,
                "user_id": "line:tdtv:U123",
                "customer_key": "line:U123",
                "role": "assistant",
                "message": "我來協助您查詢。",
                "created_at": "2026-08-24T10:00:01",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"):
                self.assertEqual(feedback_tracker_service.import_conversation_logs(records), 2)
                self.assertEqual(feedback_tracker_service.import_conversation_logs(records), 0)
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    count = conn.execute("SELECT COUNT(*) FROM tracker_conversation_logs").fetchone()[0]
                finally:
                    conn.close()

        self.assertEqual(count, 2)

    def test_latency_logs_are_filtered_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "chat_latency.log"
            dated_log_path = Path(temp_dir) / "chat_latency_2026-08-24.log"
            dated_log_path.write_text(
                "\n".join([
                    '{"timestamp":"2026-08-23T23:59:59","event":"chat_latency"}',
                    '{"timestamp":"2026-08-24T10:00:00","event":"chat_latency","user_id":"line:tdtv:U123"}',
                ]),
                encoding="utf-8",
            )
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "CHAT_LATENCY_LOG_PATH", str(log_path)), \
                    patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"):
                records = feedback_tracker_service.load_latency_log_records("2026-08-24")
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["_source_file"], dated_log_path.name)
                self.assertEqual(feedback_tracker_service.import_latency_logs(records), 1)
                self.assertEqual(feedback_tracker_service.import_latency_logs(records), 0)

    def test_pull_uses_saved_cursor_with_short_overlap(self):
        response = Mock()
        response.json.return_value = {
            "feedback_records": [{
                "feedback_id": "FB-1",
                "user_id": "line:tdtv:U123",
                "suggestion": "測試建議",
                "created_at": "2026-08-24T10:00:00",
            }],
            "feedback_cursor": "2026-08-24T10:00:00",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"), \
                    patch.object(feedback_tracker_service, "FEEDBACK_TRACKER_ONLINE_API_BASE_URL", "https://example.test"), \
                    patch.object(feedback_tracker_service, "FEEDBACK_TRACKER_SYNC_TOKEN", "test-token"), \
                    patch.object(feedback_tracker_service.requests, "get", return_value=response) as request_get:
                first = feedback_tracker_service.pull_online_feedback()
                second = feedback_tracker_service.pull_online_feedback()

        self.assertFalse(first["incremental"])
        self.assertTrue(second["incremental"])
        self.assertFalse(first["tracking_updates_available"])
        self.assertEqual(first["tracking_updates_applied"], 0)
        self.assertEqual(request_get.call_args.kwargs["params"]["feedback_after"], "2026-08-24T09:55:00")

    def test_pull_applies_newer_online_tracking_states(self):
        response = Mock()
        response.json.return_value = {
            "feedback_records": [],
            "tracking_updates": {
                "kind": "feedback_tracker_updates",
                "feedback_states": [{
                    "feedback_id": "FB-ONLINE-REVIEW",
                    "status": "processed",
                    "review_status": "passed",
                    "review_note": "客服已驗收",
                    "acceptance_feedback": "回答正確",
                    "updated_at": "2026-09-18T12:00:00",
                    "updated_by": "online-csr",
                }],
                "case_states": [],
                "case_definitions": [],
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"), \
                    patch.object(feedback_tracker_service, "FEEDBACK_TRACKER_ONLINE_API_BASE_URL", "https://example.test"), \
                    patch.object(feedback_tracker_service, "FEEDBACK_TRACKER_SYNC_TOKEN", "test-token"), \
                    patch.object(feedback_tracker_service.requests, "get", return_value=response):
                feedback_tracker_service.init_tracker_schema()
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    conn.execute(
                        """
                        INSERT INTO feedback_tracker_state (
                            feedback_id, status, review_status, updated_at, updated_by
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            "FB-ONLINE-REVIEW", "processed", "pending",
                            "2026-09-18T11:00:00", "local-codex",
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()

                result = feedback_tracker_service.pull_online_feedback()
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    row = conn.execute(
                        """
                        SELECT status, review_status, review_note, acceptance_feedback,
                               updated_at, updated_by
                        FROM feedback_tracker_state WHERE feedback_id=?
                        """,
                        ("FB-ONLINE-REVIEW",),
                    ).fetchone()
                finally:
                    conn.close()

        self.assertTrue(result["tracking_updates_available"])
        self.assertEqual(result["tracking_updates_applied"], 1)
        self.assertEqual(row["status"], "processed")
        self.assertEqual(row["review_status"], "passed")
        self.assertEqual(row["review_note"], "客服已驗收")
        self.assertEqual(row["acceptance_feedback"], "回答正確")
        self.assertEqual(row["updated_by"], "online-csr")

    def test_publish_bundle_creates_missing_august_case(self):
        payload = {
            "kind": "feedback_tracker_updates",
            "case_definitions": [{
                "case_id": "AUG-TEST-001",
                "suite": "八月案例",
                "priority": "高",
                "group_name": "帳務",
                "company_codes": "tdtv",
                "case_kind": "問答",
                "script": "請問帳單？",
                "expected_behavior": "說明帳單查詢方式",
                "must_include": "帳單",
                "must_not_include": "錯誤資訊",
                "dependency": "",
                "focus": "帳務說明",
                "source_feedback_ids_json": '["FB-1"]',
                "test_results_json": '[]',
            }],
            "feedback_states": [],
            "case_states": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "feedback_tracker.db"
            with patch.object(feedback_tracker_service, "TRACKER_DB_FILE", database_path), \
                    patch.object(feedback_tracker_service, "migrate_legacy_tracker_data"):
                self.assertEqual(feedback_tracker_service.apply_tracking_update_bundle(payload), 1)
                conn = feedback_tracker_service.tracker_db_conn()
                try:
                    row = conn.execute(
                        "SELECT suite, script, status FROM regression_cases WHERE case_id=?",
                        ("AUG-TEST-001",),
                    ).fetchone()
                finally:
                    conn.close()

        self.assertEqual(row["suite"], "八月案例")
        self.assertEqual(row["script"], "請問帳單？")
        self.assertEqual(row["status"], feedback_tracker_service.DEFAULT_CASE_STATUS)


if __name__ == "__main__":
    unittest.main()
