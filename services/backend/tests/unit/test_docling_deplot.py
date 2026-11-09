"""Offline adapter/contract tests; providers injected, never download weights."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jsonschema import ValidationError
from report_qa.application.chart_reading import ChartReadRequest
from report_qa.application.deplot_reading import DeplotChartReader, parse_table
from report_qa.application.docling_extraction import (
    extract_docling_artifact,
    normalized_box,
)
from report_qa.application.extraction_contract import validate_extraction_batch
from report_qa.application.numeric_extraction import decimal_text

FIXTURES = Path(__file__).parents[1] / "fixtures/extraction"


def artifact(data=None):
    data = data or json.loads((FIXTURES / "docling-recorded.json").read_text())
    converter = Mock()
    converter.convert.return_value = SimpleNamespace(
        status="ConversionStatus.SUCCESS",
        document=SimpleNamespace(export_to_dict=lambda: data),
    )
    return extract_docling_artifact(
        FIXTURES / "report.pdf", "version-1", locale="en", converter=converter
    )


def test_docling_table_values_headers_geometry_and_no_chart_values():
    result = artifact()
    batch = result["evidence_batch"]
    validate_extraction_batch(batch)
    tables = [e for e in batch["evidences"] if e["source_type"] == "table"]
    assert len(tables) == 12
    first = next(e for e in tables if e["numeric_value"] == "1250.50")
    assert first["table_locator"]["row_header"] == "Q1"
    assert first["table_locator"]["column_header"] == "Doanh thu"
    assert first["bbox"][2] - first["bbox"][0] < 0.2
    assert first["bbox"][3] - first["bbox"][1] < 0.05
    assert first["page_number"] == 1
    assert all(e["source_type"] != "chart" for e in batch["evidences"])
    assert result["chart_regions"]
    assert len({e["evidence_key"] for e in tables}) == len(tables)


@pytest.mark.parametrize(
    "raw,locale,expected",
    [
        ("2.785,40", "vi", "2785.40"),
        ("(123,45)", "vi", "-123.45"),
        ("0", None, "0"),
        ("-0.5", None, "-0.5"),
        ("12%", "vi", "12"),
        ("1,250.50", "en", "1250.50"),
    ],
)
def test_numbers(raw, locale, expected):
    assert decimal_text(raw, locale) == expected


def test_ambiguous_number_needs_locale():
    with pytest.raises(ValueError):
        decimal_text("1.234")


def test_missing_and_ambiguous_cells_do_not_become_zero():
    data = json.loads((FIXTURES / "docling-recorded.json").read_text())
    cells = data["tables"][0]["data"]["table_cells"]
    cells[5]["text"] = "—"
    cells[6]["text"] = "2024 1,200"
    batch = artifact(data)["evidence_batch"]
    assert any(
        e["data_status"] == "missing" and e["numeric_value"] is None
        for e in batch["evidences"]
    )
    assert any(
        e["data_status"] == "ambiguous" and e["numeric_value"] is None
        for e in batch["evidences"]
    )


def test_missing_cell_bbox_is_warned_and_not_published():
    data = json.loads((FIXTURES / "docling-recorded.json").read_text())
    data["tables"][0]["data"]["table_cells"][5]["bbox"] = None
    batch = artifact(data)["evidence_batch"]
    assert len([e for e in batch["evidences"] if e["source_type"] == "table"]) == 11
    assert any(w["code"] == "CELL_LOCATION_UNAVAILABLE" for w in batch["warnings"])


def test_coordinate_origin_and_schema_validation():
    assert normalized_box(
        {"l": 10, "r": 20, "t": 90, "b": 80, "coord_origin": "BOTTOMLEFT"}, 100, 100
    ) == [0.1, 0.1, 0.2, 0.2]
    batch = artifact()["evidence_batch"]
    del batch["evidences"][0]["bbox"]
    with pytest.raises(ValidationError):
        validate_extraction_batch(batch)


def request(**kwargs):
    defaults = {
        "document_version_id": "version-1",
        "question_plan_id": "plan-1",
        "fact_keys": ("a",),
        "chart_region_keys": ("chart-1",),
        "source_pdf_path": FIXTURES / "report.pdf",
        "page_numbers": (1,),
        "fact_requirements": (
            {
                "fact_key": "a",
                "measure": "doanh_thu",
                "period": None,
                "subject": "A",
                "unit": "VND_MILLION",
                "dimensions": {},
            },
        ),
        "chart_regions": (
            {
                "chart_region_key": "chart-1",
                "page_number": 1,
                "bbox": [0.07, 0.52, 0.93, 0.79],
            },
        ),
    }
    defaults.update(kwargs)
    return ChartReadRequest(**defaults)


RAW = (
    "TITLE | Revenue <0x0A> Region | Revenue (million VND) <0x0A> B | 87 <0x0A> A | 50"
)


def test_no_trigger_or_unselected_region_never_calls_model():
    predict = Mock()
    reader = DeplotChartReader(predict)
    assert (
        reader.read(request(chart_region_keys=()))["code"] == "CHART_TRIGGER_REQUIRED"
    )
    assert (
        reader.read(request(chart_region_keys=("other",)))["code"]
        == "CHART_REGION_NOT_FOUND"
    )
    predict.assert_not_called()


def test_chart_without_verified_method_is_ambiguous_not_guessed():
    reader = DeplotChartReader(lambda image: RAW)
    output = reader.read(request())
    validate_extraction_batch(output["evidence_batch"])
    item = output["evidence_batch"]["evidences"][0]
    assert item["raw_text"] == "50"  # A matched by label, despite B appearing first.
    assert item["numeric_value"] is None and item["data_status"] == "ambiguous"


def test_reviewed_printed_label_records_exact_label_bbox():
    region = {
        **request().chart_regions[0],
        "verified_labels": [
            {
                "category": "A",
                "series": "Revenue (million VND)",
                "value": "50",
                "bbox": [0.2, 0.6, 0.24, 0.63],
            }
        ],
    }
    output = DeplotChartReader(lambda image: RAW).read(request(chart_regions=(region,)))
    item = output["evidence_batch"]["evidences"][0]
    assert item["numeric_value"] == "50"
    assert item["method_label"] == "đọc từ nhãn"
    assert item["bbox"] == [0.2, 0.6, 0.24, 0.63]
    validate_extraction_batch(output["evidence_batch"])


def test_verified_linear_axis_preserves_deplot_decimal_and_ticks():
    region = {
        **request().chart_regions[0],
        "value_labels_absent": True,
        "axis": {
            "verified": True,
            "scale": "linear",
            "lower_tick": "0",
            "upper_tick": "100",
            "unit": "VND_MILLION",
            "label": "Revenue",
        },
    }
    output = DeplotChartReader(lambda image: RAW.replace("A | 50", "A | 50.2")).read(
        request(chart_regions=(region,))
    )
    item = output["evidence_batch"]["evidences"][0]
    assert item["numeric_value"] == "50.2"
    assert item["method_label"] == "ước lượng theo trục"
    assert item["chart_read"]["lower_tick"] == "0"
    validate_extraction_batch(output["evidence_batch"])


def test_log_axis_and_series_ambiguity_do_not_produce_valid_values():
    region = {
        **request().chart_regions[0],
        "axis": {
            "verified": True,
            "scale": "log",
            "lower_tick": "1",
            "upper_tick": "100",
            "unit": "VND_MILLION",
        },
    }
    output = DeplotChartReader(lambda image: RAW).read(request(chart_regions=(region,)))
    assert output["evidence_batch"]["evidences"][0]["numeric_value"] is None
    multi = "TITLE | Revenue\nRegion | North | South\nA | 10 | 20"
    output = DeplotChartReader(lambda image: multi).read(request())
    assert output["evidence_batch"]["evidences"] == []


def test_invalid_provider_table_is_not_published():
    assert (
        DeplotChartReader(lambda image: "garbage").read(request())["evidence_batch"][
            "evidences"
        ]
        == []
    )
    with pytest.raises(ValueError):
        parse_table("Region | A | B\nQ1 | 3")


def test_packaged_schema_matches_team_contract():
    from importlib.resources import files

    repo = Path(__file__).resolve().parents[4]
    assert json.loads(
        files("report_qa.resources")
        .joinpath("document-evidence-v2.schema.json")
        .read_text()
    ) == json.loads((repo / "contracts/document-evidence-v2.schema.json").read_text())


def test_merged_header_paths_and_repeated_cells_are_not_duplicated():
    data = json.loads((FIXTURES / "docling-recorded.json").read_text())
    cells = data["tables"][0]["data"]["table_cells"]
    cells.append(
        {
            **cells[1],
            "text": "FY2026",
            "start_col_offset_idx": 1,
            "end_col_offset_idx": 4,
        }
    )
    cells.append(dict(cells[5]))
    numbers = [
        e
        for e in artifact(data)["evidence_batch"]["evidences"]
        if e["source_type"] == "table"
    ]
    assert len(numbers) == 12
    assert "FY2026" in numbers[0]["table_locator"]["column_header"]
    cost = next(e for e in numbers if e["numeric_value"] == "810.25")
    assert cost["table_locator"]["row_header"] == "Q1"


def test_text_numbers_have_native_word_boxes_and_missing_metadata_stays_null(tmp_path):
    import pymupdf

    path = tmp_path / "text.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=400, height=300)
        page.insert_text((30, 50), "Revenue Q1/2026 was 120 million VND.")
        pdf.save(path)
    data = {
        "tables": [],
        "pictures": [],
        "texts": [
            {
                "label": "text",
                "text": "Revenue Q1/2026 was 120 million VND.",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 25,
                            "t": 30,
                            "r": 350,
                            "b": 60,
                            "coord_origin": "TOPLEFT",
                        },
                    }
                ],
            }
        ],
    }
    converter = Mock()
    converter.convert.return_value = SimpleNamespace(
        status="ConversionStatus.SUCCESS",
        document=SimpleNamespace(export_to_dict=lambda: data),
    )
    batch = extract_docling_artifact(path, "version", converter=converter)[
        "evidence_batch"
    ]
    assert len(batch["evidences"]) == 1
    item = batch["evidences"][0]
    assert item["numeric_value"] == "120"
    assert item["semantic"]["period"]["label"] == "Q1/2026"
    assert item["semantic"]["unit"] == "VND_MILLION"
    assert item["bbox"][2] - item["bbox"][0] < 0.1
    validate_extraction_batch(batch)


def test_native_chart_label_has_source_word_bbox(tmp_path):
    import pymupdf

    path = tmp_path / "native.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=400, height=300)
        page.insert_text((100, 100), "50")
        page.insert_text((103, 220), "A")
        pdf.save(path)
    region = {
        "chart_region_key": "chart-1",
        "page_number": 1,
        "bbox": [0.1, 0.1, 0.9, 0.9],
    }
    result = DeplotChartReader(lambda image: RAW).read(
        request(source_pdf_path=path, chart_regions=(region,))
    )
    item = result["evidence_batch"]["evidences"][0]
    assert item["method_label"] == "đọc từ nhãn"
    assert item["numeric_value"] == "50"
    assert item["bbox"][2] - item["bbox"][0] < 0.1


def test_axis_metadata_without_confirmation_of_absent_labels_is_not_enough():
    region = {
        **request().chart_regions[0],
        "axis": {
            "verified": True,
            "scale": "linear",
            "lower_tick": "0",
            "upper_tick": "100",
            "unit": "VND_MILLION",
        },
    }
    result = DeplotChartReader(lambda image: RAW).read(request(chart_regions=(region,)))
    assert result["evidence_batch"]["evidences"][0]["numeric_value"] is None
