from io import BytesIO
import json

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from report_qa.api import main as api_main
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
    assert health.json() == {
        "status": "ok",
        "adapter": "local_json_filesystem",
        "durability": "local_disk_logical_state",
        "ai_mode": "deterministic",
        "ai_model": "deterministic",
        "persistence_backend": "json",
        "database": {"configured": False, "status": "disabled", "backend": "json"},
    }
    assert health.headers["x-persistence-backend"] == "json"

    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/",
        "/health",
        "/api/v1/documents/uploads",
        "/api/v1/sessions",
        "/api/v1/sessions/{session_id}",
        "/api/v1/sessions/{session_id}/documents",
        "/api/v1/sessions/{session_id}/documents/{document_id}/file",
        "/api/v1/sessions/{session_id}/documents/{document_id}/evidences",
        "/api/v1/sessions/{session_id}/documents/{document_id}/evidences/{evidence_key}/revisions",
        "/api/v1/sessions/{session_id}/messages",
        "/api/v1/sessions/{session_id}/messages/{message_id}/trace",
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
    assert {tag["name"] for tag in schema["tags"]} == {"runtime", "sessions", "documents"}


def test_session_owns_documents_and_serves_the_uploaded_binary() -> None:
    created = client.post("/api/v1/sessions", json={"title": "Bao cao quy"})
    assert created.status_code == 200
    session_id = created.json()["session"]["id"]
    try:
        source = b"%PDF-1.7\n% SourceLens integration test"
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
        }
        session = client.get(f"/api/v1/sessions/{session_id}").json()["session"]
        assert session["documents"][0]["file_name"] == "quarter.pdf"
        assert "storage_name" not in session["documents"][0]
        file_response = client.get(document["file_url"])
        assert file_response.status_code == 200
        assert file_response.content == source
    finally:
        cleanup_session(session_id)


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


def test_chart_port_is_called_only_when_a_required_fact_is_missing() -> None:
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
        assert len(calls) == 1
        assert calls[0].fact_keys == ("baseline",)
        assert [event["stage"] for event in assistant["trace"]].count("chart_read") == 1
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
