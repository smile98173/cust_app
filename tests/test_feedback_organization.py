import unittest

from tools.organize_feedback_backlog_20260918 import (
    AUDIT_DEFAULT,
    AUDIT_FINDINGS,
    EXCLUDED,
    EXPECTED_CASE_COUNT,
    GROUPS,
)


class FeedbackOrganizationDefinitionTest(unittest.TestCase):
    def test_all_snapshot_items_have_exactly_one_disposition(self):
        assigned = [
            source_number
            for definition in GROUPS
            for source_number in definition["source_numbers"]
        ]

        self.assertEqual(len(GROUPS), EXPECTED_CASE_COUNT)
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertFalse(set(assigned) & set(EXCLUDED))
        self.assertEqual(set(assigned) | set(EXCLUDED), set(range(1, 165)))

    def test_case_ids_are_unique_and_contiguous(self):
        case_ids = [definition["case_id"] for definition in GROUPS]

        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertEqual(
            case_ids,
            [f"ORG-202609-{number:03d}" for number in range(1, EXPECTED_CASE_COUNT + 1)],
        )

    def test_compression_keeps_one_organizing_representative_per_case(self):
        representatives = [definition["source_numbers"][0] for definition in GROUPS]
        merged_sources = [
            source_number
            for definition in GROUPS
            for source_number in definition["source_numbers"][1:]
        ] + list(EXCLUDED)

        self.assertEqual(len(representatives), EXPECTED_CASE_COUNT)
        self.assertEqual(len(set(representatives)), EXPECTED_CASE_COUNT)
        self.assertEqual(len(merged_sources), 109)
        self.assertFalse(set(representatives) & set(merged_sources))

    def test_professional_contract_fields_are_complete(self):
        required_fields = (
            "suite",
            "priority",
            "group_name",
            "case_kind",
            "script",
            "expected_behavior",
            "must_include",
            "must_not_include",
            "dependency",
            "focus",
        )

        for definition in GROUPS:
            with self.subTest(case_id=definition["case_id"]):
                for field in required_fields:
                    self.assertTrue(str(definition.get(field) or "").strip(), field)
                self.assertTrue(definition["script"].startswith("U"))

    def test_audit_separates_ready_split_and_missing_evidence_cases(self):
        statuses = [
            AUDIT_FINDINGS.get(definition["case_id"], AUDIT_DEFAULT)[0]
            for definition in GROUPS
        ]

        self.assertEqual(statuses.count("ready_for_csr_review"), 39)
        self.assertEqual(statuses.count("needs_split"), 11)
        self.assertEqual(statuses.count("needs_evidence"), 5)


if __name__ == "__main__":
    unittest.main()
