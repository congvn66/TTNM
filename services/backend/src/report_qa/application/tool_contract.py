"""Validation and redaction helpers for provider/tool invocation envelopes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any, Mapping
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker


_CATEGORIES = {
    "validation", "unsupported_input", "timeout", "rate_limit", "provider",
    "storage", "internal", "cancelled", "stale_input",
}


def canonical_sha256(payload: Any) -> str:
    """Hash canonical UTF-8 JSON without exposing the payload in telemetry."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_tool_invocation(payload: Mapping[str, Any]) -> dict[str, Any]:
    schema = json.loads(files("report_qa.resources").joinpath("tool-invocation-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    status = payload["status"]
    if status in {"succeeded", "partial"} and payload["error"] is not None:
        raise ValueError("successful tool invocation cannot contain an error")
    if status in {"failed", "rejected", "cancelled"} and payload["error"] is None:
        raise ValueError("failed tool invocation requires an error")
    if payload["error"] is not None and payload["error"]["category"] not in _CATEGORIES:
        raise ValueError("invalid tool error category")
    return dict(payload)


def new_tool_invocation(*, trace_id: str, name: str, version: str, provider: str, model: str | None, operation: str, input_contract: str, input_version: int, input_payload: Any, artifact_refs: list[str] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "invocation_id": str(uuid4()),
        "trace_id": trace_id,
        "tool": {"name": name, "version": version, "provider": provider, "model": model},
        "operation": operation,
        "status": "running",
        "attempt": 1,
        "input": {"contract": input_contract, "version": input_version, "payload_sha256": canonical_sha256(input_payload), "artifact_refs": artifact_refs or []},
        "output": {"contract": "pending", "version": 1, "payload_sha256": canonical_sha256({}), "artifact_refs": []},
        "error": None,
        "timing": {"started_at": now, "finished_at": None, "latency_ms": None},
        "warnings": [],
    }


__all__ = ["canonical_sha256", "validate_tool_invocation", "new_tool_invocation"]
