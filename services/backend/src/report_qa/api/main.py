"""FastAPI entrypoint for the single document-QA production flow."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from hashlib import sha256
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from report_qa.application.evidence_extraction import extract_pdf_artifact
from report_qa.application.chart_reading import ChartReadRequest, PdfVectorChartReader
from report_qa.application.deplot_reading import DeplotChartReader
from report_qa.application.p0_pipeline import calculation_answer, execute_calculation, resolve_evidence
from report_qa.application.question_planner import build_catalog, plan_question
from report_qa.domain.contracts import validate_calculation_result_v1, validate_question_plan_v2
from report_qa.domain.types import validate_decimal_text
from .ai_provider import ProviderError, live_provider, planner_client, provider_mode
from report_qa.config import settings
from report_qa.infrastructure.postgres import postgres_health
from .session_storage import EXTRACTION_ROOT, UPLOAD_ROOT, document_path, extraction_path, load_catalog, save_catalog, utc_now


if settings.persistence_backend == "postgres":
    raise RuntimeError(
        "PERSISTENCE_BACKEND=postgres requested, but the session/message repository cutover is not installed yet; "
        "keep PERSISTENCE_BACKEND=json until the PostgreSQL adapter milestone is complete"
    )


logger = logging.getLogger("report_qa.flow")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _flow_handler = logging.StreamHandler()
    _flow_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_flow_handler)
logger.propagate = False


def flow_log(event: str, **fields: Any) -> None:
    """Emit a compact, grep-friendly audit record without document contents."""
    payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":"), default=str)
    logger.info("FLOW %s %s", event, payload)


def trace_event(stage: str, status: str, **fields: Any) -> dict[str, Any]:
    return {"stage": stage, "status": status, "at": utc_now(), **fields}


OPENAPI_TAGS = [
    {
        "name": "runtime",
        "description": "Runtime probe va lien ket den UI/Swagger. Health khong nam duoi /api/v1 de giu probe don gian.",
    },
    {
        "name": "sessions",
        "description": "Luồng PDF -> extraction -> retrieval -> AI (tuy chon) -> persistence. Moi message tra trace_id va co the doc trace da luu.",
    },
    {
        "name": "documents",
        "description": "Compatibility upload vao session local legacy; dung sessions API cho luong moi.",
    },
]

OPENAPI_COMMON_ERRORS = {
    404: {"description": "Resource khong ton tai hoac khong thuoc owner local."},
    409: {"description": "State chua san sang, vi du extraction chua xong."},
    422: {"description": "Payload/du lieu khong hop le hoac khong co evidence du manh."},
}


class RuntimeResponse(BaseModel):
    service: str
    status: str
    ui_url: str
    swagger_url: str
    openapi_url: str
    health_url: str


class HealthResponse(BaseModel):
    status: str
    adapter: str
    durability: str
    ai_mode: str
    ai_model: str
    persistence_backend: str
    database: dict[str, Any]

app = FastAPI(
    title="Report QA API",
    version="0.1.0",
    summary="Traceable PDF QA API",
    description=(
        "API vertical slice de theo doi data flow cua SourceLens. "
        "Moi request co X-Trace-Id; chat trace duoc luu cung assistant message. "
        "Swagger mo ta mot luong chinh: session -> document -> question -> grounded answer."
    ),
    openapi_tags=OPENAPI_TAGS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4173", "http://localhost:4173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get(
    "/",
    tags=["runtime"],
    summary="Runtime entrypoint",
    description="Tra ve trang thai service va cac URL UI, Swagger, OpenAPI, health de kiem tra nhanh server nao dang chay.",
    response_model=RuntimeResponse,
    response_description="Runtime links va service status.",
)
def root() -> dict[str, Any]:
    """Human-friendly local entrypoint; the React UI is served separately."""
    return {
        "service": "Report QA API",
        "status": "ok",
        "ui_url": "http://127.0.0.1:4173",
        "swagger_url": "/docs",
        "openapi_url": "/openapi.json",
        "health_url": "/health",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


catalog = load_catalog()
chart_reader = DeplotChartReader() if os.getenv("CHART_READER_BACKEND", "deplot") == "deplot" else PdfVectorChartReader()
MAX_PDF_BYTES = 100 * 1024 * 1024
LOCAL_OWNER_ID = "local-test-owner"


class SessionCreateRequest(BaseModel):
    title: str = Field(default="Phiên phân tích mới", min_length=1, max_length=120)


class SessionQuestionRequest(BaseModel):
    document_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)


class EvidenceRevisionCreateRequest(BaseModel):
    numeric_value: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=3, max_length=1000)
    expected_revision_id: str = Field(min_length=1, max_length=80)


# Response envelopes keep the OpenAPI surface useful without freezing the
# nested local-prototype payloads. Nested dictionaries remain open until the
# production PostgreSQL/auth contract replaces them with versioned resources.
class SessionListResponse(BaseModel):
    sessions: list[dict[str, Any]]
    persistence: dict[str, Any]


class SessionResponse(BaseModel):
    session: dict[str, Any]


class DocumentUploadResponse(BaseModel):
    session_id: str
    document: dict[str, Any]
    persistence: dict[str, Any]


class MessageResponse(BaseModel):
    user_message: dict[str, Any]
    assistant_message: dict[str, Any]
    limitations: list[str]
    trace_id: str


class MessageTraceResponse(BaseModel):
    session_id: str
    message_id: str
    trace_id: str | None = None
    trace: list[dict[str, Any]]


class LegacyUploadResponse(BaseModel):
    upload: dict[str, Any]
    next_action: str


def trace_id_for(request: Request) -> str:
    return request.headers.get("X-Trace-Id") or getattr(request.state, "trace_id", None) or str(uuid4())


@app.middleware("http")
async def trace_headers(request: Request, call_next):
    trace_id = trace_id_for(request)
    request.state.trace_id = trace_id
    started = time.perf_counter()
    flow_log("HTTP_IN", trace_id=trace_id, method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
    except Exception as exc:
        flow_log("HTTP_ERROR", trace_id=trace_id, method=request.method, path=request.url.path, error=type(exc).__name__)
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        flow_log("HTTP_OUT", trace_id=trace_id, method=request.method, path=request.url.path, status=getattr(locals().get("response"), "status_code", 500), duration_ms=elapsed_ms)
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Persistence-Backend"] = settings.persistence_backend
    return response


@app.get(
    "/health",
    tags=["runtime"],
    summary="Health va AI adapter status",
    description="Read-only probe. Cho biet adapter persistence hien tai, AI mode/model dang chay; khong tao hoac sua du lieu.",
    response_model=HealthResponse,
    response_description="Trang thai runtime hien tai.",
)
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "adapter": "local_json_filesystem",
        "durability": "local_disk_logical_state",
        "ai_mode": provider_mode(),
        "ai_model": (os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if provider_mode() == "gemini" else os.getenv("OPENROUTER_MODEL", "openai/gpt-6-luna") if provider_mode() == "openrouter" else "deterministic"),
        "persistence_backend": settings.persistence_backend,
        "database": postgres_health(),
    }


def public_session(session: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in session.items() if key not in {"owner_id", "documents"}}
    # Keep the public contract self-healing for documents created by an older
    # local prototype.  Those records may have the binary metadata but no
    # file_url; the reader can still address the immutable stored PDF by id.
    public_documents = []
    for document in session.get("documents", []):
        item = {key: value for key, value in document.items() if key not in {"storage_name", "extraction_name"}}
        item.setdefault(
            "file_url",
            f"/api/v1/sessions/{session['id']}/documents/{document['id']}/file",
        )
        public_documents.append(item)
    result["documents"] = public_documents
    return result


def get_session(session_id: str) -> dict[str, Any]:
    session = catalog["sessions"].get(session_id)
    if session is None or session.get("owner_id") != LOCAL_OWNER_ID:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "session not found"})
    session.setdefault("documents", [])
    session.setdefault("messages", [])
    return session


def extract_pdf_pages(path: Any, extraction_name: str, document_version_id: str) -> dict[str, Any]:
    try:
        artifact = extract_pdf_artifact(path, document_version_id)
        EXTRACTION_ROOT.mkdir(parents=True, exist_ok=True)
        target = extraction_path(extraction_name)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
        return {
            "status": "ready",
            "page_count": len(artifact["pages"]),
            "numeric_evidence_count": len(artifact["evidence_batch"]["evidences"]),
            "error": None,
        }
    except Exception as exc:
        return {"status": "failed", "page_count": None, "numeric_evidence_count": 0, "error": type(exc).__name__}


async def persist_pdf(file: UploadFile, session: dict[str, Any], trace_id: str | None = None) -> dict[str, Any]:
    name = file.filename or "unnamed.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail={"code": "PDF_REQUIRED", "message": "chỉ chấp nhận tệp .pdf"})
    document_id = str(uuid4())
    storage_name = f"{document_id}.pdf"
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    final_path = document_path(storage_name)
    temporary_path = final_path.with_suffix(".uploading")
    digest = sha256()
    byte_size = 0
    first_chunk = True
    try:
        with temporary_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                if first_chunk and not chunk.startswith(b"%PDF-"):
                    raise HTTPException(status_code=422, detail={"code": "INVALID_PDF", "message": "tệp không có PDF header hợp lệ"})
                first_chunk = False
                byte_size += len(chunk)
                if byte_size > MAX_PDF_BYTES:
                    raise HTTPException(status_code=413, detail={"code": "PDF_TOO_LARGE", "message": "kích thước PDF tối đa là 100 MiB"})
                digest.update(chunk)
                output.write(chunk)
        if first_chunk:
            raise HTTPException(status_code=422, detail={"code": "EMPTY_PDF", "message": "tệp PDF rỗng"})
        os.replace(temporary_path, final_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    now = utc_now()
    record = {
        "id": document_id,
        "file_name": name,
        "byte_size": byte_size,
        "sha256": digest.hexdigest(),
        "status": "stored",
        "created_at": now,
        "file_url": f"/api/v1/sessions/{session['id']}/documents/{document_id}/file",
        "storage_name": storage_name,
        "extraction_name": f"{document_id}.json",
    }
    record.update({"extraction_status": "queued", "page_count": None, "numeric_evidence_count": 0, "extraction_error": None})
    session["documents"].append(record)
    session["updated_at"] = now
    save_catalog(catalog)
    flow_log(
        "DOCUMENT_STORED",
        trace_id=trace_id,
        session_id=session["id"],
        document_id=document_id,
        byte_size=byte_size,
        sha256=record["sha256"],
        extraction_status="queued",
    )
    return {key: value for key, value in record.items() if key not in {"storage_name", "extraction_name"}}


def complete_document_extraction(session_id: str, document_id: str, trace_id: str | None = None) -> None:
    session = catalog["sessions"].get(session_id)
    if session is None:
        return
    document = next((item for item in session.get("documents", []) if item["id"] == document_id), None)
    if document is None:
        flow_log("EXTRACTION_SKIPPED", trace_id=trace_id, session_id=session_id, document_id=document_id, reason="document_not_found")
        return
    flow_log("EXTRACTION_STARTED", trace_id=trace_id, session_id=session_id, document_id=document_id)
    extraction = extract_pdf_pages(document_path(document["storage_name"]), document["extraction_name"], document_id)
    document.update({"extraction_status": extraction["status"], "page_count": extraction["page_count"], "numeric_evidence_count": extraction["numeric_evidence_count"], "extraction_error": extraction["error"]})
    if extraction["status"] == "ready":
        artifact = json.loads(extraction_path(document["extraction_name"]).read_text(encoding="utf-8"))
        ensure_document_evidence_state(document, artifact)
    session["updated_at"] = utc_now()
    save_catalog(catalog)
    flow_log(
        "EXTRACTION_FINISHED",
        trace_id=trace_id,
        session_id=session_id,
        document_id=document_id,
        status=extraction["status"],
        page_count=extraction["page_count"],
        numeric_evidence_count=extraction["numeric_evidence_count"],
        error=extraction["error"],
    )


@app.get(
    "/api/v1/sessions",
    tags=["sessions"],
    summary="List local analysis sessions",
    description="Doc catalog session cua owner local. Response gom document metadata va thong tin persistence; khong tra binary PDF.",
    response_model=SessionListResponse,
    response_description="Danh sach session theo updated_at giam dan.",
)
def list_sessions() -> dict[str, Any]:
    sessions = [public_session(item) for item in catalog["sessions"].values() if item.get("owner_id") == LOCAL_OWNER_ID]
    sessions.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"sessions": sessions, "persistence": {"metadata": "runtime/sessions.json", "pdf_bytes": "runtime/uploads"}}


@app.post(
    "/api/v1/sessions",
    tags=["sessions"],
    summary="Create an analysis session",
    description="Tao session rong va persist vao runtime/sessions.json. owner_id do server gan, client khong duoc gui.",
    response_model=SessionResponse,
    response_description="Session moi da duoc persist.",
)
def create_session(payload: SessionCreateRequest) -> dict[str, Any]:
    session_id = str(uuid4())
    now = utc_now()
    session = {"id": session_id, "owner_id": LOCAL_OWNER_ID, "title": payload.title.strip(), "created_at": now, "updated_at": now, "documents": [], "messages": []}
    catalog["sessions"][session_id] = session
    save_catalog(catalog)
    return {"session": public_session(session)}


@app.get(
    "/api/v1/sessions/{session_id}",
    tags=["sessions"],
    summary="Read session state",
    description="Doc snapshot session, documents va chat history da persist. Dung endpoint nay de xac nhan state sau upload/ask.",
    response_model=SessionResponse,
    response_description="Snapshot session hien tai.",
    responses=OPENAPI_COMMON_ERRORS,
)
def read_session(session_id: str) -> dict[str, Any]:
    return {"session": public_session(get_session(session_id))}


@app.post(
    "/api/v1/sessions/{session_id}/documents",
    tags=["sessions"],
    summary="Upload and extract a PDF",
    description=(
        "Data flow: validate extension/header/100 MiB -> stream vao temporary file -> SHA-256 -> atomic rename "
        "-> persist document metadata -> background extraction text pages. Tra document status=queued; "
        "goi GET session de thay extraction_status=ready/failed."
    ),
    response_model=DocumentUploadResponse,
    response_description="Document metadata sau khi binary da duoc giu ben vung tren local disk.",
    responses={**OPENAPI_COMMON_ERRORS, 413: {"description": "PDF vuot qua 100 MiB."}},
)
async def upload_session_document(session_id: str, request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, Any]:
    session = get_session(session_id)
    trace_id = trace_id_for(request)
    flow_log("UPLOAD_ACCEPTED", trace_id=trace_id, session_id=session_id, file_name_present=bool(file.filename))
    document = await persist_pdf(file, session, trace_id=trace_id)
    background_tasks.add_task(complete_document_extraction, session_id, document["id"], trace_id)
    return {"session_id": session_id, "document": document, "persistence": {"binary_retained": True, "max_bytes": MAX_PDF_BYTES}}


@app.get(
    "/api/v1/sessions/{session_id}/documents/{document_id}/file",
    tags=["sessions"],
    summary="Stream the immutable PDF",
    description="Ownership check -> kiem tra storage path -> tra binary PDF inline cho PDF reader. Endpoint nay khong sua metadata.",
    response_description="Binary application/pdf.",
    responses=OPENAPI_COMMON_ERRORS,
)
def read_session_document_file(session_id: str, document_id: str) -> FileResponse:
    session = get_session(session_id)
    document = next((item for item in session["documents"] if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    path = document_path(document["storage_name"])
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_FILE_MISSING", "message": "stored PDF is missing"})
    return FileResponse(path, media_type="application/pdf", filename=document["file_name"], content_disposition_type="inline")


@app.get(
    "/api/v1/sessions/{session_id}/documents/{document_id}/evidences",
    tags=["sessions"],
    summary="Inspect original/current numeric evidence and revision history",
    responses=OPENAPI_COMMON_ERRORS,
)
def list_document_evidences(session_id: str, document_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    document = next((item for item in session["documents"] if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    if document.get("extraction_status") != "ready":
        raise HTTPException(status_code=409, detail={"code": "EXTRACTION_NOT_READY", "message": "Tài liệu chưa sẵn sàng để sửa số liệu."})
    extraction = json.loads(extraction_path(document["extraction_name"]).read_text(encoding="utf-8"))
    state = ensure_document_evidence_state(document, extraction)
    records = []
    for evidence in (extraction.get("evidence_batch") or {}).get("evidences", []):
        item = state["items"][evidence["evidence_key"]]
        current = item["revisions"][-1]
        records.append({
            "evidence_key": evidence["evidence_key"], "page_number": evidence["page_number"], "bbox": evidence["bbox"],
            "raw_text": evidence.get("raw_text"), "method_label": evidence["method_label"], "semantic": evidence.get("semantic"),
            "source_type": evidence["source_type"], "source_region_key": evidence["source_region_key"],
            "data_status": evidence["data_status"], "extraction_method": evidence["extraction_method"],
            "table_locator": evidence.get("table_locator"), "chart_read": evidence.get("chart_read"),
            "confidence": evidence["confidence"],
            "original_numeric_value": item["original_numeric_value"], "current_numeric_value": current["numeric_value"],
            "current_revision_id": current["id"], "revision_count": len(item["revisions"]),
        })
    save_catalog(catalog)
    return {"document_id": document_id, "data_revision": state["data_revision"], "evidences": records}


@app.get(
    "/api/v1/sessions/{session_id}/documents/{document_id}/evidences/{evidence_key}/revisions",
    tags=["sessions"], summary="Read append-only revision history for one number", responses=OPENAPI_COMMON_ERRORS,
)
def list_evidence_revisions(session_id: str, document_id: str, evidence_key: str) -> dict[str, Any]:
    session = get_session(session_id)
    document = next((item for item in session["documents"] if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    extraction = json.loads(extraction_path(document["extraction_name"]).read_text(encoding="utf-8"))
    state = ensure_document_evidence_state(document, extraction)
    item = state["items"].get(evidence_key)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "EVIDENCE_NOT_FOUND", "message": "Không tìm thấy số liệu trong tài liệu."})
    save_catalog(catalog)
    return {"document_id": document_id, "evidence_key": evidence_key, "original_numeric_value": item["original_numeric_value"], "current_revision_id": item["current_revision_id"], "revisions": item["revisions"]}


@app.post(
    "/api/v1/sessions/{session_id}/documents/{document_id}/evidences/{evidence_key}/revisions",
    tags=["sessions"], summary="Append a corrected value and preserve old value/history", responses={**OPENAPI_COMMON_ERRORS, 409: {"description": "Revision đã bị thay đổi bởi thao tác khác."}},
)
def create_evidence_revision(session_id: str, document_id: str, evidence_key: str, payload: EvidenceRevisionCreateRequest, request: Request) -> dict[str, Any]:
    session = get_session(session_id)
    document = next((item for item in session["documents"] if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    extraction = json.loads(extraction_path(document["extraction_name"]).read_text(encoding="utf-8"))
    state = ensure_document_evidence_state(document, extraction)
    item = state["items"].get(evidence_key)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "EVIDENCE_NOT_FOUND", "message": "Không tìm thấy số liệu trong tài liệu."})
    current = item["revisions"][-1]
    if current["id"] != payload.expected_revision_id:
        raise HTTPException(status_code=409, detail={"code": "EVIDENCE_REVISION_CONFLICT", "message": "Số liệu đã được sửa bởi thao tác khác; hãy tải lại lịch sử trước khi sửa tiếp."})
    try:
        numeric_value = validate_decimal_text(payload.numeric_value)
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_DECIMAL", "message": "Giá trị phải là chuỗi thập phân chính xác, ví dụ 58 hoặc 58.25."}) from exc
    if numeric_value == current["numeric_value"]:
        raise HTTPException(status_code=422, detail={"code": "VALUE_UNCHANGED", "message": "Giá trị mới trùng giá trị hiện tại; không tạo lịch sử rỗng."})
    revision = {
        "id": str(uuid4()), "revision_no": len(item["revisions"]) + 1, "action": "edit", "created_at": utc_now(),
        "numeric_value": numeric_value, "old_numeric_value": current["numeric_value"], "previous_revision_id": current["id"],
        "reason": payload.reason.strip(),
    }
    item["revisions"].append(revision)
    item["current_revision_id"] = revision["id"]
    state["data_revision"] += 1
    affected = mark_answers_needing_update(session, document_id, evidence_key, current["id"])
    session["updated_at"] = utc_now()
    save_catalog(catalog)
    trace_id = trace_id_for(request)
    flow_log("EVIDENCE_REVISION_APPENDED", trace_id=trace_id, session_id=session_id, document_id=document_id, evidence_key=evidence_key, old_value=current["numeric_value"], new_value=numeric_value, affected_answer_count=len(affected))
    return {"document_id": document_id, "evidence_key": evidence_key, "data_revision": state["data_revision"], "revision": revision, "affected_message_ids": affected, "recalculation_required": bool(affected), "trace_id": trace_id}


def normalize_search_text(value: str) -> str:
    """Normalize PDF extraction artifacts without changing persisted source text."""
    value = unicodedata.normalize("NFKC", str(value)).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip().casefold()


def relevant_pages(document: dict[str, Any], question: str, limit: int = 3) -> list[tuple[dict[str, Any], int]]:
    if document.get("extraction_status") != "ready":
        raise HTTPException(status_code=409, detail={"code": "EXTRACTION_NOT_READY", "message": "tài liệu chưa trích xuất text thành công"})
    artifact_path = extraction_path(document["extraction_name"])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if "evidence_batch" not in payload:
        upgraded = extract_pdf_pages(
            document_path(document["storage_name"]),
            document["extraction_name"],
            document["id"],
        )
        if upgraded["status"] != "ready":
            raise HTTPException(status_code=409, detail={"code": "EXTRACTION_UPGRADE_FAILED", "message": "không thể nâng cấp artifact extraction cũ"})
        document["numeric_evidence_count"] = upgraded["numeric_evidence_count"]
        document["page_count"] = upgraded["page_count"]
        save_catalog(catalog)
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        flow_log("EXTRACTION_ARTIFACT_UPGRADED", document_id=document["id"], numeric_evidence_count=upgraded["numeric_evidence_count"])
    stop_words = {"bao", "nhiêu", "những", "của", "trong", "được", "với", "theo", "này", "là", "và", "cho", "một"}
    normalized_question = normalize_search_text(question)
    query_tokens = {token for token in re.findall(r"\w{2,}", normalized_question, flags=re.UNICODE) if token not in stop_words}
    compact_query = re.sub(r"\s+", "", normalized_question)
    ranked: list[tuple[dict[str, Any], int]] = []
    for page in payload.get("pages", []):
        if not page.get("text", "").strip():
            continue
        normalized_text = normalize_search_text(page.get("text", ""))
        text_tokens = set(re.findall(r"\w{2,}", normalized_text, flags=re.UNICODE))
        score = len(query_tokens & text_tokens)
        compact_text = re.sub(r"\s+", "", normalized_text)
        if compact_query and compact_query in compact_text:
            score += max(5, len(query_tokens) * 2)
        elif query_tokens:
            score += sum(1 for token in query_tokens if token in compact_text)
        ranked.append((page, score))
    ranked.sort(key=lambda item: (-item[1], int(item[0]["page"])))
    if not ranked:
        raise HTTPException(status_code=422, detail={"code": "NO_TEXT_EVIDENCE", "message": "không tìm thấy text có thể dùng làm căn cứ trong PDF"})
    return ranked[: max(1, limit)]


def relevant_page(document: dict[str, Any], question: str) -> tuple[dict[str, Any], int]:
    return relevant_pages(document, question, limit=1)[0]


def ensure_document_evidence_state(document: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
    """Initialize chat-local working copies without mutating base extraction."""
    state = document.setdefault("evidence_state", {"data_revision": 0, "items": {}})
    state.setdefault("data_revision", 0)
    items = state.setdefault("items", {})
    for evidence in (extraction.get("evidence_batch") or {}).get("evidences", []):
        key = evidence["evidence_key"]
        if key in items:
            continue
        now = utc_now()
        initial = {
            "id": str(uuid4()), "revision_no": 1, "action": "initialize", "created_at": now,
            "numeric_value": evidence.get("numeric_value"), "old_numeric_value": None,
            "previous_revision_id": None, "reason": "Giá trị trích xuất gốc, không thể sửa trực tiếp.",
        }
        items[key] = {
            "evidence_key": key, "original_numeric_value": evidence.get("numeric_value"),
            "current_revision_id": initial["id"], "revisions": [initial],
        }
    return state


def extraction_with_evidence_revisions(document: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
    """Overlay a chat-local current revision onto immutable extraction output."""
    state = ensure_document_evidence_state(document, extraction)
    result = json.loads(json.dumps(extraction))
    for evidence in (result.get("evidence_batch") or {}).get("evidences", []):
        item = state["items"].get(evidence["evidence_key"])
        if item is None:
            continue
        current = item["revisions"][-1]
        evidence["numeric_value"] = current["numeric_value"]
        evidence["current_revision_id"] = current["id"]
    return result


def snapshot_answer_revision(assistant_message: dict[str, Any]) -> None:
    """Append the first immutable answer snapshot for the local vertical slice."""
    if assistant_message.get("role") != "assistant" or assistant_message.get("answer_revisions"):
        return
    snapshot = {
        "id": str(uuid4()), "revision_no": 1, "created_at": assistant_message["created_at"],
        "answer_text": assistant_message.get("body", ""), "status": "answered",
        "question_plan": assistant_message.get("question_plan"),
        "calculation_result": assistant_message.get("calculation_result"),
        "answer_inputs": [dict(item) for item in assistant_message.get("answer_inputs", [])],
    }
    assistant_message["answer_revisions"] = [snapshot]
    assistant_message["current_answer_revision_id"] = snapshot["id"]
    assistant_message["needs_update"] = False


def mark_answers_needing_update(session: dict[str, Any], document_id: str, evidence_key: str, old_revision_id: str) -> list[str]:
    affected: list[str] = []
    for message in session.get("messages", []):
        if message.get("role") != "assistant" or message.get("document_id") != document_id:
            continue
        inputs = [item for revision in message.get("answer_revisions", []) for item in revision.get("answer_inputs", [])]
        if any(item.get("evidence_key") == evidence_key and item.get("evidence_revision_id") == old_revision_id for item in inputs):
            message["needs_update"] = True
            affected.append(message["id"])
    return affected


def _base_extraction_or_none(document: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return json.loads(extraction_path(document["extraction_name"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError):
        return None


def _planner_history(session: dict[str, Any], document_id: str) -> list[dict[str, Any]]:
    """Earlier questions on this document with the plan each one got, newest last."""
    turns, question = [], None
    for message in session.get("messages", []):
        if message.get("document_id") != document_id:
            continue
        if message.get("role") == "user":
            question = message.get("body")
        elif message.get("role") == "assistant" and question and message.get("question_plan"):
            turns.append({"question": question, "plan": message["question_plan"]})
            question = None
    return turns[-4:]


def _planner_call() -> dict[str, Any]:
    client = planner_client()
    return {"complete": client.complete, "model_name": f"{client.mode}/{client.model}"} if client else {}


def _persist_unsupported(session, session_id, document, question, question_plan, trace, trace_id) -> dict[str, Any]:
    message = "Câu hỏi này nằm ngoài phạm vi hệ thống hỗ trợ, ví dụ dự báo, xin ý kiến hoặc phép tính nhiều bước. Hệ thống không đưa ra con số nào."
    trace.append(trace_event("question_unsupported", "stopped", code="QUESTION_UNSUPPORTED"))
    now = utc_now()
    user_message = {"id": str(uuid4()), "role": "user", "body": question, "document_id": document["id"], "created_at": now}
    assistant_message = {
        "id": str(uuid4()), "role": "assistant", "body": message, "document_id": document["id"], "created_at": now, "mode": "question_unsupported",
        "citations": [], "trace_id": trace_id, "question_plan": question_plan,
        "structured_answer": {"presentation": "unsupported_v1", "answer": message, "summary": "Hệ thống chưa truy hồi dữ liệu hoặc thực hiện phép tính.",
                              "sections": [], "formulas": [], "tables": [], "claims": [], "warnings": [], "cited_pages": []},
    }
    snapshot_answer_revision(assistant_message)
    trace.append(trace_event("persistence", "committed", artifact="runtime/sessions.json", assistant_message_id=assistant_message["id"], citation_pages=[]))
    assistant_message["trace"] = trace
    session["messages"].extend([user_message, assistant_message])
    session["updated_at"] = now
    save_catalog(catalog)
    flow_log("UNSUPPORTED_PERSISTED", trace_id=trace_id, session_id=session_id, document_id=document["id"], assistant_message_id=assistant_message["id"])
    return {"user_message": user_message, "assistant_message": assistant_message, "limitations": ["Câu hỏi ngoài phạm vi; không truy hồi hoặc tính toán"], "trace_id": trace_id}


@app.post(
    "/api/v1/sessions/{session_id}/messages",
    tags=["sessions"],
    summary="Ask a grounded document question",
    description=(
        "Data flow: question_received -> question_plan -> local evidence resolution/retrieval -> "
        "deterministic calculator hoac optional AI provider structured_json -> answer_generation -> "
        "persistence (persist user+assistant message cung trace). AI provider fail tra 502 va khong persist assistant answer; "
        "cau hoi mo ho tra clarification ma khong chay retrieval/calculator; retrieval yeu tra 422 NO_TEXT_EVIDENCE."
    ),
    response_model=MessageResponse,
    response_description="User message, assistant message, citations, structured_answer (neu co) va trace_id.",
    responses={**OPENAPI_COMMON_ERRORS, 502: {"description": "AI provider timeout/network/invalid structured output."}},
)
def ask_session_document(session_id: str, payload: SessionQuestionRequest, request: Request) -> dict[str, Any]:
    session = get_session(session_id)
    trace_id = trace_id_for(request)
    trace = [trace_event("question_received", "ok", trace_id=trace_id, question_chars=len(payload.question))]
    document = next((item for item in session["documents"] if item["id"] == payload.document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    previous_assistant = next(
        (item for item in reversed(session["messages"]) if item.get("role") == "assistant"),
        None,
    )
    prior_clarification_plan = (
        previous_assistant.get("question_plan")
        if previous_assistant and previous_assistant.get("mode") == "question_clarification"
        else None
    )
    planning = plan_question(
        payload.question,
        document["id"],
        catalog=build_catalog(_base_extraction_or_none(document)),
        history=_planner_history(session, document["id"]),
        prior_clarification_plan=prior_clarification_plan,
        **_planner_call(),
    )
    question_plan = validate_question_plan_v2(planning.plan)
    trace.append(
        trace_event(
            "question_plan",
            question_plan["status"],
            question_plan_id=question_plan["question_plan_id"],
            operation=(question_plan.get("operation") or {}).get("type"),
            fact_keys=[item["fact_key"] for item in question_plan["facts"]],
            planner=planning.planner,
            planner_fallback=planning.fallback_code,
            rules_applied=planning.rules_applied,
        )
    )
    if question_plan["status"] == "unsupported":
        return _persist_unsupported(session, session_id, document, payload.question, question_plan, trace, trace_id)
    if question_plan["status"] == "needs_clarification":
        clarification = question_plan["clarification"]
        trace.append(trace_event("clarification_requested", "waiting_for_user", reason_code=clarification["reason_code"]))
        now = utc_now()
        user_message = {"id": str(uuid4()), "role": "user", "body": payload.question, "document_id": document["id"], "created_at": now}
        assistant_message = {
            "id": str(uuid4()),
            "role": "assistant",
            "body": clarification["question_to_user"],
            "document_id": document["id"],
            "created_at": now,
            "mode": "question_clarification",
            "citations": [],
            "trace_id": trace_id,
            "question_plan": question_plan,
            "structured_answer": {
                "presentation": "clarification_v1",
                "answer": clarification["question_to_user"],
                "summary": "Câu hỏi có nhiều cách hiểu; hệ thống chưa truy hồi dữ liệu hoặc thực hiện phép tính.",
                "sections": [{"heading": "Cần làm rõ", "points": clarification["options"], "evidence_pages": []}],
                "formulas": [],
                "tables": [],
                "claims": [],
                "warnings": [],
                "cited_pages": [],
            },
        }
        snapshot_answer_revision(assistant_message)
        trace.append(trace_event("persistence", "committed", artifact="runtime/sessions.json", assistant_message_id=assistant_message["id"], citation_pages=[]))
        assistant_message["trace"] = trace
        session["messages"].extend([user_message, assistant_message])
        session["updated_at"] = now
        save_catalog(catalog)
        flow_log("CLARIFICATION_PERSISTED", trace_id=trace_id, session_id=session_id, document_id=document["id"], assistant_message_id=assistant_message["id"], reason_code=clarification["reason_code"])
        return {"user_message": user_message, "assistant_message": assistant_message, "limitations": ["Đang chờ người dùng chọn cách hiểu trước khi truy hồi hoặc tính toán"], "trace_id": trace_id}
    retrieval_question = question_plan["original_question"]
    ranked_pages = relevant_pages(document, retrieval_question, limit=3)
    page, score = ranked_pages[0]
    context_pages = [item[0] for item in ranked_pages]
    retrieval_status = "ok" if score > 0 else "weak_match"
    context_manifest = [{"page": int(item[0]["page"]), "score": item[1], "chars": len(str(item[0].get("text", ""))), "text_sha256": sha256(str(item[0].get("text", "")).encode("utf-8")).hexdigest()} for item in ranked_pages]
    trace.append(trace_event("retrieval", retrieval_status, provider="local_token_overlap", pages=[item["page"] for item in context_pages], scores=[item[1] for item in ranked_pages], context_manifest=context_manifest))
    normalized_question = normalize_search_text(retrieval_question)
    summary_request = any(normalize_search_text(marker) in normalized_question for marker in ("tóm tắt", "tổng quan", "nội dung chính", "summary"))
    minimum_score = 2
    if score < minimum_score and not summary_request:
        trace.append(trace_event("answer_generation", "rejected", code="NO_TEXT_EVIDENCE"))
        flow_log("RETRIEVAL_REJECTED", trace_id=trace_id, session_id=session_id, document_id=document["id"], code="NO_TEXT_EVIDENCE", score=score, minimum_score=minimum_score, question_chars=len(payload.question))
        raise HTTPException(status_code=422, detail={"code": "NO_TEXT_EVIDENCE", "message": "Không tìm thấy đoạn text đủ liên quan để trả lời; hãy hỏi bằng thuật ngữ có trong tài liệu.", "trace_id": trace_id})
    flow_log(
        "RETRIEVAL_SELECTED",
        trace_id=trace_id,
        session_id=session_id,
        document_id=document["id"],
        page=page["page"],
        score=score,
        question_chars=len(payload.question),
        question_sha256=sha256(payload.question.encode("utf-8")).hexdigest(),
        provider="local_token_overlap",
    )
    selected_scores = {int(item[0]["page"]): item[1] for item in ranked_pages}
    operation = question_plan.get("operation") or {}
    if operation.get("type") != "lookup" or any(fact.get("measure") != "unknown" and fact.get("period") for fact in question_plan.get("facts", [])):
        base_extraction = json.loads(extraction_path(document["extraction_name"]).read_text(encoding="utf-8"))
        extraction = extraction_with_evidence_revisions(document, base_extraction)
        resolution = resolve_evidence(question_plan, extraction, {int(item["page"]) for item in context_pages})
        trace.append(
            trace_event(
                "evidence_resolution",
                resolution["status"],
                question_plan_id=question_plan["question_plan_id"],
                bindings=[{"fact_key": item["fact_key"], "evidence_revision_id": item["evidence_revision_id"], "page": item["page_number"]} for item in resolution["bindings"]],
                missing_fact_keys=resolution["missing_fact_keys"],
            )
        )
        allowed_chart_facts = set(question_plan["source_strategy"]["chart_fact_keys"]) & set(resolution["missing_fact_keys"])
        candidate_charts = [region for region in extraction.get("chart_regions", []) if int(region["page_number"]) in {int(item["page"]) for item in context_pages}]
        # Do not digitize all pictures on a relevant page. With multiple
        # candidates, defer until the planner/UI supplies a unique source.
        if len(candidate_charts) > 1:
            chart_terms = set(normalize_search_text(retrieval_question).split())
            ranked_charts = [(len(chart_terms & set(normalize_search_text(str(r.get("text", ""))).split())), r) for r in candidate_charts]
            best = max(score for score, _ in ranked_charts)
            candidate_charts = [r for score, r in ranked_charts if score == best] if best > 0 else []
            if len(candidate_charts) != 1:
                candidate_charts = []
        if resolution["status"] == "chart_required" and allowed_chart_facts and candidate_charts:
            chart_result = chart_reader.read(
                ChartReadRequest(
                    document_version_id=document["id"],
                    question_plan_id=question_plan["question_plan_id"],
                    fact_keys=tuple(sorted(allowed_chart_facts)),
                    chart_region_keys=tuple(region["chart_region_key"] for region in candidate_charts),
                    chart_regions=tuple(candidate_charts),
                    source_pdf_path=document_path(document["storage_name"]),
                    page_numbers=tuple(int(item["page"]) for item in context_pages),
                    fact_requirements=tuple(
                        item for item in question_plan["facts"]
                        if item["fact_key"] in allowed_chart_facts
                    ),
                )
            )
            trace.append(
                trace_event(
                    "chart_read",
                    chart_result["status"],
                    policy="only_if_required_fact_unresolved",
                    fact_keys=chart_result["fact_keys"],
                    code=chart_result["code"],
                )
            )
            if chart_result.get("evidence_batch"):
                # On-demand evidence augments this calculation only; the
                # immutable base extraction artifact is never overwritten.
                chart_artifact = dict(extraction)
                chart_batch = dict(extraction["evidence_batch"])
                chart_batch["evidences"] = [
                    *chart_batch.get("evidences", []),
                    *chart_result["evidence_batch"].get("evidences", []),
                ]
                chart_artifact["evidence_batch"] = chart_batch
                resolution = resolve_evidence(question_plan, chart_artifact, {int(item["page"]) for item in context_pages})
                trace.append(trace_event("evidence_resolution", resolution["status"], source="on_demand_chart", missing_fact_keys=resolution["missing_fact_keys"]))
        calculation = validate_calculation_result_v1(execute_calculation(question_plan, resolution))
        trace.append(
            trace_event(
                "calculation",
                calculation["status"],
                formula_id=calculation["formula_id"],
                reason_code=calculation["reason_code"],
                input_revision_ids=[item["evidence_revision_id"] for item in calculation["operands"]],
            )
        )
        answer, structured_answer = calculation_answer(question_plan, calculation, resolution["bindings"])
        citations = [
            {
                "page": int(item["page_number"]),
                "bbox": item["bbox"],
                "score": selected_scores.get(int(item["page_number"]), 0),
                "evidence_revision_id": item["evidence_revision_id"],
                "method_label": item["method_label"],
            }
            for item in resolution["bindings"]
        ]
        now = utc_now()
        user_message = {"id": str(uuid4()), "role": "user", "body": payload.question, "document_id": document["id"], "created_at": now}
        input_by_fact = {item["fact_key"]: item for item in resolution["bindings"]}
        answer_inputs = [
            {**operand, "evidence_key": input_by_fact[operand["fact_key"]]["evidence_key"], "page_number": input_by_fact[operand["fact_key"]]["page_number"], "bbox": input_by_fact[operand["fact_key"]]["bbox"]}
            for operand in calculation["operands"]
            if operand["fact_key"] in input_by_fact
        ]
        assistant_message = {
            "id": str(uuid4()),
            "role": "assistant",
            "body": answer,
            "document_id": document["id"],
            "created_at": now,
            "mode": "deterministic_calculation",
            "citations": citations,
            "trace_id": trace_id,
            "question_plan": question_plan,
            "calculation_result": calculation,
            "answer_inputs": answer_inputs,
            "structured_answer": structured_answer,
        }
        snapshot_answer_revision(assistant_message)
        trace.append(trace_event("answer_generation", "ok", provider="deterministic_calculator", format="structured_answer_v1"))
        trace.append(trace_event("persistence", "committed", artifact="runtime/sessions.json", assistant_message_id=assistant_message["id"], citation_pages=structured_answer["cited_pages"], input_revision_ids=[item["evidence_revision_id"] for item in calculation["operands"]]))
        assistant_message["trace"] = trace
        session["messages"].extend([user_message, assistant_message])
        session["updated_at"] = now
        save_catalog(catalog)
        flow_log("ANSWER_PERSISTED", trace_id=trace_id, session_id=session_id, document_id=document["id"], assistant_message_id=assistant_message["id"], citation_pages=structured_answer["cited_pages"], mode="deterministic_calculation", calculation_status=calculation["status"])
        return {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "limitations": (["Chưa xác định được nguồn biểu đồ hoặc số liệu đủ căn cứ; cần chọn vùng nguồn và xác minh nhãn/trục"] if resolution["status"] == "chart_required" else []),
            "trace_id": trace_id,
        }
    provider = None
    provider_answer = None
    mode = "deterministic_text_retrieval"
    limitations = ["Chưa dùng LLM", "Citation hiện ở mức trang; chưa có bbox cho PDF upload mới"]
    active_provider_mode = provider_mode()
    if active_provider_mode in {"gemini", "openrouter"}:
        provider_name = active_provider_mode
        default_model = "gemini-2.5-flash" if provider_name == "gemini" else "openai/gpt-6-luna"
        configured_model = os.getenv("GEMINI_MODEL" if provider_name == "gemini" else "OPENROUTER_MODEL", default_model)
        flow_log("AI_PROVIDER_REQUESTED", trace_id=trace_id, provider=provider_name, model=configured_model, context_pages=[item["page"] for item in context_pages])
        trace.append(trace_event("ai_provider", "running", provider=provider_name, model=configured_model, context_pages=[item["page"] for item in context_pages], response_format="structured_json"))
        try:
            provider = live_provider()
            provider_answer = provider.answer(payload.question, context_pages) if provider else None
        except ProviderError as exc:
            trace.append(trace_event("ai_provider", "failed", code=exc.code))
            flow_log("AI_PROVIDER_FAILED", trace_id=trace_id, code=exc.code)
            raise HTTPException(status_code=502, detail={"code": exc.code, "message": str(exc), "trace_id": trace_id}) from exc
        if provider_answer is None:
            raise HTTPException(status_code=502, detail={"code": "AI_NOT_CONFIGURED", "message": "AI provider is not configured", "trace_id": trace_id})
        trace.append(trace_event("ai_provider", "validated", provider=provider_answer.provider, model=provider_answer.model, response_sha256=provider_answer.response_sha256, cited_pages=provider_answer.cited_pages))
        flow_log("AI_PROVIDER_ACCEPTED", trace_id=trace_id, provider=provider_answer.provider, model=provider_answer.model, response_sha256=provider_answer.response_sha256, cited_pages=provider_answer.cited_pages)
        answer = provider_answer.answer_text
        citation_pages = provider_answer.cited_pages
        mode = f"ai:{provider_answer.provider}"
        limitations = ["AI chỉ diễn đạt dựa trên context đã chọn", "Chưa có bbox cho PDF upload mới", "Phép tính số vẫn phải do calculator deterministic thực hiện"]
    else:
        compact = " ".join(page["text"].split())
        excerpt = compact[:700] + ("…" if len(compact) > 700 else "")
        answer = f"Nội dung liên quan nhất tôi tìm thấy ở trang {page['page']}: {excerpt}"
        citation_pages = [page["page"]]
        # Keep the local/offline path visually equivalent to the AI path.  The
        # excerpt remains verbatim retrieval text; this structure only adds a
        # presentation contract so the UI does not fall back to one plain blob.
        structured_answer = {
            "presentation": "retrieval_excerpt",
            "retrieved_excerpt": excerpt,
            "answer": f"Có nội dung liên quan ở trang {page['page']}; dưới đây là trích đoạn được truy hồi.",
            "summary": "Câu trả lời offline chỉ trình bày dữ liệu đã truy hồi, không suy diễn thêm.",
            "sections": [{
                "heading": f"Trích đoạn liên quan · trang {page['page']}",
                "points": [],
                "evidence_pages": [page["page"]],
            }],
            "formulas": [],
            "tables": [],
            "claims": [],
            "warnings": ["Đang dùng retrieval cục bộ; bật OpenRouter/Gemini để nhận phân tích có cấu trúc và bảng."],
            "cited_pages": citation_pages,
        }
        trace.append(trace_event("answer_generation", "ok", provider="deterministic_text_retrieval"))
    if provider_answer is None:
        assistant_structured_answer = structured_answer
    else:
        assistant_structured_answer = provider_answer.structured
    citations = [{"page": citation_page, "bbox": None, "score": selected_scores.get(citation_page, 0)} for citation_page in citation_pages]
    now = utc_now()
    user_message = {"id": str(uuid4()), "role": "user", "body": payload.question, "document_id": document["id"], "created_at": now}
    assistant_message = {
        "id": str(uuid4()), "role": "assistant", "body": answer, "document_id": document["id"], "created_at": now,
        "mode": mode, "citations": citations, "trace_id": trace_id, "question_plan": question_plan,
    }
    if assistant_structured_answer is not None:
        assistant_message["structured_answer"] = assistant_structured_answer
        if provider_answer is not None:
            trace.append(trace_event("answer_generation", "ok", provider=provider_answer.provider, format="structured_answer_v1"))
    snapshot_answer_revision(assistant_message)
    trace.append(trace_event("persistence", "committed", artifact="runtime/sessions.json", assistant_message_id=assistant_message["id"], citation_pages=citation_pages))
    assistant_message["trace"] = trace
    session["messages"].extend([user_message, assistant_message])
    session["updated_at"] = now
    save_catalog(catalog)
    flow_log(
        "ANSWER_PERSISTED",
        trace_id=trace_id,
        session_id=session_id,
        document_id=document["id"],
        assistant_message_id=assistant_message["id"],
        citation_pages=citation_pages,
        mode=mode,
    )
    return {"user_message": user_message, "assistant_message": assistant_message, "limitations": limitations, "trace_id": trace_id}


@app.get(
    "/api/v1/sessions/{session_id}/messages/{message_id}/trace",
    tags=["sessions"],
    summary="Inspect persisted message data flow",
    description="Doc trace da commit cung assistant message: retrieval, AI validation (neu co), answer_generation va persistence. Khong doc prompt/raw PDF.",
    response_model=MessageTraceResponse,
    response_description="Trace events theo thu tu thuc thi.",
    responses=OPENAPI_COMMON_ERRORS,
)
def read_session_message_trace(session_id: str, message_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    message = next((item for item in session["messages"] if item["id"] == message_id), None)
    if message is None or message.get("role") != "assistant":
        raise HTTPException(status_code=404, detail={"code": "MESSAGE_TRACE_NOT_FOUND", "message": "assistant message trace not found"})
    return {"session_id": session_id, "message_id": message_id, "trace_id": message.get("trace_id"), "trace": message.get("trace", [])}


@app.post(
    "/api/v1/documents/uploads",
    tags=["documents"],
    summary="Legacy upload compatibility endpoint",
    description="Upload vao session local legacy-upload-session. Chi dung de tuong thich; luong chinh nen tao session roi POST /sessions/{session_id}/documents.",
    response_model=LegacyUploadResponse,
    response_description="Upload metadata va next_action cho PDF reader.",
    responses={413: {"description": "PDF vuot qua 100 MiB."}, 422: {"description": "Khong phai PDF hoac PDF rong."}},
)
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, Any]:
    """Compatibility upload: persist the file in a server-owned local session."""
    default_id = "legacy-upload-session"
    if default_id not in catalog["sessions"]:
        now = utc_now()
        catalog["sessions"][default_id] = {"id": default_id, "owner_id": LOCAL_OWNER_ID, "title": "Uploads", "created_at": now, "updated_at": now, "documents": [], "messages": []}
    document = await persist_pdf(file, catalog["sessions"][default_id])
    background_tasks.add_task(complete_document_extraction, default_id, document["id"])
    return {"upload": {**document, "persistence": {"adapter": "local_filesystem", "binary_retained": True, "max_bytes": MAX_PDF_BYTES}}, "next_action": "Open file_url with the PDF.js reader."}
