from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from report_qa.application.evidence_extraction import extract_legacy_pdf_artifact as extract_pdf_artifact
from report_qa.application.chart_reading import ChartReadRequest, PdfVectorChartReader
from report_qa.application.p0_pipeline import build_question_plan, execute_calculation


class P0PipelineTests(unittest.TestCase):
    def test_layout_extractor_marks_table_cell_and_keeps_numeric_bbox(self) -> None:
        writer = PdfWriter()
        page = writer.add_blank_page(width=595, height=842)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(
            b"BT /F1 12 Tf 50 760 Td (Period) Tj ET "
            b"BT /F1 12 Tf 250 760 Td (Revenue) Tj ET "
            b"BT /F1 12 Tf 50 720 Td (Q1/2026) Tj ET "
            b"BT /F1 12 Tf 250 720 Td (120) Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "table.pdf"
            with path.open("wb") as output:
                writer.write(output)
            artifact = extract_pdf_artifact(path, "doc-1")

        self.assertEqual(len(artifact["evidence_batch"]["evidences"]), 1)
        evidence = artifact["evidence_batch"]["evidences"][0]
        self.assertEqual(evidence["source_type"], "table")
        self.assertEqual(evidence["method_label"], "đọc từ ô bảng")
        self.assertEqual(evidence["table_locator"]["column_header"], "Revenue")
        self.assertEqual(evidence["table_locator"]["row_header"], "Q1/2026")
        self.assertEqual(len(evidence["bbox"]), 4)

    def test_growth_plan_orders_current_before_baseline(self) -> None:
        plan = build_question_plan(
            "By what percent did revenue change from Q1/2025 to Q1/2026?",
            "doc-1",
        )

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["operation"]["formula_id"], "growth_rate_v1")
        self.assertEqual([item["period"] for item in plan["facts"]], ["Q1/2026", "Q1/2025"])
        self.assertEqual(plan["source_strategy"]["chart_policy"], "only_if_required_fact_unresolved")

    def test_ambiguous_increase_does_not_choose_a_formula(self) -> None:
        plan = build_question_plan("How much did revenue increase?", "doc-1")

        self.assertEqual(plan["status"], "needs_clarification")
        self.assertIsNone(plan["operation"])
        self.assertEqual(plan["clarification"]["reason_code"], "AMBIGUOUS_OPERATION")

    def test_growth_without_two_periods_requests_period_clarification(self) -> None:
        plan = build_question_plan("Revenue increased by what percent?", "doc-1")

        self.assertEqual(plan["status"], "needs_clarification")
        self.assertIsNone(plan["operation"])
        self.assertEqual(plan["clarification"]["reason_code"], "AMBIGUOUS_PERIOD")

    def test_operation_clarification_followup_reuses_the_previous_question(self) -> None:
        first = build_question_plan(
            "How much did revenue increase from Q1/2025 to Q1/2026?",
            "doc-1",
        )
        second = build_question_plan("Percentage change", "doc-1", first)

        self.assertEqual(first["clarification"]["reason_code"], "AMBIGUOUS_OPERATION")
        self.assertEqual(second["status"], "ready")
        self.assertEqual(second["operation"]["formula_id"], "growth_rate_v1")
        self.assertEqual([item["period"] for item in second["facts"]], ["Q1/2026", "Q1/2025"])

    def test_calculator_handles_growth_zero_missing_and_unit_mismatch(self) -> None:
        plan = build_question_plan(
            "By what percent did revenue change from Q1/2025 to Q1/2026?",
            "doc-1",
        )
        resolved = {
            "status": "resolved",
            "missing_fact_keys": [],
            "unit_mismatch_fact_keys": [],
            "bindings": [
                {"fact_key": "current", "evidence_revision_id": "evr-current", "value": "120", "unit": "VND", "page_number": 1, "bbox": [0, 0, 0.1, 0.1], "method_label": "đọc từ văn bản"},
                {"fact_key": "baseline", "evidence_revision_id": "evr-baseline", "value": "100", "unit": "VND", "page_number": 1, "bbox": [0, 0, 0.1, 0.1], "method_label": "đọc từ văn bản"},
            ],
        }
        succeeded = execute_calculation(plan, resolved)
        self.assertEqual((succeeded["status"], succeeded["value"]), ("succeeded", "20"))

        resolved["bindings"][1]["unit"] = "USD"
        incompatible = execute_calculation(plan, resolved)
        self.assertEqual((incompatible["status"], incompatible["reason_code"]), ("unit_mismatch", "UNIT_MISMATCH"))
        resolved["bindings"][1]["unit"] = "VND"

        resolved["bindings"][1]["value"] = "0"
        zero = execute_calculation(plan, resolved)
        self.assertEqual((zero["status"], zero["reason_code"]), ("zero_denominator", "ZERO_DENOMINATOR"))

        missing = execute_calculation(
            plan,
            {"status": "chart_required", "missing_fact_keys": ["baseline"], "unit_mismatch_fact_keys": [], "bindings": resolved["bindings"][:1]},
        )
        self.assertEqual((missing["status"], missing["reason_code"]), ("missing_data", "MISSING_DATA"))

        mismatch = execute_calculation(
            plan,
            {"status": "unit_mismatch", "missing_fact_keys": ["baseline"], "unit_mismatch_fact_keys": ["baseline"], "bindings": resolved["bindings"][:1]},
        )
        self.assertEqual((mismatch["status"], mismatch["reason_code"]), ("unit_mismatch", "UNIT_MISMATCH"))

    def test_vector_chart_reader_marks_a_printed_value_as_direct_label(self) -> None:
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"40 40 20 120 re f BT /F1 12 Tf 42 165 Td (120) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "labelled-chart.pdf"
            with path.open("wb") as output: writer.write(output)
            result = PdfVectorChartReader().read(ChartReadRequest("doc-1", "plan-1", ("current",), source_pdf_path=path, page_numbers=(1,), fact_requirements=({"fact_key": "current", "measure": "doanh_thu", "period": "Q1/2026", "unit": "VND", "dimensions": {}},)))
        self.assertEqual(result["status"], "completed")
        evidence = result["evidence_batch"]["evidences"][0]
        self.assertEqual((evidence["numeric_value"], evidence["extraction_method"], evidence["method_label"]), ("120", "direct_label", "đọc từ nhãn"))

    def test_vector_chart_reader_interpolates_from_axis_when_label_is_absent(self) -> None:
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"60 40 20 100 re f BT /F1 12 Tf 15 40 Td (0) Tj ET BT /F1 12 Tf 8 140 Td (100) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "axis-chart.pdf"
            with path.open("wb") as output: writer.write(output)
            result = PdfVectorChartReader().read(ChartReadRequest("doc-1", "plan-2", ("current",), source_pdf_path=path, page_numbers=(1,), fact_requirements=({"fact_key": "current", "measure": "doanh_thu", "period": "Q1/2026", "unit": "VND", "dimensions": {}},)))
        evidence = result["evidence_batch"]["evidences"][0]
        self.assertEqual(evidence["extraction_method"], "axis_estimation")
        self.assertEqual(evidence["method_label"], "ước lượng theo trục")
        self.assertIn("lower_tick", evidence["chart_read"])


if __name__ == "__main__":
    unittest.main()
