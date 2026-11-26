from io import BytesIO
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from report_qa.api import main as api_main
from report_qa.api.ai_provider import ProviderError
from report_qa.api.main import app


client = TestClient(app)


def pdf_with_text(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 50 760 Td ({safe_text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def cleanup_session(session_id: str) -> None:
    session = api_main.catalog["sessions"].pop(session_id, None)
    if session is None:
        return
    for document in session.get("documents", []):
        api_main.document_path(document["storage_name"]).unlink(missing_ok=True)
        if document.get("extraction_name"):
            api_main.extraction_path(document["extraction_name"]).unlink(missing_ok=True)
    api_main.save_catalog(api_main.catalog)


def test_health_docs_and_openapi_expose_only_the_main_flow() -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["ui_url"] == "http://127.0.0.1:4173"
    assert client.get("/favicon.ico").status_code == 204

    health = client.get("/health")
    assert health.status_code == 200
    health_body = health.json()
    assert {key: health_body[key] for key in (
        "status", "adapter", "durability", "ai_mode", "ai_model",
        "persistence_backend", "database", "storage",
    )} == {
        "status": "ok",
        "adapter": "local_json_filesystem",
        "durability": "local_disk_logical_state",
        "ai_mode": "deterministic",
        "ai_model": "deterministic",
        "persistence_backend": "json",
        "database": {"configured": False, "status": "disabled", "backend": "json"},
        "storage": {"backend": "local", "configured": True, "durability": "local_disk", "status": "ok"},
    }
    assert health_body["readiness"]["status"] in {"ready", "degraded"}
    assert health_body["capabilities"]["ai"] == {
        "selected": "deterministic", "status": "available", "network_probe": "not_run"
    }
    assert health.headers["x-persistence-backend"] == "json"

    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/",
        "/health",
        "/health/ready",
        "/api/v1/documents/uploads",
        "/api/v1/sessions",
        "/api/v1/sessions/{session_id}",
        "/api/v1/sessions/{session_id}/documents",
        "/api/v1/sessions/{session_id}/documents/{document_id}",
        "/api/v1/sessions/{session_id}/documents/{document_id}/file",
        "/api/v1/sessions/{session_id}/documents/{document_id}/extraction",
        "/api/v1/sessions/{session_id}/documents/{document_id}/evidences",
        "/api/v1/sessions/{session_id}/documents/{document_id}/evidences/{evidence_key}/revisions",
        "/api/v1/sessions/{session_id}/messages",
            "/api/v1/sessions/{session_id}/messages/{message_id}/trace",
            "/api/v1/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/cancel",
        "/api/v1/jobs/{job_id}/events",
        "/api/v1/jobs/{job_id}/retry",
        "/api/v1/projects/{project_id}/folders",
        "/api/v1/folders/{folder_id}",
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/library",
        "/api/v1/sessions/{session_id}/project",
        "/api/v1/projects/{project_id}/documents/{document_id}",
        "/api/v1/auth/sessions",
        "/api/v1/auth/sessions/{session_id}",
        "/api/v1/auth/sessions/revoke-others",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/change-password",
        "/api/v1/settings/profile",
        "/api/v1/settings/preferences",
        }
    assert schema["paths"]["/api/v1/sessions/{session_id}/messages"]["post"]["summary"] == (
        "Ask a grounded document question"
    )
    message_description = schema["paths"]["/api/v1/sessions/{session_id}/messages"]["post"]["description"]
    assert "question_received" in message_description
    assert "persistence" in message_description
    assert schema["paths"]["/api/v1/sessions/{session_id}/messages/{message_id}/trace"]["get"]["summary"] == (
        "Inspect persisted message data flow"
    )
    assert {"get", "patch", "delete"} <= set(schema["paths"]["/api/v1/sessions/{session_id}"])
    assert {"patch", "delete"} <= set(schema["paths"]["/api/v1/sessions/{session_id}/documents/{document_id}"])
    assert {tag["name"] for tag in schema["tags"]} == {"runtime", "sessions", "documents", "auth", "settings", "jobs", "library"}


def test_session_and_document_crud_archives_without_mutating_pdf_bytes() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Draft review"})
    assert created.status_code == 200
    session_id = created.json()["session"]["id"]
    storage_name = None
    try:
        renamed = client.patch(f"/api/v1/sessions/{session_id}", json={"title": "Board review"})
        assert renamed.status_code == 200
        assert renamed.json()["session"]["title"] == "Board review"

        uploaded = client.post(
            f"/api/v1/sessions/{session_id}/documents",
            files={"file": ("draft.pdf", pdf_with_text("Revenue is 120."), "application/pdf")},
        )
        assert uploaded.status_code == 200
        document = uploaded.json()["document"]
        storage_name = api_main.catalog["sessions"][session_id]["documents"][0]["storage_name"]
        document_id = document["id"]

        renamed_document = client.patch(
            f"/api/v1/sessions/{session_id}/documents/{document_id}", json={"file_name": "final-board-copy"}
        )
        assert renamed_document.status_code == 200
        assert renamed_document.json()["document"]["file_name"] == "final-board-copy.pdf"
        assert api_main.document_path(storage_name).exists()

        archived_document = client.delete(f"/api/v1/sessions/{session_id}/documents/{document_id}")
        assert archived_document.status_code == 200
        assert client.get(f"/api/v1/sessions/{session_id}").json()["session"]["documents"] == []
        assert api_main.document_path(storage_name).exists()

        archived_session = client.delete(f"/api/v1/sessions/{session_id}")
        assert archived_session.status_code == 200
        assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
    finally:
        if storage_name:
            api_main.document_path(storage_name).unlink(missing_ok=True)
        api_main.catalog["sessions"].pop(session_id, None)
        api_main.save_catalog(api_main.catalog)


def test_session_owns_documents_and_serves_the_uploaded_binary() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Bao cao quy"})
    assert created.status_code == 200
    session_id = created.json()["session"]["id"]
    try:
        source = pdf_with_text("SourceLens integration test")
        uploaded = client.post(
            f"/api/v1/sessions/{session_id}/documents",
            files={"file": ("quarter.pdf", source, "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        document = uploaded.json()["document"]
        assert document["status"] == "stored"
        assert document["byte_size"] == len(source)
        assert uploaded.json()["persistence"] == {
            "binary_retained": True,
            "max_bytes": 100 * 1024 * 1024,
            "max_pages": 500,
        }
        session = client.get(f"/api/v1/sessions/{session_id}").json()["session"]
        assert session["documents"][0]["file_name"] == "quarter.pdf"
        assert "storage_name" not in session["documents"][0]
        file_response = client.get(document["file_url"])
        assert file_response.status_code == 200
        assert file_response.content == source
    finally:
        cleanup_session(session_id)



def test_upload_rejects_malformed_pdf_and_page_limit() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Upload limits"}).json()["session"]
    previous_limit = api_main.MAX_PDF_PAGES
    try:
        malformed = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("broken.pdf", b"%PDF-1.7\nnot-a-pdf", "application/pdf")},
        )
        assert malformed.status_code == 422
        assert malformed.json()["detail"]["code"] == "INVALID_PDF"
        assert client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"] == []

        api_main.MAX_PDF_PAGES = 1
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        payload = BytesIO()
        writer.write(payload)
        too_many = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("many-pages.pdf", payload.getvalue(), "application/pdf")},
        )
        assert too_many.status_code == 413
        assert too_many.json()["detail"]["code"] == "PDF_TOO_MANY_PAGES"
        assert client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"] == []
    finally:
        api_main.MAX_PDF_PAGES = previous_limit
        cleanup_session(created["id"])


def test_password_protected_pdf_gets_its_own_error_code() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Encrypted"}).json()["session"]
    try:
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.encrypt("secret")
        payload = BytesIO()
        writer.write(payload)
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("locked.pdf", payload.getvalue(), "application/pdf")},
        )
        assert uploaded.status_code == 422
        assert uploaded.json()["detail"]["code"] == "PDF_ENCRYPTED"
        assert "mật khẩu" in uploaded.json()["detail"]["message"]
        assert client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"] == []
    finally:
        cleanup_session(created["id"])


def test_legacy_document_without_file_url_gets_a_reader_url() -> None:
    session_id = "legacy-url-test"
    document_id = "legacy-document"
    api_main.catalog["sessions"][session_id] = {
        "id": session_id,
        "owner_id": api_main.LOCAL_OWNER_ID,
        "title": "Legacy",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "documents": [{"id": document_id, "file_name": "legacy.pdf"}],
        "messages": [],
    }
    try:
        session = client.get(f"/api/v1/sessions/{session_id}")
        assert session.status_code == 200
        assert session.json()["session"]["documents"][0]["file_url"] == (
            f"/api/v1/sessions/{session_id}/documents/{document_id}/file"
        )
    finally:
        api_main.catalog["sessions"].pop(session_id, None)
        api_main.save_catalog(api_main.catalog)


def test_uploaded_pdf_is_extracted_and_chat_returns_a_page_citation() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Text retrieval"}).json()["session"]
    try:
        source = pdf_with_text("Adjusted operating profit increased from 185 to 470 in quarter one.")
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("profit.pdf", source, "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        document = uploaded.json()["document"]
        assert document["extraction_status"] == "queued"
        stored = client.get(f"/api/v1/sessions/{created['id']}").json()["session"]
        document = next(item for item in stored["documents"] if item["id"] == document["id"])
        assert document["extraction_status"] == "ready"
        assert document["page_count"] == 1
        assert document["numeric_evidence_count"] == 2

        answer = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document["id"], "question": "What was the adjusted operating profit?"},
        )
        assert answer.status_code == 200, answer.text
        assistant = answer.json()["assistant_message"]
        assert "185 to 470" in assistant["body"]
        assert assistant["mode"] == "deterministic_text_retrieval"
        assert assistant["citations"][0]["page"] == 1
        assert assistant["citations"][0]["score"] > 0

        trace = client.get(f"/api/v1/sessions/{created['id']}/messages/{assistant['id']}/trace")
        assert trace.status_code == 200
        events = trace.json()["trace"]
        assert [event["stage"] for event in events] == [
            "question_received",
            "question_plan",
            "retrieval",
            "answer_generation",
            "persistence",
        ]
        assert len(events[2]["context_manifest"][0]["text_sha256"]) == 64
    finally:
        cleanup_session(created["id"])


def test_message_idempotency_replays_without_duplicate_answer() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Idempotency"}).json()["session"]
    try:
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("idempotency.pdf", pdf_with_text("Revenue Q1/2026 was 120."), "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        document_id = uploaded.json()["document"]["id"]
        key = "test-idempotency-key"
        payload = {"document_id": document_id, "question": "What was revenue in Q1/2026?"}
        first = client.post(f"/api/v1/sessions/{created['id']}/messages", json=payload, headers={"Idempotency-Key": key})
        second = client.post(f"/api/v1/sessions/{created['id']}/messages", json=payload, headers={"Idempotency-Key": key})
        assert first.status_code == second.status_code == 200
        assert first.json()["assistant_message"]["id"] == second.json()["assistant_message"]["id"]
        session = client.get(f"/api/v1/sessions/{created['id']}").json()["session"]
        assert len(session["messages"]) == 2
        conflict = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document_id, "question": "A different question"},
            headers={"Idempotency-Key": key},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    finally:
        cleanup_session(created["id"])

def test_client_worker_header_does_not_skip_storing_the_answer() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Worker header"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2026 was 120.")
        asked = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document_id, "question": "What was revenue in Q1/2026?"},
            headers={"X-Worker-Job": "1"},
        )
        assert asked.status_code == 200, asked.text
        assert len(client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["messages"]) == 2
    finally:
        cleanup_session(created["id"])


def test_parallel_requests_with_one_idempotency_key_answer_once(monkeypatch) -> None:
    import threading
    import time

    real_plan = api_main.plan_question

    def slow_plan(*args, **kwargs):
        time.sleep(0.3)
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(api_main, "plan_question", slow_plan)
    created = client.post("/api/v1/sessions", json={"title": "Parallel idempotency"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2026 was 120.")
        payload = {"document_id": document_id, "question": "What was revenue in Q1/2026?"}
        responses = []

        def ask():
            responses.append(client.post(f"/api/v1/sessions/{created['id']}/messages", json=payload, headers={"Idempotency-Key": "parallel-key"}))

        threads = [threading.Thread(target=ask) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert [item.status_code for item in responses] == [200] * 4
        assert len({item.json()["assistant_message"]["id"] for item in responses}) == 1
        assert len(client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["messages"]) == 2
    finally:
        cleanup_session(created["id"])


def test_reading_evidences_saves_the_catalog_only_when_something_changed(monkeypatch) -> None:
    created = client.post("/api/v1/sessions", json={"title": "Read-only GET"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2026 was 120.")
        base = f"/api/v1/sessions/{created['id']}/documents/{document_id}"
        key = client.get(f"{base}/evidences").json()["evidences"][0]["evidence_key"]
        saves = []
        real_save = api_main.save_catalog
        monkeypatch.setattr(api_main, "save_catalog", lambda *args: (saves.append(1), real_save(*args))[1])
        assert client.get(f"{base}/evidences").status_code == 200
        assert client.get(f"{base}/evidences/{key}/revisions").status_code == 200
        assert saves == []
        api_main.catalog["sessions"][created["id"]]["documents"][0].pop("evidence_state")
        assert client.get(f"{base}/evidences").status_code == 200
        assert saves == [1]
    finally:
        cleanup_session(created["id"])


def test_unmatched_question_is_rejected_instead_of_sent_to_ai() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Retrieval guard"}).json()["session"]
    try:
        source = pdf_with_text("Adjusted operating profit increased from 185 to 470 in quarter one.")
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("profit.pdf", source, "application/pdf")},
        )
        document_id = uploaded.json()["document"]["id"]
        response = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document_id, "question": "Logo zebra magenta appendix?"},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "NO_TEXT_EVIDENCE"
    finally:
        cleanup_session(created["id"])


def test_growth_question_runs_planner_evidence_resolver_and_calculator() -> None:
    created = client.post("/api/v1/sessions", json={"title": "P0 calculation"}).json()["session"]
    try:
        source = pdf_with_text("Revenue Q1/2025 was 100. Revenue Q1/2026 was 120.")
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("growth.pdf", source, "application/pdf")},
        )
        document_id = uploaded.json()["document"]["id"]
        internal_document = next(
            item for item in api_main.catalog["sessions"][created["id"]]["documents"] if item["id"] == document_id
        )
        api_main.extraction_path(internal_document["extraction_name"]).write_text(
            json.dumps({"pages": [{"page": 1, "text": "Revenue Q1/2025 was 100. Revenue Q1/2026 was 120."}]}),
            encoding="utf-8",
        )
        internal_document["numeric_evidence_count"] = 0
        response = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={
                "document_id": document_id,
                "question": "By what percent did revenue change from Q1/2025 to Q1/2026?",
            },
        )
        assert response.status_code == 200, response.text
        assistant = response.json()["assistant_message"]
        assert assistant["mode"] == "deterministic_calculation"
        assert assistant["calculation_result"]["status"] == "succeeded"
        assert assistant["calculation_result"]["value"] == "20"
        assert assistant["calculation_result"]["formula_id"] == "growth_rate_v1"
        assert api_main.catalog["sessions"][created["id"]]["documents"][0]["numeric_evidence_count"] == 2
        assert [item["fact_key"] for item in assistant["answer_inputs"]] == ["current", "baseline"]
        assert len(assistant["citations"]) == 2
        assert all(len(item["bbox"]) == 4 for item in assistant["citations"])
        assert all(item["method_label"] == "đọc từ văn bản" for item in assistant["citations"])
        assert [event["stage"] for event in assistant["trace"]] == [
            "question_received",
            "question_plan",
            "retrieval",
            "evidence_resolution",
            "calculation",
            "answer_generation",
            "persistence",
        ]
        assert "ai_provider" not in {event["stage"] for event in assistant["trace"]}
    finally:
        cleanup_session(created["id"])


def test_ambiguous_question_is_persisted_as_clarification_without_retrieval() -> None:
    created = client.post("/api/v1/sessions", json={"title": "P0 clarification"}).json()["session"]
    try:
        source = pdf_with_text("Revenue increased from 100 to 120.")
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("ambiguous.pdf", source, "application/pdf")},
        )
        document_id = uploaded.json()["document"]["id"]
        response = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document_id, "question": "How much did revenue increase?"},
        )
        assert response.status_code == 200, response.text
        assistant = response.json()["assistant_message"]
        assert assistant["mode"] == "question_clarification"
        assert assistant["question_plan"]["status"] == "needs_clarification"
        assert assistant["question_plan"]["operation"] is None
        assert assistant["citations"] == []
        assert [event["stage"] for event in assistant["trace"]] == [
            "question_received",
            "question_plan",
            "clarification_requested",
            "persistence",
        ]
    finally:
        cleanup_session(created["id"])


def test_missing_fact_without_a_chart_does_not_call_chart_reader() -> None:
    calls = []

    class SpyChartReader:
        def read(self, request):
            calls.append(request)
            return {
                "status": "not_available",
                "code": "CHART_READER_NOT_IMPLEMENTED",
                "question_plan_id": request.question_plan_id,
                "fact_keys": list(request.fact_keys),
                "evidence_batch": None,
            }

    original_reader = api_main.chart_reader
    api_main.chart_reader = SpyChartReader()
    created = client.post("/api/v1/sessions", json={"title": "P0 chart gate"}).json()["session"]
    try:
        source = pdf_with_text("Revenue Q1/2026 was 120.")
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("missing-baseline.pdf", source, "application/pdf")},
        )
        document_id = uploaded.json()["document"]["id"]
        response = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={
                "document_id": document_id,
                "question": "By what percent did revenue change from Q1/2025 to Q1/2026?",
            },
        )
        assert response.status_code == 200, response.text
        assistant = response.json()["assistant_message"]
        assert assistant["calculation_result"]["status"] == "missing_data"
        assert calls == []
        assert [event["stage"] for event in assistant["trace"]].count("chart_read") == 0
    finally:
        api_main.chart_reader = original_reader
        cleanup_session(created["id"])


def test_clarification_followup_continues_the_previous_question_plan() -> None:
    created = client.post("/api/v1/sessions", json={"title": "P0 follow-up"}).json()["session"]
    try:
        source = pdf_with_text("Revenue Q1/2025 was 100. Revenue Q1/2026 was 120.")
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("follow-up.pdf", source, "application/pdf")},
        )
        document_id = uploaded.json()["document"]["id"]
        first = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={
                "document_id": document_id,
                "question": "How much did revenue increase from Q1/2025 to Q1/2026?",
            },
        )
        assert first.status_code == 200
        assert first.json()["assistant_message"]["mode"] == "question_clarification"

        second = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document_id, "question": "Percentage change"},
        )
        assert second.status_code == 200, second.text
        assistant = second.json()["assistant_message"]
        assert assistant["mode"] == "deterministic_calculation"
        assert assistant["calculation_result"]["value"] == "20"
        assert assistant["question_plan"]["operation"]["formula_id"] == "growth_rate_v1"
    finally:
        cleanup_session(created["id"])


def test_editing_evidence_preserves_old_new_history_and_marks_linked_answer() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Week 1 revisions"}).json()["session"]
    try:
        source = pdf_with_text("Revenue Q1/2025 was 100. Revenue Q1/2026 was 120.")
        uploaded = client.post(
            f"/api/v1/sessions/{created['id']}/documents",
            files={"file": ("revisions.pdf", source, "application/pdf")},
        )
        assert uploaded.status_code == 200, uploaded.text
        document_id = uploaded.json()["document"]["id"]
        answer = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document_id, "question": "By what percent did revenue change from Q1/2025 to Q1/2026?"},
        )
        assert answer.status_code == 200, answer.text
        assistant = answer.json()["assistant_message"]
        baseline = next(item for item in assistant["answer_inputs"] if item["fact_key"] == "baseline")
        assert baseline["value"] == "100"
        assert assistant["answer_revisions"][0]["answer_inputs"][1]["evidence_revision_id"] == baseline["evidence_revision_id"]

        evidence_list = client.get(f"/api/v1/sessions/{created['id']}/documents/{document_id}/evidences")
        assert evidence_list.status_code == 200
        item = next(item for item in evidence_list.json()["evidences"] if item["evidence_key"] == baseline["evidence_key"])
        assert item["original_numeric_value"] == "100"
        edited = client.post(
            f"/api/v1/sessions/{created['id']}/documents/{document_id}/evidences/{item['evidence_key']}/revisions",
            json={"numeric_value": "110", "reason": "Đối chiếu lại PDF gốc", "expected_revision_id": item["current_revision_id"]},
        )
        assert edited.status_code == 200, edited.text
        revision = edited.json()["revision"]
        assert (revision["old_numeric_value"], revision["numeric_value"], revision["action"]) == ("100", "110", "edit")
        assert assistant["id"] in edited.json()["affected_message_ids"]
        stale = client.post(
            f"/api/v1/sessions/{created['id']}/documents/{document_id}/evidences/{item['evidence_key']}/revisions",
            json={"numeric_value": "115", "reason": "Thử revision cũ", "expected_revision_id": item["current_revision_id"]},
        )
        assert stale.status_code == 409

        history = client.get(f"/api/v1/sessions/{created['id']}/documents/{document_id}/evidences/{item['evidence_key']}/revisions")
        assert history.status_code == 200
        assert [row["numeric_value"] for row in history.json()["revisions"]] == ["100", "110"]
        session = client.get(f"/api/v1/sessions/{created['id']}").json()["session"]
        persisted = next(message for message in session["messages"] if message["id"] == assistant["id"])
        assert persisted["needs_update"] is True
    finally:
        cleanup_session(created["id"])


def test_ready_missing_fact_calls_only_selected_chart(monkeypatch):
    calls = []
    original = api_main.extract_pdf_artifact

    def base_with_chart(path, version):
        result = original(path, version)
        result['chart_regions'] = [{'chart_region_key': 'revenue-chart', 'page_number': 1,
                                    'bbox': [.1, .3, .8, .9], 'text': 'Revenue'}]
        return result

    class Spy:
        def read(self, request):
            calls.append(request)
            return {'status': 'not_found', 'code': 'CHART_READ_AMBIGUOUS',
                    'question_plan_id': request.question_plan_id,
                    'fact_keys': list(request.fact_keys), 'evidence_batch': None}

    monkeypatch.setattr(api_main, 'extract_pdf_artifact', base_with_chart)
    monkeypatch.setattr(api_main, 'chart_reader', Spy())
    created = client.post('/api/v1/sessions', json={'title': 'Triggered chart'}).json()['session']
    try:
        uploaded = client.post(f"/api/v1/sessions/{created['id']}/documents",
                               files={'file': ('report.pdf', pdf_with_text('Revenue Q1/2026 was 120.'), 'application/pdf')})
        response = client.post(f"/api/v1/sessions/{created['id']}/messages",
                               json={'document_id': uploaded.json()['document']['id'],
                                     'question': 'By what percent did revenue change from Q1/2025 to Q1/2026?'})
        assert response.status_code == 200, response.text
        assert len(calls) == 1
        assert calls[0].fact_keys == ('baseline',)
        assert calls[0].chart_region_keys == ('revenue-chart',)
        assert len(calls[0].fact_requirements) == 1
        # The reason is saved with the answer, not only in the HTTP response.
        assert any('biểu đồ' in warning for warning in response.json()['assistant_message']['structured_answer']['warnings'])
    finally:
        cleanup_session(created['id'])


class _FakePlanner:
    mode, model = "fake", "planner"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, system, user):
        self.calls.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return json.dumps(self.reply)


def _ask_with_planner(monkeypatch, reply, question, text="Revenue Q1/2025 was 100. Revenue Q1/2026 was 120."):
    planner = _FakePlanner(reply)
    monkeypatch.setattr(api_main, "planner_client", lambda: planner)
    created = client.post("/api/v1/sessions", json={"title": "AI planner"}).json()["session"]
    uploaded = client.post(f"/api/v1/sessions/{created['id']}/documents", files={"file": ("ai.pdf", pdf_with_text(text), "application/pdf")})
    document_id = uploaded.json()["document"]["id"]
    response = client.post(f"/api/v1/sessions/{created['id']}/messages", json={"document_id": document_id, "question": question})
    return created, planner, response


def test_ai_planner_is_used_by_default_and_the_program_calculates(monkeypatch):
    reply = {"status": "ready", "operation": "growth_rate", "facts": [
        {"key": "current", "measure": "doanh_thu", "subject": None, "period": "Q1/2026", "unit": None},
        {"key": "baseline", "measure": "doanh_thu", "subject": None, "period": "Q1/2025", "unit": None}]}
    created, planner, response = _ask_with_planner(monkeypatch, reply, "Doanh thu Q1/2026 tăng bao nhiêu phần trăm so với Q1/2025?")
    try:
        assert response.status_code == 200, response.text
        assistant = response.json()["assistant_message"]
        assert assistant["calculation_result"]["value"] == "20"
        plan_event = next(event for event in assistant["trace"] if event["stage"] == "question_plan")
        assert plan_event["planner"] == "ai:fake/planner" and plan_event["planner_fallback"] is None
        assert "120" not in planner.calls[0] and "100" not in planner.calls[0]
    finally:
        cleanup_session(created["id"])


def test_unsupported_question_stops_before_retrieval(monkeypatch):
    created, _, response = _ask_with_planner(monkeypatch, {"status": "unsupported", "reason": "dự báo"}, "Dự báo doanh thu năm 2027?")
    try:
        assert response.status_code == 200, response.text
        assistant = response.json()["assistant_message"]
        assert assistant["mode"] == "question_unsupported" and assistant["citations"] == []
        assert [event["stage"] for event in assistant["trace"]] == ["question_received", "question_plan", "question_unsupported", "persistence"]
    finally:
        cleanup_session(created["id"])


def test_planner_provider_failure_falls_back_to_rules(monkeypatch):
    created, _, response = _ask_with_planner(monkeypatch, TimeoutError("slow"), "By what percent did revenue change from Q1/2025 to Q1/2026?")
    try:
        assert response.status_code == 200, response.text
        assistant = response.json()["assistant_message"]
        assert assistant["calculation_result"]["value"] == "20"
        plan_event = next(event for event in assistant["trace"] if event["stage"] == "question_plan")
        assert plan_event["planner"] == "rules" and plan_event["planner_fallback"] == "PLANNER_PROVIDER_FAILED"
    finally:
        cleanup_session(created["id"])


def test_unreachable_planner_is_reported_instead_of_calling_the_question_out_of_scope(monkeypatch):
    unavailable = ProviderError("AI_PROVIDER_UNAVAILABLE", "fake planner is unreachable")
    created, _, response = _ask_with_planner(monkeypatch, unavailable, "Tổng doanh thu Q1 và Q2?")
    try:
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "AI_PROVIDER_UNAVAILABLE"
        assert client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["messages"] == []
    finally:
        cleanup_session(created["id"])


def _upload(session_id: str, text: str, name: str = "doc.pdf") -> str:
    uploaded = client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files={"file": (name, pdf_with_text(text), "application/pdf")},
    )
    assert uploaded.status_code == 200, uploaded.text
    return uploaded.json()["document"]["id"]


def test_upload_and_rename_names_keep_the_base_name_without_hidden_characters() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Names"}).json()["session"]
    try:
        names = {}
        for sent in ("../../../../etc/passwd.pdf", "..\\..\\evil.pdf", "a" * 400 + ".pdf", "Báo cáo \u202e fdp.exe.pdf"):
            document_id = _upload(created["id"], "Revenue Q1/2026 was 120.", sent)
            names[sent] = next(item["file_name"] for item in client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"] if item["id"] == document_id)
        assert names["../../../../etc/passwd.pdf"] == "passwd.pdf"
        assert names["..\\..\\evil.pdf"] == "evil.pdf"
        assert len(names["a" * 400 + ".pdf"]) == 255 and names["a" * 400 + ".pdf"].endswith(".pdf")
        assert names["Báo cáo \u202e fdp.exe.pdf"] == "Báo cáo  fdp.exe.pdf"
        renamed = client.patch(f"/api/v1/sessions/{created['id']}/documents/{document_id}", json={"file_name": "\u202eBáo cáo"})
        assert renamed.status_code == 200 and renamed.json()["document"]["file_name"] == "Báo cáo.pdf"
    finally:
        cleanup_session(created["id"])


def test_clarification_on_one_document_is_not_applied_to_another() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Two documents"}).json()["session"]
    try:
        text = "Revenue Q1/2025 was 100. Revenue Q1/2026 was 120."
        first_doc = _upload(created["id"], text, "a.pdf")
        second_doc = _upload(created["id"], text, "b.pdf")
        asked = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": first_doc, "question": "How much did revenue increase from Q1/2025 to Q1/2026?"},
        )
        assert asked.json()["assistant_message"]["mode"] == "question_clarification"

        elsewhere = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": second_doc, "question": "Percentage change"},
        )
        assert elsewhere.status_code in {200, 422}, elsewhere.text
        if elsewhere.status_code == 200:
            plan = elsewhere.json()["assistant_message"]["question_plan"]
            assert plan["original_question"] == "Percentage change"
            assert (plan.get("operation") or {}).get("type") != "growth_rate"

        # The clarification is still pending on the document it was asked about.
        answered = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": first_doc, "question": "Percentage change"},
        )
        assert answered.status_code == 200, answered.text
        assert answered.json()["assistant_message"]["calculation_result"]["value"] == "20"
    finally:
        cleanup_session(created["id"])


def test_revision_endpoints_return_409_while_extraction_is_not_ready(monkeypatch) -> None:
    def broken_extractor(path, document_version_id):
        raise RuntimeError("extractor failed")

    monkeypatch.setattr(api_main, "extract_pdf_artifact", broken_extractor)
    created = client.post("/api/v1/sessions", json={"title": "Failed extraction"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2025 was 100.")
        base = f"/api/v1/sessions/{created['id']}/documents/{document_id}/evidences/ev-any/revisions"
        history = client.get(base)
        edit = client.post(base, json={"numeric_value": "1", "reason": "test", "expected_revision_id": "x"})
        assert (history.status_code, edit.status_code) == (409, 409)
        assert history.json()["detail"]["code"] == edit.json()["detail"]["code"] == "EXTRACTION_NOT_READY"
    finally:
        cleanup_session(created["id"])


def test_same_number_with_a_different_spelling_is_not_a_new_revision() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Same value"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2025 was 100.")
        evidences = client.get(f"/api/v1/sessions/{created['id']}/documents/{document_id}/evidences").json()["evidences"]
        item = next(row for row in evidences if row["current_numeric_value"] == "100")
        response = client.post(
            f"/api/v1/sessions/{created['id']}/documents/{document_id}/evidences/{item['evidence_key']}/revisions",
            json={"numeric_value": "100.00", "reason": "same number", "expected_revision_id": item["current_revision_id"]},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "VALUE_UNCHANGED"
    finally:
        cleanup_session(created["id"])


def test_queued_documents_are_extracted_again_after_a_restart() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Interrupted extraction"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2025 was 100.")
        document = api_main.catalog["sessions"][created["id"]]["documents"][0]
        # Simulate a process that stopped before the background task ran.
        document.update({"extraction_status": "queued", "page_count": None, "numeric_evidence_count": 0})
        api_main.extraction_path(document["extraction_name"]).unlink()

        resumed = api_main.resume_interrupted_extractions(background=False)

        assert document_id in resumed
        session = client.get(f"/api/v1/sessions/{created['id']}").json()["session"]
        assert session["documents"][0]["extraction_status"] == "ready"
        assert session["documents"][0]["page_count"] == 1
    finally:
        cleanup_session(created["id"])


def test_calculation_answer_separates_value_and_unit() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Unit spacing"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2026 was 120 VND.")
        response = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document_id, "question": "What was revenue in Q1/2026?"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["assistant_message"]["body"] == "Kết quả: 120 VND."
    finally:
        cleanup_session(created["id"])


def test_failed_upload_can_be_extracted_again_without_reupload(monkeypatch) -> None:
    from report_qa.application.evidence_extraction import extract_legacy_pdf_artifact

    def broken_extractor(path, document_version_id):
        raise RuntimeError("old extractor bug")

    monkeypatch.setattr(api_main, "extract_pdf_artifact", broken_extractor)
    created = client.post("/api/v1/sessions", json={"title": "Re-extract failed"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2025 was 100.")
        assert client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"][0]["extraction_status"] == "failed"

        monkeypatch.setattr(api_main, "extract_pdf_artifact", extract_legacy_pdf_artifact)
        rerun = client.post(f"/api/v1/sessions/{created['id']}/documents/{document_id}/extraction")

        assert rerun.status_code == 200, rerun.text
        assert rerun.json()["previous_extraction"]["status"] == "failed"
        document = client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"][0]
        assert (document["extraction_status"], document["page_count"]) == ("ready", 1)
        assert [entry["status"] for entry in document["extraction_history"]] == ["failed"]
    finally:
        cleanup_session(created["id"])


def test_reextracting_a_ready_document_archives_the_old_result_and_keeps_edits() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Re-extract ready"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2025 was 100. Revenue Q1/2026 was 120.")
        answer = client.post(
            f"/api/v1/sessions/{created['id']}/messages",
            json={"document_id": document_id, "question": "By what percent did revenue change from Q1/2025 to Q1/2026?"},
        ).json()["assistant_message"]
        base = f"/api/v1/sessions/{created['id']}/documents/{document_id}"
        item = next(row for row in client.get(f"{base}/evidences").json()["evidences"] if row["current_numeric_value"] == "100")
        client.post(f"{base}/evidences/{item['evidence_key']}/revisions", json={"numeric_value": "110", "reason": "Đối chiếu PDF", "expected_revision_id": item["current_revision_id"]})
        stored = api_main.catalog["sessions"][created["id"]]["documents"][0]
        old_run_id = json.loads(api_main.extraction_path(stored["extraction_name"]).read_text(encoding="utf-8"))["evidence_batch"]["extraction_run_id"]

        rerun = client.post(f"{base}/extraction")

        assert rerun.status_code == 200, rerun.text
        previous = rerun.json()["previous_extraction"]
        assert (previous["status"], previous["extraction_run_id"]) == ("ready", old_run_id)
        assert api_main.extraction_path(previous["artifact"]).exists()  # archived, not overwritten
        assert answer["id"] in rerun.json()["affected_message_ids"]
        after = next(row for row in client.get(f"{base}/evidences").json()["evidences"] if row["evidence_key"] == item["evidence_key"])
        assert (after["original_numeric_value"], after["current_numeric_value"]) == ("100", "110")
    finally:
        api_main.extraction_path(f"{document_id}.{old_run_id}.json").unlink(missing_ok=True)
        cleanup_session(created["id"])


def test_reextraction_is_refused_while_extraction_is_running() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Re-extract busy"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2025 was 100.")
        api_main.catalog["sessions"][created["id"]]["documents"][0]["extraction_status"] = "queued"
        busy = client.post(f"/api/v1/sessions/{created['id']}/documents/{document_id}/extraction")
        assert busy.status_code == 409
        assert busy.json()["detail"]["code"] == "EXTRACTION_IN_PROGRESS"
    finally:
        cleanup_session(created["id"])


def test_subject_only_lookup_uses_table_evidence_when_it_exists(monkeypatch) -> None:
    # Recorded Docling output: table cells carry the row header (Q1..Q4) as
    # subject and no period. "Doanh thu Q1" used to skip evidence entirely.
    from pathlib import Path

    recorded = json.loads((Path(__file__).parents[4] / "examples/tien-extraction/output/document.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(api_main, "extract_pdf_artifact", lambda path, version: {**recorded, "evidence_batch": {**recorded["evidence_batch"], "document_version_id": version}})
    created = client.post("/api/v1/sessions", json={"title": "Subject lookup"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Doanh thu theo quy.")
        answer = client.post(f"/api/v1/sessions/{created['id']}/messages", json={"document_id": document_id, "question": "Doanh thu Q1 là bao nhiêu?"})
        assert answer.status_code == 200, answer.text
        assistant = answer.json()["assistant_message"]
        assert assistant["mode"] == "deterministic_calculation"
        assert assistant["answer_inputs"][0]["value"] == "1250.50"
    finally:
        cleanup_session(created["id"])


def test_subject_only_lookup_without_matching_evidence_keeps_the_text_answer() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Subject fallback"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue in region North grew strongly this year.")
        answer = client.post(f"/api/v1/sessions/{created['id']}/messages", json={"document_id": document_id, "question": "Revenue region North?"})
        assert answer.status_code == 200, answer.text
        assert answer.json()["assistant_message"]["mode"] == "deterministic_text_retrieval"
    finally:
        cleanup_session(created["id"])


@pytest.mark.parametrize(
    ("reply", "code", "provider_status"),
    [
        (ProviderError("AI_PROVIDER_HTTP_ERROR", "gemini planner request failed (HTTP 400)", 400), "AI_PROVIDER_HTTP_ERROR", 400),
        ({"action": "unknown"}, "ASSISTANT_INCOMPLETE", None),
    ],
)
def test_tools_mode_ai_failure_shows_a_vietnamese_message_and_keeps_the_code(monkeypatch, reply, code, provider_status):
    from report_qa.api import document_assistant_flow

    monkeypatch.setenv("REPORT_QA_ASSISTANT_MODE", "tools")
    monkeypatch.setattr(document_assistant_flow, "planner_client", lambda: _FakePlanner(reply))
    created = client.post("/api/v1/sessions", json={"title": "AI failure"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2026 was 120.")
        response = client.post(f"/api/v1/sessions/{created['id']}/messages", json={"document_id": document_id, "question": "Revenue?"})
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert detail["code"] == code
        assert detail["message"] == api_main.AI_ERROR_MESSAGES[code]
        assert detail.get("provider_http_status") == provider_status
    finally:
        cleanup_session(created["id"])


def test_extraction_failure_logs_the_traceback_and_stores_a_stable_code(monkeypatch, caplog):
    import logging

    def broken(path, version):
        raise KeyError("prov")

    monkeypatch.setattr(api_main, "extract_pdf_artifact", broken)
    flow_logger = logging.getLogger("report_qa.flow")
    flow_logger.addHandler(caplog.handler)
    try:
        result = api_main.extract_pdf_pages(api_main.document_path("missing.pdf"), "missing.json", "v")
    finally:
        flow_logger.removeHandler(caplog.handler)
    assert result["status"] == "failed" and result["error"] == "KeyError"
    assert any(record.exc_info and record.exc_info[0] is KeyError for record in caplog.records)


def test_object_storage_errors_are_readable_vietnamese() -> None:
    response = api_main.object_storage_error_handler(None, api_main.ObjectStorageError("down"))
    assert json.loads(response.body)["detail"]["message"] == "Cloudflare R2 tạm thời không sẵn sàng; hãy thử lại sau."


def test_session_payload_leaves_number_state_to_the_evidence_endpoints() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Small payload"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Revenue Q1/2026 was 120.")
        assert client.get(f"/api/v1/sessions/{created['id']}/documents/{document_id}/evidences").json()["evidences"]
        assert "evidence_state" in api_main.catalog["sessions"][created["id"]]["documents"][0]
        document = client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"][0]
        assert "evidence_state" not in document and "chart_extractions" not in document
    finally:
        cleanup_session(created["id"])


def _reading(*numbers):
    """A fake extraction: (key, raw_text, numeric_value, page) per number."""
    evidences = [
        {"evidence_key": key, "source_region_key": f"{key}-region", "source_type": "table", "page_number": page, "bbox": [0.1, 0.1, 0.2, 0.2],
         "raw_text": raw, "numeric_value": value, "value_kind": "number", "data_status": "valid", "extraction_method": "table_cell",
         "method_label": "đọc từ ô bảng", "semantic": {}, "table_locator": {"table_region_key": f"page-{page}-table-0", "row_index": 1, "column_index": 1},
         "chart_read": None, "confidence": 0.9}
        for key, raw, value, page in numbers
    ]
    return lambda path, version: {"pages": [{"page": 1, "text": "Doanh thu"}], "evidence_batch": {
        "schema_version": 2, "document_version_id": version, "extraction_run_id": str(uuid4()), "scope": "base_document",
        "trigger": None, "evidences": evidences, "warnings": []}}


def test_reextraction_rebuilds_numbers_and_carries_over_only_edits_at_the_same_place(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "extract_pdf_artifact", _reading(
        ("misread", "18.240", "18.24", 1), ("kept", "100", "100", 1), ("moved", "200", "200", 1), ("gone", "300", "300", 1)))
    created = client.post("/api/v1/sessions", json={"title": "Re-extract rebuild"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Doanh thu.")
        base = f"/api/v1/sessions/{created['id']}/documents/{document_id}"
        rows = {row["evidence_key"]: row for row in client.get(f"{base}/evidences").json()["evidences"]}
        for key, value in (("kept", "110"), ("moved", "210"), ("gone", "310")):
            edited = client.post(f"{base}/evidences/{key}/revisions", json={"numeric_value": value, "reason": "Đối chiếu PDF", "expected_revision_id": rows[key]["current_revision_id"]})
            assert edited.status_code == 200, edited.text
        stored = api_main.catalog["sessions"][created["id"]]["documents"][0]
        stored["chart_extractions"] = [{"chart_region_key": "page-1-picture-0", "evidence_batch": {"evidences": []}}]

        monkeypatch.setattr(api_main, "extract_pdf_artifact", _reading(
            ("misread", "18.240", "18240", 1), ("kept", "100", "100", 1), ("moved", "200", "200", 2)))
        rerun = client.post(f"{base}/extraction")

        assert rerun.status_code == 200, rerun.text
        assert sorted(edit["evidence_key"] for edit in rerun.json()["previous_extraction"]["user_edits"]) == ["gone", "kept", "moved"]
        after = {row["evidence_key"]: row for row in client.get(f"{base}/evidences").json()["evidences"]}
        assert after["misread"]["current_numeric_value"] == "18240"
        assert (after["kept"]["original_numeric_value"], after["kept"]["current_numeric_value"]) == ("100", "110")
        assert after["moved"]["current_numeric_value"] == "200"
        assert "gone" not in after
        entry = client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"][0]["extraction_history"][-1]
        assert entry["edits_carried_over"] == ["kept"]
        assert sorted((item["evidence_key"], item["code"]) for item in entry["edits_not_carried_over"]) == [("gone", "NOT_IN_NEW_READING"), ("moved", "LOCATION_CHANGED")]
        assert stored["chart_extractions"] == []
        archived = json.loads(api_main.number_state_path(entry["number_state"]).read_text(encoding="utf-8"))
        assert archived["chart_extractions"][0]["chart_region_key"] == "page-1-picture-0"
        assert archived["evidence_state"]["items"]["gone"]["revisions"][-1]["numeric_value"] == "310"
    finally:
        cleanup_session(created["id"])


def test_a_failed_reextraction_reports_every_edit_as_not_carried_over(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "extract_pdf_artifact", _reading(("kept", "100", "100", 1)))
    created = client.post("/api/v1/sessions", json={"title": "Re-extract failed reading"}).json()["session"]
    try:
        document_id = _upload(created["id"], "Doanh thu.")
        base = f"/api/v1/sessions/{created['id']}/documents/{document_id}"
        row = client.get(f"{base}/evidences").json()["evidences"][0]
        client.post(f"{base}/evidences/kept/revisions", json={"numeric_value": "110", "reason": "Đối chiếu PDF", "expected_revision_id": row["current_revision_id"]})

        def broken(path, version):
            raise RuntimeError("extractor bug")

        monkeypatch.setattr(api_main, "extract_pdf_artifact", broken)
        assert client.post(f"{base}/extraction").status_code == 200
        entry = client.get(f"/api/v1/sessions/{created['id']}").json()["session"]["documents"][0]["extraction_history"][-1]
        assert entry["edits_carried_over"] == []
        assert entry["edits_not_carried_over"] == [{"evidence_key": "kept", "numeric_value": "110", "code": "NEW_READING_FAILED"}]
    finally:
        cleanup_session(created["id"])


def test_at_most_the_configured_number_of_extractions_run_at_once(monkeypatch) -> None:
    import asyncio
    import threading
    import time

    import httpx
    from report_qa.application.evidence_extraction import extract_legacy_pdf_artifact

    created = client.post("/api/v1/sessions", json={"title": "Extraction slots"}).json()["session"]
    lock, running, peak, processing_peak = threading.Lock(), [0], [0], [0]

    def slow_extractor(path, version):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            documents = api_main.catalog["sessions"][created["id"]]["documents"]
            processing_peak[0] = max(processing_peak[0], sum(item["extraction_status"] == "processing" for item in documents))
        time.sleep(0.2)
        with lock:
            running[0] -= 1
        return extract_legacy_pdf_artifact(path, version)

    monkeypatch.setattr(api_main, "extract_pdf_artifact", slow_extractor)

    async def upload_six():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as async_client:
            return await asyncio.gather(*[
                async_client.post(f"/api/v1/sessions/{created['id']}/documents", files={"file": (f"doc{index}.pdf", pdf_with_text("Revenue Q1/2026 was 120."), "application/pdf")})
                for index in range(6)
            ])

    try:
        responses = asyncio.run(upload_six())
        assert [response.status_code for response in responses] == [200] * 6
        assert (peak[0], processing_peak[0]) == (2, 2)  # the default REPORT_QA_MAX_PARALLEL_EXTRACTIONS
        assert {item["extraction_status"] for item in api_main.catalog["sessions"][created["id"]]["documents"]} == {"ready"}
    finally:
        cleanup_session(created["id"])


def _document_with_numbers(monkeypatch, *numbers):
    monkeypatch.setattr(api_main, "extract_pdf_artifact", _reading(*numbers))
    monkeypatch.delenv("PDF_NUMBER_LOCALE", raising=False)
    created = client.post("/api/v1/sessions", json={"title": "Typed numbers"}).json()["session"]
    document_id = _upload(created["id"], "Doanh thu.")
    base = f"/api/v1/sessions/{created['id']}/documents/{document_id}"
    rows = {row["evidence_key"]: row for row in client.get(f"{base}/evidences").json()["evidences"]}
    return created["id"], base, rows


def test_typed_number_is_read_in_the_documents_number_format(monkeypatch) -> None:
    session_id, base, rows = _document_with_numbers(monkeypatch, ("total", "1.234.567", "1234567", 1), ("target", "21,5", "21.5", 1))
    try:
        body = {"input_text": "21.500", "reason": "Đối chiếu PDF", "expected_revision_id": rows["target"]["current_revision_id"]}
        preview = client.post(f"{base}/evidences/target/revisions?dry_run=true", json=body)
        assert preview.status_code == 200, preview.text
        assert preview.json() == {"parsed_value": "21500", "display": "21.500", "locale": "vi"}
        assert client.get(f"{base}/evidences/target/revisions").json()["revisions"][-1]["action"] == "initialize"
        stale = client.post(f"{base}/evidences/target/revisions?dry_run=true", json={**body, "expected_revision_id": "stale"})
        assert stale.status_code == 409

        saved = client.post(f"{base}/evidences/target/revisions", json=body)
        assert saved.status_code == 200, saved.text
        assert (saved.json()["revision"]["numeric_value"], saved.json()["display"]) == ("21500", "21.500")
        old_client = client.post(f"{base}/evidences/total/revisions", json={"numeric_value": "1234568", "reason": "Đối chiếu PDF", "expected_revision_id": rows["total"]["current_revision_id"]})
        assert (old_client.status_code, old_client.json()["display"]) == (200, "1.234.568")
    finally:
        cleanup_session(session_id)


def test_typed_number_that_the_unknown_format_cannot_decide_is_refused(monkeypatch) -> None:
    session_id, base, rows = _document_with_numbers(monkeypatch, ("target", "100", "100", 1))
    try:
        body = {"input_text": "1.250", "reason": "Đối chiếu PDF", "expected_revision_id": rows["target"]["current_revision_id"]}
        refused = client.post(f"{base}/evidences/target/revisions", json=body)
        assert refused.status_code == 422
        assert refused.json()["detail"]["code"] == "NUMBER_FORMAT_AMBIGUOUS"
        assert refused.json()["detail"]["readings"] == ["1250", "1.250"]
        decided = client.post(f"{base}/evidences/target/revisions?dry_run=true", json={**body, "input_text": "21,5"})
        assert decided.json() == {"parsed_value": "21.5", "display": "21.5", "locale": None}
        both = client.post(f"{base}/evidences/target/revisions", json={**body, "numeric_value": "1250"})
        assert both.status_code == 422
    finally:
        cleanup_session(session_id)
