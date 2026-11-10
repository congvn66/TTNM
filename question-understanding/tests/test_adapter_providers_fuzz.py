import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from qunderstand.adapters.docling_csv import table_to_evidences
from qunderstand.calculator import OPERATIONS
from qunderstand.cli import main
from qunderstand.evidence import load_store, store_from_dict
from qunderstand.parsers.llm import LLMParser
from qunderstand.parsers.rules import RuleParser
from qunderstand.pipeline import Session, ask, run_request
from qunderstand.providers import AnthropicProvider, GeminiProvider, OpenAICompatibleProvider, ProviderError, _post
from qunderstand.request import RequestError, request_from_dict

ROOT = Path(__file__).resolve().parent.parent
S1 = load_store(ROOT / "datasets" / "S1.json")
TIEN_CSV = 'Kỳ,Doanh thu,Chi phí,Tăng trưởng\nQ1,"1,250.50",810.25,12.5%\nQ2,"2,010.75","1,120.00",-3.2%\nQ3,980.00,"1,025.50",0.0%\nQ4,"3,456.78","2,100.99",18.7%\n'
SAFE_STATUSES = {"ok", "needs_clarification", "source_conflict", "not_found", "missing_data", "extraction_error", "div_by_zero", "unit_mismatch", "invalid_request", "parser_error", "invalid_question", "internal_error"}


def test_tien_real_output_runs_through_the_system():
    items = table_to_evidences(TIEN_CSV, page=1, units={"Doanh thu": "triệu đồng", "Chi phí": "triệu đồng"})
    store = store_from_dict({"document_code": "TIEN", "evidences": items})
    assert len(store.items) == 12
    record = ask(store, "Doanh thu quý 2 tăng bao nhiêu phần trăm so với quý 1?", RuleParser())
    assert record["computed_result"]["value"] == pytest.approx(60.79, abs=0.01)
    assert ask(store, "Tăng trưởng Q2 là bao nhiêu?", RuleParser())["computed_result"]["value"] == pytest.approx(-3.2)


def test_cli_converts_docling_csv(tmp_path):
    source = tmp_path / "bang.csv"
    source.write_text(TIEN_CSV, encoding="utf-8")
    out = tmp_path / "kho.json"
    assert main(["from-docling", "--csv", str(source), "--out", str(out), "--document", "TIEN", "--units", '{"Doanh thu": "triệu đồng"}']) == 0
    assert load_store(out).document_code == "TIEN"


def test_adapter_needs_the_right_locale():
    item = table_to_evidences("Kỳ,Doanh thu\nQ1,\"1,250\"\n", page=1, locale="en")[0]
    assert item["current_value"] == 1250
    assert table_to_evidences("Kỳ,Doanh thu\nQ1,\"1,250\"\n", page=1, locale="vi")[0]["current_value"] == 1.25


@pytest.mark.parametrize("cell,status", [("—", "missing"), ("n/a", "missing"), ("", "missing"), ("abc", "error"), ("0", "valid")])
def test_adapter_marks_bad_cells(cell, status):
    item = table_to_evidences(f"Kỳ,Doanh thu\nQ1,{cell}\n", page=1)[0]
    assert item["data_status"] == status
    if cell == "0":
        assert item["current_value"] == 0
    store_from_dict({"document_code": "D", "evidences": [item]})


def test_adapter_empty_and_short_rows():
    assert table_to_evidences("", page=1) == []
    assert table_to_evidences("Kỳ,Doanh thu\n", page=1) == []
    assert len(table_to_evidences("Kỳ,Doanh thu\nQ1,1,2,3\n", page=1)) == 1


class Handler(BaseHTTPRequestHandler):
    script: list = []
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.seen.append((self.path, dict(self.headers), body))
        status, reply = Handler.script.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    Handler.script, Handler.seen = [], []
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_openai_format_over_http(server):
    Handler.script = [(200, {"choices": [{"message": {"content": '{"intent":"unanswerable"}'}}]})]
    provider = OpenAICompatibleProvider("m", base_url=server, api_key="secret")
    assert provider.complete("s", "u") == '{"intent":"unanswerable"}'
    path, headers, body = Handler.seen[0]
    assert path == "/chat/completions" and headers["Authorization"] == "Bearer secret" and body["temperature"] == 0
    assert body["messages"][0]["content"] == "s"


def test_retries_then_succeeds(server):
    Handler.script = [(503, {}), (429, {}), (200, {"ok": 1})]
    assert _post(server, {}, {}, 5) == {"ok": 1}


def test_no_retry_on_client_error_and_key_is_not_in_message(server):
    Handler.script = [(401, {"error": "bad key secret"})]
    with pytest.raises(ProviderError) as info:
        OpenAICompatibleProvider("m", base_url=server, api_key="secret").complete("s", "u")
    assert "secret" not in str(info.value) and "401" in str(info.value)
    assert not Handler.script


def test_gives_up_after_retries(server):
    Handler.script = [(500, {}), (500, {}), (500, {})]
    with pytest.raises(ProviderError):
        _post(server, {}, {}, 5)


def test_full_flow_over_http(server):
    reply = {"intent": "answer", "operation": "lookup", "operands": [{"role": "subject", "series": "Số cửa hàng - Miền Nam", "period": "Cuối quý 2/2026"}]}
    Handler.script = [(200, {"choices": [{"message": {"content": "```json\n" + json.dumps(reply) + "\n```"}}]})]
    record = ask(S1, "Miền Nam có mấy cửa hàng?", LLMParser(OpenAICompatibleProvider("m", base_url=server, api_key="k")))
    assert record["computed_result"]["value"] == 55


@pytest.mark.parametrize("cls,reply", [(GeminiProvider, {"candidates": []}), (AnthropicProvider, {"content": None})])
def test_unexpected_response_shape(cls, reply, monkeypatch):
    monkeypatch.setattr("qunderstand.providers._post", lambda *a, **k: reply)
    with pytest.raises(ProviderError):
        cls("m", api_key="k").complete("s", "u")


questions = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=120)
vocab = st.lists(st.sampled_from("doanh thu thuần lợi nhuận gộp miền Bắc Trung Nam quý 1 2 tháng 6 2026 tăng giảm bao nhiêu phần trăm % so với cao nhất nào tổng còn vậy thì sao số đơn hàng cửa hàng tỷ lệ khách quay lại xuất khẩu điểm".split()), max_size=14).map(" ".join)


@settings(max_examples=1500, suppress_health_check=[HealthCheck.too_slow])
@given(st.one_of(questions, vocab))
def test_any_question_gives_a_known_status_and_no_crash(question):
    record = ask(S1, question, RuleParser(), Session())
    status = record["computed_result"]["status"]
    assert status in SAFE_STATUSES and status != "internal_error", record
    if status != "ok":
        assert record["computed_result"]["value"] is None
    json.dumps(record)


names = st.sampled_from(S1.series_names() + ["Không có", "", "Doanh thu", "Miền Bắc"])
periods = st.sampled_from(["Quý 1/2026", "Quý 2/2026", "Tháng 6/2026", "Tháng 6/2025", "quý 2", "Năm 2026", "6 tháng 2026", "abc", None])
operand = st.fixed_dictionaries({"role": st.sampled_from(["target", "base", "item", "numerator", "denominator", "rate", "subject"]), "series": names, "period": periods})


@settings(max_examples=2000, suppress_health_check=[HealthCheck.too_slow])
@given(st.sampled_from(sorted(OPERATIONS)), st.lists(operand, max_size=5), st.lists(names, max_size=4), periods, periods, st.sampled_from([None, "value", "absolute", "percentage_growth"]), st.sampled_from(["ASC", "DESC"]))
def test_any_model_request_is_safe(operation, operands, group, base, target, metric, order):
    """Whatever a model sends, the program returns a status. It does not crash or invent a value."""
    raw = {"intent": "answer", "operation": operation, "operands": operands, "group_series": [g for g in group if g], "base_period": base, "target_period": target, "metric_type": metric, "order": order}
    try:
        request = request_from_dict(raw)
    except RequestError:
        return
    record = run_request(S1, "câu hỏi", request)
    status = record["computed_result"]["status"]
    assert status in SAFE_STATUSES
    if status != "ok":
        assert record["computed_result"]["value"] is None
    json.dumps(record)
