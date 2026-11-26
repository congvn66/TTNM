import json
from unittest.mock import Mock

import pytest
from report_qa.application.document_assistant import run_assistant
from report_qa.application.python_calculator import run_calculation, validate_script


def facts():
    return {
        "a": {"evidence_key": "a", "page_number": 1, "numeric_value": "1250.50", "data_status": "valid",
              "table_locator": {"row_header": "Q1", "column_header": "Doanh thu"}},
        "b": {"evidence_key": "b", "page_number": 1, "numeric_value": "980.00", "data_status": "valid",
              "table_locator": {"row_header": "Q3", "column_header": "Doanh thu"}},
    }


def test_script_reads_current_values_and_tracks_inputs():
    result = run_calculation("result = (value('b') - value('a')) / value('a') * 100", facts())
    assert result["status"] == "succeeded"
    assert result["result"].startswith("-21.6")
    assert result["used_evidence_keys"] == ["b", "a"]


def test_realistic_model_script_with_dicts_lambda_methods_and_print():
    code = """from decimal import Decimal
rows = {}
for name, key in [('Q1', 'a'), ('Q3', 'b')]:
    rows[name] = value(key)
best = max(rows, key=lambda k: rows[k])
ranked = sorted(rows.items(), key=lambda item: item[1], reverse=True)
print('ranked', ranked)
def share(x):
    return round(x / sum(rows.values()) * 100, 2)
result = {'best': best, 'share': {k: share(v) for k, v in rows.items()}}
"""
    result = run_calculation(code, facts())
    assert result["status"] == "succeeded", result
    assert result["result"]["best"] == "Q1"
    assert result["result"]["share"]["Q1"] == "56.06"
    assert result["stdout"].startswith("ranked")


@pytest.mark.parametrize(
    "code",
    [
        "import os\nresult = os.environ",
        "result = value.__globals__",
        "result = getattr(value, '__globals__')",
        "result = __import__('os')",
        "result = '{0.__globals__}'.format(value)",
        "match 'x':\n    case str(format=f):\n        result = f",
        "class A: pass",
        "with open('/etc/passwd') as f: result = 1",
        "f = lambda __x: 1",
        "from decimal import getcontext",
        "import math as os",
    ],
)
def test_script_cannot_reach_files_environment_or_internals(code):
    with pytest.raises((ValueError, SyntaxError)):
        validate_script(code)


def test_open_eval_and_type_are_not_available():
    for code in ["result = open('/etc/passwd')", "result = eval('1')", "x = value('a')\nresult = type(x)"]:
        result = run_calculation(code, facts())
        assert result["status"] == "failed"
        assert "not available" in result["error"]


def test_unlisted_builtins_are_missing_at_runtime_too():
    result = run_calculation("x = value('a')\nresult = hash(x)", facts())
    assert result["status"] == "failed" and "NameError" in result["error"]


def test_copied_document_numbers_and_unverified_values_are_rejected():
    copied = run_calculation("result = Decimal('1250.50') + value('b')", facts())
    assert copied["status"] == "failed" and "value('a')" in copied["error"]
    assert run_calculation("result = 30", facts())["status"] == "failed"
    assert run_calculation("result = value('b') / 4 * 100", facts())["status"] == "succeeded"
    f = facts()
    f["b"]["data_status"] = "ambiguous"
    assert "unverified" in run_calculation("result = value('b')", f)["error"]


def test_numbers_typed_into_the_script_are_reported():
    code = "rate = Decimal('74') / value('a')\nresult = round((rate + Decimal(7) / 10) / 2 * 100, 2)"
    result = run_calculation(code, facts())
    assert result["status"] == "succeeded"
    assert result["manual_numbers"] == ["74", "7", "10", "2", "100"]


def test_inputs_are_the_sources_of_the_result_not_every_value_read():
    result = run_calculation("x = value('a')\nresult = {'q3': round(value('b'), 1)}", facts())
    assert result["used_evidence_keys"] == ["b"] and result["manual_numbers"] == []


def test_provenance_survives_sum_statistics_math_max_and_quantize():
    code = """total = 0
for key in ['a', 'b']:
    total += value(key)
rows = [value('a'), value('b')]
result = {'sum': sum(rows), 'mean': round(statistics.mean(rows), 2), 'root': math.sqrt(value('a')),
          'top': max(rows), 'q': (total / len(rows)).quantize(Decimal('0.01'))}
"""
    result = run_calculation(code, facts())
    assert result["status"] == "succeeded", result
    assert result["used_evidence_keys"] == ["a", "b"]
    assert result["manual_numbers"] == ["2"]  # only len(rows) entered the arithmetic from outside the Data table
    assert "2230.50" in result["traced_numbers"]


@pytest.mark.parametrize("code", [
    "a = value('a')\nvalue = lambda k: a * 0 + 101\nresult = value('b')",
    "def round(x, n):\n    return 101\nresult = round(value('a'), 2)",
    "for value in [1]:\n    pass\nresult = 1",
    "Decimal = int\nresult = value('a')",
])
def test_names_the_runtime_provides_cannot_be_rebound(code):
    result = run_calculation(code, facts())
    assert result["status"] == "failed" and "reserved name" in result["error"]


def test_a_number_built_from_strings_is_reported_as_manual():
    # The script text has no number literal; the card used to show row a as the only input.
    disguised = run_calculation("result = value('a') * 0 + int('1' + '0' + '1' + '0')", facts())
    assert disguised["status"] == "succeeded"
    assert disguised["used_evidence_keys"] == ["a"] and disguised["manual_numbers"] == ["0", "1010"]
    unsourced = run_calculation("x = value('a')\nresult = {'x': int('1' + '0' + '1')}", facts())
    assert unsourced["status"] == "failed" and "computed from value" in unsourced["error"]


def test_runaway_script_is_stopped():
    result = run_calculation("x = value('a')\nwhile True:\n    x = x + 1", facts())
    assert result["status"] == "failed"


def test_assistant_runs_script_retries_errors_and_cites_its_inputs():
    complete = Mock(side_effect=[json.dumps(a) for a in [
        {"action": "python", "code": "result = Decimal('1250.50') + Decimal('980.00')"},
        {"action": "python", "code": "result = value('a') + value('b')", "explanation": "Q1 + Q3"},
        {"action": "answer", "answer": "Tổng Q1 và Q3 là 2230.50."},
    ]])
    context = {"pages": [{"page": 1, "text": "..."}], "evidences": list(facts().values()), "chart_regions": []}
    result = run_assistant("Tổng Q1 và Q3?", context, complete=complete, read_chart=Mock())
    assert result["evidence_keys"] == ["a", "b"]
    assert [c["result"]["result"] for c in result["calculations"]] == ["2230.50"]
    feedback = json.loads(complete.call_args.args[1])["tool_results"]
    assert feedback[0]["result"]["status"] == "failed"


def test_memory_hungry_script_is_stopped_on_every_platform():
    # macOS refuses RLIMIT_AS, so without a watcher an 800 MB list just ran.
    import time

    started = time.monotonic()
    result = run_calculation("big = [0] * (10 ** 8)\nresult = value('a')", facts())

    assert result["status"] == "failed"
    assert "memory" in result["error"].lower()
    assert time.monotonic() - started < 4


def test_script_output_is_bounded_when_the_script_fails():
    import report_qa.application.python_calculator as calculator

    evidence = {"a": {"evidence_key": "a", "numeric_value": "1.5", "data_status": "valid"}}
    printed = run_calculation("print('x' * 5_000_000)\nresult = value('a') / 0", evidence)
    assert printed["status"] == "failed"
    assert len(printed["stdout"]) <= calculator.MAX_STDOUT_CHARS
    unknown = run_calculation("result = value('k' * 5_000_000)", evidence)
    assert unknown["status"] == "failed" and len(unknown["error"]) <= calculator.MAX_ERROR_CHARS


def test_scripts_run_where_the_resource_module_is_missing(monkeypatch):
    """Windows has no resource module; calculations must still work."""
    import report_qa.application.python_calculator as calculator

    monkeypatch.setattr(calculator, "_RUNNER", "import sys\nsys.modules['resource'] = None\n" + calculator._RUNNER)
    evidence = {"a": {"evidence_key": "a", "numeric_value": "1.5", "data_status": "valid"}}
    assert run_calculation("result = value('a') * 2", evidence)["result"] == "3.0"


def test_child_process_gets_no_parent_variables_except_what_windows_needs(monkeypatch):
    import report_qa.application.python_calculator as calculator

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    assert calculator._child_env() == {}
    monkeypatch.setenv("SYSTEMROOT", "C:\\Windows")
    assert calculator._child_env() == {"SYSTEMROOT": "C:\\Windows"}


@pytest.mark.parametrize("code", ["result = " + "-" * 9000 + "1", "result = 0x" + "f" * 8000 + " * value('a')"])
def test_extreme_scripts_fail_without_raising(code):
    evidence = {"a": {"evidence_key": "a", "numeric_value": "1.5", "data_status": "valid"}}
    assert run_calculation(code, evidence)["status"] in {"failed", "succeeded"}
