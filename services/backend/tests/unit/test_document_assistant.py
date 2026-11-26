import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from report_qa.application.document_assistant import AssistantError, run_assistant

REPO = Path(__file__).resolve().parents[4]


def evidences():
    return [
        {
            "evidence_key": "a",
            "page_number": 1,
            "numeric_value": "100",
            "raw_text": "100",
            "data_status": "valid",
            "table_locator": {"row_header": "Q1", "column_header": "Doanh thu"},
        },
        {
            "evidence_key": "b",
            "page_number": 1,
            "numeric_value": "130",
            "raw_text": "120",
            "data_status": "valid",
            "table_locator": {"row_header": "Q2", "column_header": "Doanh thu"},
        },
    ]


def context():
    return {
        "pages": [{"page": 1, "text": "Revenue excludes tax."}],
        "evidences": evidences(),
        "chart_regions": [{"chart_region_key": "chart-1", "read": False}],
    }


def sequence(*actions):
    return Mock(side_effect=[a if isinstance(a, str) else json.dumps(a) for a in actions])


def test_ai_receives_full_text_and_labelled_current_values():
    complete = sequence({"action": "answer", "answer": "Q2 là 130.", "evidence_keys": ["b"]})
    result = run_assistant("Q2?", context(), complete=complete, read_chart=Mock())
    sent = json.loads(complete.call_args.args[1])["document"]
    assert sent["pages"][0]["text"] == "Revenue excludes tax."
    assert sent["data"][1] == {
        "key": "b", "page": 1, "source": None, "label": "Q2 · Doanh thu",
        "value": "130", "raw": "120", "unit": None, "status": "valid",
    }
    assert sent["chart_regions"] == [{"chart_region_key": "chart-1", "read": False}]
    assert result["evidence_keys"] == ["b"]


def test_text_numbers_get_readable_labels():
    from report_qa.application.document_assistant import evidence_label

    row = {"evidence_key": "k", "semantic": {"subject": None, "measure": "unknown",
                                             "period": {"label": "2023", "granularity": "year"}}}
    assert evidence_label(row) == "2023"
    assert evidence_label({"evidence_key": "k", "semantic": {"measure": "unknown"}}) == "k"


def test_pages_are_checked_but_are_not_a_citation_on_their_own():
    complete = sequence(
        {"action": "answer", "answer": "Chưa gồm thuế.", "pages": [9]},
        {"action": "answer", "answer": "Chưa gồm thuế.", "pages": [1]},
        {"action": "answer", "answer": "Chưa gồm thuế.", "pages": [1],
         "sources": [{"page": 1, "quote": "Revenue excludes tax."}]},
    )
    result = run_assistant("Thuế?", context(), complete=complete, read_chart=Mock())
    assert result["pages"] == [1] and result["sources"][0]["quote"] == "Revenue excludes tax."
    errors = [t["error"] for t in json.loads(complete.call_args.args[1])["tool_results"]]
    assert "pages must be" in errors[0] and "pages alone are not a citation" in errors[1]


def test_a_number_no_source_contains_is_sent_back_with_the_list():
    # The data says 100; the answer used to be accepted with any number in it.
    complete = sequence(
        {"action": "answer", "answer": "Doanh thu Q1 là 9.999 tỷ, gấp 3 lần.", "evidence_keys": ["a"]},
        {"action": "answer", "answer": "Doanh thu Q1 là 100.", "evidence_keys": ["a"]},
    )
    result = run_assistant("Doanh thu Q1?", context(), complete=complete, read_chart=Mock())
    assert result["answer"] == "Doanh thu Q1 là 100."
    rejected = json.loads(complete.call_args.args[1])["tool_results"][0]
    assert rejected["untraced_numbers"] == ["9.999 tỷ", "3"]


@pytest.mark.parametrize("answer", [
    "Tăng trưởng 17,05% so với 2025.",  # rounded vi percent of a python fraction, year from the question
    "Tăng trưởng 17.1%.",  # en separator, one decimal
    "Q2 là 1.250,5 nghìn đồng, chiếm 30% (trích 'chiếm 30%').",  # value with scale word, quote number
    "Q2/2026 Miền Bắc đạt 1250500 đồng.",  # a period label and the raw value
])
def test_numbers_traced_to_results_rows_quotes_and_question_are_accepted(answer):
    from report_qa.application.document_assistant import untraced_numbers

    row = {"evidence_key": "k", "numeric_value": "1250500", "raw_text": "1.250.500", "semantic": {"unit": "VND"},
           "table_locator": {"row_header": "Miền Bắc", "column_header": "Q2/2026"}}
    assert untraced_numbers(answer, evidences=[row],
                            quotes=[{"page": 1, "quote": "Miền Nam chiếm 30% doanh thu."}], results=[{"value": "0.170547", "typed": [], "keys": []}]) == []


@pytest.mark.parametrize("answer", [
    "Doanh thu là 10 tỷ đồng (trang 5).",  # a reference to a cited page
    "Theo trang 5, doanh thu là 10 tỷ đồng.",
    "Tính đến 31/12/2023, doanh thu là 10.",  # a date
    "Trong Q3 và H1, 6T/2026, doanh thu là 10.",  # period labels glued to letters
    "Doanh thu tháng 3/2026 và tháng 6 là 10.",  # months
    "Năm 2019 và 2025 doanh thu là 10.",  # years written only in the pages
    "Trong 6 tháng đầu năm 2026, có 4 quý, trung bình 3 năm là 10.",  # durations
])
def test_honest_non_quantities_are_not_checked(answer):
    # Each of these was rejected: page refs, dates, period labels and counts were read as quantities.
    from report_qa.application.document_assistant import untraced_numbers

    row = {"evidence_key": "k", "numeric_value": "10", "raw_text": "10", "page_number": 5, "semantic": {"unit": "VND_BILLION"}}
    assert untraced_numbers(answer, evidences=[row], quotes=[], results=[], cited_pages={5}) == []


def test_digits_inside_labels_and_uncited_page_refs_are_not_sources():
    from report_qa.application.document_assistant import untraced_numbers

    row = {"evidence_key": "k", "numeric_value": "10", "raw_text": "10", "page_number": 5,
           "table_locator": {"row_header": "Doanh thu", "column_header": "Q4/2024"}}
    assert untraced_numbers("Q4/2024 là 4 tỷ.", evidences=[row], quotes=[], results=[],
                            cited_pages={5}) == ["4 tỷ"]
    assert untraced_numbers("Doanh thu là 10 (trang 7).", evidences=[row], quotes=[], results=[],
                            cited_pages={5}) == ["7"]


@pytest.mark.parametrize("locale", ["vi", None])
def test_answer_numbers_are_read_as_their_vietnamese_reader_reads_them(locale):
    # "1.250 tỷ" passed for 1.25 because the en reading of the answer was tried too.
    from report_qa.application.document_assistant import untraced_numbers

    small = {"evidence_key": "s", "numeric_value": "1.25", "raw_text": "1,25", "semantic": {"unit": "VND_BILLION"}}
    large = {"evidence_key": "l", "numeric_value": "1250", "raw_text": "1.250", "semantic": {"unit": "VND_BILLION"}}

    def check(answer, row, quotes=()):
        return untraced_numbers(answer, evidences=[row] if row else [], results=[],
                                quotes=[{"page": 1, "quote": quote} for quote in quotes],
                                locale=locale)

    assert check("Doanh thu là 1.250 tỷ đồng.", small) == ["1.250 tỷ"]
    assert check("Doanh thu là 1,250 tỷ đồng.", large) == ["1,250 tỷ"]
    assert check("Doanh thu là 1,25 tỷ đồng.", small) == []
    assert check("Doanh thu là 1.250 tỷ đồng.", large) == []
    assert check("Doanh thu là 1.250 tỷ đồng.", None, ["Doanh thu đạt 1,25 tỷ đồng."]) == ["1.250 tỷ"]


def test_quotes_are_read_in_the_document_format_and_answers_as_vietnamese():
    from report_qa.application.document_assistant import untraced_numbers

    quote = [{"page": 1, "quote": "Revenue was 2.011 in Q2."}]  # an English-format PDF: 2.011 is two and a bit
    check = lambda answer, **kw: untraced_numbers(answer, evidences=[], quotes=quote, results=[], locale="en", **kw)
    assert check("Doanh thu Q2 là 2,011.") == []
    assert check("Doanh thu Q2 là 2.011.") == ["2.011"]  # a Vietnamese reader reads two thousand and eleven
    result = [{"value": "1250", "typed": [], "keys": []}]
    assert untraced_numbers("Tổng là 1.250 và 1,250.50.", evidences=[], quotes=[], results=result + [
        {"value": "1250.5", "typed": [], "keys": []}], locale="en") == []
    assert untraced_numbers("Tổng là 1,250.", evidences=[], quotes=[], results=result, locale="en") == ["1,250"]
    assert untraced_numbers("Tăng 17.1%.", evidences=[], quotes=[], results=[{"value": "17.1", "typed": [], "keys": []}]) == []


def test_a_corrected_number_does_not_trace_through_its_printed_text_or_a_quote_of_its_page():
    # The row was corrected 1250 -> 1350; the old PDF number used to trace through raw_text and quotes.
    from report_qa.application.document_assistant import untraced_numbers

    row = {"evidence_key": "k", "page_number": 1, "numeric_value": "1350", "raw_text": "1.250", "semantic": {"unit": "VND_BILLION"}}
    quote = [{"page": 1, "quote": "Doanh thu năm 2023 đạt 1.250 tỷ đồng."}]
    other_page = [{"page": 2, "quote": "Chi phí năm 2023 là 1.250 tỷ đồng."}]
    check = lambda answer, quotes: untraced_numbers(answer, evidences=[row], quotes=quotes, results=[],
                                                    rows=[row], locale="vi")
    assert check("Doanh thu 2023 là 1.250 tỷ đồng.", []) == ["1.250 tỷ"]
    assert check("Doanh thu 2023 là 1.250 tỷ đồng.", quote) == ["1.250 tỷ"]
    assert check("Doanh thu 2023 là 1.350 tỷ đồng.", quote) == []
    assert check("Chi phí 2023 là 1.250 tỷ đồng.", other_page) == []
    unread = {"evidence_key": "u", "page_number": 1, "numeric_value": None, "raw_text": "42.03", "data_status": "ambiguous",
              "source_type": "chart", "semantic": {"unit": "PERCENT"}}
    assert untraced_numbers("Khoảng 42,03%.", evidences=[unread], quotes=[], results=[], locale="vi") == []


def test_the_question_is_not_a_source_of_quantities():
    # "có đạt 500 tỷ không?" let "đạt 500 tỷ" pass; a leading question let its premise through.
    complete = sequence(
        {"action": "answer", "answer": "Đúng, doanh thu Q1 là 5.000 tỷ.", "evidence_keys": ["a"]},
        {"action": "answer", "answer": "Không, doanh thu Q1 là 100.", "evidence_keys": ["a"]},
    )
    result = run_assistant("Có phải doanh thu Q1 là 5.000 tỷ không?", context(), complete=complete, read_chart=Mock())
    assert result["answer"] == "Không, doanh thu Q1 là 100."
    assert json.loads(complete.call_args.args[1])["tool_results"][0]["untraced_numbers"] == ["5.000 tỷ"]


@pytest.mark.parametrize(("answer", "result", "untraced"), [
    ("Doanh thu giảm 5%.", "0.05", ["5%"]),
    ("Doanh thu tăng 3,2%.", "-3.2", ["3,2%"]),
    ("Doanh thu giảm 3,2%.", "-3.2", []),
    ("Doanh thu tăng 17,05%.", "0.1705", []),
    ("Chênh lệch là 3,2%.", "-3.2", []),  # no direction word: the magnitude is enough
    ("Doanh thu tăng trưởng 3,2%.", "-3.2", ["3,2%"]),
])
def test_a_direction_word_must_agree_with_the_sign_of_a_python_result(answer, result, untraced):
    from report_qa.application.document_assistant import untraced_numbers

    assert untraced_numbers(answer, evidences=[], quotes=[], results=[{"value": result, "typed": [], "keys": []}], locale="vi") == untraced


def test_a_negative_data_value_is_signed_but_a_positive_one_is_not():
    from report_qa.application.document_assistant import untraced_numbers

    falling = {"evidence_key": "f", "numeric_value": "-3.2", "raw_text": "-3,2%", "semantic": {"unit": "PERCENT"}}
    rate = {"evidence_key": "r", "numeric_value": "5", "raw_text": "5%", "semantic": {"unit": "PERCENT"}}
    assert untraced_numbers("Biên lợi nhuận tăng 3,2%.", evidences=[falling], quotes=[], results=[], locale="vi") == ["3,2%"]
    assert untraced_numbers("Doanh thu giảm 5%.", evidences=[rate], quotes=[], results=[], locale="vi") == []


def test_a_result_built_with_an_uncited_typed_number_traces_nothing():
    # value('a') - value('a') + 987654 only warned in the summary; the answer check accepted 987654.
    complete = sequence(
        {"action": "python", "code": "result = value('a') - value('a') + 987654"},
        {"action": "answer", "answer": "Doanh thu là 987.654.", "evidence_keys": ["a"]},
        {"action": "python", "code": "result = value('a') * Decimal('0.3') + value('a')"},
        {"action": "answer", "answer": "Q1 cộng thêm 30% là 130.", "evidence_keys": ["a"],
         "sources": [{"page": 1, "quote": "Miền Nam chiếm 30% doanh thu."}]},
    )
    ctx = {**context(), "pages": [{"page": 1, "text": "Miền Nam chiếm 30% doanh thu."}], "number_locale": "vi"}
    result = run_assistant("Doanh thu?", ctx, complete=complete, read_chart=Mock())
    assert result["answer"] == "Q1 cộng thêm 30% là 130."  # 0.3 is cited by the quote, so its result is a source
    assert json.loads(complete.call_args.args[1])["tool_results"][1]["untraced_numbers"] == ["987.654"]


@pytest.mark.parametrize(("answer", "untraced"), [
    ("Doanh thu là 1.250,5 tỷ đồng.", []),
    ("Doanh thu là 1.250.500 triệu đồng.", []),
    ("Doanh thu là 1.250,5.", []),  # no scale word: the number as printed
    ("Doanh thu là 1.250,5 triệu đồng.", ["1.250,5 triệu"]),  # used to pass: a factor of 1 was always tried
    ("Doanh thu là 1.250,5%.", ["1.250,5%"]),
])
def test_a_scale_word_must_match_the_unit_of_the_source(answer, untraced):
    from report_qa.application.document_assistant import untraced_numbers

    row = {"evidence_key": "k", "numeric_value": "1250.5", "raw_text": "1.250,5", "semantic": {"unit": "VND_BILLION"}}
    assert untraced_numbers(answer, evidences=[row], quotes=[], results=[], locale="vi") == untraced


def test_quote_numbers_carry_their_own_scale_word():
    from report_qa.application.document_assistant import untraced_numbers

    quote = [{"page": 1, "quote": "Mục tiêu doanh thu là 220 tỷ đồng."}]
    check = lambda answer: untraced_numbers(answer, evidences=[], quotes=quote, results=[], locale="vi")
    assert check("Mục tiêu là 220 tỷ đồng, tức 220.000 triệu đồng.") == []
    assert check("Mục tiêu là 220 triệu đồng.") == ["220 triệu"]


@pytest.mark.parametrize(("answer", "untraced"), [
    ("Khoảng 3.460 tỷ đồng.", []),  # rounded at the third significant digit
    ("Khoảng 3.457 tỷ đồng.", []),
    ("Khoảng 3.500 tỷ đồng.", []),
    ("Hơn 3.000 tỷ đồng.", []),
    ("Khoảng 3.450 tỷ đồng.", ["3.450 tỷ"]),
])
def test_a_whole_number_may_be_rounded_at_its_last_significant_digit(answer, untraced):
    from report_qa.application.document_assistant import untraced_numbers

    row = {"evidence_key": "k", "numeric_value": "3456.78", "raw_text": "3.456,78", "semantic": {"unit": "VND_BILLION"}}
    assert untraced_numbers(answer, evidences=[row], quotes=[], results=[], locale="vi") == untraced


def test_a_number_word_states_an_amount_that_the_source_must_have():
    # "1.250,5 triệu, tức 1.250,5 tỷ" passed for a row of no stated unit.
    from report_qa.application.document_assistant import untraced_numbers

    row = {"evidence_key": "k", "numeric_value": "1250.50", "raw_text": "1,250.50"}
    answer = "Doanh thu là 1.250,50; 1.250,5 triệu, tức 1.250,5 tỷ."
    assert untraced_numbers(answer, evidences=[row], quotes=[], results=[], locale="en") == ["1.250,5 triệu", "1.250,5 tỷ"]
    assert untraced_numbers("Khoảng 1 nghìn, 1,25 nghìn.", evidences=[row], quotes=[], results=[], locale="en") == []
    small = {"evidence_key": "c", "numeric_value": "12", "raw_text": "12"}
    assert untraced_numbers("Có 10 cửa hàng.", evidences=[small], quotes=[], results=[]) == ["10"]  # small numbers are exact
    total = [{"value": "2500", "typed": [], "keys": ["m", "n"]}]  # a sum of two rows in triệu đồng stays in triệu đồng
    rows = [{"evidence_key": k, "numeric_value": "1250", "semantic": {"unit": "VND_MILLION"}} for k in "mn"]
    assert untraced_numbers("Tổng 2.500 triệu đồng, tức 2,5 tỷ.", evidences=[], quotes=[], results=total, rows=rows) == []


def test_a_number_from_an_uncited_row_is_not_traced():
    from report_qa.application.document_assistant import untraced_numbers

    assert untraced_numbers("Q2 là 130.", evidences=[], quotes=[], results=[]) == ["130"]


def test_ungrounded_answer_is_retried_unless_not_found():
    complete = sequence(
        {"action": "answer", "answer": "Lợi nhuận là 5."},
        {"action": "answer", "answer": "Tài liệu không có lợi nhuận.", "not_found": True},
    )
    result = run_assistant("Lợi nhuận?", context(), complete=complete, read_chart=Mock())
    assert result["not_found"] is True
    assert complete.call_count == 2


def test_invented_evidence_key_and_non_json_are_retried():
    complete = sequence(
        "not json",
        {"action": "answer", "answer": "Q1 là 100.", "evidence_keys": ["invented"]},
        {"action": "answer", "answer": "Q1 là 100.", "evidence_keys": ["a"]},
    )
    result = run_assistant("Q1?", context(), complete=complete, read_chart=Mock())
    assert result["evidence_keys"] == ["a"]
    errors = [t["error"] for t in json.loads(complete.call_args.args[1])["tool_results"]]
    assert errors[0] == "Return exactly one JSON object"
    assert "do not invent keys" in errors[1]


def test_chart_is_read_only_when_ai_calls_the_tool_and_rows_become_data():
    chart_row = {
        "evidence_key": "chart-b", "page_number": 1, "numeric_value": "26", "raw_text": "26",
        "data_status": "valid", "chart_read": {"category_label": "B", "series_label": "Revenue"},
    }
    complete = sequence(
        {"action": "read_chart", "chart_region_key": "chart-1"},
        {"action": "read_chart", "chart_region_key": "chart-1"},
        {"action": "answer", "answer": "Vùng B là 26.", "evidence_keys": ["chart-b"]},
    )
    read = Mock(return_value={
        "status": "completed", "evidences": [chart_row], "warnings": [],
        "all_evidences": [*evidences(), chart_row],
    })
    result = run_assistant("Vùng B?", context(), complete=complete, read_chart=read)
    read.assert_called_once_with("chart-1")
    final = json.loads(complete.call_args.args[1])
    assert final["tool_results"][0]["rows"][0]["label"] == "B · Revenue"
    assert "already read" in final["tool_results"][1]["error"]
    assert final["document"]["chart_regions"][0]["read"] is True
    assert result["evidence_keys"] == ["chart-b"]


def test_unknown_chart_cannot_be_read():
    complete = sequence(
        {"action": "read_chart", "chart_region_key": "invented"},
        {"action": "answer", "answer": "Không có dữ liệu.", "not_found": True},
    )
    read = Mock()
    run_assistant("Missing?", context(), complete=complete, read_chart=read)
    read.assert_not_called()


def test_unverified_chart_value_is_flagged():
    ctx = context()
    ctx["evidences"][0]["data_status"] = "ambiguous"
    complete = sequence({"action": "answer", "answer": "Khoảng 100 (chưa xác minh).", "evidence_keys": ["a"]})
    result = run_assistant("Q1?", ctx, complete=complete, read_chart=Mock())
    assert result["unverified_keys"] == ["a"]


def test_step_limit_raises_with_tool_feedback():
    complete = Mock(return_value=json.dumps({"action": "guess"}))
    with pytest.raises(AssistantError) as error:
        run_assistant("?", context(), complete=complete, read_chart=Mock(), max_steps=2)
    assert len(error.value.tool_results) == 2


def test_chart_batch_is_persisted_and_current_revision_is_exposed(tmp_path, monkeypatch):
    from report_qa.api import document_assistant_flow as flow
    from report_qa.api.main import extraction_with_evidence_revisions, snapshot_answer_revision

    base = json.loads((REPO / "examples/tien-extraction/output/document.json").read_text())
    path = tmp_path / "base.json"
    path.write_text(json.dumps(base))
    monkeypatch.setattr(flow, "extraction_path", lambda name: path)
    save = Mock()
    monkeypatch.setattr(flow, "save_catalog", save)
    chart = copy.deepcopy(base["evidence_batch"]["evidences"][0])
    region = base["chart_regions"][0]["chart_region_key"]
    chart.update(
        evidence_key="chart-b", source_region_key=region, source_type="chart", numeric_value="26",
        raw_text="26", extraction_method="direct_label", method_label="đọc từ nhãn", table_locator=None,
        chart_read={
            "chart_region_key": region, "series_label": "Revenue", "category_label": "B", "axis_label": None,
            "axis_unit": None, "lower_tick": None, "upper_tick": None, "assumptions": ["test"],
        },
    )
    batch = {
        **base["evidence_batch"], "scope": "on_demand_chart",
        "trigger": {"question_plan_id": "q", "fact_keys": ["b"], "chart_region_keys": [region]},
        "evidences": [chart],
    }
    read = Mock(return_value={"status": "completed", "evidence_batch": batch, "raw_output": "B | 26"})
    monkeypatch.setattr(flow, "read_chart_region", read)
    doc = {"id": "doc", "extraction_name": "base.json", "storage_name": "source.pdf"}
    session = {"messages": []}
    catalog = {"sessions": {"test": session}}

    def ask(*actions):
        return flow.answer_document(
            session, doc, "B?", "trace", [], catalog,
            overlay=extraction_with_evidence_revisions, snapshot=snapshot_answer_revision,
            complete=sequence(*actions),
        )["assistant_message"]

    message = ask(
        {"action": "read_chart", "chart_region_key": region},
        {"action": "answer", "answer": "Vùng B là 26.", "evidence_keys": ["chart-b"]},
    )
    assert len(doc["chart_extractions"]) == 1
    assert message["answer_inputs"][0]["value"] == "26"
    assert message["citations"][0]["label"] == "B · Revenue"
    assert len(flow.with_chart_batches(doc, base)["evidence_batch"]["evidences"]) == 13

    state = doc["evidence_state"]["items"]["chart-b"]
    state["revisions"].append({"id": "edited", "action": "edit", "numeric_value": "30"})
    message = ask({"action": "answer", "answer": "Vùng B đã sửa là 30.", "evidence_keys": ["chart-b"]})
    assert message["answer_inputs"][0]["value"] == "30"
    assert state["original_numeric_value"] == "26"
    read.assert_called_once()
    assert save.call_count >= 3


def test_chart_read_with_a_failed_visual_check_is_retried_on_the_next_question(tmp_path, monkeypatch):
    # A provider 503 during the visual check used to be cached, leaving every
    # value of that chart unverified for all later questions.
    from report_qa.api import document_assistant_flow as flow
    from report_qa.api.main import extraction_with_evidence_revisions, snapshot_answer_revision

    base = json.loads((REPO / "examples/tien-extraction/output/document.json").read_text())
    path = tmp_path / "base.json"
    path.write_text(json.dumps(base))
    monkeypatch.setattr(flow, "extraction_path", lambda name: path)
    monkeypatch.setattr(flow, "save_catalog", Mock())
    region = base["chart_regions"][0]["chart_region_key"]
    empty_batch = {**base["evidence_batch"], "scope": "on_demand_chart", "evidences": [], "warnings": [],
                   "trigger": {"question_plan_id": "q", "fact_keys": ["b"], "chart_region_keys": [region]}}
    read = Mock(side_effect=[
        {"status": "completed", "evidence_batch": empty_batch, "raw_output": "B | 26", "visual_check_error": "HTTP 503"},
        {"status": "completed", "evidence_batch": empty_batch, "raw_output": "B | 26", "visual_check_error": None},
    ])
    monkeypatch.setattr(flow, "read_chart_region", read)
    doc = {"id": "doc", "extraction_name": "base.json", "storage_name": "source.pdf"}
    session = {"messages": []}

    def ask():
        flow.answer_document(
            session, doc, "B?", "trace", [], {"sessions": {"test": session}},
            overlay=extraction_with_evidence_revisions, snapshot=snapshot_answer_revision,
            complete=sequence({"action": "read_chart", "chart_region_key": region},
                              {"action": "answer", "answer": "Không đọc được.", "not_found": True}),
        )

    ask()
    ask()
    ask()  # third question reuses the successful read
    assert read.call_count == 2


def test_value_withheld_by_a_failed_check_is_filled_in_when_the_chart_is_read_again(tmp_path, monkeypatch):
    # The first read stored the key with no value; the verified re-read used
    # the same key, but the empty first value stayed current forever.
    from report_qa.api import document_assistant_flow as flow
    from report_qa.api.main import extraction_with_evidence_revisions, snapshot_answer_revision

    base = json.loads((REPO / "examples/tien-extraction/output/document.json").read_text())
    path = tmp_path / "base.json"
    path.write_text(json.dumps(base))
    monkeypatch.setattr(flow, "extraction_path", lambda name: path)
    monkeypatch.setattr(flow, "save_catalog", Mock())
    region = base["chart_regions"][0]["chart_region_key"]

    def batch(value, status):
        chart = copy.deepcopy(base["evidence_batch"]["evidences"][0])
        chart.update(
            evidence_key="chart-e", source_region_key=region, source_type="chart", numeric_value=value, raw_text="77",
            data_status=status, extraction_method="direct_label", method_label="đọc từ nhãn", table_locator=None,
            chart_read={"chart_region_key": region, "series_label": "Revenue", "category_label": "E", "axis_label": None,
                        "axis_unit": None, "lower_tick": None, "upper_tick": None, "assumptions": ["test"]},
        )
        return {**base["evidence_batch"], "scope": "on_demand_chart", "evidences": [chart], "warnings": [],
                "trigger": {"question_plan_id": "q", "fact_keys": ["e"], "chart_region_keys": [region]}}

    read = Mock(side_effect=[
        {"status": "completed", "evidence_batch": batch(None, "ambiguous"), "raw_output": "E | 77", "visual_check_error": "HTTP 503"},
        {"status": "completed", "evidence_batch": batch("77", "valid"), "raw_output": "E | 77", "visual_check_error": None},
    ])
    monkeypatch.setattr(flow, "read_chart_region", read)
    doc = {"id": "doc", "extraction_name": "base.json", "storage_name": "source.pdf"}
    session = {"messages": []}

    def ask(*actions):
        return flow.answer_document(
            session, doc, "E?", "trace", [], {"sessions": {"test": session}},
            overlay=extraction_with_evidence_revisions, snapshot=snapshot_answer_revision, complete=sequence(*actions),
        )["assistant_message"]

    ask({"action": "read_chart", "chart_region_key": region}, {"action": "answer", "answer": "Chưa xác minh.", "not_found": True})
    message = ask(
        {"action": "read_chart", "chart_region_key": region},
        {"action": "python", "code": "result = value('chart-e')"},
        {"action": "answer", "answer": "Vùng E là 77.", "evidence_keys": ["chart-e"]},
    )

    assert message["tool_calculations"][0]["result"]["result"] == "77"
    revisions = doc["evidence_state"]["items"]["chart-e"]["revisions"]
    assert [(r["action"], r["numeric_value"]) for r in revisions] == [("initialize", None), ("reread", "77")]


def test_history_skips_a_queued_question_and_its_placeholder():
    from report_qa.api.document_assistant_flow import _history

    session = {"messages": [
        {"role": "user", "document_id": "d", "body": "q1"},
        {"role": "assistant", "document_id": "d", "body": "a1", "status": "completed"},
        {"role": "user", "document_id": "other", "body": "q2"},
        {"role": "assistant", "document_id": "other", "body": "a2"},
        {"role": "user", "document_id": "d", "body": "q3", "status": "accepted"},
        {"role": "assistant", "document_id": "d", "body": "Đang tạo câu trả lời…", "status": "processing", "mode": "answer_question_job"},
    ]}
    assert [turn["text"] for turn in _history(session, "d")] == ["q1", "a1"]


def test_an_over_long_answer_is_sent_back_to_the_model():
    complete = sequence(
        {"action": "answer", "answer": "x" * 12001, "evidence_keys": ["b"]},
        {"action": "answer", "answer": "Q2 là 130.", "evidence_keys": ["b"]},
    )
    result = run_assistant("Q2?", context(), complete=complete, read_chart=Mock())
    assert result["answer"] == "Q2 là 130."
    assert "12000" in result["tool_results"][0]["error"]


def test_each_history_turn_is_bounded():
    from report_qa.api.document_assistant_flow import _history

    session = {"messages": [{"role": "user", "document_id": "d", "body": "q"}, {"role": "assistant", "document_id": "d", "body": "a" * 1_000_000}]}
    turns = _history(session, "d")
    assert turns[0]["text"] == "q" and len(turns[1]["text"]) <= 12001


@pytest.mark.parametrize("check_error", [None, "HTTP 503"])
def test_durable_storage_keeps_only_chart_reads_whose_check_passed(monkeypatch, check_error):
    from report_qa.api import document_assistant_flow as flow
    from report_qa.api.main import extraction_with_evidence_revisions, snapshot_answer_revision

    region = {"chart_region_key": "r1", "page_number": 1, "bbox": [0.1, 0.1, 0.9, 0.9], "text": ""}
    value = {
        "evidence_key": "chart-a", "source_region_key": "r1", "source_type": "chart", "page_number": 1, "bbox": [0.1, 0.1, 0.9, 0.9],
        "raw_text": "50", "numeric_value": None if check_error else "50", "data_status": "ambiguous" if check_error else "valid",
        "method_label": "đọc từ nhãn", "semantic": {"subject": "A"}, "chart_read": {"category_label": "A"},
    }
    monkeypatch.setattr(flow, "validate_extraction_batch", lambda batch: None)
    monkeypatch.setattr(flow, "quote_bbox", lambda *args: None)
    read = Mock(return_value={"status": "completed", "evidence_batch": {"evidences": [value], "warnings": []}, "visual_check_error": check_error})
    monkeypatch.setattr(flow, "read_chart_region", read)
    actions = iter([
        {"action": "read_chart", "chart_region_key": "r1"},
        {"action": "answer", "answer": "A", "evidence_keys": ["chart-a"], "sources": [{"page": 1, "quote": "Doanh thu theo vùng"}]},
    ])
    persist, save = Mock(), Mock()
    result = flow.answer_document(
        {"messages": []}, {"id": "d", "version_id": "v", "storage_name": "d.pdf", "extraction_name": "d.json"}, "A?", "t", [], {},
        overlay=extraction_with_evidence_revisions, snapshot=snapshot_answer_revision, complete=lambda *args, **kwargs: json.dumps(next(actions)),
        load_extraction=lambda name: {"pages": [{"page": 1, "text": "Doanh thu theo vùng"}], "evidence_batch": {"evidences": []}, "chart_regions": [region]},
        resolve_pdf=lambda name: Path(name), save=save, persist_chart=persist,
    )
    assert read.call_args.args[2] == "v"
    assert persist.called is (check_error is None)
    revision = result["assistant_message"]["answer_inputs"][0]["evidence_revision_id"]
    assert (revision is None) is (check_error is not None)
    assert save.call_count == 1


@pytest.mark.parametrize("bad", [
    {"action": ["answer"]},
    {"action": "read_chart", "chart_region_key": ["r1"]},
    {"action": "answer", "answer": "x", "evidence_keys": [{"key": "a"}]},
    {"action": "answer", "answer": "x", "pages": [[1]]},
    {"action": "answer", "answer": "x", "pages": [True]},
    {"action": "answer", "answer": "x", "sources": [{"page": [1], "quote": "Doanh thu theo vùng"}]},
])
def test_badly_typed_model_output_is_retried_not_raised(bad):
    good = {"action": "answer", "answer": "ok", "sources": [{"page": 1, "quote": "Doanh thu theo vùng"}]}
    actions = iter([bad, good])
    context = {"pages": [{"page": 1, "text": "Doanh thu theo vùng"}], "evidences": [], "chart_regions": []}
    result = run_assistant("q", context, complete=lambda *args: json.dumps(next(actions)), read_chart=Mock())
    assert result["answer"] == "ok"


@pytest.mark.parametrize("options, expected", [(3, []), ("a", []), (["A", 1, " ", "B"], ["A", "B"])])
def test_clarify_options_keep_only_text(options, expected):
    context = {"pages": [], "evidences": [], "chart_regions": []}
    action = {"action": "clarify", "answer": "Kỳ nào?", "options": options}
    assert run_assistant("q", context, complete=lambda *args: json.dumps(action), read_chart=Mock())["options"] == expected


def test_an_unexpected_chart_error_is_reported_to_the_model():
    actions = iter([
        {"action": "read_chart", "chart_region_key": "r1"},
        {"action": "answer", "answer": "Chưa đọc được biểu đồ", "not_found": True},
    ])
    context = {"pages": [], "evidences": [], "chart_regions": [{"chart_region_key": "r1", "read": False}]}
    result = run_assistant("q", context, complete=lambda *args: json.dumps(next(actions)), read_chart=Mock(side_effect=KeyError("x" * 900)))
    assert result["tool_results"][0]["error"].startswith("KeyError") and len(result["tool_results"][0]["error"]) <= 300
    assert result["tool_results"][0]["status"] == "failed"
    assert "không kết luận tài liệu không có thông tin" in result["tool_results"][0]["message"]


def test_a_quote_without_pymupdf_keeps_its_text_and_loses_only_the_highlight(monkeypatch):
    import sys
    from report_qa.api.document_assistant_flow import _quote_citation

    monkeypatch.setitem(sys.modules, "pymupdf", None)
    citation = _quote_citation("missing.pdf", {"page": 1, "quote": "abc", "match": "exact"})
    assert citation["quote"] == "abc" and citation["bbox"] is None


def test_a_database_error_while_saving_a_chart_shows_no_database_details(monkeypatch):
    from report_qa.api import main

    class Store:
        def persist_on_demand_chart(self, **kwargs):
            raise OSError("password=secret host=db")

    monkeypatch.setattr(main, "_runtime_for_owner", lambda owner: Store())
    identifier = "00000000-0000-0000-0000-0000000000aa"
    with pytest.raises(RuntimeError) as error:
        main._persist_chart_read({"id": identifier}, {"id": identifier}, {"evidence_batch": {"trigger": {"question_plan_id": "q"}}}, "r1")
    assert str(error.value) == "CHART_EVIDENCE_PERSISTENCE_FAILED"


def _tools_answer(evidence_rows, *actions):
    from report_qa.api import document_assistant_flow as flow

    extraction = {"pages": [{"page": 1, "text": "Revenue excludes tax."}], "evidence_batch": {"evidences": evidence_rows}, "chart_regions": []}
    return flow.answer_document(
        {"messages": []}, {"id": "doc", "extraction_name": "x", "storage_name": "x"}, "q", "trace", [], {"sessions": {}},
        overlay=lambda document, value: value, snapshot=lambda message: None, complete=sequence(*actions),
        load_extraction=lambda name: extraction, resolve_pdf=lambda name: name, save=lambda catalog: None,
    )["assistant_message"]["structured_answer"]


def _row(key, status, source):
    return {**evidences()[0], "evidence_key": key, "data_status": status, "source_type": source, "bbox": [0, 0, 1, 1], "method_label": "bảng"}


def test_unverified_warning_names_charts_only_when_every_unverified_value_is_from_a_chart():
    table = _tools_answer([_row("t", "ambiguous", "table")], {"action": "answer", "answer": "100", "evidence_keys": ["t"]})
    chart = _tools_answer([_row("c", "ambiguous", "chart")], {"action": "answer", "answer": "100", "evidence_keys": ["c"]})
    assert table["warnings"] == ["Một số giá trị chưa được xác minh; xem bảng Dữ liệu để kiểm tra."]
    assert chart["warnings"] == ["Một số giá trị biểu đồ chưa được xác minh; xem bảng Dữ liệu để kiểm tra."]


def test_summary_does_not_claim_data_table_values_when_the_script_typed_numbers():
    rows = [_row("a", "valid", "table")]
    typed = _tools_answer(rows, {"action": "python", "code": "result = value('a') + 37", "explanation": "x"},
                          {"action": "answer", "answer": "Đã cộng thêm phí.", "evidence_keys": ["a"]})
    read = _tools_answer(rows, {"action": "python", "code": "result = value('a') + value('a')", "explanation": "x"},
                         {"action": "answer", "answer": "200", "evidence_keys": ["a"]})
    assert "gõ tay" in typed["summary"]
    assert read["summary"] == "Phép tính được chạy bằng script Python trên giá trị hiện tại của bảng Dữ liệu."


def test_a_percent_change_is_not_flagged_as_typed_by_hand():
    rows = [{**_row("a", "valid", "table"), "numeric_value": "18240"}, {**_row("b", "valid", "table"), "numeric_value": "21350"}]
    percent = _tools_answer(rows, {"action": "python", "code": "result = round((value('b') - value('a')) / value('a') * 100, 2)"},
                            {"action": "answer", "answer": "Tăng 17,05%.", "evidence_keys": ["a", "b"]})
    assert percent["summary"] == "Phép tính được chạy bằng script Python trên giá trị hiện tại của bảng Dữ liệu."


@pytest.mark.parametrize("change", ["reextract", "edit", None])
def test_an_answer_whose_inputs_changed_while_it_ran_is_stored_as_needing_update(change):
    from report_qa.api import document_assistant_flow as flow
    from report_qa.api.main import extraction_with_evidence_revisions, snapshot_answer_revision

    extraction = {"pages": [{"page": 1, "text": "x"}], "evidence_batch": {"evidences": [_row("a", "valid", "table")]}, "chart_regions": []}
    document = {"id": "doc", "extraction_name": "x", "storage_name": "x"}
    session = {"messages": []}
    answer = json.dumps({"action": "answer", "answer": "100", "evidence_keys": ["a"]})

    def complete(system, user, timeout=None):
        # What a re-run or an edit does to the document while the AI is still answering.
        if change == "reextract":
            document.setdefault("extraction_history", []).append({"status": "ready"})
        elif change == "edit":
            document["evidence_state"]["items"]["a"]["current_revision_id"] = "edited"
        return answer

    message = flow.answer_document(
        session, document, "q", "trace", [], {"sessions": {}},
        overlay=extraction_with_evidence_revisions, snapshot=snapshot_answer_revision, complete=complete,
        load_extraction=lambda name: extraction, resolve_pdf=lambda name: name, save=lambda catalog: None,
    )["assistant_message"]
    assert session["messages"][-1]["needs_update"] is (change is not None)
    assert message["needs_update"] is (change is not None)


def test_a_python_number_without_a_data_source_does_not_trace_the_answer():
    complete = sequence(
        {"action": "python", "code": "result = {'q2': value('b'), 'made_up': int('9' + '99')}"},
        {"action": "answer", "answer": "Q2 là 130, dự báo 999.", "evidence_keys": ["b"]},
        {"action": "answer", "answer": "Q2 là 130.", "evidence_keys": ["b"]},
    )
    result = run_assistant("Q2?", context(), complete=complete, read_chart=Mock())
    assert result["answer"] == "Q2 là 130."
    assert result["calculations"][0]["result"]["manual_numbers"] == ["999"]
    assert json.loads(complete.call_args.args[1])["tool_results"][1]["untraced_numbers"] == ["999"]


def test_rows_stated_by_an_accepted_quote_become_answer_inputs_so_an_edit_flags_the_answer():
    from report_qa.api import document_assistant_flow as flow
    from report_qa.api.main import extraction_with_evidence_revisions, mark_answers_needing_update, snapshot_answer_revision

    page = "Doanh thu quý 2 đạt 130 tỷ đồng. Chi phí là 1.130 tỷ đồng."
    rows = [{**_row("rev", "valid", "table"), "raw_text": "130", "numeric_value": "130"},
            {**_row("cost", "valid", "table"), "raw_text": "1.130", "numeric_value": "1130"},
            {**_row("other", "valid", "table"), "raw_text": "130", "numeric_value": "130", "page_number": 2}]
    extraction = {"pages": [{"page": 1, "text": page}, {"page": 2, "text": "x"}], "evidence_batch": {"evidences": rows}, "chart_regions": []}
    document = {"id": "doc", "extraction_name": "x", "storage_name": "x"}
    session = {"messages": []}
    answer = {"action": "answer", "answer": "Doanh thu quý 2 là 130 tỷ đồng.",
              "sources": [{"page": 1, "quote": "Doanh thu quý 2 đạt 130 tỷ đồng."}]}
    message = flow.answer_document(
        session, document, "Doanh thu quý 2?", "trace", [], {"sessions": {}},
        overlay=extraction_with_evidence_revisions, snapshot=snapshot_answer_revision, complete=sequence(answer),
        load_extraction=lambda name: extraction, resolve_pdf=lambda name: name, save=lambda catalog: None,
    )["assistant_message"]
    assert [i["evidence_key"] for i in message["answer_inputs"]] == ["rev"]
    revision = message["answer_inputs"][0]["evidence_revision_id"]
    assert mark_answers_needing_update(session, "doc", "rev", revision) == [message["id"]]


def _long_document(pages=60):
    text = "Báo cáo hoạt động kinh doanh trong kỳ. " * 200
    page_list = [{"page": n, "text": text} for n in range(1, pages + 1)]
    page_list[41]["text"] += " Lợi nhuận gộp mảng thép xây dựng đạt 77 tỷ đồng."
    rows = [{**_row(f"ev-{n}", "valid", "table"), "page_number": n} for n in range(1, pages + 1)]
    regions = [{"chart_region_key": f"chart-{n}", "page_number": n, "bbox": [0, 0, 1, 1], "text": ""} for n in range(1, pages + 1)]
    return {"pages": page_list, "evidence_batch": {"evidences": rows}, "chart_regions": regions}


def test_a_long_document_sends_the_relevant_and_named_pages_and_lists_the_rest():
    from report_qa.api import document_assistant_flow as flow

    extraction = _long_document()
    sent = []

    def complete(system, user, timeout=None):
        sent.append(json.loads(user))
        return json.dumps({"action": "answer", "answer": "Lợi nhuận gộp mảng thép là 77 tỷ đồng.",
                           "sources": [{"page": 42, "quote": "Lợi nhuận gộp mảng thép xây dựng đạt 77 tỷ đồng."}]})

    message = flow.answer_document(
        {"messages": []}, {"id": "doc", "extraction_name": "x", "storage_name": "x"},
        "Lợi nhuận gộp mảng thép? Xem cả trang 7.", "trace", [], {"sessions": {}},
        overlay=lambda document, value: value, snapshot=lambda m: None, complete=complete,
        load_extraction=lambda name: extraction, resolve_pdf=lambda name: name, save=lambda catalog: None,
    )["assistant_message"]
    document = sent[0]["document"]
    pages = [p["page"] for p in document["pages"]]
    assert len(json.dumps(document, ensure_ascii=False)) <= flow.MAX_CONTEXT_CHARS
    assert 7 in pages and 42 in pages and 0 < len(pages) < 60
    assert sorted(pages + document["omitted_pages"]) == list(range(1, 61))
    assert {r["page"] for r in document["data"]} == set(pages)
    assert {r["page_number"] for r in document["chart_regions"]} == set(pages)
    assert message["citations"][0]["page"] == 42


def test_history_is_dropped_oldest_first_and_a_short_document_is_sent_whole():
    from report_qa.api.document_assistant_flow import fit_context

    history = [{"role": "user", "text": f"turn {i} " + "x" * 1000} for i in range(8)]
    context = {"pages": [{"page": 1, "text": "a" * 500}], "evidences": [], "chart_regions": [], "history": history}
    assert fit_context(context, "q", budget=100_000) is context
    fitted = fit_context(context, "q", budget=2_700)
    assert [t["text"][:6] for t in fitted["history"]] == ["turn 6", "turn 7"] and fitted["pages"] == context["pages"]
    assert "omitted_pages" not in fitted


def test_every_model_call_of_an_answer_shares_one_time_budget(monkeypatch):
    from report_qa.api.ai_provider import ProviderError
    from report_qa.application import document_assistant

    clock = [100.0]
    monkeypatch.setattr(document_assistant.time, "monotonic", lambda: clock[0])
    timeouts = []

    def complete(system, user, timeout):
        timeouts.append(timeout)
        clock[0] += 25  # each model step takes 25 s
        return json.dumps({"action": "python", "code": "result = value('a')"})

    with pytest.raises(ProviderError) as error:
        run_assistant("Q1?", context(), complete=document_assistant.with_time_budget(complete, 60), read_chart=Mock())
    assert error.value.code == "AI_ANSWER_TIMEOUT"
    assert timeouts == [60, 35, 10]


def test_an_answer_past_its_budget_fails_with_a_vietnamese_message(monkeypatch):
    from report_qa.api import main
    from report_qa.api.ai_provider import ProviderError

    monkeypatch.setenv("REPORT_QA_ANSWER_TIMEOUT_SECONDS", "0")
    with pytest.raises(ProviderError) as error:
        _tools_answer([_row("a", "valid", "table")], {"action": "answer", "answer": "100", "evidence_keys": ["a"]})
    assert error.value.code == "AI_ANSWER_TIMEOUT"
    assert main.ai_failure("AI_ANSWER_TIMEOUT", "x", "t").detail["message"].startswith("Trợ lý chưa trả lời xong")


def test_formula_result_rows_take_the_data_label_of_a_value_read_unchanged():
    rows = [{**_row("a", "valid", "table"), "numeric_value": "18240", "raw_text": "18.240",
             "table_locator": {"row_header": "Miền Bắc", "column_header": "Quý 1/2026"}},
            {**_row("b", "valid", "table"), "numeric_value": "21350", "raw_text": "21.350",
             "table_locator": {"row_header": "Miền Bắc", "column_header": "Quý 2/2026"}}]
    answer = _tools_answer(rows, {"action": "python", "code": "result = {'dt_bac_q2': value('b'), 'total': value('a') + value('b')}"},
                           {"action": "answer", "answer": "Quý 2 là 21.350, tổng 39.590.", "evidence_keys": ["a", "b"]})
    assert answer["formulas"][0]["result_rows"] == [
        {"label": "Miền Bắc · Quý 2/2026", "name": "dt_bac_q2", "value": "21350", "source_keys": ["b"]},
        {"label": "total", "name": "total", "value": "39590", "source_keys": ["a", "b"]},
    ]


def test_the_same_script_run_twice_is_one_calculation():
    rows = [{**_row("a", "valid", "table"), "numeric_value": "18240", "raw_text": "18.240"}]
    script = {"action": "python", "code": "result = value('a') + value('a')"}
    answer = _tools_answer(rows, script, script, {"action": "answer", "answer": "Gấp đôi là 36.480.", "evidence_keys": ["a"]})
    assert len(answer["formulas"]) == 1


@pytest.mark.parametrize("locale", ["vi", None])
def test_quoted_rows_compare_quantities_not_digit_strings(locale):
    # Rows "8" and "2023" were marked as inputs of "tăng 8%" and raw "1250" was missed for "1.250".
    from report_qa.api.document_assistant_flow import quoted_rows

    rows = [{"evidence_key": key, "page_number": 1, "raw_text": raw}
            for key, raw in [("eight", "8"), ("year", "2023"), ("printed", "1.250"), ("plain", "1250"), ("pct", "8%")]]
    growth = [{"page": 1, "quote": "Doanh thu thuần năm 2023 tăng 8% so với năm trước."}]
    profit = [{"page": 1, "quote": "Lợi nhuận sau thuế năm 2023 đạt 1.250 tỷ đồng."}]
    assert [e["evidence_key"] for e in quoted_rows(growth, rows, locale)] == ["pct"]
    assert [e["evidence_key"] for e in quoted_rows(profit, rows, locale)] == ["printed", "plain"]
