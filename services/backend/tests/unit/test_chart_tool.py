import json
from pathlib import Path

from report_qa.api.ai_provider import ProviderError
from report_qa.application.chart_tool import read_chart_region
from report_qa.application.extraction_contract import validate_extraction_batch

PDF = Path(__file__).parents[1] / "fixtures/extraction/report.pdf"
REGION = {
    "chart_region_key": "chart-1",
    "page_number": 1,
    "bbox": [0.07, 0.52, 0.93, 0.79],
}
RAW = "TITLE | Sales\nRegion | Revenue (million VND)\nA | 50\nB | 87"


def test_deplot_numbers_are_preserved_when_visual_check_fails():
    def fail(*args):
        raise ProviderError("UNAVAILABLE", "visual checker failed")

    result = read_chart_region(
        PDF, REGION, "v", "q", complete=fail, predictor=lambda image: RAW
    )
    batch = result["evidence_batch"]
    validate_extraction_batch(batch)
    assert [e["raw_text"] for e in batch["evidences"]] == ["50", "87"]
    assert all(
        e["numeric_value"] is None and e["data_status"] == "ambiguous"
        for e in batch["evidences"]
    )
    assert result["raw_output"] == RAW
    assert result["visual_check_error"] == "visual checker failed"


def test_visual_label_check_adds_source_method_and_bbox_without_rewriting_values():
    def verify(system, content):
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        return json.dumps(
            {
                "rows": [
                    {
                        "category": "A",
                        "series": "Revenue (million VND)",
                        "value": "50",
                        "method": "direct_label",
                        "label_bbox": [0.2, 0.3, 0.25, 0.35],
                        "measure": "doanh_thu",
                        "unit": "VND_MILLION",
                        "confidence": 0.8,
                    }
                ]
            }
        )

    result = read_chart_region(
        PDF, REGION, "v", "q", complete=verify, predictor=lambda image: RAW
    )
    items = result["evidence_batch"]["evidences"]
    assert (
        items[0]["numeric_value"] == "50" and items[0]["method_label"] == "đọc từ nhãn"
    )
    assert (
        "model_visual_check_not_human_confirmation"
        in items[0]["chart_read"]["assumptions"]
    )
    assert items[1]["numeric_value"] is None
    validate_extraction_batch(result["evidence_batch"])


def test_visual_checker_cannot_replace_deplot_value():
    def verify(*args):
        return json.dumps(
            {
                "rows": [
                    {
                        "category": "A",
                        "series": "Revenue (million VND)",
                        "value": "500",
                        "method": "direct_label",
                        "label_bbox": [0.2, 0.3, 0.25, 0.35],
                        "confidence": 0.8,
                    }
                ]
            }
        )

    result = read_chart_region(
        PDF, REGION, "v", "q", complete=verify, predictor=lambda image: RAW
    )
    assert result["evidence_batch"]["evidences"][0]["numeric_value"] is None


def test_single_series_can_use_a_null_visual_series_label():
    def verify(*args):
        return json.dumps(
            {
                "rows": [
                    {
                        "category": "B",
                        "series": None,
                        "value": "87",
                        "method": "direct_label",
                        "label_bbox": [0.3, 0.3, 0.35, 0.35],
                        "measure": "doanh_thu",
                        "unit": "VND_MILLION",
                        "confidence": 0.9,
                    }
                ]
            }
        )

    result = read_chart_region(
        PDF, REGION, "v", "q", complete=verify, predictor=lambda image: RAW
    )
    assert result["evidence_batch"]["evidences"][1]["numeric_value"] == "87"
    multi = "TITLE | Grouped\nRegion | North | South\nB | 87 | 90"
    result = read_chart_region(
        PDF, REGION, "v", "q", complete=verify, predictor=lambda image: multi
    )
    assert all(
        e["numeric_value"] is None for e in result["evidence_batch"]["evidences"]
    )


def _verifier_with_boxes(boxes):
    def verify(system, content):
        return json.dumps({"rows": [
            {"category": category, "series": "Revenue (million VND)", "value": value, "method": "direct_label",
             "label_bbox": box, "confidence": 0.95}
            for (category, value), box in zip([("A", "50"), ("B", "87")], boxes)
        ]})
    return verify


def test_label_box_slightly_past_the_crop_edge_keeps_the_confirmed_value():
    # Real run: the right-most bar's label came back as x1=1.036, and the
    # confirmed value (DePlot 77 = visual check 77) was discarded.
    result = read_chart_region(
        PDF, REGION, "v", "q", complete=_verifier_with_boxes([[0.2, 0.3, 0.25, 0.35], [0.991, 0.162, 1.036, 0.202]]),
        predictor=lambda image: RAW,
    )
    by_category = {e["chart_read"]["category_label"]: e for e in result["evidence_batch"]["evidences"]}
    assert (by_category["B"]["numeric_value"], by_category["B"]["data_status"]) == ("87", "valid")
    assert all(0 <= v <= 1 for v in by_category["B"]["bbox"])


def test_unusable_label_box_keeps_the_agreed_value_on_the_chart_region():
    # Real run: the checker's box for the right-most label was entirely past
    # the crop ([1.002, 0.176, 1.038, 0.213]); the agreed value was dropped.
    result = read_chart_region(
        PDF, REGION, "v", "q", complete=_verifier_with_boxes([[0.2, 0.3, 0.25, 0.35], [1.4, 0.2, 1.5, 0.3]]),
        predictor=lambda image: RAW,
    )
    by_category = {e["chart_read"]["category_label"]: e for e in result["evidence_batch"]["evidences"]}
    b = by_category["B"]
    assert (b["numeric_value"], b["data_status"]) == ("87", "valid")
    assert b["confidence"] <= 0.6 < by_category["A"]["confidence"]
    assert "label_bbox_unusable_chart_region_used" in b["chart_read"]["assumptions"]
    assert all(0 <= v <= 1 for v in b["bbox"])


def test_value_the_checker_disagrees_with_is_still_withheld():
    def verify(system, content):
        return json.dumps({"rows": [{"category": "B", "series": "Revenue (million VND)", "value": "78",
                                     "method": "direct_label", "label_bbox": None, "confidence": 0.95}]})

    result = read_chart_region(PDF, REGION, "v", "q", complete=verify, predictor=lambda image: RAW)
    b = next(e for e in result["evidence_batch"]["evidences"] if e["chart_read"]["category_label"] == "B")
    assert (b["numeric_value"], b["data_status"]) == (None, "ambiguous")


def test_checker_rows_with_wrong_types_are_cleaned():
    from report_qa.application.chart_tool import _checked_row

    row = _checked_row({"category": "A", "series": 3, "unit": {"x": 1}, "axis_label": ["y"], "value": 5, "confidence": 0.9})
    assert row["category"] == "A" and row["series"] is None and row["unit"] is None and row["axis_label"] is None
    assert row["value"] == 5 and row["confidence"] == 0.9


def test_repeated_deplot_category_gets_distinct_keys():
    raw = "TITLE | Doanh thu\nNăm | Doanh thu\n2023 | 10\n2023 | 12\n2024 | 15"
    read = lambda: read_chart_region(
        PDF, REGION, "v", "q", complete=lambda *args: json.dumps({"rows": []}), predictor=lambda image: raw
    )
    first, second = read(), read()
    keys = [e["evidence_key"] for e in first["evidence_batch"]["evidences"]]
    assert len(keys) == 3 and len(set(keys)) == 3
    assert keys == [e["evidence_key"] for e in second["evidence_batch"]["evidences"]]


def test_deplot_cache_lives_under_the_configured_runtime_root(tmp_path, monkeypatch):
    from report_qa.api import session_storage
    from report_qa.application import chart_tool

    monkeypatch.setattr(session_storage, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(chart_tool, "predict_chart", lambda image: RAW)
    read_chart_region(PDF, REGION, "v", "q", complete=lambda *args: json.dumps({"rows": []}))
    assert len(list((tmp_path / "chart-cache").glob("*.json"))) == 1


# google/deplot's real output for S1 page 2 ("Số đơn hàng theo tháng"): a unit
# subtitle on its own line after TITLE, and Vietnamese letters as byte tokens.
S1_ORDERS_RAW = (
    "TITLE | Bi<0xE1><0xBB><0x83>u đ<0xE1><0xBB><0x93> 1. S<0xE1><0xBB><0x91> đon hàng theo tháng, 6 th<0xE1><0xBA><0xA3>ng "
    "đầu năm 2026<0x0A>Don vì: nghin đ<0xE1><0xBB><0x93>n<0x0A>T1 | Miên B<0xE1><0xBA><0xAF>c | Mi<0xE1><0xBB><0x81>n Trung | "
    "Mi<0xE1><0xBB><0x81>n Nam<0x0A>T2 | 35 | 15 | 30<0x0A>T3 | 41 | 19 | 36<0x0A>T4 | 44 | 21 | 35<0x0A>T5 | 49 | 24 | 37"
    "<0x0A>T6 | 47 | 30 | 38"
)


def test_real_deplot_output_with_a_subtitle_line_and_byte_tokens_is_parsed():
    from report_qa.application.deplot_reading import parse_table

    title, rows = parse_table(S1_ORDERS_RAW)
    assert title == "Biểu đồ 1. Số đon hàng theo tháng, 6 thảng đầu năm 2026 Don vì: nghin đồn"
    assert ("T4", "Miền Nam", "35", "35") in rows and ("T5", "Miên Bắc", "49", "49") in rows
    assert len(rows) == 15  # T1 is DePlot's header cell, so its bars were not read; nothing is guessed


def test_grouped_bar_chart_values_get_category_and_series_labels():
    result = read_chart_region(
        PDF, REGION, "v", "q", complete=lambda *args: json.dumps({"rows": []}), predictor=lambda image: S1_ORDERS_RAW
    )
    labels = {(e["chart_read"]["category_label"], e["chart_read"]["series_label"]): e["raw_text"]
              for e in result["evidence_batch"]["evidences"]}
    assert labels[("T4", "Miền Nam")] == "35" and labels[("T5", "Miên Bắc")] == "49"
