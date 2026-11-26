"""Legacy extractor: number normalization and keyword tagging regressions."""

import threading
from pathlib import Path

import pymupdf
import pytest

from report_qa.api import session_storage
from report_qa.application.evidence_extraction import (
    _decimal_text,
    _measure,
    _period_near,
    _private_use_share,
    _unit_near,
    extract_legacy_pdf_artifact,
)
from report_qa.application.table_extraction import _decimal, _header_count, _page_bbox, _row_header
from report_qa.domain.types import validate_decimal_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+12", "12"),
        ("+12.5%", "12.5"),
        ("0.5", "0.5"),
        ("-0.5", "-0.5"),
        ("0.0%", "0"),
        ("-0", "0"),
        ("007", "7"),
        ("1.250,5", "1250.5"),
        ("1,250", "1250"),
        ("1250.50", "1250.50"),
    ],
)
def test_text_numbers_normalize_to_contract_decimals(raw, expected):
    assert _decimal_text(raw) == expected
    assert validate_decimal_text(_decimal_text(raw)) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0.5", "0.5"), ("0.0%", "0"), ("+3", "3"), ("12,5%", "12.5"), ("1.234.567", "1234567")],
)
def test_table_cell_numbers_normalize_to_contract_decimals(raw, expected):
    # lstrip("0") used to turn "0.5" into ".5" and fail the whole document.
    assert _decimal(raw) == expected
    assert validate_decimal_text(_decimal(raw)) == expected


def test_signed_and_fractional_numbers_do_not_fail_the_whole_document(tmp_path):
    path = tmp_path / "signs.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Revenue Q2/2024 grew +12 VND.", fontname="helv", fontsize=11)
    page.insert_text((72, 100), "Margin Q2/2024 was 0.5 percent.", fontname="helv", fontsize=11)
    doc.save(path)

    artifact = extract_legacy_pdf_artifact(path, "doc-signs")

    values = {item["raw_text"]: item["numeric_value"] for item in artifact["evidence_batch"]["evidences"]}
    assert values["+12"] == "12"
    assert values["0.5"] == "0.5"


def test_keywords_match_across_non_breaking_spaces():
    # pypdf returns U+00A0 between words for many real PDFs.
    assert _measure("Doanh\xa0thu\xa0Q1/2024\xa0đạt\xa01250") == "doanh_thu"
    assert _measure("Lợi\xa0nhuận Q1/2024") == "loi_nhuan"
    assert _unit_near("đạt\xa01250\xa0tỷ\xa0đồng.", "1250") == "VND_BILLION"
    assert _period_near("Doanh thu Q1\xa02024 đạt 1250", 20)["label"] == "Q1/2024"


def test_concurrent_catalog_saves_do_not_collide(tmp_path, monkeypatch):
    # A shared "sessions.tmp" let one writer's os.replace() move the other
    # writer's file away (FileNotFoundError) or publish a half-written one.
    monkeypatch.setattr(session_storage, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(session_storage, "CATALOG_FILE", tmp_path / "sessions.json")
    catalog = {"sessions": {f"s{index}": {"id": f"s{index}", "messages": list(range(200))} for index in range(50)}}
    errors = []

    def save_many():
        try:
            for _ in range(20):
                session_storage.save_catalog(catalog)
        except Exception as exc:  # noqa: BLE001 - any failure is the regression
            errors.append(exc)

    threads = [threading.Thread(target=save_many) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert session_storage.load_catalog() == catalog
    assert list(tmp_path.glob("*.tmp")) == []


REPORT_PDF = Path(__file__).parents[1] / "fixtures/extraction/report.pdf"


def test_table_cells_are_published_once_with_headers_and_period():
    pytest.importorskip("pdfplumber")
    # The table is drawn under a "cm" translation; ignoring it misplaced the
    # text-run cells, so they were never deduplicated against pdfplumber.
    artifact = extract_legacy_pdf_artifact(REPORT_PDF, "doc-report")
    cells = [item for item in artifact["evidence_batch"]["evidences"] if item["source_type"] == "table"]

    assert len(cells) == 12
    assert len({item["raw_text"] + str(item["table_locator"]["row_index"]) + str(item["table_locator"]["column_index"]) for item in cells}) == 12
    revenue_q1 = next(item for item in cells if item["raw_text"] == "1,250.50")
    assert revenue_q1["table_locator"]["row_header"] == "Q1"
    assert revenue_q1["table_locator"]["column_header"] == "Doanh thu"
    assert revenue_q1["semantic"]["measure"] == "doanh_thu"
    assert revenue_q1["semantic"]["period"]["label"] == "Q1/2024"
    growth_q3 = next(item for item in cells if item["raw_text"] == "0.0%")
    assert (growth_q3["numeric_value"], growth_q3["semantic"]["unit"]) == ("0", "PERCENT")


def test_text_position_includes_the_transformation_matrix(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    # Text at (0, 0) of a block translated to (300, 421) by "cm".
    stream.set_data(b"q 1 0 0 1 300 421 cm BT /F1 12 Tf 0 0 Td (Revenue Q1/2024 was 1250 VND.) Tj ET Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "shifted.pdf"
    with path.open("wb") as handle:
        writer.write(handle)

    artifact = extract_legacy_pdf_artifact(path, "doc-shifted")
    x0, y0, x1, y1 = next(item for item in artifact["evidence_batch"]["evidences"] if item["raw_text"] == "1250")["bbox"]

    # Without the cm translation the number was placed at the page corner.
    assert 0.5 < x0 < 0.9 and 0.45 < y0 < 0.52, (x0, y0, x1, y1)


def test_bare_quarter_takes_the_only_year_on_the_page():
    from report_qa.application.evidence_extraction import _period_for

    assert _period_for("Q3 Doanh thu 980.00", "980.00", "2024")["label"] == "Q3/2024"
    assert _period_for("Q3 Doanh thu 980.00", "980.00", None) is None
    assert _period_for("Doanh thu Q3/2023 980.00", "980.00", "2024")["label"] == "Q3/2023"


def _player_table_pdf(path: Path) -> None:
    """Header bar with column borders, data rows with horizontal rules only."""

    doc = pymupdf.open()
    page = doc.new_page(width=960, height=540)
    # Clipped background drawn far outside the page, as Chrome prints it.
    page.draw_rect(pymupdf.Rect(0, -540, 960, 1080), color=(1, 1, 1), fill=(0.98, 0.98, 0.98))
    columns = [12, 60, 260, 420, 580, 948]
    for left, right, title in zip(columns, columns[1:], ["#", "Player", "Total Distance (m)", "Zone 1 0-7 km/h (m)", "Top Speed (km/h)"]):
        page.draw_rect(pymupdf.Rect(left, 80, right, 104), color=(0, 0, 0.8), fill=(0.2, 0.3, 1))
        page.insert_text((left + 6, 96), title, fontsize=9, color=(1, 1, 1))
    players = [("16", "Mike Alpha", "4962.4", "3790.7", "23.9"), ("2", "Malo Beta", "9555.2", "3483.0", "33.5"), ("10", "Kylian Gamma", "8287.4", "4398.7", "36.0")]
    for index, cells in enumerate(players):
        top = 104 + index * 24
        page.draw_line((12, top + 24), (948, top + 24), color=(0.8, 0.8, 0.9))
        for left, text in zip(columns, cells):
            page.insert_text((left + 6, top + 16), text, fontsize=9)
    doc.save(path)


def test_player_table_without_row_borders_keeps_names_and_headers(tmp_path):
    path = tmp_path / "players.pdf"
    _player_table_pdf(path)

    artifact = extract_legacy_pdf_artifact(path, "doc-players")

    cells = {
        (item["table_locator"]["row_header"], item["table_locator"]["column_header"]): item["numeric_value"]
        for item in artifact["evidence_batch"]["evidences"]
        if item["table_locator"]
    }
    assert cells[("Kylian Gamma", "Total Distance (m)")] == "8287.4"
    assert cells[("Malo Beta", "Top Speed (km/h)")] == "33.5"


def test_box_overshooting_the_page_by_rounding_is_clamped():
    assert _page_bbox((0, -2e-13, 959.99996, 540.0000001), 960, 540) == [0.0, 0.0, 1.0, 1.0]
    # A background clipped from a 54-page print is not a table on this page.
    assert _page_bbox((0, -1620, 960, 27000), 960, 540) is None


def test_single_column_frame_does_not_hide_the_numbers_inside(tmp_path):
    path = tmp_path / "frame.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    for top in (60, 120):
        page.draw_rect(pymupdf.Rect(60, top, 400, top + 60))
    page.insert_text((72, 90), "Possession 41.5", fontsize=11)
    page.insert_text((250, 90), "Shots 19", fontsize=11)
    page.insert_text((72, 150), "Passes 453", fontsize=11)
    doc.save(path)

    artifact = extract_legacy_pdf_artifact(path, "doc-frame")

    raw = {item["raw_text"] for item in artifact["evidence_batch"]["evidences"]}
    assert {"41.5", "19", "453"} <= raw


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        (["16", "Mike Alpha", "15"], "Mike Alpha"),
        (["1", "Doanh thu"], "Doanh thu"),
        (["2024"], "2024"),
        ([None, None, "0", "0 1 0"], None),
        ([], None),
    ],
)
def test_row_header_is_a_name_not_an_index_or_a_value(cells, expected):
    assert _row_header(cells) == expected


def test_header_rows_below_a_numbered_group_title_are_not_data():
    assert _header_count([["", "4 Units", None], ["#", "Player", "Passes"], ["16", "Mike", "7"]]) == 2
    assert _header_count([["Chỉ tiêu", "2023", "2024"], ["Doanh thu", "10", "12"]]) == 1
    assert _header_count([["Chỉ tiêu", "2023"], ["Kinh doanh", None], ["Doanh thu", "10"]]) == 1


def test_unreadable_glyph_codes_are_read_with_pymupdf(tmp_path, monkeypatch):
    path = tmp_path / "glyphs.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text((72, 100), "Kylian Gamma", fontsize=11)
    page.insert_text((300, 100), "8287.4", fontsize=11)
    doc.save(path)
    from pypdf import PageObject

    def garbled(self, visitor_text=None, **_):
        text = "Kylian Gamma "
        if visitor_text:
            visitor_text(text, [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 72, 300], None, 11)
        return text

    monkeypatch.setattr(PageObject, "extract_text", garbled)

    artifact = extract_legacy_pdf_artifact(path, "doc-glyphs")

    assert "8287.4" in artifact["pages"][0]["text"]
    [item] = artifact["evidence_batch"]["evidences"]
    assert item["raw_text"] == "8287.4"
    assert item["table_locator"]["row_header"] == "Kylian Gamma"
    assert 0.49 < item["bbox"][0] < 0.51


def test_a_few_icon_characters_do_not_switch_the_reader():
    assert _private_use_share(" Doanh thu quý 2 tăng mạnh so với cùng kỳ") < 0.05


def test_damaged_catalog_is_set_aside_not_overwritten(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(session_storage, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(session_storage, "CATALOG_FILE", tmp_path / "sessions.json")
    damaged = '{"sessions": {"a": {"id": "a"'
    (tmp_path / "sessions.json").write_text(damaged, encoding="utf-8")

    assert session_storage.load_catalog() == {"sessions": {}}
    session_storage.save_catalog({"sessions": {}})

    [kept] = tmp_path.glob("sessions.json.corrupt-*")
    assert kept.read_text(encoding="utf-8") == damaged
    assert "not valid" in caplog.text


def test_catalog_save_syncs_before_replacing(tmp_path, monkeypatch):
    monkeypatch.setattr(session_storage, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(session_storage, "CATALOG_FILE", tmp_path / "sessions.json")
    calls = []
    real_fsync, real_replace = session_storage.os.fsync, session_storage.os.replace
    monkeypatch.setattr(session_storage.os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(session_storage.os, "replace", lambda a, b: (calls.append("replace"), real_replace(a, b))[1])

    session_storage.save_catalog({"sessions": {}})

    assert calls == ["fsync", "replace"]
