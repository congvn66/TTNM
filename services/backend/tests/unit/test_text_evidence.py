import json
from pathlib import Path
from unittest.mock import Mock

from report_qa.application.document_assistant import run_assistant
from report_qa.application.text_evidence import match_quote, quote_bbox, suggest_quote

PDF = Path(__file__).parents[1] / "fixtures/extraction/report.pdf"
PAGE = (
    "Báo cáo thử nghiệm xu hướng doanh thu. Biểu đồ đường thể hiện biến động của năm khu\n"
    "vực A đến E. Bảng dữ liệu chứa doanh thu, chi phí và tỷ lệ tăng trưởng; mọi con số đều là dữ\n"
    "liệu giả phục vụ đánh giá.\nHình 1. Doanh thu theo khu vực. Đọc năm giá trị A–E.\n"
)


def test_exact_quote_across_line_breaks_returns_document_text():
    match = match_quote(PAGE, "biểu đồ đường thể hiện biến động của năm khu vực A đến E.")
    assert match == {"quote": "Biểu đồ đường thể hiện biến động của năm khu vực A đến E.", "match": "exact"}


def test_dash_and_quote_styles_do_not_break_exact_match():
    match = match_quote(PAGE, "“Đọc năm giá trị A-E.”")
    assert match["quote"] == "Đọc năm giá trị A–E." and match["match"] == "exact"


def test_small_copy_error_snaps_to_the_real_sentence():
    match = match_quote(PAGE, "Biểu đồ đường thể hiện biến động của 5 khu vực A đến E")
    assert match == {"quote": "Biểu đồ đường thể hiện biến động của năm khu vực A đến E.", "match": "snapped"}


def test_paraphrase_or_invented_text_is_rejected_with_a_hint():
    assert match_quote(PAGE, "Lợi nhuận tăng mạnh trong năm 2024") is None
    assert match_quote(PAGE, "Q1") is None
    hint = suggest_quote(PAGE, "mọi số liệu đều là dữ liệu giả để phục vụ cho việc đánh giá")
    assert hint == "mọi con số đều là dữ liệu giả phục vụ đánh giá."


def test_quote_is_located_on_the_pdf_page():
    import pymupdf

    with pymupdf.open(PDF) as pdf:
        line = next(line for line in pdf[0].get_text().splitlines() if len(line.split()) >= 4)
    box = quote_bbox(PDF, 1, line)
    assert box is not None and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1
    assert quote_bbox(PDF, 1, "không có trong tài liệu này") is None
    assert quote_bbox(PDF, 99, line) is None



def test_repeated_quote_box_covers_only_the_first_occurrence(tmp_path):
    import pymupdf

    sentence = "Doanh thu tăng 15 phần trăm trong năm 2024."
    paragraph = "Doanh thu tăng mười lăm phần trăm trong năm hai nghìn không trăm hai mươi bốn ở mọi khu vực"
    path = tmp_path / "repeat.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 80), sentence, fontname="helv")
        page.insert_text((50, 760), sentence, fontname="helv")
        page.insert_textbox(pymupdf.Rect(50, 200, 250, 300), paragraph)
        page.insert_textbox(pymupdf.Rect(50, 500, 250, 600), paragraph)
        pdf.save(path)
    with pymupdf.open(path) as pdf:
        sentence, paragraph = (" ".join(pdf[0].get_textbox(rect).split()) for rect in
                               (pymupdf.Rect(40, 60, 560, 90), pymupdf.Rect(40, 190, 260, 310)))
    line = quote_bbox(path, 1, sentence)
    assert line[3] < 0.15
    box = quote_bbox(path, 1, paragraph)
    assert 0.2 < box[1] < box[3] < 0.45

def context():
    return {
        "pages": [{"page": 1, "text": PAGE}],
        "evidences": [{"evidence_key": "a", "page_number": 1, "numeric_value": "26", "data_status": "valid"}],
        "chart_regions": [],
    }


def sequence(*actions):
    return Mock(side_effect=[json.dumps(a) for a in actions])


def test_explanation_needs_a_verbatim_quote_and_gets_a_hint_on_retry():
    complete = sequence(
        {"action": "answer", "answer": "Số liệu là giả lập.",
         "sources": [{"page": 1, "quote": "mọi số liệu đều là dữ liệu giả để phục vụ cho việc đánh giá"}]},
        {"action": "answer", "answer": "Số liệu là giả lập.",
         "sources": [{"page": 1, "quote": "mọi con số đều là dữ liệu giả phục vụ đánh giá."}]},
    )
    result = run_assistant("Số liệu có thật không?", context(), complete=complete, read_chart=Mock())
    feedback = json.loads(complete.call_args.args[1])["tool_results"][0]
    assert feedback["rejected_sources"][0]["closest_text_on_page"] == "mọi con số đều là dữ liệu giả phục vụ đánh giá."
    assert result["sources"] == [{"page": 1, "quote": "mọi con số đều là dữ liệu giả phục vụ đánh giá.", "match": "exact"}]


def test_bad_extra_quote_is_dropped_when_data_citations_ground_the_answer():
    complete = sequence({
        "action": "answer", "answer": "Vùng B là 26.", "evidence_keys": ["a"],
        "sources": [{"page": 1, "quote": "Vùng B dẫn đầu"}, {"page": 7, "quote": "Hình 1."}],
    })
    result = run_assistant("B?", context(), complete=complete, read_chart=Mock())
    assert result["evidence_keys"] == ["a"] and result["sources"] == []
    assert result["trace"][-1] == {"stage": "citation_validation", "status": "omitted_unsupported_quotes", "count": 2}


def test_flow_returns_located_text_and_data_evidence(tmp_path, monkeypatch):
    from report_qa.api import document_assistant_flow as flow
    from report_qa.api.main import extraction_with_evidence_revisions, snapshot_answer_revision

    repo = Path(__file__).resolve().parents[4]
    base = json.loads((repo / "examples/tien-extraction/output/document.json").read_text())
    path = tmp_path / "base.json"
    path.write_text(json.dumps(base))
    monkeypatch.setattr(flow, "extraction_path", lambda name: path)
    monkeypatch.setattr(flow, "document_path", lambda name: repo / "examples/tien-extraction/report.pdf")
    monkeypatch.setattr(flow, "save_catalog", Mock())
    quote = "Báo cáo thử nghiệm doanh thu năm 2024."
    key = base["evidence_batch"]["evidences"][0]["evidence_key"]
    session = {"messages": []}
    message = flow.answer_document(
        session, {"id": "doc", "extraction_name": "x", "storage_name": "x"}, "?", "trace", [], {"sessions": {}},
        overlay=extraction_with_evidence_revisions, snapshot=snapshot_answer_revision,
        complete=sequence({"action": "answer", "answer": "Báo cáo doanh thu 2024; Q1 là 1250.50.",
                           "evidence_keys": [key], "sources": [{"page": 1, "quote": quote}]}),
    )["assistant_message"]
    text, data = message["structured_answer"]["evidence"]
    assert text["kind"] == "text" and text["quote"] == quote and text["bbox"] is not None
    assert data["kind"] == "data" and data["label"] == "Q1 · Doanh thu" and data["value"] == "1250.50"
    assert message["citations"] == message["structured_answer"]["evidence"]
