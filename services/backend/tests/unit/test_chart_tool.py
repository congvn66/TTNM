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
