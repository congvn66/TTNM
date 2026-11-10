from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.reference_flow import (
    IdempotencyConflict,
    InvalidState,
    NotFound,
    ReferenceFlow,
    RevisionConflict,
)
from scripts.check_design_consistency import check_all as check_design
from scripts.validate_mock_data import validate_all


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "tests" / "mock_data" / "domain_seed.json"


class ReferenceFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        validate_all()

    def setUp(self) -> None:
        self.flow = ReferenceFlow.from_file(SEED)
        self.ids = self.flow.data["_ids"][0]

    def test_mock_dataset_is_structurally_valid(self) -> None:
        counts = validate_all()
        self.assertEqual(counts["domain_tables"], 23)
        self.assertEqual(counts["questions"], 180)
        self.assertEqual(counts["pdfs"], 20)

    def test_design_documents_and_contracts_are_consistent(self) -> None:
        result = check_design()
        self.assertEqual(result["tables"], 23)
        self.assertGreaterEqual(result["triggers"], 10)
        self.assertEqual(result["contracts"], 7)

    def test_submit_question_is_idempotent(self) -> None:
        before = len(self.flow.rows("messages"))
        first = self.flow.submit_question(self.ids["alice"], self.ids["chat_b"], "Doanh thu Q1?", "same-key")
        second = self.flow.submit_question(self.ids["alice"], self.ids["chat_b"], "Doanh thu Q1?", "same-key")
        self.assertEqual(first, second)
        self.assertEqual(len(self.flow.rows("messages")), before + 2)
        with self.assertRaises(IdempotencyConflict):
            self.flow.submit_question(self.ids["alice"], self.ids["chat_b"], "Nội dung khác", "same-key")

    def test_cross_owner_access_is_hidden(self) -> None:
        with self.assertRaises(NotFound):
            self.flow.submit_question(self.ids["alice"], self.ids["chat_bob"], "Đọc dữ liệu Bob", "forbidden")

    def test_edit_38_to_58_recalculates_ranking_and_preserves_history(self) -> None:
        old_answer = self.flow.by_id("answer_revisions", self.ids["answer_a"])
        old_input_ids = {row["evidence_revision_id"] for row in self.flow.rows("answer_inputs") if row["answer_revision_id"] == old_answer["id"]}
        result = self.flow.edit_evidence(
            self.ids["alice"], self.ids["ce_a_mb_q1"], self.ids["er_a_mb_q1"], "58", "Nhãn biểu đồ ghi 58"
        )
        self.assertEqual(result["affected_message_ids"], [self.ids["assistant_a"]])
        self.assertEqual(len(result["job_ids"]), 1)
        recalculated = self.flow.run_recalculation(result["job_ids"][0])
        self.assertIsNotNone(recalculated)
        assert recalculated is not None
        self.assertEqual(recalculated["result"]["winner_subjects"], ["Miền Nam"])
        self.assertEqual(recalculated["result"]["rates"]["Miền Bắc"], "50")
        self.assertEqual(recalculated["result"]["rates"]["Miền Nam"], "80")
        self.assertIn(self.ids["er_a_mb_q1"], old_input_ids)
        self.assertEqual(old_answer["result"]["winner_subjects"], ["Miền Bắc"])
        self.assertEqual(self.flow.current_revision(self.ids["ce_b_mb_q1"])["numeric_value"], "38")

    def test_second_editor_with_stale_revision_gets_conflict(self) -> None:
        first = self.flow.edit_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], self.ids["er_a_mb_q1"], "58", "first")
        with self.assertRaises(RevisionConflict) as conflict:
            self.flow.edit_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], self.ids["er_a_mb_q1"], "60", "second")
        self.assertIn(first["revision_id"], str(conflict.exception))

    def test_stale_recalculation_job_cannot_publish(self) -> None:
        first = self.flow.edit_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], self.ids["er_a_mb_q1"], "58", "first")
        second = self.flow.edit_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], first["revision_id"], "60", "second")
        self.assertIsNone(self.flow.run_recalculation(first["job_ids"][0]))
        self.assertEqual(self.flow.by_id("jobs", first["job_ids"][0])["status"], "superseded")
        current = self.flow.run_recalculation(second["job_ids"][0])
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current["input_data_revision"], second["chat_data_revision"])

    def test_restore_creates_new_revision_instead_of_moving_pointer_back(self) -> None:
        edited = self.flow.edit_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], self.ids["er_a_mb_q1"], "58", "edit")
        restored = self.flow.restore_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], edited["revision_id"], self.ids["er_a_mb_q1"], "restore original")
        current = self.flow.current_revision(self.ids["ce_a_mb_q1"])
        self.assertEqual(current["id"], restored["revision_id"])
        self.assertNotEqual(current["id"], self.ids["er_a_mb_q1"])
        self.assertEqual(current["numeric_value"], "38")
        self.assertEqual(current["action"], "restore")
        self.assertEqual(current["revision_no"], 3)

    def test_scope_dependency_marks_answer_even_without_direct_input(self) -> None:
        self.flow.data["answer_inputs"] = [
            row for row in self.flow.rows("answer_inputs") if row["evidence_revision_id"] != self.ids["er_a_mb_q1"]
        ]
        result = self.flow.edit_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], self.ids["er_a_mb_q1"], "58", "scope change")
        self.assertEqual(result["affected_message_ids"], [self.ids["assistant_a"]])

    def test_missing_and_zero_are_distinct(self) -> None:
        regions = {row["id"]: row for row in self.flow.rows("source_regions")}
        by_key = {regions[row["source_region_id"]]["region_key"]: row for row in self.flow.rows("extracted_evidences")}
        self.assertEqual(by_key["zero-q1"]["data_status"], "valid")
        self.assertEqual(by_key["zero-q1"]["raw_value"], "0")
        self.assertEqual(by_key["profit-missing"]["data_status"], "missing")
        self.assertIsNone(by_key["profit-missing"]["raw_value"])

    def test_zero_denominator_does_not_produce_partial_winner(self) -> None:
        edit = self.flow.edit_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], self.ids["er_a_mb_q1"], "0", "test denominator zero")
        answer = self.flow.run_recalculation(edit["job_ids"][0])
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertEqual(answer["answer_status"], "insufficient_data")
        self.assertFalse(answer["result"]["defined"])
        self.assertEqual(answer["result"]["winner_subjects"], [])
        self.assertIn("Miền Bắc", answer["result"]["incomplete_subjects"])

    def test_edit_requires_reason(self) -> None:
        with self.assertRaises(InvalidState):
            self.flow.edit_evidence(self.ids["alice"], self.ids["ce_a_mb_q1"], self.ids["er_a_mb_q1"], "58", "")

    def test_switch_source_preserves_old_answer_scope(self) -> None:
        old_scope = next(row for row in self.flow.rows("answer_scopes") if row["answer_revision_id"] == self.ids["answer_a"])
        old_source_id = old_scope["chat_source_id"]
        new_source_id = self.flow.switch_source(self.ids["alice"], self.ids["chat_a"], self.ids["version_sales_v2"], self.ids["run_sales_v2"])
        self.assertEqual(self.flow.by_id("chat_sources", old_source_id)["source_status"], "inactive")
        self.assertEqual(self.flow.by_id("chat_sources", new_source_id)["source_status"], "active")
        self.assertEqual(old_scope["chat_source_id"], old_source_id)


if __name__ == "__main__":
    unittest.main()
