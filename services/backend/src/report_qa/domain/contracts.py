"""Boundary validation for the versioned JSON contracts.

This is the dependency-free core validator. A production API may add a full
JSON-Schema validator, but it must preserve these semantic invariants.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from uuid import UUID

from .errors import InvariantError
from .types import DataStatus, ValueKind, validate_bbox, validate_decimal_text


def _required(mapping: Mapping[str, Any], names: Sequence[str], label: str) -> None:
    missing = [name for name in names if name not in mapping]
    if missing:
        raise InvariantError(f"{label} missing required fields: {', '.join(missing)}")


def validate_semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _required(payload, ("schema_version", "measure", "subject", "unit", "period", "dimensions", "value_operator"), "semantic")
    if payload["schema_version"] != 1:
        raise InvariantError("semantic schema_version must be 1")
    period = payload["period"]
    if not isinstance(period, Mapping):
        raise InvariantError("semantic.period must be an object")
    _required(period, ("status", "label", "start", "end", "basis", "source_region_ids"), "semantic.period")
    status = period["status"]
    if status == "known" and (not period["start"] or not period["end"]):
        raise InvariantError("known period requires start and end")
    if status in {"unspecified", "not_applicable"} and (period["start"] is not None or period["end"] is not None):
        raise InvariantError("unspecified period cannot contain start/end")
    if period["basis"] not in {"explicit", "context", "user", None}:
        raise InvariantError("invalid semantic period basis")
    for region_id in period["source_region_ids"]:
        try:
            UUID(str(region_id))
        except ValueError as exc:
            raise InvariantError("period source_region_ids must be UUIDs") from exc
    unit = payload["unit"]
    if unit is not None:
        _required(unit, ("code", "label", "multiplier"), "semantic.unit")
        validate_decimal_text(unit["multiplier"])
    return dict(payload)


def validate_provider_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _required(payload, ("schema_version", "regions", "evidences", "warnings"), "provider extraction")
    if payload["schema_version"] != 1:
        raise InvariantError("provider extraction schema_version must be 1")
    region_keys: set[str] = set()
    for region in payload["regions"]:
        _required(region, ("region_key", "page_number", "bbox", "region_type", "text", "meta"), "provider region")
        key = str(region["region_key"])
        if not key or key in region_keys:
            raise InvariantError("provider region_key must be unique and non-empty")
        region_keys.add(key)
        if int(region["page_number"]) <= 0:
            raise InvariantError("provider page_number must be positive")
        if region["region_type"] not in {"paragraph", "table", "table_cell", "chart", "chart_element", "image", "other"}:
            raise InvariantError("provider region_type is invalid")
        validate_bbox(region["bbox"])
    evidence_keys: set[str] = set()
    for evidence in payload["evidences"]:
        _required(
            evidence,
            ("evidence_key", "source_region_key", "value_kind", "raw_value", "raw_text", "semantic", "data_status", "extraction_method", "confidence"),
            "provider evidence",
        )
        evidence_key = str(evidence["evidence_key"])
        if not evidence_key or evidence_key in evidence_keys:
            raise InvariantError("provider evidence_key must be unique and non-empty")
        evidence_keys.add(evidence_key)
        if evidence["source_region_key"] not in region_keys:
            raise InvariantError("provider evidence references an unknown region")
        try:
            kind = ValueKind(str(evidence["value_kind"]))
            status = DataStatus(str(evidence["data_status"]))
        except ValueError as exc:
            raise InvariantError("provider evidence contains an invalid value_kind/data_status") from exc
        raw_value = evidence["raw_value"]
        raw_text = evidence["raw_text"]
        if raw_value is not None:
            validate_decimal_text(raw_value)
        if status is DataStatus.VALID and kind is ValueKind.NUMBER and (raw_value is None or raw_text is not None):
            raise InvariantError("provider valid number must contain raw_value only")
        if status is DataStatus.VALID and kind is ValueKind.TEXT and (raw_text is None or raw_value is not None):
            raise InvariantError("provider valid text must contain raw_text only")
        if status is not DataStatus.VALID and (raw_value is not None or raw_text is not None):
            raise InvariantError("provider missing/error cannot contain a value")
        if evidence["confidence"] is not None and not 0 <= float(evidence["confidence"]) <= 1:
            raise InvariantError("provider confidence must be between 0 and 1")
        validate_semantic_payload(evidence["semantic"])
    return dict(payload)


def validate_document_evidence_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    _required(payload, ("schema_version", "document_version_id", "extraction_run_id", "scope", "trigger", "evidences", "warnings"), "document evidence v2")
    if payload["schema_version"] != 2:
        raise InvariantError("document evidence schema_version must be 2")
    if payload["scope"] not in {"base_document", "on_demand_chart"}:
        raise InvariantError("document evidence scope is invalid")
    if payload["scope"] == "base_document" and payload["trigger"] is not None:
        raise InvariantError("base extraction cannot have a question trigger")
    if payload["scope"] == "on_demand_chart" and not isinstance(payload["trigger"], Mapping):
        raise InvariantError("on-demand chart extraction requires a trigger")
    seen: set[str] = set()
    labels = {
        "text": "đọc từ văn bản",
        "table_cell": "đọc từ ô bảng",
        "ocr": "đọc bằng OCR",
        "direct_label": "đọc từ nhãn",
        "axis_estimation": "ước lượng theo trục",
    }
    for evidence in payload["evidences"]:
        _required(
            evidence,
            ("evidence_key", "source_region_key", "source_type", "page_number", "bbox", "raw_text", "numeric_value", "data_status", "extraction_method", "method_label", "semantic", "table_locator", "chart_read", "confidence"),
            "document evidence item",
        )
        key = str(evidence["evidence_key"])
        if not key or key in seen:
            raise InvariantError("document evidence_key must be unique and non-empty")
        seen.add(key)
        if int(evidence["page_number"]) < 1:
            raise InvariantError("document evidence page_number must be positive")
        validate_bbox(evidence["bbox"])
        if evidence["numeric_value"] is not None:
            validate_decimal_text(evidence["numeric_value"])
        method = evidence["extraction_method"]
        if method not in labels or evidence["method_label"] != labels[method]:
            raise InvariantError("document evidence method label does not match extraction_method")
        if evidence["source_type"] == "chart" and method not in {"direct_label", "axis_estimation"}:
            raise InvariantError("chart evidence must be read from a label or estimated from an axis")
        if evidence["source_type"] != "chart" and evidence["chart_read"] is not None:
            raise InvariantError("non-chart evidence cannot contain chart_read metadata")
        if evidence["source_type"] == "table" and not isinstance(evidence["table_locator"], Mapping):
            raise InvariantError("table evidence requires a cell locator")
        if not 0 <= float(evidence["confidence"]) <= 1:
            raise InvariantError("document evidence confidence must be between 0 and 1")
    return dict(payload)


def validate_question_plan_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    _required(payload, ("schema_version", "question_plan_id", "document_version_id", "original_question", "language", "status", "facts", "operation", "source_strategy", "clarification"), "question plan v2")
    if payload["schema_version"] != 2:
        raise InvariantError("question plan schema_version must be 2")
    if payload["status"] not in {"ready", "needs_clarification", "unsupported"}:
        raise InvariantError("question plan status is invalid")
    if payload["status"] == "ready" and (not payload["facts"] or not isinstance(payload["operation"], Mapping) or payload["clarification"] is not None):
        raise InvariantError("ready question plan requires facts and operation without clarification")
    if payload["status"] == "needs_clarification" and not isinstance(payload["clarification"], Mapping):
        raise InvariantError("ambiguous question plan requires clarification")
    strategy = payload["source_strategy"]
    if strategy.get("priority") != ["table", "text", "chart"] or strategy.get("chart_policy") != "only_if_required_fact_unresolved":
        raise InvariantError("question plan source strategy drifted")
    if isinstance(payload["operation"], Mapping):
        operation = payload["operation"]
        expected = {
            "lookup": "identity_v1",
            "sum": "sum_v1",
            "difference": "subtract_v1",
            "absolute_change": "absolute_change_v1",
            "growth_rate": "growth_rate_v1",
            "percentage_point_change": "percentage_point_change_v1",
            "compare": "compare_v1",
            "ranking": "ranking_v1",
        }
        if expected.get(operation.get("type")) != operation.get("formula_id"):
            raise InvariantError("question plan operation/formula mismatch")
        fact_keys = {item["fact_key"] for item in payload["facts"]}
        if not set(operation.get("operand_fact_keys", [])) <= fact_keys:
            raise InvariantError("question plan operand references an unknown fact")
    return dict(payload)


def validate_calculation_result_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    _required(payload, ("schema_version", "question_plan_id", "status", "formula_id", "operands", "value", "unit", "reason_code", "warnings"), "calculation result v1")
    if payload["schema_version"] != 1:
        raise InvariantError("calculation result schema_version must be 1")
    if payload["status"] not in {"succeeded", "missing_data", "zero_denominator", "unit_mismatch", "ambiguous"}:
        raise InvariantError("calculation result status is invalid")
    for operand in payload["operands"]:
        _required(operand, ("fact_key", "evidence_revision_id", "value", "unit"), "calculation operand")
        validate_decimal_text(operand["value"])
    if payload["status"] == "succeeded":
        validate_decimal_text(payload["value"])
        if payload["reason_code"] is not None:
            raise InvariantError("successful calculation cannot have a reason code")
    elif payload["value"] is not None or not payload["reason_code"]:
        raise InvariantError("failed calculation requires null value and a reason code")
    return dict(payload)
