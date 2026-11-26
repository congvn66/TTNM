"""Persist document-aware assistant answers using the local session runtime."""

import json
from uuid import uuid4

from report_qa.api.ai_provider import ProviderError, planner_client
from report_qa.api.session_storage import (
    catalog_lock,
    document_path,
    extraction_path,
    save_catalog,
    utc_now,
)
from report_qa.application.chart_tool import read_chart_region
from report_qa.application.document_assistant import evidence_label, run_assistant
from report_qa.application.extraction_contract import validate_extraction_batch
from report_qa.application.text_evidence import quote_bbox
from report_qa.application.text_safety import storable

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
        "kind": "data",
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


def _quote_citation(pdf_path, source):
    try:
        bbox = quote_bbox(pdf_path, source["page"], source["quote"])
    except (ImportError, OSError, RuntimeError, ValueError):
        bbox = None  # the viewer still highlights by matching the quote text
    return {"kind": "text", "page": source["page"], "bbox": bbox, "quote": source["quote"], "match": source["match"]}


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
        "manual_numbers": result.get("manual_numbers") or [],
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


def _calculation_summary(calculations):
    if not calculations:
        return ""
    if any(record["result"].get("manual_numbers") for record in calculations):
        return "Phép tính được chạy bằng script Python; có số được gõ tay trong script, không lấy từ bảng Dữ liệu."
    return "Phép tính được chạy bằng script Python trên giá trị hiện tại của bảng Dữ liệu."


def _unverified_warning(evidences):
    if not evidences:
        return []
    if all(e.get("source_type") == "chart" for e in evidences):
        return ["Một số giá trị biểu đồ chưa được xác minh; xem bảng Dữ liệu để kiểm tra."]
    return ["Một số giá trị chưa được xác minh; xem bảng Dữ liệu để kiểm tra."]


def _history(session, document_id):
    """Recent finished turns; a queued question and its placeholder are not history."""
    turns = []
    for message in session["messages"]:
        if message.get("status") == "processing" or message.get("mode") == "answer_question_job":
            if turns and turns[-1]["role"] == "user":
                turns.pop()
            continue
        if message.get("document_id") == document_id:
            turns.append({"role": message["role"], "text": message.get("body", "")})
    return turns[-8:]


def answer_document(
    session, document, question, trace_id, trace, catalog, *,
    overlay, snapshot, complete=None, load_extraction=None, resolve_pdf=None, save=None, persist_chart=None,
):
    """Answer with the tools assistant and persist the exchange.

    The caller injects storage: local JSON by default, or PostgreSQL/R2 through
    load_extraction, resolve_pdf, save and persist_chart.
    """
    load_extraction = load_extraction or (lambda name: json.loads(extraction_path(name).read_text(encoding="utf-8")))
    resolve_pdf = resolve_pdf or document_path
    save = save or save_catalog
    client = planner_client() if complete is None else None
    if complete is None and client is None:
        raise ProviderError("AI_NOT_CONFIGURED", "Document assistant requires an AI provider")
    complete = complete or client.complete
    extraction = load_extraction(document["extraction_name"])
    unstored_keys = set()
    current = overlay(document, with_chart_batches(document, extraction))
    # A read whose visual check failed does not count: the AI may read it again.
    read_regions = {r.get("chart_region_key") for r in document.get("chart_extractions", []) if not r.get("visual_check_error")}
    # Full text, current numeric values and readable chart regions.
    context = {
        "pages": current["pages"],
        "evidences": current["evidence_batch"]["evidences"],
        "chart_regions": [
            {**region, "read": region["chart_region_key"] in read_regions}
            for region in current.get("chart_regions", [])
        ],
        "history": _history(session, document["id"]),
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
        # Reuse a completed read, but not one whose visual check failed (e.g.
        # provider HTTP 503): caching that left every value of the chart
        # unverified for good. DePlot's own output is cached on disk, so a
        # retry only repeats the visual check.
        cached = next(
            (
                r for r in reversed(document.get("chart_extractions", []))
                if r.get("chart_region_key") == key and not r.get("visual_check_error")
            ),
            None,
        )
        if cached is None:
            region = next(r for r in context["chart_regions"] if r["chart_region_key"] == key)
            result = storable(read_chart_region(
                resolve_pdf(document["storage_name"]), region, document.get("version_id") or document["id"], f"tools:{key}", complete=complete,
            ))
            validate_extraction_batch(result["evidence_batch"])
            # Persist chart values immediately so the Data drawer shows them,
            # even if a later model request fails.
            if persist_chart is not None and not result.get("visual_check_error"):
                persist_chart(result, key)
            elif persist_chart is not None:
                # Stored chart runs are immutable, so a read whose check failed
                # is used for this answer only and read again next time.
                unstored_keys.update(e["evidence_key"] for e in result["evidence_batch"]["evidences"])
            with catalog_lock:
                document.setdefault("chart_extractions", []).append({**result, "chart_region_key": key, "created_at": utc_now()})
            if persist_chart is None:
                save(catalog)
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
    pdf_path = resolve_pdf(document["storage_name"])
    citations = [_quote_citation(pdf_path, source) for source in result["sources"]]
    citations += [_citation(e) for e in used]
    citations += [
        {"kind": "page", "page": page, "bbox": None}
        for page in result["pages"]
        if page not in {c["page"] for c in citations}
    ]
    structured = {
        "presentation": "document_assistant",
        "answer": result["answer"],
        "summary": _calculation_summary(result["calculations"]),
        "sections": [],
        "formulas": [_formula(record, by_key) for record in result["calculations"]],
        "tables": [],
        "claims": [],
        "warnings": _unverified_warning([by_key[k] for k in result["unverified_keys"]]),
        "cited_pages": sorted({c["page"] for c in citations}),
        "evidence": citations,
        "not_found": result["not_found"],
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
                "evidence_revision_id": None if e["evidence_key"] in unstored_keys else e.get("current_revision_id"),
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
    user, assistant = storable(user), storable(assistant)
    with catalog_lock:
        session["messages"].extend([user, assistant])
        session["updated_at"] = now
    try:
        save(catalog)
    except Exception:
        # Not stored: keep the refused pair out of every later save.
        with catalog_lock:
            session["messages"] = [item for item in session["messages"] if item is not user and item is not assistant]
        raise
    return {"user_message": user, "assistant_message": assistant, "trace_id": trace_id, "limitations": []}
