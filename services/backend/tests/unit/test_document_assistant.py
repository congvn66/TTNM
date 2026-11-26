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


def test_text_answer_can_cite_pages_but_not_invented_ones():
    complete = sequence(
        {"action": "answer", "answer": "Chưa gồm thuế.", "pages": [9]},
        {"action": "answer", "answer": "Chưa gồm thuế.", "pages": [1]},
    )
    result = run_assistant("Thuế?", context(), complete=complete, read_chart=Mock())
    assert result["pages"] == [1]
    assert "pages must be" in json.loads(complete.call_args.args[1])["tool_results"][0]["error"]


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
        overlay=extraction_with_evidence_revisions, snapshot=snapshot_answer_revision, complete=lambda *args: json.dumps(next(actions)),
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
                          {"action": "answer", "answer": "137", "evidence_keys": ["a"]})
    read = _tools_answer(rows, {"action": "python", "code": "result = value('a') * 2", "explanation": "x"},
                         {"action": "answer", "answer": "200", "evidence_keys": ["a"]})
    assert "gõ tay" in typed["summary"]
    assert read["summary"] == "Phép tính được chạy bằng script Python trên giá trị hiện tại của bảng Dữ liệu."
