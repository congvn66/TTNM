"""Chart reading cases found in QA round 2 (G2): "%" values, a title line holding the series
names, pies, a series read on the wrong axis, DePlot estimates a bar's height disagrees with,
and which pictures are offered as charts with which caption."""

import io
import json

import pymupdf
import pytest

from report_qa.application.chart_geometry import read_chart_image, tick_value
from report_qa.application.chart_regions import chart_candidates
from report_qa.application.chart_tool import CHART_READER_VERSION, _percent_outliers, chart_crop, read_chart_region
from report_qa.application.deplot_reading import parse_table
from report_qa.application.extraction_contract import validate_extraction_batch

# google/deplot's output for MSN "Hình 8" (bars, no printed numbers): the first category became the header.
MSN_SHARE_RAW = (
    "TITLE | Hình 8 MCH vẫn duy trì\nNước mâm | 70.0%\nTượng ốt | 68.3%\nNước tương | 53.3%\n"
    "Mỹ an liên | 42.0%\nCà phé hòa tan | 43.0%\nNường lực | 14.0%\nBột giặt | 5.0%"
)
# google/deplot's output for SHS HCM page 7 (stacked bars and a line): the series names are on the TITLE line.
HCM_BROKERAGE_RAW = (
    "TITLE | Doanh thu và biên lỡi nhuận gộp hoạt động Mồi giới | KHCN | KHTC | BLNG\n"
    "2018 | 493 | 270 | 759\n2019 | 275 | 183 | 32%\n2020 | 381 | 622 | 32%\n2021 | 968 | 370 | 45%\n"
    "2022 | 568 | 291 | 35%\n2023 | 391 | 258 | 30%\n2024 | 848 | 29% | 848"
)
NO_CHECK = lambda *args: json.dumps({"rows": []})  # noqa: E731
NAVY = (0, 0.125, 0.376)


def test_a_percent_header_is_the_first_data_row_of_a_one_series_chart():
    title, rows = parse_table(MSN_SHARE_RAW)
    assert len(rows) == 7 and rows[0] == ("Nước mâm", "Hình 8 MCH vẫn duy trì", "70.0%", "70.0")
    assert rows[-1][2:] == ("5.0%", "5.0")


def test_series_names_on_the_title_line_are_recovered():
    title, rows = parse_table(HCM_BROKERAGE_RAW)
    assert title == "Doanh thu và biên lỡi nhuận gộp hoạt động Mồi giới"
    assert len(rows) == 21 and rows[:3] == [("2018", "KHCN", "493", "493"), ("2018", "KHTC", "270", "270"), ("2018", "BLNG", "759", "759")]
    assert ("2019", "BLNG", "32%", "32") in rows


def test_a_category_name_broken_over_lines_is_joined():
    # MSN Hình 16: "Bắc Trung Bộ và Duyên hải miền Trung" came back over three lines.
    _, rows = parse_table("TITLE | Ty le\n | Ty le\nBac Trung Bo va\nDuyen hai mien\nTrung | 2.0\nTay Nguyen | 2.4")
    assert [row[0] for row in rows] == ["Bac Trung Bo va Duyen hai mien Trung", "Tay Nguyen"]
    with pytest.raises(ValueError, match="row width"):
        parse_table("TITLE | Ty le\n | Ty le\nTay Nguyen | 2.4\nBac Trung Bo")


def test_unnamed_series_still_fail():
    with pytest.raises(ValueError, match="series names"):
        parse_table("TITLE | x\nT1 | 38 | 17 | 33\nT2 | 35 | 15 | 30")


def test_values_written_unlike_their_series_are_found():
    _, rows = parse_table(HCM_BROKERAGE_RAW)
    assert _percent_outliers(rows) == {("2018", "BLNG", "759"), ("2024", "KHTC", "29%"), ("2024", "BLNG", "848")}


@pytest.mark.parametrize("text, value", [("2.500", 2500), ("2,500", 2500), ("45%", 45), ("-", 0), ("0.5", 0.5), ("(10)", -10), ("1,5", 1.5), ("x", None)])
def test_tick_values(text, value):
    assert tick_value(text) == value


def _bar_chart(path, values, labels, right_ticks=False):
    """A vector bar chart like MSN Hình 8: navy bars on a 0%..80% axis, names under the bars."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 120), "Figure 8: Market share", fontsize=10)
    for tick in range(0, 100, 20):
        page.insert_text((70, 400 - tick / 80 * 200 + 3), f"{tick}%", fontsize=8)
    if right_ticks:
        for tick in range(6):
            page.insert_text((510, 400 - tick / 5 * 200 + 3), f"{tick}%", fontsize=8)
    for index, (value, label) in enumerate(zip(values, labels)):
        x = 120 + index * 80
        page.draw_rect(pymupdf.Rect(x, 400 - value / 80 * 200, x + 30, 400), color=None, fill=NAVY)
        page.insert_text((x, 415), label, fontsize=8)
    doc.save(path)
    return {"chart_region_key": "page-1-picture-0", "page_number": 1, "bbox": [50 / 595, 100 / 842, 550 / 595, 430 / 842],
            "text": "Figure 8: Market share"}


def test_a_bar_height_confirms_or_overrules_deplot(tmp_path):
    # True values 68.8 / 23.7 / 10.0; DePlot read 70 (close), 42 (wrong), 14 (wrong).
    region = _bar_chart(tmp_path / "chart.pdf", [68.8, 23.7, 10.0], ["Alpha", "Beta", "Gamma"])
    raw = "TITLE | Figure 8: Market shere\nAlpah | 70.0%\nBeta | 42.0%\nGama | 14.0%"
    result = read_chart_region(tmp_path / "chart.pdf", region, "v", "q", complete=NO_CHECK, predictor=lambda image: raw)
    validate_extraction_batch(result["evidence_batch"])
    by_name = {e["chart_read"]["category_label"]: e for e in result["evidence_batch"]["evidences"]}
    assert set(by_name) == {"Alpha", "Beta", "Gamma"}  # the names printed under the bars, not DePlot's spelling
    alpha = by_name["Alpha"]
    assert (alpha["numeric_value"], alpha["data_status"], alpha["method_label"]) == ("70.0", "valid", "ước lượng theo trục")
    assert {"geometry_axis_estimate_match", "box_bar"} <= set(alpha["chart_read"]["assumptions"])
    assert (alpha["chart_read"]["lower_tick"], alpha["chart_read"]["upper_tick"]) == ("0", "80")
    assert alpha["chart_read"]["series_label"] == "Figure 8: Market share" and alpha["semantic"]["unit"] == "PERCENT"
    assert alpha["bbox"][3] - alpha["bbox"][1] < 0.3  # its own bar, not the whole chart
    for name in ("Beta", "Gamma"):
        assert by_name[name]["numeric_value"] is None and by_name[name]["data_status"] == "ambiguous"
    disagree = [w["message"] for w in result["evidence_batch"]["warnings"] if w["code"] == "CHART_VALUE_DISAGREES_WITH_BAR"]
    assert len(disagree) == 2 and "DePlot đọc 42.0%" in disagree[0] and "khoảng 23." in disagree[0]
    assert result["reader_version"] == CHART_READER_VERSION == 5


def test_a_right_axis_series_read_on_the_left_scale_is_withheld(tmp_path):
    # MSN Hình 19: the margin line (right axis, 0%..5%) came out as 1283..2327, the left axis's scale.
    region = _bar_chart(tmp_path / "combo.pdf", [40, 60], ["2023", "2024"], right_ticks=True)
    raw = "TITLE | \n | EBITDA (ty dong, trai) | Bien EBITDA (%, phai)\n2023 | 40 | 1283.1\n2024 | 60 | 2.9"
    result = read_chart_region(tmp_path / "combo.pdf", region, "v", "q", complete=NO_CHECK, predictor=lambda image: raw)
    off = [w for w in result["evidence_batch"]["warnings"] if w["code"] == "CHART_VALUE_OFF_AXIS"]
    assert len(off) == 1 and "1283.1" in off[0]["message"] and "trục phải (0 đến 5)" in off[0]["message"]
    flagged = next(e for e in result["evidence_batch"]["evidences"] if e["evidence_key"] == off[0]["evidence_key"])
    assert flagged["raw_text"] == "1283.1" and flagged["numeric_value"] is None
    # The one bar colour belongs to the one series not on the right axis: its heights confirm 40 and 60.
    bars = [e for e in result["evidence_batch"]["evidences"] if e["chart_read"]["series_label"].startswith("EBITDA")]
    assert [(e["numeric_value"], "box_bar" in e["chart_read"]["assumptions"]) for e in bars] == [("40", True), ("60", True)]


def _pie_pdf(path):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (400, 400), "white")
    draw = ImageDraw.Draw(image)
    start = 0
    for share, colour in [(32, (91, 155, 213)), (17, (237, 125, 49)), (31, (112, 173, 71)), (20, (68, 114, 196))]:
        draw.pieslice([40, 40, 360, 360], start, start + share * 3.6, fill=colour, outline="white", width=3)
        start += share * 3.6
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(100, 300, 300, 500), stream=buffer.getvalue())
    doc.save(path)
    return {"chart_region_key": "page-1-picture-0", "page_number": 1, "bbox": [100 / 595, 300 / 842, 300 / 595, 500 / 842]}


def test_a_pie_whose_parts_do_not_add_up_is_not_readable(tmp_path):
    # SHS HCM "Cơ cấu cổ đông": DePlot kept 3 of 6 parts.
    region = _pie_pdf(tmp_path / "pie.pdf")
    raw = "TITLE | Co cau co dong\nCo dong ca nhan | 0.309\nCo dong to chuc | 0.128\nCo phieu quy | 0.0012"
    result = read_chart_region(tmp_path / "pie.pdf", region, "v", "q", complete=NO_CHECK, predictor=lambda image: raw)
    validate_extraction_batch(result["evidence_batch"])
    assert result["status"] == "not_readable" and result["evidence_batch"]["evidences"] == []
    [warning] = result["evidence_batch"]["warnings"]
    assert warning["code"] == "CHART_NOT_READABLE" and warning["message"].startswith("Biểu đồ tròn này chưa đọc được")
    assert "cộng lại 43.82%, không phải 100%" in warning["message"]


def test_a_pie_whose_table_breaks_is_not_readable_and_one_that_adds_up_is_read(tmp_path):
    region = _pie_pdf(tmp_path / "pie.pdf")
    broken = "TITLE | Co cau\nCo dong ca\nnhan, 30,93% | 0.309\nCo dong to\nchuc, 18,51% | 0.128"
    result = read_chart_region(tmp_path / "pie.pdf", region, "v", "q", complete=NO_CHECK, predictor=lambda image: broken)
    assert result["status"] == "not_readable" and "Biểu đồ tròn" in result["evidence_batch"]["warnings"][0]["message"]
    whole = "TITLE | Co cau\n | Ty le\nDC | 32%\nHFIC | 17%\nCa nhan | 31%\nTo chuc | 20%"
    result = read_chart_region(tmp_path / "pie.pdf", region, "v", "q", complete=NO_CHECK, predictor=lambda image: whole)
    assert result["status"] == "completed" and len(result["evidence_batch"]["evidences"]) == 4


def test_an_unusable_table_is_not_readable_instead_of_an_error(tmp_path):
    region = _bar_chart(tmp_path / "chart.pdf", [40], ["Alpha"])
    result = read_chart_region(tmp_path / "chart.pdf", region, "v", "q", complete=NO_CHECK, predictor=lambda image: "Region | A | B\nQ1 | 3")
    assert result["status"] == "not_readable"
    assert result["evidence_batch"]["warnings"][0]["message"].startswith("Biểu đồ này chưa đọc được")


def test_round_and_bar_images_are_told_apart(tmp_path):
    region = _pie_pdf(tmp_path / "pie.pdf")
    with pymupdf.open(tmp_path / "pie.pdf") as pdf:
        png = pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=chart_crop(pdf[0], region["bbox"])).tobytes("png")
    assert read_chart_image(png, region["bbox"], [], [], words=[])["shape"] == "pie"
    region = _bar_chart(tmp_path / "bars.pdf", [68.8, 23.7, 10.0], ["Alpha", "Beta", "Gamma"])
    with pymupdf.open(tmp_path / "bars.pdf") as pdf:
        png = pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=chart_crop(pdf[0], region["bbox"])).tobytes("png")
    assert read_chart_image(png, region["bbox"], [], [], words=[])["shape"] is None


def test_the_crop_stops_at_the_paragraph_under_a_source_note(tmp_path):
    # MSN page 8: "Nguồn: …" and the paragraph under it are one text block that starts inside the chart region.
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(30, 430, 560, 480), "Source: MSN\nMCH kept its market share in a weak market", fontsize=10)
    doc.save(tmp_path / "crop.pdf")
    with pymupdf.open(tmp_path / "crop.pdf") as pdf:
        lines = [line["bbox"] for block in pdf[0].get_text("dict")["blocks"] for line in block.get("lines", [])]
        crop = chart_crop(pdf[0], [50 / 595, 300 / 842, 550 / 595, (lines[0][1] + 2) / 842])
    assert crop.y1 < lines[1][1]


def _page_with_pictures(path):
    from PIL import Image

    def png(colour):
        buffer = io.BytesIO()
        Image.new("RGB", (60, 40), colour).save(buffer, format="PNG")
        return buffer.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(470, 20, 560, 45), stream=png((200, 30, 30)))  # header logo
    page.insert_image(pymupdf.Rect(50, 560, 300, 760), stream=png((120, 120, 120)))  # a photo
    page.insert_text((50, 180), "Figure 4: Revenue by segment", fontsize=9)
    page.insert_text((320, 180), "Figure 5: Gross profit by segment", fontsize=9)
    for left in (50, 320):
        for tick in range(5):
            page.insert_text((left + 5, 390 - tick * 40), f"{tick * 10},000", fontsize=7)
    doc.save(path)
    box = lambda x0, y0, x1, y1: [x0 / 595, y0 / 842, x1 / 595, y1 / 842]  # noqa: E731
    return [
        {"chart_region_key": "page-1-picture-0", "page_number": 1, "bbox": box(470, 20, 560, 45), "text": "Figure 5: Gross profit by segment"},
        {"chart_region_key": "page-1-picture-1", "page_number": 1, "bbox": box(50, 190, 290, 400), "text": ""},
        {"chart_region_key": "page-1-picture-2", "page_number": 1, "bbox": box(320, 190, 560, 400), "text": "Figure 4: Revenue by segment Figure 5: Gross profit"},
        {"chart_region_key": "page-1-picture-3", "page_number": 1, "bbox": box(50, 560, 300, 760), "text": ""},
    ]


def test_logos_and_photos_are_not_chart_candidates_and_captions_are_the_nearest(tmp_path):
    charts = _page_with_pictures(tmp_path / "page.pdf")
    with pymupdf.open(tmp_path / "page.pdf") as pdf:
        kept = chart_candidates(pdf, charts, read_image_text=lambda page, rect: [])
    assert [(r["chart_region_key"], r["text"]) for r in kept] == [
        ("page-1-picture-1", "Figure 4: Revenue by segment"),
        ("page-1-picture-2", "Figure 5: Gross profit by segment"),
    ]


def test_a_picture_with_text_only_in_its_pixels_is_kept(tmp_path):
    charts = _page_with_pictures(tmp_path / "page.pdf")
    with pymupdf.open(tmp_path / "page.pdf") as pdf:
        kept = chart_candidates(pdf, charts, read_image_text=lambda page, rect: ["Doanh", "thu", "2024"])
    assert "page-1-picture-3" in {r["chart_region_key"] for r in kept}


def test_a_scanned_page_keeps_its_pictures_and_their_layout_captions(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.save(tmp_path / "scan.pdf")
    region = {"chart_region_key": "page-1-picture-0", "page_number": 1, "bbox": [0.1, 0.2, 0.9, 0.5], "text": "Biểu đồ 1. Doanh thu"}
    with pymupdf.open(tmp_path / "scan.pdf") as pdf:
        assert chart_candidates(pdf, [region], read_image_text=lambda page, rect: []) == [region]


def test_quarter_and_year_labels_are_put_back_on_one_run():
    from report_qa.application.chart_tool import _period_sequence

    # DePlot's categories for S2 Biểu đồ 1 (Q1/25 … Q3/26).
    assert _period_sequence(["Q1/25", "Q2/26", "Q3/25", "Q4/25", "Q1/28", "Q2/26", "Q3/26"]) == [
        "Q1/25", "Q2/25", "Q3/25", "Q4/25", "Q1/26", "Q2/26", "Q3/26"]
    assert _period_sequence(["2020", "2021", "2029", "2023"]) == ["2020", "2021", "2022", "2023"]
    assert _period_sequence(["Q1/25", "Q2/25", "Q3/25"]) is None  # already consecutive
    assert _period_sequence(["Q1/25", "Q4/27", "Q2/22"]) is None  # no run to trust
    assert _period_sequence(["T1", "T2", "T3"]) is None


def _bar_and_margin_line(path, margins):
    """S2 Biểu đồ 1 drawn as vectors: bars on a 0..350 left axis, a margin line on a 10..24 right axis."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    top, bottom = 150, 400
    for tick in range(0, 400, 50):
        page.insert_text((60, bottom - tick / 350 * (bottom - top) + 3), str(tick), fontsize=8)
    for tick in range(10, 26, 2):
        page.insert_text((520, bottom - (tick - 10) / 14 * (bottom - top) + 3), str(tick), fontsize=8)
    points = []
    for index, margin in enumerate(margins):
        x = 110 + index * 55
        page.draw_rect(pymupdf.Rect(x, bottom - 250 / 350 * (bottom - top), x + 30, bottom), color=None, fill=NAVY)
        page.insert_text((x + 2, 415), f"Q{index % 4 + 1}/{25 + index // 4}", fontsize=8)
        points.append(pymupdf.Point(x + 15, bottom - (margin - 10) / 14 * (bottom - top)))
    page.draw_polyline(points, color=(0, 0, 0), width=1.5)
    page.insert_text((110, 440), "Doanh thu thuan (truc trai)", fontsize=8)
    page.insert_text((300, 440), "Bien loi nhuan gop (truc phai)", fontsize=8)
    doc.save(path)
    return {"chart_region_key": "page-1-picture-0", "page_number": 1, "bbox": [40 / 595, 120 / 842, 560 / 595, 450 / 842], "text": ""}


def test_a_right_axis_line_read_on_the_left_scale_is_read_where_it_is_drawn(tmp_path):
    margins = [17.9, 16.9, 18.6, 20.0, 15.3, 16.9, 18.8]
    region = _bar_and_margin_line(tmp_path / "s2.pdf", margins)
    # DePlot's output for S2: the margin line came back on the left axis's scale, the series named "Biểu đồ".
    raw = ("TITLE | Biểu đồ\n | Doanh thu thuận (tục trả) | Biểu đồ\nQ1/25 | 250 | 241.0\nQ2/26 | 250 | 153.13\n"
           "Q3/25 | 250 | 223.23\nQ4/25 | 250 | 277.87\nQ1/28 | 250 | 188.1\nQ2/26 | 250 | 158.46\nQ3/26 | 250 | 167.38")
    result = read_chart_region(tmp_path / "s2.pdf", region, "v", "q", complete=NO_CHECK, predictor=lambda image: raw)
    validate_extraction_batch(result["evidence_batch"])
    line = [e for e in result["evidence_batch"]["evidences"] if e["chart_read"]["series_label"] == "Bien loi nhuan gop (truc phai)"]
    assert [e["chart_read"]["category_label"] for e in line] == ["Q1/25", "Q2/25", "Q3/25", "Q4/25", "Q1/26", "Q2/26", "Q3/26"]
    assert all(e["data_status"] == "valid" and e["confidence"] == 0.6 for e in line)
    assert all(abs(float(e["numeric_value"]) - margin) <= 0.3 for e, margin in zip(line, margins))
    assert all({"geometry_line_point_reading", "box_point"} <= set(e["chart_read"]["assumptions"]) for e in line)
    assert (line[0]["chart_read"]["lower_tick"], line[0]["chart_read"]["upper_tick"]) == ("10", "24")
    moved = [w["message"] for w in result["evidence_batch"]["warnings"] if w["code"] == "CHART_VALUE_FROM_LINE"]
    assert len(moved) == 7 and "DePlot đọc 241.0" in moved[0]


def test_s2_scanned_margin_line_is_read_on_the_right_axis():
    from pathlib import Path

    source = Path(__file__).resolve().parents[5] / "pdf-test" / "S2-logistics-bac-nam-scan.pdf"
    if not source.exists():
        pytest.skip("S2 test report not next to this checkout")
    region = {"chart_region_key": "page-1-picture-0", "page_number": 1, "bbox": [0.132, 0.607, 0.89, 0.901]}
    raw = ("TITLE | Biểu đồ\n | Doanh thu thuận (tục trả) | Biểu đồ\nQ1/25 | 182.7 | 241.0\nQ2/26 | 196.93 | 153.13\n"
           "Q3/25 | 211.18 | 223.23\nQ4/25 | 225.66 | 277.87\nQ1/28 | 200.98 | 188.1\nQ2/26 | 213.26 | 158.46\nQ3/26 | 236.10 | 167.38")
    result = read_chart_region(source, region, "v", "q", complete=NO_CHECK, predictor=lambda image: raw)
    line = {e["chart_read"]["category_label"]: float(e["numeric_value"]) for e in result["evidence_batch"]["evidences"]
            if "phải" in e["chart_read"]["series_label"] and e["numeric_value"] is not None}
    # Answer key: Q1/26 15.3, Q2/26 16.9, Q3/26 18.8 (±0.5); the others read from the image.
    expected = {"Q1/25": 17.9, "Q2/25": 16.9, "Q3/25": 18.6, "Q4/25": 20.0, "Q1/26": 15.3, "Q2/26": 16.9, "Q3/26": 18.8}
    assert line.keys() == expected.keys()
    assert all(abs(line[quarter] - value) <= 0.5 for quarter, value in expected.items())
