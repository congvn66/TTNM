"""Persist document-aware assistant answers using the local session runtime."""

import json
import math
import re
from uuid import uuid4

from report_qa.api.ai_provider import MAX_ANSWER_CHARS, ProviderError, planner_client
from report_qa.api.session_storage import (
    catalog_lock,
    document_path,
    extraction_path,
    save_catalog,
    utc_now,
)
from report_qa.application.chart_tool import read_chart_region
from report_qa.application.document_assistant import (
    answer_timeout_seconds,
    data_rows,
    evidence_label,
    run_assistant,
    with_time_budget,
)
from report_qa.application.extraction_contract import validate_extraction_batch
from report_qa.application.text_evidence import quote_bbox
from report_qa.application.text_safety import storable

MAX_CONTEXT_CHARS = 300_000
_WORD = re.compile(r"\w+")
_NAMED_PAGES = re.compile(r"\b(?:trang|page)\s*(\d+)(?:\s*(?:-|–|đến|to)\s*(\d+))?", re.IGNORECASE)


def _size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def _model_view(context) -> dict:
    """What the model is sent about the document (the payload's document part)."""
    return {"pages": context["pages"], "data": data_rows(context["evidences"]),
            "chart_regions": context["chart_regions"], "history": context["history"]}


def _words(text) -> set[str]:
    return set(_WORD.findall(str(text).casefold()))


def named_pages(question: str) -> set[int]:
    """Pages the question names: "trang 5", "page 3", "trang 2-4"."""
    pages = set()
    for match in _NAMED_PAGES.finditer(question):
        first = int(match.group(1))
        last = int(match.group(2) or first)
        pages.update(range(first, min(last, first + 50) + 1))
    return pages


def fit_context(context: dict, question: str, budget: int = MAX_CONTEXT_CHARS) -> dict:
    """The whole document when it fits the budget; otherwise as much of it as fits.

    First the oldest history turns are dropped. If the document alone is still
    too large, the most relevant pages are sent whole, each with its Data rows
    and chart regions: pages the question names first, then the others by
    word overlap with the question and the last exchange (each shared word
    weighted by how few pages contain it, ties in page order), each page
    taken while it fits. The model is told which pages were left out.
    """
    history = list(context["history"])
    while history and _size(_model_view({**context, "history": history})) > budget:
        history.pop(0)
    if _size(_model_view({**context, "history": history})) <= budget:
        return context if len(history) == len(context["history"]) else {**context, "history": history}
    page_words = {p["page"]: _words(p.get("text", "")) for p in context["pages"]}
    query = _words(question) | set().union(*(_words(t["text"]) for t in context["history"][-2:]))
    pages_with = {w: sum(w in found for found in page_words.values()) for w in query}
    total = len(page_words)

    def relevance(page):
        return sum(math.log((1 + total) / pages_with[w]) for w in query & page_words[page["page"]])

    named = named_pages(question)
    room = budget - _size({"pages": [], "data": [], "chart_regions": [], "history": [],
                           "omitted_pages": [p["page"] for p in context["pages"]]})
    kept = set()
    for page in sorted(context["pages"], key=lambda p: (p["page"] not in named, -relevance(p), p["page"])):
        rows = [e for e in context["evidences"] if e["page_number"] == page["page"]]
        charts = [r for r in context["chart_regions"] if r.get("page_number") == page["page"]]
        cost = _size(page) + _size(data_rows(rows)) + _size(charts) + 3  # separators between items
        if cost <= room:
            room -= cost
            kept.add(page["page"])
    return {
        **context,
        "pages": [p for p in context["pages"] if p["page"] in kept],
        "evidences": [e for e in context["evidences"] if e["page_number"] in kept],
        "chart_regions": [r for r in context["chart_regions"] if r.get("page_number") in kept],
        "history": [],
        "omitted_pages": [p["page"] for p in context["pages"] if p["page"] not in kept],
    }


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


_NUMERAL = re.compile(r"\d+(?:[.,]\d+)*")


def quoted_rows(sources, evidences):
    """Data rows a quote states: same page, and every number of the row's raw PDF text is a number of the quote."""
    rows = []
    for source in sources:
        quoted = set(_NUMERAL.findall(source["quote"]))
        rows += [
            e for e in evidences
            if e["page_number"] == source["page"] and (numerals := _NUMERAL.findall(e.get("raw_text") or ""))
            and quoted.issuperset(numerals)
        ]
    return rows


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


def extraction_marker(document):
    """Changes whenever a re-run archives the extraction an answer may have read."""
    return len(document.get("extraction_history") or [])


def flag_if_inputs_changed(document, assistant, marker):
    """Mark an answer stale if its inputs changed while it was being made. Call under catalog_lock."""
    inputs = assistant.get("answer_inputs") or []
    if not inputs:
        return
    items = (document.get("evidence_state") or {}).get("items", {})
    edited = any(
        item.get("evidence_revision_id") is not None
        and item["evidence_key"] in items
        and items[item["evidence_key"]]["current_revision_id"] != item["evidence_revision_id"]
        for item in inputs
    )
    if edited or extraction_marker(document) != marker:
        assistant["needs_update"] = True


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
            # No stored turn may crowd the document out of the context; an
            # answer within the answer cap is kept whole.
            text = message.get("body", "")
            if len(text) > MAX_ANSWER_CHARS:
                text = text[:MAX_ANSWER_CHARS] + "…"
            turns.append({"role": message["role"], "text": text})
    return turns[-8:]


def answer_document(
    session, document, question, trace_id, trace, catalog, *,
    overlay, snapshot, complete=None, load_extraction=None, resolve_pdf=None, save=None, persist_chart=None,
):
    """Answer with the tools assistant and persist the exchange.

    The caller injects storage: local JSON by default, or PostgreSQL/R2 through
    load_extraction, resolve_pdf, save and persist_chart.
    """
    marker = extraction_marker(document)
    load_extraction = load_extraction or (lambda name: json.loads(extraction_path(name).read_text(encoding="utf-8")))
    resolve_pdf = resolve_pdf or document_path
    save = save or save_catalog
    client = planner_client() if complete is None else None
    if complete is None and client is None:
        raise ProviderError("AI_NOT_CONFIGURED", "Document assistant requires an AI provider")
    # One time budget covers every model call of this answer, chart checks included.
    complete = with_time_budget(complete or client.complete, answer_timeout_seconds())
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
    context = fit_context(context, question)
    trace.append({
        "stage": "ai_context",
        "status": "ready",
        "at": utc_now(),
        "pages": len(context["pages"]),
        "numeric_values": len(context["evidences"]),
        "chart_regions": len(context["chart_regions"]),
        "omitted_pages": context.get("omitted_pages", []),
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
        sent_pages = {p["page"] for p in context["pages"]}
        return {
            "status": result["status"],
            "evidences": [e for e in refreshed["evidence_batch"]["evidences"] if e["evidence_key"] in batch_keys],
            "warnings": result["evidence_batch"]["warnings"],
            "all_evidences": [e for e in refreshed["evidence_batch"]["evidences"] if e["page_number"] in sent_pages],
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
            for e in {e["evidence_key"]: e for e in used + quoted_rows(result["sources"], context["evidences"])}.values()
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
        flag_if_inputs_changed(document, assistant, marker)
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
