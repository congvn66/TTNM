"""FastAPI entrypoint for the single document-QA production flow."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import unicodedata
from contextlib import asynccontextmanager
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, model_validator
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError

from report_qa.application.evidence_extraction import extract_pdf_artifact
from report_qa.application.chart_reading import ChartReadRequest, PdfVectorChartReader
from report_qa.application.deplot_reading import DeplotChartReader
from report_qa.application.p0_pipeline import calculation_answer, execute_calculation, resolve_evidence
from report_qa.application.question_planner import build_catalog, plan_question
from report_qa.application.text_safety import storable
from report_qa.api.document_assistant_flow import answer_document, extraction_marker, flag_if_inputs_changed, with_chart_batches
from report_qa.application.document_assistant import AssistantError
from report_qa.domain.contracts import validate_calculation_result_v1, validate_question_plan_v2
from report_qa.domain.types import validate_decimal_text
from .ai_provider import ProviderError, _load_local_env, assistant_mode, live_provider, planner_client, provider_mode
from .jobs import router as jobs_router
from .library import router as library_router
from .auth import DEMO_OWNER_ID, owner_id_for_request, router as auth_router, settings_router as auth_settings_router
from .devices import router as auth_sessions_router
from report_qa.config import settings
from report_qa.infrastructure.postgres import postgres_health
from report_qa.infrastructure.integrations import readiness as integration_readiness
from report_qa.infrastructure.integrations import runtime_capabilities
from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore
from report_qa.infrastructure.postgres.job_queue import PostgresJobQueue
from .session_storage import (
    EXTRACTION_ROOT,
    NUMBER_STATE_FIELDS,
    UPLOAD_ROOT,
    catalog_lock,
    document_path,
    extraction_path,
    load_catalog,
    number_state,
    number_state_path,
    save_catalog as disk_save_catalog,
    utc_now,
    write_json_atomically,
)
from .object_storage_runtime import (
    ObjectStorageError,
    cache_extraction,
    cache_pdf,
    pdf_storage_key,
    persist_extraction_cache,
    persist_pdf_cache,
    storage_health,
    uses_remote_object_storage,
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


# The web client shows the same text for these codes (apps/web/src/shared/api/client.js).
AI_ERROR_MESSAGES = {
    "AI_PROVIDER_UNAVAILABLE": "Không kết nối được tới dịch vụ AI. Kiểm tra mạng hoặc thử lại sau.",
    "AI_PROVIDER_TIMEOUT": "Dịch vụ AI phản hồi quá lâu. Bạn có thể thử lại câu hỏi.",
    "AI_MODEL_UNAVAILABLE": "Mô hình AI hiện không khả dụng. Kiểm tra lại cấu hình model.",
    "AI_PROVIDER_HTTP_ERROR": "Dịch vụ AI từ chối yêu cầu. Kiểm tra API key và giới hạn sử dụng.",
    "AI_NOT_CONFIGURED": "Chưa cấu hình nhà cung cấp AI cho môi trường này.",
    "AI_INVALID_OUTPUT": "AI trả về dữ liệu không đúng định dạng. Hãy thử lại câu hỏi.",
    "AI_UNGROUNDED_CITATION": "AI trả về trích dẫn không nằm trong tài liệu. Hãy thử lại câu hỏi.",
    "AI_UNSUPPORTED_EVIDENCE": "AI chưa xác minh được evidence trong tài liệu. Hãy thử lại câu hỏi.",
    "DOCUMENT_CONTEXT_TOO_LARGE": "Tài liệu quá dài để trợ lý đọc hết trong một lần hỏi.",
    "ASSISTANT_INCOMPLETE": "Trợ lý chưa hoàn tất câu trả lời trong số bước cho phép. Hãy thử lại hoặc hỏi cụ thể hơn.",
}


def ai_failure(code: str, internal: str, trace_id: str, http_status: int | None = None) -> HTTPException:
    """A 502 with a user message; the internal reason goes only to the server log."""
    flow_log("AI_FAILURE", trace_id=trace_id, code=code, http_status=http_status, reason=internal)
    detail: dict[str, Any] = {"code": code, "message": AI_ERROR_MESSAGES.get(code, "Không thể tạo câu trả lời. Hãy thử lại."), "trace_id": trace_id}
    if http_status is not None:
        detail["provider_http_status"] = http_status
    return HTTPException(status_code=502, detail=detail)


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
    {
        "name": "auth",
        "description": "Email/password account lifecycle. Session token chi nam trong HttpOnly cookie; khong tra bearer token.",
    },
    {
        "name": "settings",
        "description": "Profile va user preferences, owner-scoped theo auth session.",
    },
    {
        "name": "jobs",
        "description": "Durable PostgreSQL job state, append-only events, retry va cancel.",
    },
    {
        "name": "library",
        "description": "Folder/library primitives; tat ca thao tac phai filter theo owner.",
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
    readiness_url: str


class HealthResponse(BaseModel):
    status: str
    adapter: str
    durability: str
    ai_mode: str
    ai_model: str
    persistence_backend: str
    database: dict[str, Any]
    storage: dict[str, Any]
    capabilities: dict[str, Any]
    readiness: dict[str, Any]
    assistant_mode: str | None = None
    assistant_provider: str | None = None
    assistant_model: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Without the durable queue, extraction runs as an in-process background
    # task; documents left "queued" by a restart would stay queued forever.
    # With the queue, the worker owns unfinished jobs.
    if durable_job_queue is None:
        resume_interrupted_extractions()
    yield


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
    lifespan=lifespan,
)
app.include_router(jobs_router)
app.include_router(library_router)
app.include_router(auth_router)
app.include_router(auth_settings_router)
app.include_router(auth_sessions_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4173", "http://localhost:4173"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

@app.exception_handler(ObjectStorageError)
def object_storage_error_handler(_: Request, __: ObjectStorageError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": {"code": "OBJECT_STORAGE_UNAVAILABLE", "message": "Cloudflare R2 tạm thời không sẵn sàng; hãy thử lại sau."}})


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
        "readiness_url": "/health/ready",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


# Read extractor/chart-reader settings from .env too, before they are used.
_load_local_env()
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_FILE_NAME_CHARS = 255
PDF_ENCRYPTED_MESSAGE = "PDF này được đặt mật khẩu nên không đọc được. Hãy gỡ mật khẩu rồi tải lên lại."
# Control and text-direction characters: U+202E alone can show "fdp.exe" as
# "exe.pdf" in the document list.
_HIDDEN_NAME_CHARACTERS = re.compile("[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
# A stable owner keeps the current single-user demo compatible with the
# normalized users/chats foreign keys until auth is enabled.
LOCAL_OWNER_ID = str(DEMO_OWNER_ID)
chart_reader = DeplotChartReader() if os.getenv("CHART_READER_BACKEND", "deplot") == "deplot" else PdfVectorChartReader()


def _load_extraction_for_persistence(document: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return json.loads(cache_extraction(document["extraction_name"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError):
        return None


postgres_runtime = (
    PostgresRuntimeStore(settings.database_url, LOCAL_OWNER_ID, extraction_root=EXTRACTION_ROOT)
    if settings.persistence_backend == "postgres"
    else None
)
durable_job_queue = PostgresJobQueue(settings.database_url) if postgres_runtime else None
# PostgreSQL is the source of truth in cutover mode. Do not hydrate every
# session/revision graph while importing the ASGI module: Supabase network
# latency would make uvicorn appear frozen as the workspace grows. Individual
# requests load only the session they address; the in-process catalog remains
# a short-lived background-task cache.
catalog = {"sessions": {}} if postgres_runtime else load_catalog()


def _runtime_for_owner(owner_id: str | UUID) -> PostgresRuntimeStore:
    return PostgresRuntimeStore(settings.database_url, str(owner_id), extraction_root=EXTRACTION_ROOT)


def save_catalog(value: dict[str, Any], owner_id: str | UUID | None = None) -> None:
    if postgres_runtime:
        selected_owner = owner_id
        if selected_owner is None:
            sessions = list(value.get("sessions", {}).values())
            if sessions:
                selected = max(sessions, key=lambda item: item.get("updated_at", ""))
                selected_owner = selected.get("owner_id", LOCAL_OWNER_ID)
        owner = str(selected_owner or LOCAL_OWNER_ID)
        try:
            _runtime_for_owner(owner).sync_catalog(value, extraction_loader=_load_extraction_for_persistence)
        except Exception:
            # The database refused this snapshot. Drop the owner's cached
            # sessions, so the next request reloads good rows instead of
            # failing on the same data again.
            with catalog_lock:
                for session_id in [key for key, item in value.get("sessions", {}).items() if str(item.get("owner_id")) == owner]:
                    value["sessions"].pop(session_id, None)
            raise
    else:
        disk_save_catalog(value)


class StorableRequest(BaseModel):
    """A request whose text is saved as it is, so it must hold no unstorable character."""

    @model_validator(mode="before")
    @classmethod
    def _remove_unstorable_characters(cls, data: Any) -> Any:
        return storable(data)


class SessionCreateRequest(StorableRequest):
    title: str = Field(default="Phiên phân tích mới", min_length=1, max_length=120)


class SessionUpdateRequest(StorableRequest):
    """User-editable metadata only; server-owned fields stay immutable."""

    title: str = Field(min_length=1, max_length=120)


class DocumentUpdateRequest(StorableRequest):
    """Rename the display name of a stored PDF without replacing its bytes."""

    file_name: str = Field(min_length=1, max_length=255)


class SessionQuestionRequest(StorableRequest):
    document_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)


class EvidenceRevisionCreateRequest(StorableRequest):
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
    status: str = "completed"
    job: dict[str, Any] | None = None


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
    response_model_exclude_none=True,
    description="Read-only probe. Cho biet adapter persistence hien tai, AI mode/model dang chay; khong tao hoac sua du lieu.",
    response_model=HealthResponse,
    response_description="Trang thai runtime hien tai.",
)
def health() -> dict[str, Any]:
    database = postgres_health()
    storage = storage_health()
    capabilities = runtime_capabilities(database=database, storage=storage)
    readiness_status, blockers = integration_readiness(capabilities)
    mode = assistant_mode()
    client = planner_client() if mode == "tools" else None
    return {
        "status": "ok",
        "adapter": "postgres_catalog_cloudflare_r2" if postgres_runtime and uses_remote_object_storage() else "postgres_catalog_local_filesystem" if postgres_runtime else "local_json_filesystem",
        "durability": "postgres_metadata_cloudflare_r2" if postgres_runtime and uses_remote_object_storage() else "postgres_metadata_local_pdf_bytes" if postgres_runtime else "local_disk_logical_state",
        "ai_mode": client.mode if client else provider_mode(),
        "ai_model": client.model if client else (os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if provider_mode() == "gemini" else os.getenv("OPENROUTER_MODEL", "openai/gpt-6-luna") if provider_mode() == "openrouter" else "deterministic"),
        "persistence_backend": settings.persistence_backend,
        "database": database,
        "storage": storage,
        "capabilities": capabilities,
        "readiness": {"status": readiness_status, "blockers": blockers},
        **({"assistant_mode": "tools", "assistant_provider": client.mode if client else None,
            "assistant_model": client.model if client else None} if mode == "tools" else {}),
    }


@app.get(
    "/health/ready",
    tags=["runtime"],
    summary="Readiness cua cac adapter da chon",
    description=(
        "Khac voi /health (liveness), endpoint nay cho biet PDF extractor, "
        "chart reader, database va object storage da san sang chua. "
        "Khong tai trong model DePlot va khong goi AI provider."
    ),
)
def readiness_probe() -> JSONResponse:
    database = postgres_health()
    storage = storage_health()
    capabilities = runtime_capabilities(database=database, storage=storage)
    state, blockers = integration_readiness(capabilities)
    body = {
        "status": state,
        "ready": state == "ready",
        "blockers": blockers,
        "capabilities": capabilities,
    }
    return JSONResponse(status_code=200 if state == "ready" else 503, content=body)


# Storage names are server-side; number state is large and has its own
# endpoints (/evidences), so the session payload stays metadata only.
PRIVATE_DOCUMENT_FIELDS = {"storage_name", "extraction_name", *NUMBER_STATE_FIELDS}


def public_document(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key not in PRIVATE_DOCUMENT_FIELDS}


def public_session(session: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in session.items() if key not in {"owner_id", "documents", "request_keys"}}
    # Keep the public contract self-healing for documents created by an older
    # local prototype.  Those records may have the binary metadata but no
    # file_url; the reader can still address the immutable stored PDF by id.
    public_documents = []
    for document in session.get("documents", []):
        item = public_document(document)
        item.setdefault(
            "file_url",
            f"/api/v1/sessions/{session['id']}/documents/{document['id']}/file",
        )
        public_documents.append(item)
    result["documents"] = public_documents
    return result


def get_session(session_id: str, owner_id: str | UUID | None = None) -> dict[str, Any]:
    if postgres_runtime:
        try:
            loaded = _runtime_for_owner(owner_id or LOCAL_OWNER_ID).load_session(UUID(session_id))
        except (ValueError, TypeError):
            loaded = None
        if loaded is not None:
            catalog["sessions"][session_id] = loaded
            return loaded
    session = catalog["sessions"].get(session_id)
    if session is None or session.get("owner_id") != str(owner_id or LOCAL_OWNER_ID):
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "session not found"})
    session.setdefault("documents", [])
    session.setdefault("messages", [])
    return session


def clean_file_name(name: str) -> str:
    """A display name without hidden characters, capped while keeping its extension."""
    name = _HIDDEN_NAME_CHARACTERS.sub("", storable(name)).strip()
    if len(name) <= MAX_FILE_NAME_CHARS:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot or len(extension) > 10:
        return name[:MAX_FILE_NAME_CHARS].rstrip()
    return stem[: MAX_FILE_NAME_CHARS - len(extension) - 1].rstrip() + "." + extension


def extract_pdf_pages(path: Any, extraction_name: str, document_version_id: str) -> dict[str, Any]:
    try:
        artifact = storable(extract_pdf_artifact(path, document_version_id))
        EXTRACTION_ROOT.mkdir(parents=True, exist_ok=True)
        target = extraction_path(extraction_name)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
        persist_extraction_cache(extraction_name, target)
        return {
            "status": "ready",
            "page_count": len(artifact["pages"]),
            "numeric_evidence_count": len(artifact["evidence_batch"]["evidences"]),
            "error": None,
        }
    except ModuleNotFoundError as exc:
        # e.g. the default Docling extractor is not installed; name the
        # package instead of a bare "ModuleNotFoundError".
        return {"status": "failed", "page_count": None, "numeric_evidence_count": 0, "error": f"MISSING_DEPENDENCY:{exc.name}"}
    except Exception as exc:
        logger.exception("PDF extraction failed for %s", extraction_name)
        return {"status": "failed", "page_count": None, "numeric_evidence_count": 0, "error": type(exc).__name__}


async def persist_pdf(file: UploadFile, session: dict[str, Any], trace_id: str | None = None) -> dict[str, Any]:
    # Browsers may send a client path; only its last part is the name.
    name = clean_file_name(re.split(r"[\\/]", file.filename or "unnamed.pdf")[-1])
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail={"code": "PDF_REQUIRED", "message": "chỉ chấp nhận tệp .pdf"})
    document_id = str(uuid4())
    storage_name = pdf_storage_key(document_id) if uses_remote_object_storage() else f"{document_id}.pdf"
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    final_path = document_path(storage_name)
    temporary_path = final_path.with_suffix(".uploading")
    final_path.parent.mkdir(parents=True, exist_ok=True)
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
    try:
        page_count = len(PdfReader(str(final_path), strict=False).pages)
    except FileNotDecryptedError as exc:
        final_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail={"code": "PDF_ENCRYPTED", "message": PDF_ENCRYPTED_MESSAGE}) from exc
    except Exception as exc:
        final_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail={"code": "INVALID_PDF", "message": "Không thể đọc cấu trúc PDF"}) from exc
    if page_count > MAX_PDF_PAGES:
        final_path.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail={"code": "PDF_TOO_MANY_PAGES", "message": f"PDF vượt quá giới hạn {MAX_PDF_PAGES} trang"})
    now = utc_now()
    try:
        persist_pdf_cache(storage_name, final_path)
    except ObjectStorageError as exc:
        final_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail={"code": "OBJECT_STORAGE_UNAVAILABLE", "message": "Không thể lưu PDF vào Cloudflare R2; hãy thử lại sau."}) from exc

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
    record.update({"extraction_status": "queued", "page_count": page_count, "numeric_evidence_count": 0, "extraction_error": None})
    with catalog_lock:
        session["documents"].append(record)
        session["updated_at"] = now
    save_catalog(catalog, session.get("owner_id", LOCAL_OWNER_ID))
    flow_log(
        "DOCUMENT_STORED",
        trace_id=trace_id,
        session_id=session["id"],
        document_id=document_id,
        byte_size=byte_size,
        sha256=record["sha256"],
        extraction_status="queued",
    )
    return public_document(record)


def complete_document_extraction(session_id: str, document_id: str, trace_id: str | None = None, owner_id: str | UUID | None = None) -> None:
    # A durable worker runs in a different process from uvicorn. Hydrate the
    # requested chat from PostgreSQL before touching the extraction artifact;
    # relying only on the API process cache would silently acknowledge a job
    # without updating the database.
    # Each upload can add a document to an existing session. Never reuse the
    # worker's stale session snapshot from an earlier job in that session.
    if postgres_runtime:
        loaded = _runtime_for_owner(owner_id or LOCAL_OWNER_ID).load_session(UUID(session_id))
        if loaded is not None:
            catalog["sessions"][session_id] = loaded
    session = catalog["sessions"].get(session_id)
    if session is None:
        raise RuntimeError("EXTRACTION_SESSION_NOT_FOUND")
    document = next((item for item in session.get("documents", []) if item["id"] == document_id), None)
    if document is None:
        flow_log("EXTRACTION_SKIPPED", trace_id=trace_id, session_id=session_id, document_id=document_id, reason="document_not_found")
        raise RuntimeError("EXTRACTION_DOCUMENT_NOT_FOUND")
    flow_log("EXTRACTION_STARTED", trace_id=trace_id, session_id=session_id, document_id=document_id)
    owner = session.get("owner_id", LOCAL_OWNER_ID)
    with catalog_lock:
        document.update(extraction_status="processing", extraction_error=None)
    save_catalog(catalog, owner)
    extraction = extract_pdf_pages(cache_pdf(document["storage_name"]), document["extraction_name"], document_id)
    artifact = json.loads(cache_extraction(document["extraction_name"]).read_text(encoding="utf-8")) if extraction["status"] == "ready" else None
    with catalog_lock:
        document.update({"extraction_status": extraction["status"], "page_count": extraction["page_count"], "numeric_evidence_count": extraction["numeric_evidence_count"], "extraction_error": extraction["error"]})
        if artifact is not None:
            ensure_document_evidence_state(document, artifact)
        _carry_over_edits(document, artifact)
        session["updated_at"] = utc_now()
    try:
        save_catalog(catalog, owner)
    except Exception:
        with catalog_lock:
            document.update(extraction_status="failed", extraction_error="EXTRACTION_PUBLISH_FAILED")
        # Persist a terminal document state when the artifact cannot be saved
        # (e.g. schema validation); never leave the UI polling indefinitely.
        save_catalog(catalog, owner)
        raise
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
    if extraction["status"] != "ready":
        # The worker must retry/fail the job instead of acknowledging success.
        raise RuntimeError(f"EXTRACTION_FAILED:{extraction['error']}")


def _extract_in_background(session_id: str, document_id: str, trace_id: str | None = None, owner_id: str | UUID | None = None) -> None:
    """Run extraction without the durable queue.

    The failure is already stored on the document for the UI; only the worker
    needs the exception, to retry the job.
    """
    try:
        complete_document_extraction(session_id, document_id, trace_id, owner_id)
    except RuntimeError as exc:
        flow_log("EXTRACTION_BACKGROUND_FAILED", trace_id=trace_id, session_id=session_id, document_id=document_id, error=str(exc))


def resume_interrupted_extractions(*, background: bool = True) -> list[str]:
    """Re-run extraction for documents a previous process left "queued"."""
    with catalog_lock:
        pending = [
            (session_id, document["id"])
            for session_id, session in catalog["sessions"].items()
            for document in session.get("documents", [])
            if document.get("extraction_status") in {"queued", "processing"}
        ]
    if not pending:
        return []
    flow_log("EXTRACTION_RESUMED", document_count=len(pending))

    def run() -> None:
        for session_id, document_id in pending:
            _extract_in_background(session_id, document_id)

    if background:
        threading.Thread(target=run, name="resume-extractions", daemon=True).start()
    else:
        run()
    return [document_id for _, document_id in pending]


@app.get(
    "/api/v1/sessions",
    tags=["sessions"],
    summary="List local analysis sessions",
    description="Doc catalog session cua owner local. Response gom document metadata va thong tin persistence; khong tra binary PDF.",
    response_model=SessionListResponse,
    response_description="Danh sach session theo updated_at giam dan.",
)
def list_sessions(request: Request) -> dict[str, Any]:
    owner_id = owner_id_for_request(request)
    if postgres_runtime:
        sessions = [public_session(item) for item in _runtime_for_owner(owner_id).load_catalog()["sessions"].values() if item.get("owner_id") == str(owner_id)]
    else:
        with catalog_lock:
            # Deep copy under the lock: the response is serialized after this
            # returns, while other threads may still be appending to the catalog.
            sessions = json.loads(json.dumps([public_session(item) for item in catalog["sessions"].values() if item.get("owner_id") == str(owner_id)]))
    sessions.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"sessions": sessions, "persistence": {"metadata": "postgresql" if postgres_runtime else "runtime/sessions.json", "pdf_bytes": "cloudflare_r2" if uses_remote_object_storage() else "runtime/uploads"}}


@app.post(
    "/api/v1/sessions",
    tags=["sessions"],
    summary="Create an analysis session",
    description="Tao session rong va persist vao runtime/sessions.json. owner_id do server gan, client khong duoc gui.",
    response_model=SessionResponse,
    response_description="Session moi da duoc persist.",
)
def create_session(payload: SessionCreateRequest, request: Request) -> dict[str, Any]:
    owner_id = owner_id_for_request(request)
    session_id = str(uuid4())
    now = utc_now()
    session = {"id": session_id, "owner_id": str(owner_id), "title": payload.title.strip(), "created_at": now, "updated_at": now, "documents": [], "messages": []}
    with catalog_lock:
        catalog["sessions"][session_id] = session
    save_catalog(catalog, owner_id)
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
def read_session(session_id: str, request: Request) -> dict[str, Any]:
    # Load first: in PostgreSQL mode this is a network round trip, which must
    # not happen while the catalog lock is held.
    session = get_session(session_id, owner_id_for_request(request))
    with catalog_lock:
        return {"session": json.loads(json.dumps(public_session(session)))}


@app.patch(
    "/api/v1/sessions/{session_id}",
    tags=["sessions"],
    summary="Rename an analysis session",
    response_model=SessionResponse,
    responses=OPENAPI_COMMON_ERRORS,
)
def update_session(session_id: str, payload: SessionUpdateRequest, request: Request) -> dict[str, Any]:
    owner_id = owner_id_for_request(request)
    session = get_session(session_id, owner_id)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail={"code": "SESSION_TITLE_REQUIRED", "message": "Session title is required"})
    if postgres_runtime:
        if not _runtime_for_owner(owner_id).rename_chat(session_id, title):
            raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "session not found"})
    else:
        with catalog_lock:
            session["title"] = title
            session["updated_at"] = utc_now()
        save_catalog(catalog, owner_id)
    session["title"] = title
    session["updated_at"] = utc_now()
    flow_log("SESSION_RENAMED", trace_id=trace_id_for(request), session_id=session_id)
    return {"session": public_session(session)}


@app.delete(
    "/api/v1/sessions/{session_id}",
    tags=["sessions"],
    summary="Archive an analysis session",
    responses=OPENAPI_COMMON_ERRORS,
)
def delete_session(session_id: str, request: Request) -> dict[str, Any]:
    owner_id = owner_id_for_request(request)
    get_session(session_id, owner_id)
    if postgres_runtime:
        if not _runtime_for_owner(owner_id).archive_chat(session_id):
            raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "session not found"})
    else:
        with catalog_lock:
            catalog["sessions"].pop(session_id, None)
        save_catalog(catalog, owner_id)
    with catalog_lock:
        catalog["sessions"].pop(session_id, None)
    flow_log("SESSION_ARCHIVED", trace_id=trace_id_for(request), session_id=session_id)
    return {"deleted": True, "session_id": session_id, "storage": "soft_deleted"}


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
    owner_id = owner_id_for_request(request)
    session = get_session(session_id, owner_id)
    trace_id = trace_id_for(request)
    flow_log("UPLOAD_ACCEPTED", trace_id=trace_id, session_id=session_id, file_name_present=bool(file.filename))
    document = await persist_pdf(file, session, trace_id=trace_id)
    job = None
    if durable_job_queue:
        job = durable_job_queue.enqueue(
            owner_id=UUID(str(session.get("owner_id", owner_id))),
            chat_id=UUID(session_id),
            kind="extract_document",
            dedup_key=f"extract:{document['id']}",
            payload={"session_id": session_id, "document_id": document["id"], "trace_id": trace_id, "owner_id": str(session.get("owner_id", owner_id))},
        )
    else:
        background_tasks.add_task(_extract_in_background, session_id, document["id"], trace_id)
    persistence = {"binary_retained": True, "max_bytes": MAX_PDF_BYTES, "max_pages": MAX_PDF_PAGES}
    if durable_job_queue:
        persistence["execution"] = "postgres_queue"
    return {"session_id": session_id, "document": document, "job": job, "persistence": persistence}


@app.patch(
    "/api/v1/sessions/{session_id}/documents/{document_id}",
    tags=["sessions"],
    summary="Rename a PDF in its analysis session",
    responses=OPENAPI_COMMON_ERRORS,
)
def update_session_document(session_id: str, document_id: str, payload: DocumentUpdateRequest, request: Request) -> dict[str, Any]:
    owner_id = owner_id_for_request(request)
    session = get_session(session_id, owner_id)
    document = next((item for item in session["documents"] if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    file_name = clean_file_name(payload.file_name)
    if not file_name or any(part in file_name for part in ("/", "\\")):
        raise HTTPException(status_code=422, detail={"code": "DOCUMENT_NAME_INVALID", "message": "document name is invalid"})
    if not file_name.lower().endswith(".pdf"):
        file_name = clean_file_name(f"{file_name}.pdf")
    if postgres_runtime:
        if not _runtime_for_owner(owner_id).rename_document(session_id, document_id, file_name):
            raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    document["file_name"] = file_name
    session["updated_at"] = utc_now()
    if not postgres_runtime:
        save_catalog(catalog, owner_id)
    flow_log("DOCUMENT_RENAMED", trace_id=trace_id_for(request), session_id=session_id, document_id=document_id)
    return {"session_id": session_id, "document": public_document(document)}


@app.delete(
    "/api/v1/sessions/{session_id}/documents/{document_id}",
    tags=["sessions"],
    summary="Archive a PDF from its analysis session",
    responses=OPENAPI_COMMON_ERRORS,
)
def delete_session_document(session_id: str, document_id: str, request: Request) -> dict[str, Any]:
    owner_id = owner_id_for_request(request)
    session = get_session(session_id, owner_id)
    document = next((item for item in session["documents"] if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    if postgres_runtime:
        if not _runtime_for_owner(owner_id).archive_document(session_id, document_id):
            raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    session["documents"] = [item for item in session["documents"] if item["id"] != document_id]
    session["updated_at"] = utc_now()
    if not postgres_runtime:
        save_catalog(catalog, owner_id)
    flow_log("DOCUMENT_ARCHIVED", trace_id=trace_id_for(request), session_id=session_id, document_id=document_id)
    return {"deleted": True, "document_id": document_id, "storage": "soft_deleted"}


def _archive_extraction(document: dict[str, Any]) -> dict[str, Any]:
    """Move the current reading aside under its run id: its artifact, its number state and the user's edits.

    The document then has no number state until the new reading builds it.
    """
    entry = {
        "status": document.get("extraction_status"), "error": document.get("extraction_error"),
        "page_count": document.get("page_count"), "numeric_evidence_count": document.get("numeric_evidence_count"),
        "archived_at": utc_now(), "extraction_run_id": None, "artifact": None, "number_state": None,
        "user_edits": [], "edits_carried_over": None, "edits_not_carried_over": None,
    }
    current = extraction_path(document["extraction_name"])
    artifact = None
    if current.exists():
        try:
            artifact = json.loads(current.read_text(encoding="utf-8"))
            run_id = artifact["evidence_batch"]["extraction_run_id"]
        except (OSError, ValueError, KeyError, TypeError):
            artifact, run_id = None, None
        entry["extraction_run_id"] = run_id
    archived_name = f"{document['id']}.{entry['extraction_run_id'] or uuid4()}"
    if current.exists():
        os.replace(current, extraction_path(f"{archived_name}.json"))
        entry["artifact"] = f"{archived_name}.json"
    state = number_state(document)
    if state:
        entry["user_edits"] = _user_edits(document, artifact)
        write_json_atomically(number_state_path(archived_name), state)
        entry["number_state"] = archived_name
    document.pop("evidence_state", None)
    document["chart_extractions"] = []
    document.setdefault("extraction_history", []).append(entry)
    return entry


def _evidence_location(evidence: dict[str, Any]) -> dict[str, Any]:
    """Where a number sits in the PDF and how it is printed there."""
    chart = evidence.get("chart_read") or {}
    return {
        "page_number": evidence.get("page_number"),
        "source_region_key": evidence.get("source_region_key"),
        "table_locator": evidence.get("table_locator"),
        "chart_locator": {key: chart.get(key) for key in ("chart_region_key", "series_label", "category_label")} if chart else None,
        "raw_text": evidence.get("raw_text"),
    }


def _user_edits(document: dict[str, Any], artifact: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Numbers whose current value is a user edit, with where each one sat in this reading."""
    reading = with_chart_batches(document, artifact or {"evidence_batch": {"evidences": []}})
    evidences = {item["evidence_key"]: item for item in reading["evidence_batch"]["evidences"]}
    edits = []
    for key, item in ((document.get("evidence_state") or {}).get("items") or {}).items():
        current = item["revisions"][-1]
        if current.get("action") != "edit":
            continue
        edits.append({
            "evidence_key": key, "numeric_value": current["numeric_value"], "reason": current.get("reason"),
            "revision_id": current["id"], "location": _evidence_location(evidences[key]) if key in evidences else None,
        })
    return edits


def _carry_over_edits(document: dict[str, Any], artifact: dict[str, Any] | None) -> None:
    """Re-apply the archived user edits to the new reading. Call under catalog_lock.

    An edit is carried over only when the new reading has the same key at the
    same location with the same printed text; every other edit is listed as
    not carried over. A failed reading carries over nothing.
    """
    history = document.get("extraction_history") or []
    if not history or history[-1].get("edits_carried_over") is not None:
        return
    entry = history[-1]
    evidences = {item["evidence_key"]: item for item in (artifact or {}).get("evidence_batch", {}).get("evidences", [])}
    items = (document.get("evidence_state") or {}).get("items") or {}
    carried, not_carried = [], []
    for edit in entry.get("user_edits") or []:
        key = edit["evidence_key"]
        if artifact is None:
            code = "NEW_READING_FAILED"
        elif key not in evidences or key not in items:
            code = "NOT_IN_NEW_READING"
        elif edit["location"] != _evidence_location(evidences[key]):
            code = "LOCATION_CHANGED"
        else:
            _append_carried_edit(document["evidence_state"], items[key], edit)
            carried.append(key)
            continue
        not_carried.append({"evidence_key": key, "numeric_value": edit["numeric_value"], "code": code})
    entry["edits_carried_over"] = carried
    entry["edits_not_carried_over"] = not_carried


def _append_carried_edit(state: dict[str, Any], item: dict[str, Any], edit: dict[str, Any]) -> None:
    current = item["revisions"][-1]
    if current["numeric_value"] is not None and Decimal(current["numeric_value"]) == Decimal(edit["numeric_value"]):
        return  # the new reading already has the edited value
    revision = {
        "id": str(uuid4()), "revision_no": len(item["revisions"]) + 1, "action": "edit", "created_at": utc_now(),
        "numeric_value": edit["numeric_value"], "old_numeric_value": current["numeric_value"], "previous_revision_id": current["id"],
        "reason": edit["reason"], "carried_over_from_revision_id": edit["revision_id"],
    }
    item["revisions"].append(revision)
    item["current_revision_id"] = revision["id"]
    state["data_revision"] += 1


@app.post(
    "/api/v1/sessions/{session_id}/documents/{document_id}/extraction",
    tags=["sessions"],
    summary="Re-run extraction for an uploaded PDF",
    description=(
        "Chay lai extraction bang extractor hien tai. Lan doc cu (artifact, so lieu, bieu do da doc) duoc luu tru; "
        "so lieu duoc dung lai tu lan doc moi. So da sua chi duoc giu khi lan doc moi co cung key, cung vi tri va cung "
        "chu in; ket qua nam o extraction_history[-1].edits_carried_over / edits_not_carried_over. Cau tra loi cu "
        "duoc danh dau needs_update. Tra 409 neu tai lieu dang duoc trich xuat."
    ),
    responses=OPENAPI_COMMON_ERRORS,
)
def rerun_document_extraction(session_id: str, document_id: str, request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    owner_id = owner_id_for_request(request)
    if postgres_runtime:
        # Completed extraction rows are immutable in PostgreSQL and a document
        # version has one base run; re-running needs a new version.
        raise HTTPException(status_code=409, detail={"code": "REEXTRACTION_NOT_SUPPORTED", "message": "Chưa hỗ trợ trích xuất lại khi lưu bằng PostgreSQL; hãy tải lại PDF."})
    session = get_session(session_id, owner_id)
    trace_id = trace_id_for(request)
    with catalog_lock:
        document = next((item for item in session["documents"] if item["id"] == document_id), None)
        if document is None:
            raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
        if document.get("extraction_status") in {"queued", "processing"}:
            raise HTTPException(status_code=409, detail={"code": "EXTRACTION_IN_PROGRESS", "message": "Tài liệu đang được trích xuất."})
        previous = _archive_extraction(document)
        affected = []
        if previous["status"] == "ready":
            # Their inputs came from the archived extraction; keep the
            # snapshots and flag them for recalculation.
            for message in session["messages"]:
                if message.get("role") == "assistant" and message.get("document_id") == document_id and message.get("answer_inputs"):
                    message["needs_update"] = True
                    affected.append(message["id"])
        document.update({"extraction_status": "queued", "page_count": None, "numeric_evidence_count": 0, "extraction_error": None})
        session["updated_at"] = utc_now()
        save_catalog(catalog)
        document_payload = json.loads(json.dumps(public_document(document)))
    flow_log("EXTRACTION_RERUN_QUEUED", trace_id=trace_id, session_id=session_id, document_id=document_id, previous_status=previous["status"], affected_answer_count=len(affected))
    background_tasks.add_task(_extract_in_background, session_id, document_id, trace_id)
    return {"session_id": session_id, "document": document_payload, "previous_extraction": previous, "affected_message_ids": affected, "trace_id": trace_id}


@app.get(
    "/api/v1/sessions/{session_id}/documents/{document_id}/file",
    tags=["sessions"],
    summary="Stream the immutable PDF",
    description="Ownership check -> kiem tra storage path -> tra binary PDF inline cho PDF reader. Endpoint nay khong sua metadata.",
    response_description="Binary application/pdf.",
    responses=OPENAPI_COMMON_ERRORS,
)
def read_session_document_file(session_id: str, document_id: str, request: Request) -> FileResponse:
    session = get_session(session_id, owner_id_for_request(request))
    document = next((item for item in session["documents"] if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    path = cache_pdf(document["storage_name"])
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_FILE_MISSING", "message": "stored PDF is missing"})
    return FileResponse(path, media_type="application/pdf", filename=document["file_name"], content_disposition_type="inline")


def _ready_document(session: dict[str, Any], document_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Document plus its extraction (with chart batches); 404/409 instead of a 500."""
    document = next((item for item in session["documents"] if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    if document.get("extraction_status") != "ready":
        raise HTTPException(status_code=409, detail={"code": "EXTRACTION_NOT_READY", "message": "Tài liệu chưa sẵn sàng để sửa số liệu."})
    extraction = with_chart_batches(document, _load_extraction_artifact(document["extraction_name"]))
    return document, extraction


@app.get(
    "/api/v1/sessions/{session_id}/documents/{document_id}/evidences",
    tags=["sessions"],
    summary="Inspect original/current numeric evidence and revision history",
    responses=OPENAPI_COMMON_ERRORS,
)
def list_document_evidences(session_id: str, document_id: str, request: Request) -> dict[str, Any]:
    session = get_session(session_id, owner_id_for_request(request))
    document, extraction = _ready_document(session, document_id)
    with catalog_lock:
        return _evidence_records(document, document_id, extraction)


def _evidence_records(document: dict[str, Any], document_id: str, extraction: dict[str, Any]) -> dict[str, Any]:
    state, changed = _ensure_evidence_state_reporting_change(document, extraction)
    records = []
    for evidence in (extraction.get("evidence_batch") or {}).get("evidences", []):
        item = state["items"][evidence["evidence_key"]]
        current = item["revisions"][-1]
        records.append({
            "evidence_key": evidence["evidence_key"], "page_number": evidence["page_number"], "bbox": evidence["bbox"],
            "raw_text": evidence.get("raw_text"), "method_label": evidence["method_label"], "semantic": evidence.get("semantic"),
            "source_type": evidence["source_type"], "source_region_key": evidence["source_region_key"],
            "data_status": "valid" if current.get("action") == "edit" else evidence["data_status"], "extraction_method": evidence["extraction_method"],
            "table_locator": evidence.get("table_locator"), "chart_read": evidence.get("chart_read"),
            "confidence": evidence["confidence"],
            "original_numeric_value": item["original_numeric_value"], "current_numeric_value": current["numeric_value"],
            "current_revision_id": current["id"], "revision_count": len(item["revisions"]),
        })
    if changed and not postgres_runtime:
        save_catalog(catalog)
    return json.loads(json.dumps({"document_id": document_id, "data_revision": state["data_revision"], "evidences": records}))


@app.get(
    "/api/v1/sessions/{session_id}/documents/{document_id}/evidences/{evidence_key}/revisions",
    tags=["sessions"], summary="Read append-only revision history for one number", responses=OPENAPI_COMMON_ERRORS,
)
def list_evidence_revisions(session_id: str, document_id: str, evidence_key: str, request: Request) -> dict[str, Any]:
    session = get_session(session_id, owner_id_for_request(request))
    document, extraction = _ready_document(session, document_id)
    with catalog_lock:
        state, changed = _ensure_evidence_state_reporting_change(document, extraction)
        item = state["items"].get(evidence_key)
        if item is None:
            raise HTTPException(status_code=404, detail={"code": "EVIDENCE_NOT_FOUND", "message": "Không tìm thấy số liệu trong tài liệu."})
        if changed and not postgres_runtime:
            save_catalog(catalog)
        return json.loads(json.dumps({"document_id": document_id, "evidence_key": evidence_key, "original_numeric_value": item["original_numeric_value"], "current_revision_id": item["current_revision_id"], "revisions": item["revisions"]}))


@app.post(
    "/api/v1/sessions/{session_id}/documents/{document_id}/evidences/{evidence_key}/revisions",
    tags=["sessions"], summary="Append a corrected value and preserve old value/history", responses={**OPENAPI_COMMON_ERRORS, 409: {"description": "Revision đã bị thay đổi bởi thao tác khác."}},
)
def create_evidence_revision(session_id: str, document_id: str, evidence_key: str, payload: EvidenceRevisionCreateRequest, request: Request) -> dict[str, Any]:
    owner_id = owner_id_for_request(request)
    session = get_session(session_id, owner_id)
    document, extraction = _ready_document(session, document_id)
    # The conflict check and the append are one critical section so two
    # concurrent edits cannot both pass expected_revision_id.
    with catalog_lock:
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
        # Compare numbers, not spellings: "1300" -> "1300.0" is not a change.
        if current["numeric_value"] is not None and Decimal(numeric_value) == Decimal(current["numeric_value"]):
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
        if not postgres_runtime:
            save_catalog(catalog)
    if postgres_runtime:
        # The database repeats the expected_revision_id check in its own
        # transaction, so this network call stays outside the catalog lock.
        try:
            _runtime_for_owner(owner_id).append_evidence_revision(
                chat_id=UUID(session_id),
                document_id=UUID(document_id),
                evidence_key=evidence_key,
                revision=revision,
                expected_revision_id=UUID(current["id"]),
            )
        except ValueError as exc:
            if str(exc) == "EVIDENCE_REVISION_CONFLICT":
                raise HTTPException(status_code=409, detail={"code": "EVIDENCE_REVISION_CONFLICT", "message": "Số liệu đã được sửa bởi thao tác khác; hãy tải lại lịch sử trước khi sửa tiếp."}) from exc
            raise HTTPException(status_code=404, detail={"code": "EVIDENCE_NOT_FOUND", "message": "Không tìm thấy số liệu trong database."}) from exc
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
    artifact_path = cache_extraction(document["extraction_name"])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if "evidence_batch" not in payload:
        upgraded = extract_pdf_pages(
            cache_pdf(document["storage_name"]),
            document["extraction_name"],
            document["id"],
        )
        if upgraded["status"] != "ready":
            raise HTTPException(status_code=409, detail={"code": "EXTRACTION_UPGRADE_FAILED", "message": "không thể nâng cấp artifact extraction cũ"})
        with catalog_lock:
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


def ensure_document_evidence_state(document: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
    """Initialize chat-local working copies without mutating base extraction."""
    # A new reading starts with no state (see _archive_extraction), so the
    # state built here belongs to this reading's run.
    state = document.setdefault("evidence_state", {"data_revision": 0, "items": {}, "extraction_run_id": (extraction.get("evidence_batch") or {}).get("extraction_run_id")})
    state.setdefault("data_revision", 0)
    items = state.setdefault("items", {})
    for evidence in (extraction.get("evidence_batch") or {}).get("evidences", []):
        key = evidence["evidence_key"]
        if key in items:
            _record_reread_value(state, items[key], evidence.get("numeric_value"))
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


def _evidence_state_shape(document: dict[str, Any]) -> tuple[Any, ...] | None:
    state = document.get("evidence_state")
    return None if state is None else (state.get("data_revision"), "items" in state, len(state.get("items", {})))


def _ensure_evidence_state_reporting_change(document: dict[str, Any], extraction: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """The evidence state, and whether bringing it up to date changed anything that must be saved."""
    before = _evidence_state_shape(document)
    state = ensure_document_evidence_state(document, extraction)
    return state, _evidence_state_shape(document) != before


def _record_reread_value(state: dict[str, Any], item: dict[str, Any], value: str | None) -> None:
    """Append the value a later read supplies when the first read withheld it.

    E.g. a chart whose visual check failed (provider 503) is read again and
    now verified under the same evidence key. Without this the key kept its
    first, empty value forever. User edits always win; history stays append-only.
    """
    current = item["revisions"][-1]
    if value is None or current.get("numeric_value") is not None or current.get("action") == "edit":
        return
    revision = {
        "id": str(uuid4()), "revision_no": len(item["revisions"]) + 1, "action": "reread", "created_at": utc_now(),
        "numeric_value": value, "old_numeric_value": None, "previous_revision_id": current["id"],
        "reason": "Giá trị được đọc lại và xác minh.",
    }
    item["revisions"].append(revision)
    item["current_revision_id"] = revision["id"]
    state["data_revision"] = state.get("data_revision", 0) + 1


def extraction_with_evidence_revisions(document: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
    """Overlay a chat-local current revision onto immutable extraction output."""
    with catalog_lock:
        state = json.loads(json.dumps(ensure_document_evidence_state(document, extraction)))
    result = json.loads(json.dumps(extraction))
    for evidence in (result.get("evidence_batch") or {}).get("evidences", []):
        item = state["items"].get(evidence["evidence_key"])
        if item is None:
            continue
        current = item["revisions"][-1]
        evidence["numeric_value"] = current["numeric_value"]
        evidence["current_revision_id"] = current["id"]
        if current.get("action") == "edit":
            evidence["data_status"] = "valid"
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


def _append_exchange(session: dict[str, Any], user_message: dict[str, Any], assistant_message: dict[str, Any], now: str, *, document: dict[str, Any] | None = None, marker: int | None = None) -> None:
    for message in (user_message, assistant_message):
        cleaned = storable(message)
        message.clear()
        message.update(cleaned)
    with catalog_lock:
        if document is not None:
            flag_if_inputs_changed(document, assistant_message, marker)
        session["messages"].extend([user_message, assistant_message])
        session["updated_at"] = now
    try:
        save_catalog(catalog, session.get("owner_id", LOCAL_OWNER_ID))
    except Exception:
        # Not stored: keep the refused pair out of every later save.
        with catalog_lock:
            session["messages"] = [item for item in session["messages"] if item is not user_message and item is not assistant_message]
        raise


def _load_extraction_artifact(extraction_name: str) -> dict[str, Any]:
    return json.loads(cache_extraction(extraction_name).read_text(encoding="utf-8"))


def _persist_chart_read(session: dict[str, Any], document: dict[str, Any], result: dict[str, Any], region_key: str) -> None:
    """Store a tools-mode chart read in PostgreSQL and adopt its revision ids."""
    store = _runtime_for_owner(session.get("owner_id", LOCAL_OWNER_ID))
    batch = result["evidence_batch"]
    try:
        store.persist_on_demand_chart(
            chat_id=UUID(session["id"]),
            document_version_id=UUID(str(document.get("version_id") or document["id"])),
            evidence_batch=batch,
            question_plan_id=str(batch["trigger"]["question_plan_id"]),
            chart_record={**result, "chart_region_key": region_key, "created_at": utc_now()},
        )
        document["evidence_state"] = store.load_evidence_state(session["id"], document["id"])
    except Exception as exc:
        # The assistant gets a stable code, never database details, and can
        # still answer from the other evidence.
        flow_log("CHART_PERSISTENCE_FAILED", session_id=session["id"], document_id=document["id"], chart_region_key=region_key, error=type(exc).__name__)
        raise RuntimeError("CHART_EVIDENCE_PERSISTENCE_FAILED") from exc


def _base_extraction_or_none(document: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return json.loads(cache_extraction(document["extraction_name"]).read_text(encoding="utf-8"))
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
    _append_exchange(session, user_message, assistant_message, now)
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
def ask_session_document(session_id: str, payload: SessionQuestionRequest, request: Request, response: Response) -> dict[str, Any]:
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return _ask_session_document(session_id, payload, request, response)
    # Same-key requests run one at a time: a duplicate waits for the first
    # and then gets its stored response instead of answering again.
    slot = (session_id, idempotency_key)
    while True:
        with catalog_lock:
            running = _idempotency_in_flight.get(slot)
            if running is None:
                _idempotency_in_flight[slot] = threading.Event()
                break
        running.wait()
    try:
        return _ask_session_document(session_id, payload, request, response)
    finally:
        with catalog_lock:
            _idempotency_in_flight.pop(slot).set()


_idempotency_in_flight: dict[tuple[str, str], threading.Event] = {}


def _ask_session_document(session_id: str, payload: SessionQuestionRequest, request: Request, response: Response) -> dict[str, Any]:
    session = get_session(session_id, owner_id_for_request(request))
    # A durable worker reuses this pipeline as a computation.  Isolate its
    # working snapshot so temporary messages and intermediate saves cannot
    # become a second persisted conversation before the worker publishes the
    # result into the existing placeholder.
    # Only the in-process worker adapter sets this request-state marker; a
    # network client can send the X-Worker-Job header but cannot set state.
    worker_mode = getattr(request.state, "worker_job", False) is True
    if worker_mode:
        session = deepcopy(session)
    trace_id = trace_id_for(request)
    trace = [trace_event("question_received", "ok", trace_id=trace_id, question_chars=len(payload.question))]
    idempotency_key = request.headers.get("Idempotency-Key")
    request_fingerprint = sha256(f"{payload.document_id}|{payload.question}".encode("utf-8")).hexdigest()
    request_keys = session.setdefault("request_keys", {})
    if idempotency_key and len(idempotency_key) > 200:
        raise HTTPException(status_code=422, detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": "Idempotency-Key quá dài"})
    if idempotency_key and idempotency_key in request_keys:
        stored = request_keys[idempotency_key]
        if stored.get("request_hash") != request_fingerprint:
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "Idempotency-Key đã được dùng cho payload khác"})
        return stored["response"]
    def finish(response: dict[str, Any]) -> dict[str, Any]:
        if idempotency_key:
            request_keys[idempotency_key] = {"request_hash": request_fingerprint, "response": response, "created_at": utc_now()}
            if len(request_keys) > 128:
                oldest = min(request_keys, key=lambda key: request_keys[key].get("created_at", ""))
                request_keys.pop(oldest, None)
            save_catalog(catalog, session.get("owner_id", LOCAL_OWNER_ID))
        return response
    document = next((item for item in session["documents"] if item["id"] == payload.document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "document not found"})
    marker = extraction_marker(document)
    # PostgreSQL mode can move the expensive answer path out of the request.
    # The default stays synchronous for the offline compatibility tests; the
    # flag is explicit so operators cannot accidentally run a worker-less UI.
    if durable_job_queue and settings.async_answer_jobs and not worker_mode:
        now = utc_now()
        user_message = {"id": str(uuid4()), "role": "user", "body": payload.question, "document_id": document["id"], "created_at": now, "status": "accepted"}
        assistant_message = {
            "id": str(uuid4()), "role": "assistant", "body": "Đang tạo câu trả lời…", "document_id": document["id"], "created_at": now,
            "status": "processing", "mode": "answer_question_job", "citations": [], "trace_id": trace_id,
            "structured_answer": {"presentation": "processing_v1", "answer": "Đang tạo câu trả lời…", "summary": "Worker đang truy hồi evidence và kiểm tra cấu trúc trả lời.", "sections": [], "formulas": [], "tables": [], "claims": [], "warnings": [], "cited_pages": []},
        }
        queued_trace = [
            trace_event("question_received", "ok", trace_id=trace_id, question_chars=len(payload.question)),
            trace_event("job_enqueue", "queued", kind="answer_question"),
        ]
        if document.get("extraction_status") != "ready":
            queued_trace.append(trace_event("wait_for_document", "waiting", extraction_status=document.get("extraction_status", "queued")))
            assistant_message["body"] = "Đã nhận câu hỏi. Trợ lý sẽ trả lời ngay khi tài liệu sẵn sàng."
            assistant_message["structured_answer"]["answer"] = assistant_message["body"]
            assistant_message["structured_answer"]["summary"] = "Câu hỏi đang chờ tài liệu được đọc xong."
        assistant_message["trace"] = queued_trace
        session["messages"].extend([user_message, assistant_message])
        session["updated_at"] = now
        job = durable_job_queue.enqueue(
            owner_id=UUID(str(session.get("owner_id", LOCAL_OWNER_ID))),
            chat_id=UUID(session_id),
            kind="answer_question",
            dedup_key=f"answer:{assistant_message['id']}",
            payload={"session_id": session_id, "document_id": document["id"], "question": payload.question, "user_message_id": user_message["id"], "assistant_message_id": assistant_message["id"], "trace_id": trace_id, "owner_id": str(session.get("owner_id", LOCAL_OWNER_ID))},
            input_data_revision=int(session.get("data_revision") or 0),
        )
        save_catalog(catalog, session.get("owner_id", LOCAL_OWNER_ID))
        response.status_code = 202
        flow_log("ANSWER_JOB_QUEUED", trace_id=trace_id, session_id=session_id, document_id=document["id"], job_id=job.get("id"), assistant_message_id=assistant_message["id"])
        return finish({"user_message": user_message, "assistant_message": assistant_message, "limitations": [], "trace_id": trace_id, "status": "queued", "job": job})
    if assistant_mode() == "tools":
        if document.get("extraction_status") != "ready":
            raise HTTPException(status_code=409, detail={"code": "EXTRACTION_NOT_READY", "message": "Tài liệu chưa trích xuất xong."})
        owner = session.get("owner_id", LOCAL_OWNER_ID)
        try:
            return finish(answer_document(
                session, document, payload.question, trace_id, trace, catalog,
                overlay=extraction_with_evidence_revisions,
                snapshot=snapshot_answer_revision,
                load_extraction=_load_extraction_artifact,
                resolve_pdf=cache_pdf,
                save=lambda value: save_catalog(value, owner),
                persist_chart=(lambda result, region_key: _persist_chart_read(session, document, result, region_key)) if postgres_runtime else None,
            ))
        except ProviderError as exc:
            raise ai_failure(exc.code, str(exc), trace_id, exc.http_status) from exc
        except AssistantError as exc:
            flow_log("ASSISTANT_INCOMPLETE", trace_id=trace_id, session_id=session_id, document_id=document["id"],
                     tool_errors=[item.get("error") for item in getattr(exc, "tool_results", []) if item.get("error")])
            raise ai_failure("ASSISTANT_INCOMPLETE", str(exc), trace_id) from exc
    # Only a clarification asked about *this* document can be answered here;
    # a pending clarification on another PDF in the session must not be
    # merged into this question.
    previous_assistant = next(
        (item for item in reversed(session["messages"]) if item.get("role") == "assistant" and item.get("document_id") == document["id"]),
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
        if planning.fallback_code == "AI_PROVIDER_UNAVAILABLE":
            # The rules alone call many answerable questions out of scope;
            # saying so would hide that the AI planner could not be reached.
            raise ai_failure(planning.fallback_code, "planner unavailable; rules fallback found the question unsupported", trace_id)
        return finish(_persist_unsupported(session, session_id, document, payload.question, question_plan, trace, trace_id))
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
        _append_exchange(session, user_message, assistant_message, now)
        flow_log("CLARIFICATION_PERSISTED", trace_id=trace_id, session_id=session_id, document_id=document["id"], assistant_message_id=assistant_message["id"], reason_code=clarification["reason_code"])
        return finish({"user_message": user_message, "assistant_message": assistant_message, "limitations": ["Đang chờ người dùng chọn cách hiểu trước khi truy hồi hoặc tính toán"], "trace_id": trace_id})
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
    facts = question_plan.get("facts", [])
    structured = operation.get("type") != "lookup" or any(fact.get("measure") != "unknown" and fact.get("period") for fact in facts)
    if not structured and any(fact.get("measure") != "unknown" and fact.get("subject") for fact in facts):
        # A lookup naming only a subject ("doanh thu vùng A") used to skip
        # evidence and charts entirely. Use them when they can answer: a
        # matching number, or a chart on the retrieved pages; otherwise keep
        # the text answer.
        probe_extraction = extraction_with_evidence_revisions(document, with_chart_batches(document, _load_extraction_artifact(document["extraction_name"])))
        context_page_numbers = {int(item["page"]) for item in context_pages}
        probe = resolve_evidence(question_plan, probe_extraction, context_page_numbers)
        structured = probe["status"] == "resolved" or (
            probe["status"] == "chart_required"
            and any(int(region["page_number"]) in context_page_numbers for region in probe_extraction.get("chart_regions", []))
        )
    if structured:
        base_extraction = with_chart_batches(document, _load_extraction_artifact(document["extraction_name"]))
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
                    document_version_id=str(document.get("version_id") or document["id"]),
                    question_plan_id=question_plan["question_plan_id"],
                    fact_keys=tuple(sorted(allowed_chart_facts)),
                    chart_region_keys=tuple(region["chart_region_key"] for region in candidate_charts),
                    chart_regions=tuple(candidate_charts),
                    source_pdf_path=cache_pdf(document["storage_name"]),
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
                chart_batch_payload = chart_result["evidence_batch"]
                if postgres_runtime:
                    # Lazy chart extraction is still durable.  Persist before
                    # resolving the answer so every citation/input points to
                    # a real chat-local evidence revision, never an ``evr:``
                    # placeholder that cannot be inserted into PostgreSQL.
                    try:
                        chart_revision_ids = _runtime_for_owner(
                            UUID(str(session.get("owner_id", LOCAL_OWNER_ID)))
                        ).persist_on_demand_chart(
                            chat_id=UUID(session_id),
                            document_version_id=UUID(str(document.get("version_id") or document["id"])),
                            evidence_batch=chart_batch_payload,
                            question_plan_id=question_plan["question_plan_id"],
                        )
                    except (PermissionError, RuntimeError, ValueError) as exc:
                        trace.append(trace_event("chart_persistence", "failed", code=str(exc)))
                        raise HTTPException(
                            status_code=503,
                            detail={
                                "code": "CHART_EVIDENCE_PERSISTENCE_FAILED",
                                "message": "Không thể lưu evidence biểu đồ để tạo liên kết trích dẫn bền vững.",
                                "trace_id": trace_id,
                            },
                        ) from exc
                    for item in chart_batch_payload.get("evidences", []):
                        revision_id = chart_revision_ids.get(str(item.get("evidence_key")))
                        if revision_id:
                            item["current_revision_id"] = str(revision_id)
                    trace.append(
                        trace_event(
                            "chart_persistence",
                            "committed",
                            extraction_run_id=chart_batch_payload.get("extraction_run_id"),
                            revision_count=len(chart_revision_ids),
                        )
                    )
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
        if resolution["status"] == "chart_required":
            # The reason was only in the HTTP response's limitations, so the
            # saved answer just said "Không đủ dữ liệu" with no explanation.
            chart_attempted = any(event["stage"] == "chart_read" for event in trace)
            structured_answer["warnings"].append(
                "Đã đọc biểu đồ nhưng chưa xác minh được nhãn/trục, nên không dùng số đọc được; chế độ AI có bước kiểm tra trực quan."
                if chart_attempted else "Số liệu cần lấy từ biểu đồ nhưng chưa xác định được biểu đồ nguồn."
            )
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
        _append_exchange(session, user_message, assistant_message, now, document=document, marker=marker)
        flow_log("ANSWER_PERSISTED", trace_id=trace_id, session_id=session_id, document_id=document["id"], assistant_message_id=assistant_message["id"], citation_pages=structured_answer["cited_pages"], mode="deterministic_calculation", calculation_status=calculation["status"])
        return finish({
            "user_message": user_message,
            "assistant_message": assistant_message,
            "limitations": (["Chưa xác định được nguồn biểu đồ hoặc số liệu đủ căn cứ; cần chọn vùng nguồn và xác minh nhãn/trục"] if resolution["status"] == "chart_required" else []),
            "trace_id": trace_id,
        })
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
            raise ai_failure(exc.code, str(exc), trace_id, exc.http_status) from exc
        if provider_answer is None:
            raise ai_failure("AI_NOT_CONFIGURED", "AI provider is not configured", trace_id)
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
    _append_exchange(session, user_message, assistant_message, now)
    flow_log(
        "ANSWER_PERSISTED",
        trace_id=trace_id,
        session_id=session_id,
        document_id=document["id"],
        assistant_message_id=assistant_message["id"],
        citation_pages=citation_pages,
        mode=mode,
    )
    return finish({"user_message": user_message, "assistant_message": assistant_message, "limitations": limitations, "trace_id": trace_id})


@app.get(
    "/api/v1/sessions/{session_id}/messages/{message_id}/trace",
    tags=["sessions"],
    summary="Inspect persisted message data flow",
    description="Doc trace da commit cung assistant message: retrieval, AI validation (neu co), answer_generation va persistence. Khong doc prompt/raw PDF.",
    response_model=MessageTraceResponse,
    response_description="Trace events theo thu tu thuc thi.",
    responses=OPENAPI_COMMON_ERRORS,
)
def read_session_message_trace(session_id: str, message_id: str, request: Request) -> dict[str, Any]:
    session = get_session(session_id, owner_id_for_request(request))
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
async def upload_document(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, Any]:
    """Compatibility upload: persist the file in a server-owned local session."""
    owner_id = owner_id_for_request(request)
    default_id = f"legacy-upload-{owner_id}"
    with catalog_lock:
        if default_id not in catalog["sessions"]:
            now = utc_now()
            catalog["sessions"][default_id] = {"id": default_id, "owner_id": str(owner_id), "title": "Uploads", "created_at": now, "updated_at": now, "documents": [], "messages": []}
    document = await persist_pdf(file, catalog["sessions"][default_id])
    background_tasks.add_task(_extract_in_background, default_id, document["id"], trace_id_for(request), owner_id)
    return {"upload": {**document, "persistence": {"adapter": "cloudflare_r2" if uses_remote_object_storage() else "local_filesystem", "binary_retained": True, "max_bytes": MAX_PDF_BYTES, "max_pages": MAX_PDF_PAGES}}, "next_action": "Open file_url with the PDF.js reader."}
