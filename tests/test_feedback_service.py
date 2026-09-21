import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.feedback_service import append_feedback_csv, build_feedback_record, dated_csv_path, save_feedback


class FeedbackServiceTest(unittest.TestCase):
    def test_build_feedback_record_uses_last_turn_and_memory_snapshot(self):
        record = build_feedback_record(
            user_id="u1",
            tv_cable="tdtv",
            feedback_type="loop",
            suggestion="不要重複問同一句，應該進入下一步排錯。",
            memory={
                "company_code": "tdtv",
                "company": "大屯有線",
                "decision_type": "direct_reply",
                "pending_tool": "create_repair_ticket",
                "pending_tool_args": ["contact_name"],
                "known_info": {"troubleshooting_step": "tv_reboot"},
            },
            conversation=[
                {"role": "user", "content": "電視不能看"},
                {"role": "assistant", "content": "請確認機上盒電源。"},
                {"role": "user", "content": "有亮"},
                {"role": "assistant", "content": "請問畫面是什麼？"},
            ],
        )

        self.assertEqual(record["user_message"], "有亮")
        self.assertEqual(record["ai_response"], "請問畫面是什麼？")
        self.assertEqual(record["feedback_type"], "loop")
        self.assertEqual(json.loads(record["known_info_json"])["troubleshooting_step"], "tv_reboot")
        self.assertEqual(record["region_code"], "central")
        self.assertEqual(record["regional_knowledge_base"], "通用-中區")
        self.assertEqual(record["station_knowledge_base"], "大屯")

    def test_append_feedback_csv_writes_header_and_row(self):
        record = build_feedback_record(
            user_id="u1",
            tv_cable="tdtv",
            feedback_type="bad_answer",
            suggestion="應回答退租需臨櫃辦理。",
            memory={"known_info": {}},
            conversation=[{"role": "assistant", "content": "我幫您辦理。"}],
        )

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "feedback.csv"
            append_feedback_csv(record, str(csv_path))

            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["feedback_id"], record["feedback_id"])
        self.assertEqual(rows[0]["suggestion"], "應回答退租需臨櫃辦理。")

    def test_append_feedback_csv_migrates_legacy_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "feedback.csv"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["feedback_id", "suggestion"])
                writer.writeheader()
                writer.writerow({"feedback_id": "legacy", "suggestion": "舊資料"})

            record = build_feedback_record(
                user_id="u2",
                tv_cable="hya",
                feedback_type="bad_answer",
                suggestion="新資料",
                memory={
                    "company_code": "hya",
                    "resolved_knowledge_bases": ["通用-嘉南區", "新永安"],
                    "applied_policy_rules": [{
                        "rule_key": "billing.next_bill_after_no_unpaid",
                        "source": "region:jiannan",
                    }],
                },
                conversation=[],
            )
            append_feedback_csv(record, str(csv_path))

            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        self.assertIn("region_code", reader.fieldnames)
        self.assertEqual(rows[0]["feedback_id"], "legacy")
        self.assertEqual(rows[1]["region_code"], "jiannan")
        self.assertEqual(
            json.loads(rows[1]["resolved_knowledge_bases_json"]),
            ["通用-嘉南區", "新永安"],
        )

    def test_dated_csv_path_adds_date_suffix(self):
        path = dated_csv_path("feedback/ai_feedback.csv", enabled=True)

        self.assertTrue(path.name.startswith("ai_feedback_"))
        self.assertEqual(path.suffix, ".csv")

    def test_dated_csv_path_uses_feedback_dir_when_path_is_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.services.feedback_service.FEEDBACK_CSV_PATH", ""), \
                    patch("app.services.feedback_service.FEEDBACK_DIR", Path(tmp)):
                path = dated_csv_path("", enabled=True)

        self.assertTrue(path.name.startswith("ai_feedback_"))
        self.assertEqual(path.parent, Path(tmp))

    def test_save_feedback_still_succeeds_when_database_insert_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "feedback.csv"
            with patch("app.services.feedback_service.FEEDBACK_CSV_PATH", str(csv_path)), \
                    patch("app.services.feedback_service.insert_feedback_record", side_effect=RuntimeError("db down")), \
                    patch("app.services.feedback_service.log_exception") as log_exception:
                result = save_feedback(
                    user_id="test_web:u1",
                    tv_cable="tdtv",
                    feedback_type="bad_answer",
                    suggestion="應改成先確認燈號。",
                    memory={"company_code": "tdtv", "company": "大屯有線"},
                    conversation=[{"role": "assistant", "content": "請重開機。"}],
                )

            self.assertFalse(result["db_saved"])
            self.assertTrue(Path(result["csv_path"]).exists())
            log_exception.assert_called_once()

    def test_save_feedback_returns_existing_id_for_identical_recent_submission(self):
        with patch(
            "app.services.feedback_service.find_recent_duplicate_feedback",
            return_value="FB-existing",
        ), patch("app.services.feedback_service.append_feedback_csv") as append_csv, patch(
            "app.services.feedback_service.insert_feedback_record"
        ) as insert_record:
            result = save_feedback(
                user_id="test_web:u1",
                tv_cable="tdtv",
                feedback_type="bad_answer",
                suggestion="同一份建議。",
                memory={"company_code": "tdtv", "company": "大屯有線"},
                conversation=[{"role": "assistant", "content": "同一段回答。"}],
            )

        self.assertTrue(result["duplicate"])
        self.assertEqual(result["feedback_id"], "FB-existing")
        append_csv.assert_not_called()
        insert_record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
