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


def test_deplot_provider_failure_is_structured_and_does_not_publish_values():
    def unavailable(_image):
        raise OSError("model cache unavailable")

    output = DeplotChartReader(unavailable).read(request())
    assert output["status"] == "not_available"
    assert output["code"] == "CHART_PROVIDER_UNAVAILABLE"
    assert output["evidence_batch"]["evidences"] == []
    assert output["evidence_batch"]["warnings"][0]["code"] == "CHART_PROVIDER_UNAVAILABLE"


def test_packaged_schema_matches_team_contract():
    from importlib.resources import files

    repo = Path(__file__).resolve().parents[4]
    assert json.loads(
        files("report_qa.resources")
        .joinpath("document-evidence-v2.schema.json")
        .read_text(encoding="utf-8")
    ) == json.loads((repo / "contracts/document-evidence-v2.schema.json").read_text(encoding="utf-8"))


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


def _text_artifact(tmp_path, items, locale="vi"):
    import pymupdf

    path = tmp_path / "prose.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=400)
        for i, (_, line) in enumerate(items):
            page.insert_text((20, 40 + 30 * i), line, fontname="helv", fontsize=9)
        pdf.save(path)
    data = {"tables": [], "pictures": [], "texts": [
        {"label": label, "text": line,
         "prov": [{"page_no": 1, "bbox": {"l": 15, "t": 28 + 30 * i, "r": 590, "b": 45 + 30 * i, "coord_origin": "TOPLEFT"}}]}
        for i, (label, line) in enumerate(items)
    ]}
    converter = Mock()
    converter.convert.return_value = SimpleNamespace(status="ConversionStatus.SUCCESS",
                                                     document=SimpleNamespace(export_to_dict=lambda: data))
    return extract_docling_artifact(path, "version", locale=locale, converter=converter)["evidence_batch"]["evidences"]


def test_a_number_ends_at_its_last_digit_not_at_the_punctuation_after_it(tmp_path):
    # "Nhóm 7," came out as the row "7,"; a sentence-final "1.250." could not be read as a number at all.
    evidences = _text_artifact(tmp_path, [("text", "Tai lieu do Nhom 7, doanh thu dat 1.250.")])
    assert [(e["raw_text"], e["numeric_value"], e["data_status"]) for e in evidences] == [("7", "7", "valid"), ("1.250", "1250", "valid")]


def test_numbers_are_read_in_the_format_the_page_text_proves_when_none_is_configured(tmp_path):
    # S1 prints "6,5%", so its table's "18.240" is 18240, not a number the user must confirm.
    evidences = _text_artifact(tmp_path, [("text", "Doanh thu 18.240 VND, chi phi 6,5% doanh thu.")], locale=None)
    assert [(e["raw_text"], e["numeric_value"]) for e in evidences] == [("18.240", "18240"), ("6,5%", "6.5")]
    mixed = _text_artifact(tmp_path, [("text", "Doanh thu 18.240 VND, chi phi 6,5%, lai 21.7%.")], locale=None)
    assert mixed[0]["data_status"] == "ambiguous"


def test_headings_and_period_numbers_are_not_published_as_values(tmp_path):
    # "1.", "2." headings came out as Data rows marked "Cần kiểm tra"; "quý 2", "tháng 6" came out as values 2 and 6.
    evidences = _text_artifact(tmp_path, [
        ("section_header", "1. Pham vi"),
        ("text", "Doanh thu tháng 6 cao trong quý 2 nam 2026, sau 6 tháng; muc tieu 220 VND."),
    ])
    assert [e["raw_text"] for e in evidences] == ["220"]


def test_a_text_number_is_labelled_from_its_own_sentence(tmp_path):
    # 6,5% and the 220 target were labelled "Doanh thu · 2026" from the paragraph's first measure word.
    evidences = _text_artifact(tmp_path, [(
        "text",
        "Doanh thu quý 1 nam 2026 cao. Chi phi van chuyen trong quý 2 bang 6,5% tong doanh thu. "
        "Muc tieu doanh thu nam 2026 la 220 VND.",
    )])
    rate, target = evidences
    assert rate["raw_text"] == "6,5%"
    assert rate["semantic"]["measure"] == "unknown" and rate["semantic"]["period"]["label"] == "Q2/2026"
    assert rate["semantic"]["subject"] == "Chi phi van chuyen trong quý 2 bang" and rate["semantic"]["unit"] == "PERCENT"
    assert target["semantic"]["measure"] == "doanh_thu" and target["semantic"]["period"]["label"] == "2026"
    assert target["semantic"]["unit"] == "VND"


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


def test_scanned_page_uses_ocr_tokens_and_keeps_retrieval_text(tmp_path):
    import pymupdf
    from report_qa.application.ocr_extraction import OcrPage

    path = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=400, height=300)
        pdf.save(path)

    data = {"tables": [], "pictures": [], "texts": []}
    converter = Mock()
    converter.convert.return_value = SimpleNamespace(
        status="ConversionStatus.SUCCESS",
        document=SimpleNamespace(export_to_dict=lambda: data),
    )

    class FakeOcr:
        def available(self):
            return True, None

        def read_page(self, _path, page_number):
            assert page_number == 1
            return OcrPage(
                page_number=1,
                width=800,
                height=600,
                tokens=(
                    {"text": "Doanh", "bbox": [0.1, 0.1, 0.2, 0.15], "confidence": 0.91},
                    {"text": "120", "bbox": [0.3, 0.1, 0.36, 0.15], "confidence": 0.88},
                ),
            )

    result = extract_docling_artifact(
        path, "scan-version", converter=converter, ocr_engine=FakeOcr()
    )
    assert result["pages"][0]["text"] == "Doanh 120"
    item = result["evidence_batch"]["evidences"][0]
    assert item["extraction_method"] == "ocr"
    assert item["numeric_value"] == "120"
    assert item["confidence"] == 0.88
    assert item["bbox"] == [0.3, 0.1, 0.36, 0.15]


def test_scanned_number_takes_the_unit_written_after_it_else_the_page_note(tmp_path):
    import pymupdf
    from report_qa.application.ocr_extraction import OcrPage

    path = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=400, height=300)
        pdf.save(path)
    converter = Mock()
    converter.convert.return_value = SimpleNamespace(
        status="ConversionStatus.SUCCESS",
        document=SimpleNamespace(export_to_dict=lambda: {"tables": [], "pictures": [], "texts": []}),
    )
    words = "Doanh thu (đơn vị: triệu đồng) Miền Bắc 1.250 . Mục tiêu năm 2026 là 220 tỷ đồng."

    class FakeOcr:
        def available(self):
            return True, None

        def read_page(self, _path, _page_number):
            tokens = tuple({"text": w, "bbox": [0.1, 0.1, 0.2, 0.15], "confidence": 0.9} for w in words.split())
            return OcrPage(page_number=1, width=800, height=600, tokens=tokens)

    result = extract_docling_artifact(path, "scan-version", converter=converter, ocr_engine=FakeOcr())
    units = {e["raw_text"]: e["semantic"]["unit"] for e in result["evidence_batch"]["evidences"]}
    assert units["220"] == "VND_BILLION"
    assert units["1.250"] == "VND_MILLION"


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


def test_docling_cell_semantics_come_from_its_own_header_path():
    data = json.loads((FIXTURES / "docling-recorded.json").read_text())
    cells = data["tables"][0]["data"]["table_cells"]
    by_text = {c["text"]: c for c in cells}
    by_text["Q1"]["text"] = "Q1/25"
    by_text["1,120.00"]["text"] = "-"
    numbers = {(e["table_locator"]["row_index"], e["table_locator"]["column_index"]): e
               for e in artifact(data)["evidence_batch"]["evidences"] if e["source_type"] == "table"}
    q1_cost = numbers[(1, 2)]
    assert q1_cost["semantic"]["period"]["label"] == "Q1/2025"  # not the page's 2024
    assert q1_cost["semantic"]["measure"] == "unknown"  # "Chi phí", not the page's "doanh thu"
    assert numbers[(1, 1)]["semantic"]["measure"] == "doanh_thu"
    assert numbers[(2, 3)]["table_locator"]["row_header"] == "Q2"  # the "-" cell left of it is a value
    assert numbers[(2, 3)]["semantic"]["subject"] == "Q2"


def test_a_cell_unit_comes_from_its_headers_or_the_table_note_not_nearby_prose():
    # S1's table in triệu đồng was tagged PERCENT from "tỷ lệ phần trăm khách hàng" in the paragraph above it.
    from report_qa.application.evidence_extraction import unit_after, unit_note

    nearby = "Tỷ lệ khách hàng quay lại là tỷ lệ phần trăm khách hàng. Bảng 1. Doanh thu (đơn vị: triệu đồng)"
    assert unit_note(nearby) == "VND_MILLION"
    assert unit_note("Tỷ lệ phần trăm khách hàng quay lại.") is None
    assert unit_after("đạt 33 nghìn đơn", 6, "33") == "THOUSAND"
    assert unit_after("là 220 tỷ đồng.", 6, "220") == "VND_BILLION"
    assert unit_after("đạt 33 đơn", 6, "33") is None


def test_a_page_without_text_is_reported_in_readable_vietnamese(tmp_path):
    import pymupdf

    path = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=600, height=400)
        pdf.save(path)
    converter = Mock()
    converter.convert.return_value = SimpleNamespace(status="ConversionStatus.SUCCESS",
                                                     document=SimpleNamespace(export_to_dict=lambda: {"tables": [], "pictures": [], "texts": []}))
    ocr = Mock(available=lambda: (False, "OCR_UNAVAILABLE"))
    warnings = extract_docling_artifact(path, "version", locale="vi", converter=converter, ocr_engine=ocr)["evidence_batch"]["warnings"]
    # The message was stored double-encoded ("khÃ´ng cÃ³ lá»›p chá»¯").
    assert warnings[0]["message"] == "Trang 1 không có lớp chữ; chưa trích xuất số từ trang này."
