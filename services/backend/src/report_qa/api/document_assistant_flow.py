"""Persist document-aware assistant answers using the local session runtime."""

import json
from uuid import uuid4

from report_qa.api.ai_provider import ProviderError, planner_client
from report_qa.api.session_storage import (
    document_path,
    extraction_path,
    save_catalog,
    utc_now,
)
from report_qa.application.chart_tool import read_chart_region
from report_qa.application.document_assistant import evidence_label, run_assistant
from report_qa.application.extraction_contract import validate_extraction_batch

MAX_CONTEXT_CHARS = 300_000


def with_chart_batches(document, extraction):
    """Base Docling evidence plus every on-demand chart batch, newest first."""
    result = json.loads(json.dumps(extraction))
    evidences = result["evidence_batch"]["evidences"]
    seen = {e["evidence_key"] for e in evidences}
    for record in reversed(document.get("chart_extractions", [])):
        for e in record["evidence_batch"]["evidences"]:
            if e["evidence_key"] not in seen:
                evidences.append(e)
                seen.add(e["evidence_key"])
    return result


def _citation(evidence):
    return {
        "page": evidence["page_number"],
        "bbox": evidence["bbox"],
        "evidence_key": evidence["evidence_key"],
        "evidence_revision_id": evidence.get("current_revision_id"),
        "method_label": evidence["method_label"],
        "label": evidence_label(evidence),
        "value": evidence.get("numeric_value"),
        "raw_text": evidence.get("raw_text"),
        "data_status": evidence.get("data_status"),
    }


def _display(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def _formula(record, by_key):
    """One executed script: code, the Data rows it read and its output."""
    result = record["result"]
    inputs = [by_key[k] for k in result.get("used_evidence_keys", []) if k in by_key]
    return {
        "name": "Python",
        "expression": record["code"],
        "substitution": record["explanation"],
        "result": _display(result["result"]),
        "unit": None,
        "stdout": result.get("stdout") or "",
        "inputs": [
            {
                "evidence_key": e["evidence_key"],
                "label": evidence_label(e),
                "value": e.get("numeric_value"),
                "page": e["page_number"],
                "bbox": e["bbox"],
            }
            for e in inputs
        ],
        "calculation": {"status": "succeeded", "computed_result": _display(result["result"]), "unit": None},
    }


def answer_document(session, document, question, trace_id, trace, catalog, *, overlay, snapshot, complete=None):
    client = planner_client() if complete is None else None
    if complete is None and client is None:
        raise ProviderError("AI_NOT_CONFIGURED", "Document assistant requires an AI provider")
    complete = complete or client.complete
    extraction = json.loads(extraction_path(document["extraction_name"]).read_text(encoding="utf-8"))
    current = overlay(document, with_chart_batches(document, extraction))
    read_regions = {r.get("chart_region_key") for r in document.get("chart_extractions", [])}
    # Full text, current numeric values and readable chart regions.
    context = {
        "pages": current["pages"],
        "evidences": current["evidence_batch"]["evidences"],
        "chart_regions": [
            {**region, "read": region["chart_region_key"] in read_regions}
            for region in current.get("chart_regions", [])
        ],
        "history": [
            {"role": m["role"], "text": m.get("body", "")}
            for m in session["messages"]
            if m.get("document_id") == document["id"]
        ][-8:],
    }
    if len(json.dumps(context, ensure_ascii=False)) > MAX_CONTEXT_CHARS:
        raise ProviderError("DOCUMENT_CONTEXT_TOO_LARGE", "Document is too large for full-context mode")
    trace.append({
        "stage": "ai_context",
        "status": "ready",
        "at": utc_now(),
        "pages": len(context["pages"]),
        "numeric_values": len(context["evidences"]),
        "chart_regions": len(context["chart_regions"]),
        "provider": f"{client.mode}/{client.model}" if client else "injected",
    })

    def chart_tool(key):
        cached = next(
            (r for r in reversed(document.get("chart_extractions", [])) if r.get("chart_region_key") == key),
            None,
        )
        if cached is None:
            region = next(r for r in context["chart_regions"] if r["chart_region_key"] == key)
            result = read_chart_region(
                document_path(document["storage_name"]), region, document["id"], str(uuid4()), complete=complete,
            )
            validate_extraction_batch(result["evidence_batch"])
            document.setdefault("chart_extractions", []).append({**result, "chart_region_key": key, "created_at": utc_now()})
            # Persist chart values immediately so the Data drawer shows them,
            # even if a later model request fails.
            save_catalog(catalog)
        else:
            result = cached
        refreshed = overlay(document, with_chart_batches(document, extraction))
        batch_keys = {e["evidence_key"] for e in result["evidence_batch"]["evidences"]}
        return {
            "status": result["status"],
            "evidences": [e for e in refreshed["evidence_batch"]["evidences"] if e["evidence_key"] in batch_keys],
            "warnings": result["evidence_batch"]["warnings"],
            "all_evidences": refreshed["evidence_batch"]["evidences"],
        }

    result = run_assistant(question, context, complete=complete, read_chart=chart_tool)
    by_key = {e["evidence_key"]: e for e in context["evidences"]}
    used = [by_key[k] for k in result["evidence_keys"]]
    citations = [_citation(e) for e in used]
    citations += [{"page": page, "bbox": None} for page in result["pages"] if page not in {c["page"] for c in citations}]
    structured = {
        "presentation": "document_assistant",
        "answer": result["answer"],
        "summary": "Phép tính được chạy bằng script Python trên giá trị hiện tại của bảng Dữ liệu."
        if result["calculations"] else "",
        "sections": [],
        "formulas": [_formula(record, by_key) for record in result["calculations"]],
        "tables": [],
        "claims": [],
        "warnings": ["Một số giá trị biểu đồ chưa được xác minh; xem bảng Dữ liệu để kiểm tra."]
        if result["unverified_keys"] else [],
        "cited_pages": sorted({c["page"] for c in citations}),
        "options": result["options"],
    }
    now = utc_now()
    assistant = {
        "id": str(uuid4()),
        "role": "assistant",
        "body": result["answer"],
        "document_id": document["id"],
        "created_at": now,
        "mode": f"ai:{client.mode}" if client else "ai:injected",
        "trace_id": trace_id,
        "citations": citations,
        "structured_answer": structured,
        "answer_inputs": [
            {
                "evidence_key": e["evidence_key"],
                "evidence_revision_id": e.get("current_revision_id"),
                "value": e["numeric_value"],
                "page_number": e["page_number"],
                "bbox": e["bbox"],
            }
            for e in used
        ],
        "tool_calculations": result["calculations"],
        "tool_results": result["tool_results"],
    }
    snapshot(assistant)
    trace.extend({**event, "at": utc_now()} for event in result["trace"])
    trace.append({"stage": "persistence", "status": "committed", "at": utc_now(), "assistant_message_id": assistant["id"]})
    assistant["trace"] = trace
    user = {"id": str(uuid4()), "role": "user", "body": question, "document_id": document["id"], "created_at": now}
    session["messages"].extend([user, assistant])
    session["updated_at"] = now
    save_catalog(catalog)
    return {"user_message": user, "assistant_message": assistant, "trace_id": trace_id, "limitations": []}
