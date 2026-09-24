import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.handlers.chat_handler import apply_customer_reply_policies
from app.services.regional_policy import (
    REGION_CENTRAL,
    REGION_JIANNAN,
    get_policy_rule,
    resolve_policy_context,
)


class RegionalPolicyTest(unittest.TestCase):
    def test_resolves_central_and_jiannan_from_company_code(self):
        central = resolve_policy_context({"company_code": "tdtv"})
        jiannan = resolve_policy_context({"company_code": "hya"})

        self.assertEqual(central["region_code"], REGION_CENTRAL)
        self.assertEqual(central["regional_knowledge_base"], "通用-中區")
        self.assertEqual(central["station_knowledge_base"], "大屯")
        self.assertEqual(jiannan["region_code"], REGION_JIANNAN)
        self.assertEqual(jiannan["regional_knowledge_base"], "通用-嘉南區")
        self.assertEqual(jiannan["station_knowledge_base"], "新永安")

    def test_ambiguous_scope_uses_global_policy_only(self):
        memory = {"company_code": "tdtv"}
        context = resolve_policy_context(
            memory,
            {
                "通用-中區": ["大屯"],
                "通用-嘉南區": ["大屯"],
            },
        )

        self.assertEqual(context["region_code"], "ambiguous")
        self.assertEqual(context["policy_resolution_status"], "conflict")
        self.assertIsNone(context["regional_knowledge_base"])

    def test_paired_billing_replies_use_separate_region_overrides(self):
        overrides = {
            "regions": {
                "central": {
                    "billing.next_bill_after_no_unpaid": {
                        "reply": "中區下期帳單回覆",
                    },
                },
                "jiannan": {
                    "billing.next_bill_after_no_unpaid": {
                        "reply": "嘉南區下期帳單回覆",
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "regional_policies.json"
            path.write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")
            with patch("app.services.regional_policy.REGIONAL_POLICY_PATH", str(path)):
                central_memory = {
                    "company_code": "tdtv",
                    "last_bill_query_status": {"status": "no_unpaid"},
                }
                jiannan_memory = {
                    "company_code": "hya",
                    "last_bill_query_status": {"status": "no_unpaid"},
                }
                central = get_policy_rule(central_memory, "billing.next_bill_after_no_unpaid")
                jiannan = get_policy_rule(jiannan_memory, "billing.next_bill_after_no_unpaid")

        self.assertEqual(central["reply"], "中區下期帳單回覆")
        self.assertEqual(jiannan["reply"], "嘉南區下期帳單回覆")
        self.assertEqual(
            central_memory["applied_policy_rules"][0]["source"],
            "region:central",
        )
        self.assertEqual(
            jiannan_memory["applied_policy_rules"][0]["source"],
            "region:jiannan",
        )

    def test_paired_promotion_replies_use_separate_region_overrides(self):
        overrides = {
            "regions": {
                "central": {
                    "promotion.social_discount_stacking": {
                        "reply": "中區優惠不可重複",
                    },
                },
                "jiannan": {
                    "promotion.social_discount_stacking": {
                        "reply": "嘉南區優惠不可重複",
                    },
                },
            },
        }
        docs = [{"question": "低收入戶優惠", "answer": "低收入戶優惠方案"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "regional_policies.json"
            path.write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")
            with patch("app.services.regional_policy.REGIONAL_POLICY_PATH", str(path)):
                central = apply_customer_reply_policies(
                    "低收入優惠可以跟活動一起用嗎",
                    "需確認",
                    docs,
                    memory={"company_code": "tdtv"},
                )
                jiannan = apply_customer_reply_policies(
                    "低收入優惠可以跟活動一起用嗎",
                    "需確認",
                    docs,
                    memory={"company_code": "hya"},
                )

        self.assertEqual(central, "中區優惠不可重複")
        self.assertEqual(jiannan, "嘉南區優惠不可重複")

    def test_station_override_has_highest_priority(self):
        overrides = {
            "regions": {
                "central": {
                    "support.remote_control_price": {"reply": "中區價格"},
                },
            },
            "stations": {
                "大屯": {
                    "support.remote_control_price": {"reply": "大屯價格"},
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "regional_policies.json"
            path.write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")
            with patch("app.services.regional_policy.REGIONAL_POLICY_PATH", str(path)):
                rule = get_policy_rule(
                    {"company_code": "tdtv"},
                    "support.remote_control_price",
                )

        self.assertEqual(rule["reply"], "大屯價格")
        self.assertEqual(rule["_policy_source"], "station:大屯")


if __name__ == "__main__":
    unittest.main()
