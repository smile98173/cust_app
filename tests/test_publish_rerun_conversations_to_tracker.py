import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
from publish_rerun_conversations_to_tracker import publish_directly_to_local_tracker


class PublishRerunConversationsTest(unittest.TestCase):
    def test_direct_publish_uses_tracker_local_timestamp_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "tracker.db"
            conn = sqlite3.connect(database_path)
            try:
                conn.execute(
                    "CREATE TABLE feedback_tracker_state ("
                    "feedback_id TEXT PRIMARY KEY, status TEXT, review_status TEXT, "
                    "adjusted_conversation_json TEXT, updated_at TEXT, updated_by TEXT)"
                )
                conn.commit()
            finally:
                conn.close()

            published = publish_directly_to_local_tracker(
                [{
                    "feedback_id": "FB-TEST", "status": "RAN",
                    "rerun_messages": [{"role": "assistant", "content": "new reply"}],
                }],
                database_path,
                False,
            )
            conn = sqlite3.connect(database_path)
            try:
                row = conn.execute(
                    "SELECT adjusted_conversation_json, updated_at "
                    "FROM feedback_tracker_state WHERE feedback_id='FB-TEST'"
                ).fetchone()
            finally:
                conn.close()

        self.assertEqual(published, 1)
        self.assertEqual(json.loads(row[0])[0]["content"], "new reply")
        self.assertIsNone(datetime.fromisoformat(row[1]).tzinfo)
