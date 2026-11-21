from __future__ import annotations

import pytest

from report_qa.application.tool_contract import (
    canonical_sha256,
    new_tool_invocation,
    validate_tool_invocation,
)


def test_tool_invocation_hash_is_canonical_and_does_not_depend_on_key_order():
    assert canonical_sha256({"b": 2, "a": "x"}) == canonical_sha256({"a": "x", "b": 2})


def test_running_invocation_can_be_created_without_payload_logging():
    payload = new_tool_invocation(
        trace_id="trace-1",
        name="deplot_chart_reader",
        version="1.0.0",
        provider="huggingface",
        model="google/deplot",
        operation="read_chart",
        input_contract="chart-read-request",
        input_version=1,
        input_payload={"page": 2, "fact_keys": ["revenue"]},
    )
    assert payload["status"] == "running"
    assert "payload" not in payload["input"]
    assert validate_tool_invocation(payload)["schema_version"] == 1


def test_failed_invocation_requires_retryable_error():
    payload = new_tool_invocation(
        trace_id="trace-1",
        name="docling",
        version="1.0.0",
        provider="local",
        model=None,
        operation="extract_pdf",
        input_contract="pdf-reference",
        input_version=1,
        input_payload={"sha256": "abc"},
    )
    payload["status"] = "failed"
    with pytest.raises(Exception):
        validate_tool_invocation(payload)
    payload["error"] = {"code": "TIMEOUT", "category": "timeout", "retryable": True, "message": "provider timeout"}
    assert validate_tool_invocation(payload)["error"]["retryable"] is True
