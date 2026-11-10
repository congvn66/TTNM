"""Contract-first P0 question planning, evidence resolution and calculation."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4


FORMULAS = {
    "lookup": "identity_v1",
    "sum": "sum_v1",
    "difference": "subtract_v1",
    "absolute_change": "absolute_change_v1",
    "growth_rate": "growth_rate_v1",
    "percentage_point_change": "percentage_point_change_v1",
    "compare": "compare_v1",
    "ranking": "ranking_v1",
}


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character)).replace("đ", "d")


def _periods(question: str) -> list[str]:
    plain = _plain(question)
    found: list[tuple[int, str]] = []
    for match in re.finditer(r"\b(?:q|quy\s*)([1-4])\s*[/\- ]\s*((?:19|20)\d{2})\b", plain):
        found.append((match.start(), f"Q{int(match.group(1))}/{match.group(2)}"))
    if not found:
        for match in re.finditer(r"\b((?:19|20)\d{2})\b", plain):
            found.append((match.start(), match.group(1)))
    result: list[str] = []
    for _, label in found:
        if label not in result:
            result.append(label)
    return result


def _measure(question: str) -> str:
    plain = _plain(question)
    aliases = (
        (("doanh thu", "revenue"), "doanh_thu"),
        (("loi nhuan", "profit"), "loi_nhuan"),
        (("bookings",), "bookings"),
        (("wer",), "wer"),
        (("cer",), "cer"),
    )
    for names, key in aliases:
        if any(name in plain for name in names):
            return key
    return "unknown"


def _operation(question: str) -> tuple[str | None, str | None]:
    plain = _plain(question)
    if "diem phan tram" in plain or "percentage point" in plain:
        return "percentage_point_change", None
    if any(marker in plain for marker in ("phan tram", "percent", "%", "growth rate", "ty le tang")) and any(
        marker in plain for marker in ("tang", "giam", "thay doi", "change", "increase", "decrease", "growth")
    ):
        return "growth_rate", None
    if any(marker in plain for marker in ("muc tang tuyet doi", "absolute change")):
        return "absolute_change", None
    if any(marker in plain for marker in ("chenh lech", "difference between", "subtract")):
        return "difference", None
    if any(marker in plain for marker in ("tong cua", "cong lai", "sum of", "add together")):
        return "sum", None
    if any(marker in plain for marker in ("xep hang", "ranking", "rank ")):
        return "ranking", None
    if any(marker in plain for marker in ("so sanh", "compare")):
        return "compare", None
    if any(marker in plain for marker in ("tang bao nhieu", "giam bao nhieu", "how much did", "how much has")):
        return None, "AMBIGUOUS_OPERATION"
    return "lookup", None


def build_question_plan(
    question: str,
    document_version_id: str,
    prior_clarification_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if prior_clarification_plan and prior_clarification_plan.get("status") == "needs_clarification":
        clarification = prior_clarification_plan.get("clarification") or {}
        selection = _plain(question)
        if clarification.get("reason_code") == "AMBIGUOUS_OPERATION":
            if any(marker in selection for marker in ("phan tram", "percent", "ty le")):
                question = f"{prior_clarification_plan['original_question']} Tính tỷ lệ thay đổi phần trăm."
            elif any(marker in selection for marker in ("tuyet doi", "absolute")):
                question = f"{prior_clarification_plan['original_question']} Tính mức thay đổi tuyệt đối."
    operation, ambiguity = _operation(question)
    periods = _periods(question)
    measure = _measure(question)
    plan_id = str(uuid4())

    if ambiguity:
        return {
            "schema_version": 2,
            "question_plan_id": plan_id,
            "document_version_id": document_version_id,
            "original_question": question,
            "language": "vi" if any(character in question for character in "ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ") else "en",
            "status": "needs_clarification",
            "facts": [],
            "operation": None,
            "source_strategy": {"priority": ["table", "text", "chart"], "chart_policy": "only_if_required_fact_unresolved", "chart_fact_keys": []},
            "clarification": {
                "reason_code": ambiguity,
                "question_to_user": "Bạn muốn xem mức thay đổi tuyệt đối hay tỷ lệ thay đổi phần trăm?",
                "options": ["Mức thay đổi tuyệt đối", "Tỷ lệ thay đổi phần trăm"],
            },
        }

    period_is_ambiguous = (
        operation in {"growth_rate", "percentage_point_change"} and len(periods) < 2
    ) or (
        operation in {"difference", "absolute_change"} and len(periods) == 1
    )
    if period_is_ambiguous:
        return {
            "schema_version": 2,
            "question_plan_id": plan_id,
            "document_version_id": document_version_id,
            "original_question": question,
            "language": "vi" if "quý" in question.casefold() else "en",
            "status": "needs_clarification",
            "facts": [],
            "operation": None,
            "source_strategy": {"priority": ["table", "text", "chart"], "chart_policy": "only_if_required_fact_unresolved", "chart_fact_keys": []},
            "clarification": {
                "reason_code": "AMBIGUOUS_PERIOD",
                "question_to_user": "Bạn muốn so sánh kỳ này với kỳ nào?",
                "options": ["Cùng kỳ năm trước", "Kỳ liền trước"],
            },
        }

    ordered_periods = periods
    if operation == "growth_rate" and len(periods) >= 2:
        def period_order(label: str) -> tuple[int, int]:
            quarter = re.fullmatch(r"Q([1-4])/((?:19|20)\d{2})", label)
            return (int(quarter.group(2)), int(quarter.group(1))) if quarter else (int(label), 0)

        ordered_periods = sorted(periods, key=period_order, reverse=True)

    fact_count = 2 if operation in {"growth_rate", "difference", "absolute_change", "percentage_point_change", "compare", "ranking"} else max(1, len(ordered_periods))
    fact_keys = ["current", "baseline"] if fact_count == 2 else [f"value_{index + 1}" for index in range(fact_count)]
    expected_unit = "PERCENT" if operation == "percentage_point_change" else None
    facts = []
    for index, fact_key in enumerate(fact_keys):
        facts.append(
            {
                "fact_key": fact_key,
                "measure": measure,
                "subject": None,
                "period": ordered_periods[index] if index < len(ordered_periods) else None,
                "unit": expected_unit,
                "dimensions": {},
                "required": True,
                "allowed_sources": ["table", "text", "chart"],
            }
        )
    result_unit = "PERCENT" if operation in {"growth_rate", "percentage_point_change"} else None
    return {
        "schema_version": 2,
        "question_plan_id": plan_id,
        "document_version_id": document_version_id,
        "original_question": question,
        "language": "vi" if any(character in question for character in "ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ") else "en",
        "status": "ready",
        "facts": facts,
        "operation": {"type": operation, "formula_id": FORMULAS[operation], "operand_fact_keys": fact_keys, "result_unit": result_unit},
        "source_strategy": {"priority": ["table", "text", "chart"], "chart_policy": "only_if_required_fact_unresolved", "chart_fact_keys": fact_keys},
        "clarification": None,
    }


def resolve_evidence(plan: dict[str, Any], extraction: dict[str, Any], selected_pages: set[int]) -> dict[str, Any]:
    batch = extraction.get("evidence_batch") or {"evidences": []}
    contexts = extraction.get("evidence_contexts") or {}
    evidences = [item for item in batch.get("evidences", []) if item.get("data_status") == "valid" and item.get("numeric_value") is not None]
    used: set[str] = set()
    bindings: list[dict[str, Any]] = []
    missing: list[str] = []
    unit_mismatches: list[str] = []

    question_tokens = set(re.findall(r"[a-z0-9_]{2,}", _plain(plan["original_question"])))
    for fact in plan["facts"]:
        candidates: list[tuple[int, dict[str, Any]]] = []
        for evidence in evidences:
            if evidence["evidence_key"] in used or int(evidence["page_number"]) not in selected_pages:
                continue
            semantic = evidence.get("semantic") or {}
            evidence_period = (semantic.get("period") or {}).get("label")
            if fact.get("period") and evidence_period != fact["period"]:
                continue
            if fact.get("unit") and semantic.get("unit") and fact["unit"] != semantic["unit"]:
                unit_mismatches.append(fact["fact_key"])
                continue
            score = 0
            if fact.get("period") and evidence_period == fact["period"]:
                score += 20
            if fact.get("measure") != "unknown" and semantic.get("measure") == fact["measure"]:
                score += 10
            context_tokens = set(re.findall(r"[a-z0-9_]{2,}", _plain(contexts.get(evidence["evidence_key"], ""))))
            score += len(question_tokens & context_tokens)
            score += 2 if evidence.get("source_type") == "table" else 1
            candidates.append((score, evidence))
        if not candidates:
            missing.append(fact["fact_key"])
            continue
        _, selected = max(candidates, key=lambda item: (item[0], -int(item[1]["page_number"])))
        used.add(selected["evidence_key"])
        bindings.append(
            {
                "fact_key": fact["fact_key"],
                "evidence_key": selected["evidence_key"],
                "evidence_revision_id": selected.get("current_revision_id") or f"evr:{plan['document_version_id']}:{selected['evidence_key']}",
                "value": selected["numeric_value"],
                "unit": (selected.get("semantic") or {}).get("unit"),
                "page_number": selected["page_number"],
                "bbox": selected["bbox"],
                "method_label": selected["method_label"],
                "raw_text": selected.get("raw_text"),
            }
        )

    status = "resolved"
    if missing:
        status = "unit_mismatch" if unit_mismatches and set(missing) <= set(unit_mismatches) else "chart_required"
    return {"status": status, "bindings": bindings, "missing_fact_keys": missing, "unit_mismatch_fact_keys": sorted(set(unit_mismatches))}


def execute_calculation(plan: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    operation = plan["operation"]
    operands_by_key = {item["fact_key"]: item for item in resolution["bindings"]}
    ordered = [operands_by_key.get(key) for key in operation["operand_fact_keys"]]
    if any(item is None for item in ordered):
        reason = "UNIT_MISMATCH" if resolution["status"] == "unit_mismatch" else "MISSING_DATA"
        status = "unit_mismatch" if reason == "UNIT_MISMATCH" else "missing_data"
        available_operands = [_public_operand(item) for item in resolution["bindings"]]
        return {"schema_version": 1, "question_plan_id": plan["question_plan_id"], "status": status, "formula_id": operation["formula_id"], "operands": available_operands, "value": None, "unit": operation.get("result_unit"), "reason_code": reason, "warnings": [f"Thiếu fact: {', '.join(resolution['missing_fact_keys'])}"]}

    operand_units = {item.get("unit") for item in ordered if item.get("unit") is not None}
    percentage_point_units_invalid = operation["type"] == "percentage_point_change" and any(
        item.get("unit") not in {None, "PERCENT"} for item in ordered
    )
    if len(operand_units) > 1 or percentage_point_units_invalid:
        return {"schema_version": 1, "question_plan_id": plan["question_plan_id"], "status": "unit_mismatch", "formula_id": operation["formula_id"], "operands": [], "value": None, "unit": None, "reason_code": "UNIT_MISMATCH", "warnings": ["Các toán hạng không cùng đơn vị."]}

    try:
        values = [Decimal(item["value"]) for item in ordered]
        if operation["type"] == "lookup":
            result = values[0]
        elif operation["type"] == "sum":
            result = sum(values, Decimal("0"))
        elif operation["type"] in {"difference", "absolute_change", "percentage_point_change"}:
            result = values[0] - values[1]
        elif operation["type"] == "growth_rate":
            if values[1] == 0:
                return {"schema_version": 1, "question_plan_id": plan["question_plan_id"], "status": "zero_denominator", "formula_id": operation["formula_id"], "operands": [_public_operand(item) for item in ordered], "value": None, "unit": "PERCENT", "reason_code": "ZERO_DENOMINATOR", "warnings": ["Giá trị kỳ gốc bằng 0."]}
            result = (values[0] - values[1]) / values[1] * Decimal("100")
        else:
            return {"schema_version": 1, "question_plan_id": plan["question_plan_id"], "status": "ambiguous", "formula_id": operation["formula_id"], "operands": [_public_operand(item) for item in ordered], "value": None, "unit": operation.get("result_unit"), "reason_code": "AMBIGUOUS_INPUT", "warnings": ["Operation chưa có scalar result trong P0."]}
    except (InvalidOperation, ValueError):
        return {"schema_version": 1, "question_plan_id": plan["question_plan_id"], "status": "ambiguous", "formula_id": operation["formula_id"], "operands": [], "value": None, "unit": operation.get("result_unit"), "reason_code": "AMBIGUOUS_INPUT", "warnings": ["Giá trị đầu vào không hợp lệ."]}

    value = format(result, "f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    if value in {"", "-0"}:
        value = "0"
    unit = operation.get("result_unit") or next((item.get("unit") for item in ordered if item.get("unit")), None)
    return {"schema_version": 1, "question_plan_id": plan["question_plan_id"], "status": "succeeded", "formula_id": operation["formula_id"], "operands": [_public_operand(item) for item in ordered], "value": value, "unit": unit, "reason_code": None, "warnings": []}


def _public_operand(binding: dict[str, Any]) -> dict[str, Any]:
    return {"fact_key": binding["fact_key"], "evidence_revision_id": binding["evidence_revision_id"], "value": binding["value"], "unit": binding.get("unit")}


def calculation_answer(plan: dict[str, Any], result: dict[str, Any], bindings: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    if result["status"] != "succeeded":
        reason_messages = {
            "missing_data": "Không đủ dữ liệu để thực hiện phép tính.",
            "zero_denominator": "Không thể tính tỷ lệ thay đổi vì giá trị kỳ gốc bằng 0.",
            "unit_mismatch": "Không thể tính vì các giá trị không tương thích đơn vị.",
            "ambiguous": "Chưa thể xác định một kết quả duy nhất.",
        }
        answer = reason_messages[result["status"]]
    else:
        unit_label = "%" if result.get("unit") == "PERCENT" else (result.get("unit") or "")
        answer = f"Kết quả: {result['value']}{unit_label}."
    cited_pages = sorted({int(item["page_number"]) for item in bindings})
    structured = {
        "presentation": "deterministic_calculation_v1",
        "answer": answer,
        "summary": "Kết quả được tính bằng chương trình từ các evidence đã liên kết; AI không thực hiện phép tính.",
        "sections": [{"heading": "Kết quả", "points": [answer], "evidence_pages": cited_pages}],
        "formulas": [{"name": result["formula_id"], "expression": result["formula_id"], "substitution": " ; ".join(f"{item['fact_key']}={item['value']}" for item in result["operands"]), "result": result.get("value"), "unit": result.get("unit"), "evidence_pages": cited_pages, "calculation": {"status": result["status"], "computed_result": result.get("value"), "unit": result.get("unit"), "calculator": result["formula_id"]}}],
        "tables": [{"title": "Dữ liệu đầu vào", "columns": ["Fact", "Giá trị", "Đơn vị", "Nguồn"], "rows": [[item["fact_key"], item["value"], item.get("unit") or "", item["method_label"]] for item in bindings], "evidence_pages": cited_pages}],
        "claims": [],
        "warnings": result["warnings"],
        "cited_pages": cited_pages,
    }
    return answer, structured


__all__ = ["build_question_plan", "resolve_evidence", "execute_calculation", "calculation_answer"]
