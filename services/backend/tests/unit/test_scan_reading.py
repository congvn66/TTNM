"""Rules for reading statements and scans: which cells are values, how printed and OCR'd numbers are read.

Each test names the QA finding it covers (D2 = scans, C2 = digital uploads, E2 = reader).
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from report_qa.application import docling_extraction
from report_qa.application.docling_extraction import _merge_scanned, extract_docling_artifact, scan_pages
from report_qa.application.evidence_extraction import label_unit, unit_after, unit_note
from report_qa.application.numeric_extraction import (
    PERIOD,
    _period,
    decimal_text,
    is_value_text,
    joined_number,
    quantities,
)
from report_qa.application.ocr_extraction import OcrPage

# ---------------------------------------------------------------- numbers


@pytest.mark.parametrize("raw,locale,expected", [
    ("140,852,122,738", "vi", "140852122738"),  # D2-4: English grouping in an all-OCR (Vietnamese) document
    ("1.357.205", "en", "1357205"),
    ("250.000.000.000", None, "250000000000"),
    ("2.785,40", "vi", "2785.40"),
    ("7.0", "vi", "7.0"),  # C2 ACBS: one or two digits after one separator are decimals
    ("-5.4", "vi", "-5.4"),
    ("52,077, 141,846", "vi", "52077141846"),  # spaces OCR puts inside a number
])
def test_numbers_are_read_whatever_the_document_format_when_only_one_reading_exists(raw, locale, expected):
    assert decimal_text(raw, locale) == expected


@pytest.mark.parametrize("raw,locale,exact", [
    ("1,013.545", "vi", False),  # D2-3: OCR slip of 1.013.545, never 1013.545
    ("6.5", "vi", True),  # OCR: "." is often a misread ","
    ("1.234", None, False),
])
def test_numbers_with_two_readings_are_unsure(raw, locale, exact):
    with pytest.raises(ValueError):
        decimal_text(raw, locale, exact=exact)


@pytest.mark.parametrize("text,expected", [
    ("4 968 956 415", "4968956415"),  # C2-4
    ("(4 968 956 415)", "(4968956415)"),
    ("- 57 580 598", "-57580598"),
    ("1430 350 876 514", "1430350876514"),  # a 13-digit amount in a "### ### ### ###" format
    ("52,077, 141,846", "52,077,141,846"),  # D2-4
    ("20,96 1,264,731", "20,961,264,731"),
    ("2024 1,200", "2024 1,200"),  # two numbers stay two numbers
    ("15 20", "15 20"),
    ("4.813 (*)", "4.813 (*)"),
])
def test_space_grouped_numbers_are_one_number(text, expected):
    assert joined_number(text) == expected


# ---------------------------------------------------------------- labels and identifiers


@pytest.mark.parametrize("text,value", [
    ("1. Vốn góp của chủ sở hữu", False),  # D2-5, C2-6
    ("17.Lợi nhuận sau thuế", False),
    ("8 Chi phi ban hang", False),  # the same, read by OCR
    ("1 0. Lợi nhuận thuần", False),
    ("] 11. Thu nhập khác", False),
    ("a) Trả trước cho người bán", False),
    ("V.01", False),  # D2-6, C2-5
    ("VI.9", False),
    ("Thấp/Cao 52 tuần", False),  # C2-5
    ("Giá mục tiêu 2026:", False),
    ("Tổng cộng 2.370.750", True),
    ("1.144", True),
    ("(768.818)", True),
    ("4.813 (*)", True),
    ("+12,1%", True),
    ("-", True),
])
def test_numbered_rows_and_note_references_are_labels(text, value):
    assert is_value_text(text) is value


@pytest.mark.parametrize("text", [
    "Căn cứ Điều 14 và Điều 22 của thông tư số 96/2020/TT-BTC ngày 16 tháng 11 năm 2020",  # D2-8
    "Pursuant to Article 14 and Article 22 of Circular No. 96/2020/TT-BTC",
    "Số 55 Đường K2, phường Từ Liêm",  # C2-5
    "Công ty đặt tại số 55, đường K2",
    "Mã số thuế: 0100779340",
    "470 Đồng Văn Cống, Phường Thạnh Mỹ Lợi",  # E2-9
    "Tel: (+84 28) 7300 7000 (x1083)",
    "(+84 8) 7300 7000 - Ext: 1044",
    "thỏa mãn đồng thời hai (2) điều kiện sau",
    "hướng dẫn thực hiện (06) chuẩn mực kế toán",
    "Chuẩn mực Kế toán Việt Nam số 16 \"Chi phí đi vay\"",
    "Khoản cho vay được phản ánh ở TK 1283",
    "đăng ký thay đổi lần 14 ngày 26/12/2024",
    "BAO CAO HOAT DONG 9 THANG NAM 2026",  # OCR dropped the accents
    "Bang 3. Doanh thu",
    "Thấp/Cao 52 tuần",
    "VNIndex 1765,28/292,64",  # two values joined by "/", never "64"
    "Hà Nội, ngày.30 tháng 9",
])
def test_identifiers_dates_and_headings_are_not_quantities(text):
    assert [m.group() for m in quantities(text)] == []


def test_amounts_next_to_identifiers_are_still_quantities():
    text = "Vốn điều lệ theo đăng ký lần 14 ngày 26/12/2024 là: 250.000.000.000 đồng; chi phí bằng 6,5% doanh thu."
    assert [m.group() for m in quantities(text)] == ["250.000.000.000", "6,5%"]


@pytest.mark.parametrize("text,label", [
    ("Lũy kế 9 tháng năm 2025", "9T/2025"),  # D2-9
    ("9tháng2026", "9T/2026"),
    ("9 tháng 2026", "9T/2026"),
    ("9 thắng2025", "9T/2025"),  # OCR swapped the accent
    ("Quý III năm 2025", "Q3/2025"),
    ("Quy 3/2025", "Q3/2025"),
    ("quý III.2025", "Q3/2025"),
    ("tháng 10 năm 2025", "T10/2025"),
    ("6 tháng đầu năm 2026", "6T/2026"),
])
def test_periods_written_in_words_or_without_accents(text, label):
    assert [_period(m)["label"] for m in PERIOD.finditer(text)] == [label]


# ---------------------------------------------------------------- units


def test_units_of_ratios_and_tonnes():
    # D2-11
    assert label_unit("Biên lợi nhuận gộp (%)") == "PERCENT"
    assert label_unit("Hệ số nợ trên vốn chủ sở hữu (lần)") == "TIMES"
    assert unit_note("Bảng 2. Sản lượng (đơn vị: nghìn tấn)") == "THOUSAND_TONNE"
    assert unit_note("(đơn vị: nghìn tắn)") == "THOUSAND_TONNE"  # OCR
    assert unit_after("đạt 1.284,6 nghìn tấn", 11, "1.284,6") == "THOUSAND_TONNE"
    # E2-9: a street named "Đồng Văn Cống" is not đồng.
    assert unit_after("470 Đồng Văn Cống", 3, "470") is None
    assert unit_after("đạt 470 Đồng.", 7, "470") == "VND"


# ---------------------------------------------------------------- tables

W, H = 600, 800


def _cell(row, col, text, header=False, row_header=False):
    left, top = 40 + col * 100, 100 + row * 20
    return {"bbox": {"l": left + 5, "t": top + 4, "r": left + 95, "b": top + 16, "coord_origin": "TOPLEFT"},
            "row_span": 1, "col_span": 1, "start_row_offset_idx": row, "end_row_offset_idx": row + 1,
            "start_col_offset_idx": col, "end_col_offset_idx": col + 1, "text": text,
            "column_header": header, "row_header": row_header, "row_section": False}


def _table(page, rows, header_rows=1):
    cells = [_cell(r, c, text, header=r < header_rows) for r, row in enumerate(rows) for c, text in enumerate(row) if text]
    return {"prov": [{"page_no": page, "bbox": {"l": 40, "t": 100, "r": 40 + 100 * len(rows[0]), "b": 100 + 20 * len(rows),
                                                 "coord_origin": "TOPLEFT"}}],
            "data": {"table_cells": cells, "num_rows": len(rows), "num_cols": len(rows[0])}}


def _note(page, text):
    return {"label": "caption", "text": text,
            "prov": [{"page_no": page, "bbox": {"l": 40, "t": 80, "r": 500, "b": 96, "coord_origin": "TOPLEFT"}}]}


def _pdf(tmp_path, pages=1, text=None):
    import pymupdf

    path = tmp_path / "report.pdf"
    with pymupdf.open() as pdf:
        for _ in range(pages):
            page = pdf.new_page(width=W, height=H)
            if text:
                page.insert_text((40, 40), text)
        pdf.save(path)
    return path


def _converter(data):
    converter = Mock()
    converter.convert.return_value = SimpleNamespace(status="ConversionStatus.SUCCESS",
                                                     document=SimpleNamespace(export_to_dict=lambda: data))
    return converter


def _cells(result):
    return {e["raw_text"]: e for e in result["evidence_batch"]["evidences"] if e["source_type"] == "table"}


BALANCE = [
    ["TÀI SẢN", "Mã số", "Thuyết minh", "30/09/2025", "01/01/2025"],
    ["1", "2", "3", "4", "5"],
    ["A. TÀI SẢN NGẮN HẠN", "100", "", "1.357.205", "1.198.206"],
    ["I. Tiền", "110", "V.01", "254.318", "198.402"],
    ["1. Vốn góp của chủ sở hữu", "411", "", "800.000", "800.001"],
    ["TỔNG CỘNG TÀI SẢN", "270", "", "2.370.750", "2.203.659"],
]


def test_code_note_and_column_number_cells_are_not_values_and_numbered_rows_keep_their_name(tmp_path):
    # D2-5, D2-6, E2-3, C2-5, C2-6
    data = {"texts": [_note(1, "Đơn vị tính: triệu đồng")], "pictures": [], "tables": [_table(1, BALANCE, header_rows=2)]}
    result = extract_docling_artifact(_pdf(tmp_path, text="Bang can doi"), "v", locale="vi", converter=_converter(data))
    cells = _cells(result)
    assert sorted(cells) == sorted(["1.357.205", "1.198.206", "254.318", "198.402", "800.000", "800.001", "2.370.750", "2.203.659"])
    assert cells["800.000"]["table_locator"]["row_header"] == "1. Vốn góp của chủ sở hữu"
    assert cells["254.318"]["table_locator"]["row_header"] == "I. Tiền"  # not "I. Tiền · V.01"
    assert cells["2.370.750"]["table_locator"]["column_header"] == "30/09/2025"  # not "30/09/2025 · 4"
    assert cells["800.000"]["semantic"]["unit"] == "VND_MILLION"


def test_a_code_column_with_a_garbled_header_is_found_by_its_rising_codes(tmp_path):
    rows = [["Chỉ tiêu", "Ma sé", "Quý 3/2025"], ["Doanh thu", "01", "845.620"], ["Giảm trừ", "02", "12.408"],
            ["Doanh thu thuần", ":10", "833.212"], ["Giá vốn", "1\"", "628.540"], ["Lợi nhuận gộp", "| 20", "204.672"]]
    data = {"texts": [], "pictures": [], "tables": [_table(1, rows)]}
    cells = _cells(extract_docling_artifact(_pdf(tmp_path, text="x"), "v", locale="vi", converter=_converter(data)))
    assert sorted(cells) == ["12.408", "204.672", "628.540", "833.212", "845.620"]


def test_a_table_continued_on_the_next_page_keeps_its_headers_and_unit(tmp_path):
    # D2-10, C2-6: the first row of the second part became its header ("542", "14. Tổng lợi nhuận…").
    first = _table(1, [["Tuyến", "9 tháng 2026", "9 tháng 2025"], ["Hà Nội – TP. HCM", "312,4", "290,1"]])
    second = _table(2, [["Hà Nội – Lào Cai", "54,2", "49,8"], ["Tổng", "1.284,6", "1.185,5"]])
    second["data"]["table_cells"][1]["column_header"] = second["data"]["table_cells"][2]["column_header"] = True
    data = {"texts": [_note(1, "Bảng 2. Sản lượng (đơn vị: nghìn tấn)")], "pictures": [], "tables": [first, second]}
    cells = _cells(extract_docling_artifact(_pdf(tmp_path, pages=2, text="x"), "v", locale="vi", converter=_converter(data)))
    assert cells["54,2"]["numeric_value"] == "54.2"
    assert cells["54,2"]["table_locator"]["row_header"] == "Hà Nội – Lào Cai"
    assert cells["54,2"]["table_locator"]["column_header"] == "9 tháng 2026"
    assert cells["54,2"]["semantic"]["period"]["label"] == "9T/2026"
    assert cells["1.185,5"]["semantic"]["unit"] == "THOUSAND_TONNE"


def test_ratio_rows_take_the_unit_their_label_states(tmp_path):
    rows = [["Chỉ tiêu", "Quý 3/2025"], ["Biên lợi nhuận gộp (%)", "24,6"], ["Hệ số nợ/VCSH (lần)", "0,73"]]
    data = {"texts": [_note(1, "Đơn vị tính: triệu đồng")], "pictures": [], "tables": [_table(1, rows)]}
    cells = _cells(extract_docling_artifact(_pdf(tmp_path, text="x"), "v", locale="vi", converter=_converter(data)))
    assert cells["24,6"]["semantic"]["unit"] == "PERCENT"
    assert cells["0,73"]["semantic"]["unit"] == "TIMES"


# ---------------------------------------------------------------- scans


class _Ocr:
    def __init__(self, words=""):
        self.words = words

    def available(self):
        return True, None

    def read_page(self, _path, page_number):
        tokens = tuple({"text": w, "bbox": [0.05 + 0.01 * i, 0.02, 0.06 + 0.01 * i, 0.04], "confidence": 0.9}
                       for i, w in enumerate(self.words.split()))
        return OcrPage(page_number=page_number, width=W, height=H, tokens=tokens)


def _scan_reading(tmp_path, monkeypatch, data, words="", pages=1):
    monkeypatch.setattr(docling_extraction, "_ocr_converter", lambda: _converter(data))
    return extract_docling_artifact(_pdf(tmp_path, pages=pages), "v", ocr_engine=_Ocr(words))


def test_ocr_decimal_slips_are_unsure_never_sure(tmp_path, monkeypatch):
    # D2-3: each of these was shown as a sure value 10x to 1000x off.
    amounts = [["Chỉ tiêu", "30/09/2025", "9T/2024"], ["A. Tài sản ngắn hạn", "1.357.205", "2.185.430"],
               ["B. Tài sản dài hạn", "1,013.545", "19,774"], ["C. Nợ", "1.000.534", "785"]]
    ratios = [["Chỉ tiêu", "Q3/2025", "Q3/2024"], ["Biên lợi nhuận gộp (%)", "24,6", "22,1"],
              ["Tăng trưởng (%)", "10,7", "54"], ["Hệ số nợ (lần)", "073", "0,78"]]
    customers = [["Khách hàng", "Doanh thu"], ["Khách hàng A", "1094). |"], ["Khách hàng B", "72.6"],
                 ["Khách hàng C", "512"], ["Khách hàng E", "30,1"], ["Cộng", "301,8"]]
    data = {"texts": [], "pictures": [], "tables": [_table(1, amounts), _table(2, ratios), _table(3, customers)]}
    cells = _cells(_scan_reading(tmp_path, monkeypatch, data, pages=3))
    status = {raw: (e["data_status"], e["numeric_value"]) for raw, e in cells.items()}
    for misread in ("1,013.545", "19,774", "54", "073", "1094). |", "512", "72.6"):
        assert status[misread] == ("ambiguous", None), misread
    assert status["1.357.205"] == ("valid", "1357205")
    assert status["785"] == ("valid", "785")  # a whole number among amounts is fine
    assert status["24,6"] == ("valid", "24.6")
    assert status["301,8"] == ("valid", "301.8")


def test_ocr_total_rows_get_their_name_back(tmp_path, monkeypatch):
    # D2-7: "Téng" and "TONG CONG" were never seen as total rows.
    rows = [["Mảng", "Quý 1/2026"], ["Đường bộ", "152.340"], ["‘Téng", "259.115"], ["TONG CONG TAI SAN", "411.455"], ["Cong", "1.000"]]
    data = {"texts": [], "pictures": [], "tables": [_table(1, rows)]}
    cells = _cells(_scan_reading(tmp_path, monkeypatch, data))
    assert cells["259.115"]["table_locator"]["row_header"] == "Tổng"
    assert cells["411.455"]["table_locator"]["row_header"] == "TỔNG CỘNG TAI SAN"
    assert cells["1.000"]["table_locator"]["row_header"] == "Cộng"


def test_ocr_words_in_headings_and_lone_short_numbers_are_not_values(tmp_path, monkeypatch):
    # D2-8
    heading = {"label": "section_header", "text": "BÁO CÁO 9 THÁNG",
               "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 0, "r": W, "b": 0.05 * H, "coord_origin": "TOPLEFT"}}]}
    words = "Trang 7 . Công ty xuất khẩu 6 lô hàng , Nhóm 7, tăng 48,2% đạt 91,5 tỷ đồng"
    data = {"texts": [heading], "pictures": [], "tables": []}
    result = _scan_reading(tmp_path, monkeypatch, data, words=words)
    assert [e["raw_text"] for e in result["evidence_batch"]["evidences"]] == []  # every word sits in the heading box
    data = {"texts": [], "pictures": [], "tables": []}
    result = _scan_reading(tmp_path, monkeypatch, data, words=words)
    assert [e["raw_text"] for e in result["evidence_batch"]["evidences"]] == ["6", "48,2%", "91,5"]


def test_a_scan_with_a_signature_stamp_is_read_by_ocr(tmp_path):
    # D2-2: a scanned page carrying "Digitally signed by…" text was not OCR'd at all.
    import pymupdf

    path = tmp_path / "signed.pdf"
    with pymupdf.open() as pdf:
        image = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 60, 80), False)
        image.clear_with(200)
        for text in ("Digitally signed by CONG TY A", None):
            page = pdf.new_page(width=W, height=H)
            page.insert_image(page.rect, pixmap=image)
            if text:
                page.insert_text((450, 30), text, fontsize=6)
        page = pdf.new_page(width=W, height=H)
        page.insert_image(page.rect, pixmap=image)  # a page-size background under real text is not a scan
        for line in range(40):
            page.insert_text((40, 40 + line * 18), "Doanh thu thuần quý 3 năm 2025 đạt 845.620 triệu đồng, tăng 10,7%.")
        page = pdf.new_page(width=W, height=H)
        page.insert_text((40, 40), "Trang chỉ có chữ")
        pdf.save(path)
    with pymupdf.open(path) as pdf:
        assert scan_pages(pdf) == {1, 2}
    data = {"texts": [], "pictures": [], "tables": []}
    result = extract_docling_artifact(path, "v", locale="vi", converter=_converter(data), ocr_engine=_Ocr("Doanh thu 845.620"))
    numbers = [(e["page_number"], e["raw_text"], e["extraction_method"]) for e in result["evidence_batch"]["evidences"]]
    assert (1, "845.620", "ocr") in numbers and (2, "845.620", "ocr") in numbers
    assert result["pages"][0]["text"] == "Doanh thu 845.620"


def test_scanned_pages_of_a_digital_report_replace_its_reading_of_those_pages():
    digital = {"texts": [{"text": "p1", "prov": [{"page_no": 1}]}, {"text": "stamp", "prov": [{"page_no": 2}]},
                         {"text": "cap", "prov": [{"page_no": 3}]}],
               "tables": [{"prov": [{"page_no": 3}]}, {"prov": [{"page_no": 2}]}],
               "pictures": [{"prov": [{"page_no": 2}]}, {"prov": [{"page_no": 3}], "captions": [{"$ref": "#/texts/2"}]}]}
    scanned = {"texts": [{"text": "ocr", "prov": [{"page_no": 1}]}], "tables": [{"prov": [{"page_no": 1}]}], "pictures": []}
    merged = _merge_scanned(digital, scanned, [2])
    assert [t["text"] for t in merged["texts"]] == ["p1", "cap", "ocr"]
    assert [t["prov"][0]["page_no"] for t in merged["texts"]] == [1, 3, 2]
    assert [t["prov"][0]["page_no"] for t in merged["tables"]] == [2, 3]  # in page order, the page-2 one from OCR
    assert merged["pictures"] == [{"prov": [{"page_no": 3}], "captions": [{"$ref": "#/texts/1"}]}]
