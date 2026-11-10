from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "mock_data"
PDF_DIR = OUTPUT / "pdfs"
FIXED_TIME = "2026-01-15T08:00:00Z"

TABLES = (
    "users",
    "projects",
    "documents",
    "project_documents",
    "document_versions",
    "extraction_runs",
    "source_regions",
    "extracted_evidences",
    "chats",
    "chat_sources",
    "chat_evidences",
    "evidence_revisions",
    "messages",
    "answer_revisions",
    "answer_inputs",
    "answer_scopes",
    "message_pins",
    "auth_sessions",
    "account_tokens",
    "jobs",
    "job_events",
    "audit_events",
    "request_keys",
)


def uid(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"report-qa-mock:{name}"))


def dump_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def dump_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    path.write_text(text, encoding="utf-8")


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_simple_pdf(path: Path, pages: list[list[str]]) -> None:
    """Write a small valid ASCII PDF without external dependencies."""
    objects: list[bytes] = []
    page_object_ids = [4 + index * 2 for index in range(len(pages))]
    kids = " ".join(f"{object_id} 0 R" for object_id in page_object_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii")
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    for page_index, lines in enumerate(pages):
        page_id = page_object_ids[page_index]
        content_id = page_id + 1
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        commands = ["BT", "/F1 10 Tf", "48 744 Td"]
        for line_index, line in enumerate(lines):
            if line_index:
                commands.append("0 -15 Td")
            commands.append(f"({pdf_escape(line)}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("ascii", errors="replace")
        content = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
        objects.extend((page, content))

    output = bytearray(b"%PDF-1.4\n%mock\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(output)


def semantic(
    measure: str,
    subject: str | None,
    period: str | None,
    *,
    unit: str | None = "VND_MILLION",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "measure": {"code": measure.lower().replace(" ", "_"), "label": measure},
        "subject": None if subject is None else {"code": subject.lower().replace(" ", "_"), "label": subject},
        "unit": None
        if unit is None
        else {"code": unit, "label": "triệu đồng", "multiplier": "1000000"},
        "period": {
            "status": "partial" if period else "not_applicable",
            "label": period,
            "start": None,
            "end": None,
            "basis": "explicit" if period else None,
            "source_region_ids": [],
        },
        "dimensions": {},
        "value_operator": "eq",
    }


def build_domain_seed() -> dict[str, list[dict[str, Any]]]:
    data = {table: [] for table in TABLES}
    alice, bob = uid("user-alice"), uid("user-bob")
    project_a, project_b = uid("project-a"), uid("project-b")
    doc_sales, doc_missing, doc_bob = uid("doc-sales"), uid("doc-missing"), uid("doc-bob")
    version_sales_v1, version_sales_v2 = uid("sales-v1"), uid("sales-v2")
    version_missing, version_bob = uid("missing-v1"), uid("bob-v1")
    run_sales_v1, run_sales_v2 = uid("run-sales-v1"), uid("run-sales-v2")
    run_missing, run_bob = uid("run-missing"), uid("run-bob")

    data["users"] = [
        {"id": alice, "email": "alice@example.test", "normalized_email": "alice@example.test", "display_name": "Alice", "created_at": FIXED_TIME},
        {"id": bob, "email": "bob@example.test", "normalized_email": "bob@example.test", "display_name": "Bob", "created_at": FIXED_TIME},
    ]
    data["projects"] = [
        {"id": project_a, "owner_id": alice, "name": "Phân tích doanh thu", "created_at": FIXED_TIME},
        {"id": project_b, "owner_id": bob, "name": "Dữ liệu Bob", "created_at": FIXED_TIME},
    ]
    data["documents"] = [
        {"id": doc_sales, "owner_id": alice, "title": "Báo cáo doanh thu", "created_at": FIXED_TIME},
        {"id": doc_missing, "owner_id": alice, "title": "Báo cáo thiếu lợi nhuận", "created_at": FIXED_TIME},
        {"id": doc_bob, "owner_id": bob, "title": "Tài liệu riêng Bob", "created_at": FIXED_TIME},
    ]
    data["project_documents"] = [
        {"owner_id": alice, "project_id": project_a, "document_id": doc_sales, "added_at": FIXED_TIME},
        {"owner_id": alice, "project_id": project_a, "document_id": doc_missing, "added_at": FIXED_TIME},
        {"owner_id": bob, "project_id": project_b, "document_id": doc_bob, "added_at": FIXED_TIME},
    ]
    data["document_versions"] = [
        {"id": version_sales_v1, "document_id": doc_sales, "version_no": 1, "file_name": "sales-v1.pdf", "storage_key": "alice/sales/v1.pdf", "file_hash": "mock-sales-v1", "byte_size": 1000, "page_count": 3, "status": "ready", "uploaded_at": FIXED_TIME},
        {"id": version_sales_v2, "document_id": doc_sales, "version_no": 2, "file_name": "sales-v2.pdf", "storage_key": "alice/sales/v2.pdf", "file_hash": "mock-sales-v2", "byte_size": 1100, "page_count": 3, "status": "ready", "uploaded_at": FIXED_TIME},
        {"id": version_missing, "document_id": doc_missing, "version_no": 1, "file_name": "missing.pdf", "storage_key": "alice/missing/v1.pdf", "file_hash": "mock-missing", "byte_size": 800, "page_count": 2, "status": "ready", "uploaded_at": FIXED_TIME},
        {"id": version_bob, "document_id": doc_bob, "version_no": 1, "file_name": "bob.pdf", "storage_key": "bob/private/v1.pdf", "file_hash": "mock-bob", "byte_size": 700, "page_count": 2, "status": "ready", "uploaded_at": FIXED_TIME},
    ]
    data["extraction_runs"] = [
        {"id": run_sales_v1, "document_version_id": version_sales_v1, "run_no": 1, "status": "completed", "extractor_name": "mock", "extractor_version": "1", "config": {"schema_version": 1}, "created_at": FIXED_TIME},
        {"id": run_sales_v2, "document_version_id": version_sales_v2, "run_no": 1, "status": "completed", "extractor_name": "mock", "extractor_version": "1", "config": {"schema_version": 1}, "created_at": FIXED_TIME},
        {"id": run_missing, "document_version_id": version_missing, "run_no": 1, "status": "completed", "extractor_name": "mock", "extractor_version": "1", "config": {"schema_version": 1}, "created_at": FIXED_TIME},
        {"id": run_bob, "document_version_id": version_bob, "run_no": 1, "status": "completed", "extractor_name": "mock", "extractor_version": "1", "config": {"schema_version": 1}, "created_at": FIXED_TIME},
    ]

    evidence_specs = [
        ("mb-q1", run_sales_v1, 2, "chart_element", "38", "Doanh thu", "Miền Bắc", "Quý 1", "valid"),
        ("mb-q3", run_sales_v1, 2, "chart_element", "87", "Doanh thu", "Miền Bắc", "Quý 3", "valid"),
        ("mn-q1", run_sales_v1, 2, "chart_element", "50", "Doanh thu", "Miền Nam", "Quý 1", "valid"),
        ("mn-q3", run_sales_v1, 2, "chart_element", "90", "Doanh thu", "Miền Nam", "Quý 3", "valid"),
        ("zero-q1", run_sales_v1, 2, "table_cell", "0", "Chi phí", "Miền Trung", "Quý 1", "valid"),
        ("context-vat", run_sales_v1, 1, "paragraph", None, "Định nghĩa doanh thu", None, None, "valid"),
        ("profit-missing", run_missing, 1, "paragraph", None, "Lợi nhuận", None, None, "missing"),
        ("bob-private", run_bob, 1, "table_cell", "999", "Doanh thu", "Riêng tư", "Quý 1", "valid"),
        ("mb-q1-v2", run_sales_v2, 2, "chart_element", "58", "Doanh thu", "Miền Bắc", "Quý 1", "valid"),
        ("mb-q3-v2", run_sales_v2, 2, "chart_element", "87", "Doanh thu", "Miền Bắc", "Quý 3", "valid"),
    ]
    region_by_name: dict[str, str] = {}
    evidence_by_name: dict[str, str] = {}
    for index, (name, run_id, page, region_type, raw, measure, subject, period, status) in enumerate(evidence_specs, start=1):
        region_id, evidence_id = uid(f"region-{name}"), uid(f"evidence-{name}")
        region_by_name[name], evidence_by_name[name] = region_id, evidence_id
        data["source_regions"].append(
            {
                "id": region_id,
                "extraction_run_id": run_id,
                "region_key": name,
                "page_number": page,
                "bbox": [0.1, 0.1 + index * 0.02, 0.8, 0.18 + index * 0.02],
                "region_type": region_type,
                "extracted_text": "Doanh thu chưa bao gồm thuế" if name == "context-vat" else raw,
                "meta": {"schema_version": 1},
                "created_at": FIXED_TIME,
            }
        )
        value_kind = "text" if name == "context-vat" else "number"
        raw_text = "Doanh thu chưa bao gồm thuế" if name == "context-vat" else None
        data["extracted_evidences"].append(
            {
                "id": evidence_id,
                "extraction_run_id": run_id,
                "source_region_id": region_id,
                "value_kind": value_kind,
                "raw_value": raw if value_kind == "number" and status == "valid" else None,
                "raw_text": raw_text if status == "valid" else None,
                "semantic": semantic(measure, subject, period, unit=None if value_kind == "text" else "VND_MILLION"),
                "data_status": status,
                "extraction_method": "text" if value_kind == "text" else "direct_label",
                "confidence": "0.95" if status == "valid" else None,
                "created_at": FIXED_TIME,
            }
        )

    chat_a, chat_b, chat_bob = uid("chat-a"), uid("chat-b"), uid("chat-bob")
    source_a, source_b, source_bob = uid("source-a"), uid("source-b"), uid("source-bob")
    data["chats"] = [
        {"id": chat_a, "owner_id": alice, "project_id": project_a, "title": "Xếp hạng doanh thu A", "data_revision": 1, "next_sequence_no": 3, "created_at": FIXED_TIME},
        {"id": chat_b, "owner_id": alice, "project_id": project_a, "title": "Phiên độc lập B", "data_revision": 0, "next_sequence_no": 1, "created_at": FIXED_TIME},
        {"id": chat_bob, "owner_id": bob, "project_id": project_b, "title": "Chat riêng Bob", "data_revision": 0, "next_sequence_no": 1, "created_at": FIXED_TIME},
    ]
    data["chat_sources"] = [
        {"id": source_a, "chat_id": chat_a, "document_version_id": version_sales_v1, "extraction_run_id": run_sales_v1, "source_status": "active", "added_at": FIXED_TIME},
        {"id": source_b, "chat_id": chat_b, "document_version_id": version_sales_v1, "extraction_run_id": run_sales_v1, "source_status": "active", "added_at": FIXED_TIME},
        {"id": source_bob, "chat_id": chat_bob, "document_version_id": version_bob, "extraction_run_id": run_bob, "source_status": "active", "added_at": FIXED_TIME},
    ]

    current_revision: dict[tuple[str, str], str] = {}
    chat_evidence_ids: dict[tuple[str, str], str] = {}
    for chat_name, chat_id, source_id, names in (
        ("a", chat_a, source_a, ("mb-q1", "mb-q3", "mn-q1", "mn-q3", "zero-q1", "context-vat")),
        ("b", chat_b, source_b, ("mb-q1", "mb-q3", "mn-q1", "mn-q3")),
        ("bob", chat_bob, source_bob, ("bob-private",)),
    ):
        for name in names:
            ce_id, er_id = uid(f"chat-evidence-{chat_name}-{name}"), uid(f"evidence-revision-{chat_name}-{name}-1")
            chat_evidence_ids[(chat_name, name)] = ce_id
            current_revision[(chat_name, name)] = er_id
            origin = next(row for row in data["extracted_evidences"] if row["id"] == evidence_by_name[name])
            data["chat_evidences"].append(
                {"id": ce_id, "chat_id": chat_id, "chat_source_id": source_id, "extracted_evidence_id": evidence_by_name[name], "extraction_run_id": origin["extraction_run_id"], "current_revision_id": er_id, "created_at": FIXED_TIME}
            )
            data["evidence_revisions"].append(
                {
                    "id": er_id,
                    "chat_id": chat_id,
                    "chat_evidence_id": ce_id,
                    "revision_no": 1,
                    "value_kind": origin["value_kind"],
                    "numeric_value": origin["raw_value"],
                    "text_value": origin["raw_text"],
                    "semantic": origin["semantic"],
                    "data_status": origin["data_status"],
                    "verification_status": "unverified",
                    "action": "initialize",
                    "reason": None,
                    "created_by": None,
                    "created_at": FIXED_TIME,
                }
            )

    question, assistant = uid("message-question-a"), uid("message-answer-a")
    answer = uid("answer-revision-a-1")
    data["messages"] = [
        {"id": question, "chat_id": chat_a, "role": "user", "content": "Trong quý 3, khu vực nào tăng nhiều nhất so với quý 1 theo tỷ lệ phần trăm?", "reply_to_message_id": None, "sequence_no": 1, "status": "accepted", "needs_update": False, "current_answer_revision_id": None, "created_at": FIXED_TIME},
        {"id": assistant, "chat_id": chat_a, "role": "assistant", "content": "", "reply_to_message_id": question, "sequence_no": 2, "status": "completed", "needs_update": False, "current_answer_revision_id": answer, "created_at": FIXED_TIME},
    ]
    data["answer_revisions"] = [
        {
            "id": answer,
            "chat_id": chat_a,
            "message_id": assistant,
            "revision_no": 1,
            "answer_status": "answered",
            "question_context": {
                "schema_version": 1,
                "measure": {"code": "doanh_thu", "label": "Doanh thu"},
                "subjects": {"mode": "all_in_scope", "values": []},
                "requested_periods": [
                    {"label": "Quý 1", "status": "partial"},
                    {"label": "Quý 3", "status": "partial"}
                ],
                "time_required": True,
                "operation": "ranking",
                "comparison_basis": "percent",
                "dimensions": {},
                "ambiguities": []
            },
            "operation": {"schema_version": 1, "name": "growth_rate_ranking", "calculator_version": 1},
            "result": {"schema_version": 1, "defined": True, "winner_subjects": ["Miền Bắc"], "value": "128.9473684210526315789473684"},
            "answer_text": "Miền Bắc tăng cao nhất.",
            "assessment": {"schema_version": 1, "complete": True, "reasons": []},
            "input_data_revision": 1,
            "created_at": FIXED_TIME,
        }
    ]
    for name, key in (("mb-q1", "MB_Q1"), ("mb-q3", "MB_Q3"), ("mn-q1", "MN_Q1"), ("mn-q3", "MN_Q3")):
        data["answer_inputs"].append(
            {"answer_revision_id": answer, "evidence_revision_id": current_revision[("a", name)], "chat_id": chat_a, "role": "comparison_group", "param_key": key, "created_at": FIXED_TIME}
        )
    data["answer_inputs"].append(
        {"answer_revision_id": answer, "evidence_revision_id": current_revision[("a", "context-vat")], "chat_id": chat_a, "role": "context_text", "param_key": "CONTEXT_VAT", "created_at": FIXED_TIME}
    )
    data["answer_scopes"] = [
        {"id": uid("answer-scope-a-1"), "answer_revision_id": answer, "chat_source_id": source_a, "chat_id": chat_a, "filter": {"schema_version": 1, "measure_key": "doanh_thu", "subject_mode": "all", "subject_keys": [], "period_keys": ["Quý 1", "Quý 3"], "dimensions": {}, "region_ids": [], "include_text_context": True}, "created_at": FIXED_TIME}
    ]
    data["message_pins"] = [
        {"id": uid("pin-a"), "owner_id": alice, "chat_id": chat_a, "message_id": assistant, "answer_revision_id": answer, "pinned_at": FIXED_TIME}
    ]
    data["auth_sessions"] = [
        {"id": uid("session-alice"), "user_id": alice, "token_hash": "sha256:session-alice", "created_at": FIXED_TIME, "expires_at": "2026-02-15T08:00:00Z", "revoked_at": None}
    ]
    data["account_tokens"] = [
        {"id": uid("reset-bob"), "user_id": bob, "token_hash": "sha256:reset-bob", "purpose": "reset_password", "created_at": FIXED_TIME, "expires_at": "2026-01-15T09:00:00Z", "used_at": None}
    ]
    answer_job = uid("job-answer-a-1")
    data["jobs"] = [
        {"id": answer_job, "owner_id": alice, "chat_id": chat_a, "kind": "answer_question", "dedup_key": f"answer:{assistant}:1", "status": "succeeded", "input_data_revision": 1, "payload": {"schema_version": 1, "message_id": assistant}, "result": {"answer_revision_id": answer}, "attempts": 1, "max_attempts": 3, "created_at": FIXED_TIME}
    ]
    data["job_events"] = [
        {"id": uid("job-event-answer-a-1"), "job_id": answer_job, "event_no": 1, "event_type": "succeeded", "payload": {"answer_revision_id": answer}, "created_at": FIXED_TIME}
    ]
    data["audit_events"] = [
        {"id": uid("audit-login-alice"), "actor_id": alice, "action": "auth.login", "target_type": "user", "target_id": alice, "metadata": {"schema_version": 1}, "created_at": FIXED_TIME}
    ]
    data["request_keys"] = [
        {"owner_id": alice, "route": "POST /api/v1/chats/{id}/messages", "key": "seed-question-a", "request_hash": "seed-hash", "response_status": 202, "response": {"assistant_message_id": assistant, "job_id": answer_job}, "created_at": FIXED_TIME, "expires_at": "2026-01-18T08:00:00Z"}
    ]
    data["_ids"] = [
        {
            "alice": alice,
            "bob": bob,
            "chat_a": chat_a,
            "chat_b": chat_b,
            "chat_bob": chat_bob,
            "source_a": source_a,
            "source_b": source_b,
            "assistant_a": assistant,
            "answer_a": answer,
            "ce_a_mb_q1": chat_evidence_ids[("a", "mb-q1")],
            "er_a_mb_q1": current_revision[("a", "mb-q1")],
            "ce_b_mb_q1": chat_evidence_ids[("b", "mb-q1")],
            "er_b_mb_q1": current_revision[("b", "mb-q1")],
            "version_sales_v2": version_sales_v2,
            "run_sales_v2": run_sales_v2,
        }
    ]
    return data


def build_reports() -> list[dict[str, Any]]:
    reports = []
    feature_sets = (
        ["paragraph", "table"],
        ["paragraph", "grouped_bar"],
        ["paragraph", "line_chart"],
        ["table", "missing_value"],
        ["table", "source_conflict"],
    )
    for index in range(1, 21):
        report_id = f"syn-report-{index:03d}"
        page_count = 2 + index % 3
        reports.append(
            {
                "report_id": report_id,
                "version": 1,
                "language": "vi",
                "page_count": page_count,
                "source_kind": "synthetic",
                "license": "project-owned",
                "features": feature_sets[(index - 1) % len(feature_sets)],
                "file": f"pdfs/{report_id}.pdf",
                "generator_version": 1,
            }
        )
    return reports


def write_report_pdfs(reports: list[dict[str, Any]]) -> None:
    for index, report in enumerate(reports, start=1):
        pages = []
        for page in range(1, report["page_count"] + 1):
            pages.append(
                [
                    f"MOCK REPORT {index:03d} - PAGE {page}",
                    "Measure: Doanh thu (million VND)",
                    "Mien Bac: Q1=38 Q3=87",
                    "Mien Nam: Q1=50 Q3=90",
                    "Context: revenue excludes tax",
                    f"Features: {', '.join(report['features'])}",
                ]
            )
        write_simple_pdf(PDF_DIR / f"{report['report_id']}.pdf", pages)


def build_questions(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    distribution = {
        "dev": (("lookup", 30), ("calculation", 30), ("mixed", 20), ("followup", 20), ("exception", 20)),
        "final": (("lookup", 15), ("calculation", 15), ("mixed", 10), ("followup", 10), ("exception", 10)),
    }
    report_ids = {
        "dev": [row["report_id"] for row in reports[:14]],
        "final": [row["report_id"] for row in reports[14:]],
    }
    rows = []
    number = 0
    for split, groups in distribution.items():
        split_counter = 0
        for task, count in groups:
            for local_index in range(count):
                number += 1
                report_id = report_ids[split][split_counter % len(report_ids[split])]
                split_counter += 1
                action = "answer"
                reason_code = None
                if task == "exception":
                    action, reason_code = (
                        ("insufficient_data", "missing_measure"),
                        ("clarify", "ambiguous_growth_basis"),
                        ("select_source", "source_conflict"),
                    )[local_index % 3]
                question_text = {
                    "lookup": "Doanh thu quý 1 của Miền Bắc là bao nhiêu?",
                    "calculation": "Khu vực nào tăng nhiều nhất từ quý 1 đến quý 3 theo phần trăm?",
                    "mixed": "Theo định nghĩa trong báo cáo, doanh thu quý 3 của Miền Nam là bao nhiêu?",
                    "followup": "Còn nếu so với quý 2 thì sao?",
                    "exception": "Chỉ tiêu này tăng nhiều nhất là bao nhiêu?",
                }[task]
                rows.append(
                    {
                        "question_id": f"q-{number:04d}",
                        "split": split,
                        "report_id": report_id,
                        "conversation_id": f"{split}-{report_id}-conv-{local_index // 2:03d}-{task}",
                        "turn_no": 1 + local_index % 2,
                        "question_vi": question_text,
                        "primary_task": task,
                        "tags": ["table" if local_index % 2 == 0 else "bar_chart", "direct_label"],
                        "expected_action": action,
                        "reason_code": reason_code,
                        "oracle_answer": None
                        if action != "answer"
                        else {
                            "schema_version": 1,
                            "defined": True,
                            "value": "38" if task == "lookup" else "80",
                            "unit": "VND_MILLION" if task == "lookup" else "PERCENT",
                            "winner_subjects": [] if task == "lookup" else ["Miền Nam"],
                        },
                        "required_evidence_ids": [f"{report_id}-ev-01"],
                        "scope": {"measure_key": "doanh_thu", "period_keys": ["Q1", "Q3"]},
                    }
                )
    return rows


def build_mutations(domain: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    ids = domain["_ids"][0]
    templates = [
        ("38", "58", [ids["answer_a"]], "winner changes to Mien Nam"),
        ("38", "0", [ids["answer_a"]], "growth becomes undefined for one subject"),
        ("38", None, [ids["answer_a"]], "missing member prevents complete ranking"),
        ("38", "38", [], "verification-only revision preserves result"),
    ]
    rows = []
    for index in range(12):
        before, after, affected, expectation = templates[index % len(templates)]
        rows.append(
            {
                "mutation_id": f"mutation-{index + 1:03d}",
                "chat_id": ids["chat_a"],
                "chat_evidence_id": ids["ce_a_mb_q1"],
                "from": before,
                "to": after,
                "data_status": "missing" if after is None else "valid",
                "reason": f"mock mutation {index + 1}",
                "affected_answer_ids": affected,
                "expectation": expectation,
            }
        )
    return rows


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    domain = build_domain_seed()
    reports = build_reports()
    questions = build_questions(reports)
    mutations = build_mutations(domain)
    write_report_pdfs(reports)

    dump_json(OUTPUT / "domain_seed.json", domain)
    dump_jsonl(OUTPUT / "reports.jsonl", reports)
    dump_jsonl(OUTPUT / "evaluation_questions.jsonl", questions)
    dump_jsonl(OUTPUT / "mutation_scenarios.jsonl", mutations)

    files = [
        OUTPUT / "domain_seed.json",
        OUTPUT / "reports.jsonl",
        OUTPUT / "evaluation_questions.jsonl",
        OUTPUT / "mutation_scenarios.jsonl",
        *sorted(PDF_DIR.glob("*.pdf")),
    ]
    manifest = {
        "schema_version": 1,
        "generated_at": FIXED_TIME,
        "generator": "scripts/generate_mock_data.py",
        "counts": {
            "domain_tables": len(TABLES),
            "domain_rows": sum(len(domain[table]) for table in TABLES),
            "reports": len(reports),
            "questions": len(questions),
            "mutations": len(mutations),
            "pdfs": len(list(PDF_DIR.glob("*.pdf"))),
        },
        "sha256": {str(path.relative_to(OUTPUT)).replace("\\", "/"): file_hash(path) for path in files},
    }
    dump_json(OUTPUT / "manifest.json", manifest)
    print(json.dumps(manifest["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
