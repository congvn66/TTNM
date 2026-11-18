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
