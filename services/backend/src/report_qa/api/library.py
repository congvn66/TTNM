"""Minimal owner-scoped folder commands for the document library."""

from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator
from psycopg.rows import dict_row

from report_qa.config import settings
from .auth import owner_id_for_request
from .user_messages import user_error


router = APIRouter(prefix="/api/v1", tags=["library"])
RUNTIME_OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")


class FolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class FolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: UUID | None = None
    expected_version: int = Field(default=1, ge=1)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("name must not be blank")
        return value


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class ProjectDocumentUpdateRequest(BaseModel):
    folder_id: UUID | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    expected_version: int = Field(default=1, ge=1)

    @field_validator("display_name")
    @classmethod
    def display_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("display_name must not be blank")
        return value


class SessionProjectUpdateRequest(BaseModel):
    project_id: UUID


def _connection():
    if settings.persistence_backend != "postgres":
        raise user_error(503, "LIBRARY_REQUIRES_POSTGRES")
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _project(connection, project_id: UUID, owner_id: UUID):
    row = connection.execute("SELECT id,owner_id,name,created_at,updated_at,deleted_at FROM projects WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (project_id, owner_id)).fetchone()
    if row is None:
        raise user_error(404, "PROJECT_NOT_FOUND")
    return row


def _ensure_default_project(connection, owner_id: UUID):
    # Build the canonical label from code points so this path remains correct
    # even when a Windows shell decodes source files with a legacy code page.
    canonical_name = "Workspace " + chr(0x00E1) + " nh" + chr(0x00E2) + "n"
    canonical = connection.execute(
        "SELECT id,owner_id,name,created_at,updated_at FROM projects WHERE owner_id=%s AND name=%s AND deleted_at IS NULL ORDER BY created_at LIMIT 1",
        (owner_id, canonical_name),
    ).fetchone()
    if canonical:
        return canonical
    return connection.execute(
        """INSERT INTO projects (owner_id,name) VALUES (%s,%s)
           ON CONFLICT (owner_id,name) WHERE deleted_at IS NULL
           DO UPDATE SET updated_at=projects.updated_at
           RETURNING id,owner_id,name,created_at,updated_at""",
        (owner_id, canonical_name),
    ).fetchone()
    row = connection.execute("SELECT id,owner_id,name,created_at,updated_at FROM projects WHERE owner_id=%s AND name='Workspace cá nhân' AND deleted_at IS NULL ORDER BY created_at LIMIT 1", (owner_id,)).fetchone()
    if row:
        return row
    return connection.execute("INSERT INTO projects (owner_id,name) VALUES (%s,%s) RETURNING id,owner_id,name,created_at,updated_at", (owner_id, "Workspace cá nhân")).fetchone()


@router.get("/projects")
def list_projects(request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        _ensure_default_project(connection, owner_id)
        rows = connection.execute(
            """SELECT p.id,p.name,p.created_at,p.updated_at,
                      count(DISTINCT c.id)::int AS session_count,
                      count(DISTINCT pd.document_id)::int AS document_count
                 FROM projects p
                 LEFT JOIN chats c ON c.project_id=p.id AND c.deleted_at IS NULL
                 LEFT JOIN project_documents pd ON pd.project_id=p.id
                WHERE p.owner_id=%s AND p.deleted_at IS NULL
                GROUP BY p.id ORDER BY p.updated_at DESC,p.name""",
            (owner_id,),
        ).fetchall()
    return {"projects": [dict(row) for row in rows]}


@router.post("/projects", status_code=201)
def create_project(payload: ProjectCreateRequest, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        try:
            row = connection.execute("INSERT INTO projects (owner_id,name) VALUES (%s,%s) RETURNING id,owner_id,name,created_at,updated_at", (owner_id, payload.name.strip())).fetchone()
        except Exception as error:
            if getattr(error, "sqlstate", None) == "23505":
                raise user_error(409, "PROJECT_NAME_CONFLICT") from error
            raise
    return {"project": dict(row)}


@router.patch("/projects/{project_id}")
def update_project(project_id: UUID, payload: ProjectUpdateRequest, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        _project(connection, project_id, owner_id)
        row = connection.execute("UPDATE projects SET name=%s,updated_at=now() WHERE id=%s AND owner_id=%s AND deleted_at IS NULL RETURNING id,owner_id,name,created_at,updated_at", (payload.name.strip(), project_id, owner_id)).fetchone()
    return {"project": dict(row)}


@router.delete("/projects/{project_id}")
def archive_project(project_id: UUID, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        _project(connection, project_id, owner_id)
        counts = connection.execute(
            """SELECT
                     (SELECT count(*) FROM chats WHERE project_id=%s AND owner_id=%s AND deleted_at IS NULL) AS session_count,
                     (SELECT count(*) FROM project_documents WHERE project_id=%s AND owner_id=%s) AS document_count""",
            (project_id, owner_id, project_id, owner_id),
        ).fetchone()
        if counts["session_count"] or counts["document_count"]:
            raise user_error(409, "PROJECT_NOT_EMPTY")
        connection.execute("UPDATE projects SET deleted_at=now(),updated_at=now() WHERE id=%s AND owner_id=%s", (project_id, owner_id))
    return {"project_id": str(project_id), "status": "archived"}


@router.get("/projects/{project_id}/library")
def project_library(project_id: UUID, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        project = _project(connection, project_id, owner_id)
        folders = connection.execute("SELECT id,parent_id,name,normalized_name,sort_order,version,created_at,updated_at FROM folders WHERE project_id=%s AND owner_id=%s AND deleted_at IS NULL ORDER BY parent_id NULLS FIRST,sort_order,name", (project_id, owner_id)).fetchall()
        sessions = connection.execute("SELECT id,title,created_at,updated_at FROM chats WHERE project_id=%s AND owner_id=%s AND deleted_at IS NULL ORDER BY updated_at DESC", (project_id, owner_id)).fetchall()
        documents = connection.execute(
            """SELECT pd.document_id,pd.folder_id,pd.display_name,pd.sort_order,pd.version,
                      d.title,d.created_at,dv.file_name,dv.byte_size,dv.page_count,dv.status AS version_status,
                      COALESCE(er.status,'queued') AS extraction_status,c.id AS session_id,c.title AS session_title
                 FROM project_documents pd
                 JOIN documents d ON d.id=pd.document_id AND d.owner_id=pd.owner_id AND d.deleted_at IS NULL
                 LEFT JOIN LATERAL (SELECT * FROM document_versions WHERE document_id=d.id ORDER BY version_no DESC LIMIT 1) dv ON TRUE
                 LEFT JOIN LATERAL (SELECT status FROM extraction_runs WHERE document_version_id=dv.id ORDER BY run_no DESC LIMIT 1) er ON TRUE
                 LEFT JOIN LATERAL (SELECT c.id,c.title FROM chats c JOIN chat_documents cd ON cd.chat_id=c.id JOIN document_versions linked ON linked.id=cd.document_version_id WHERE c.project_id=pd.project_id AND c.owner_id=pd.owner_id AND linked.document_id=d.id AND c.deleted_at IS NULL ORDER BY c.updated_at DESC LIMIT 1) c ON TRUE
                WHERE pd.project_id=%s AND pd.owner_id=%s ORDER BY d.updated_at DESC""",
            (project_id, owner_id),
        ).fetchall()
    return {"project": dict(project), "folders": [dict(row) for row in folders], "sessions": [dict(row) for row in sessions], "documents": [dict(row) for row in documents]}


@router.patch("/sessions/{session_id}/project")
def move_session_to_project(session_id: UUID, payload: SessionProjectUpdateRequest, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        _project(connection, payload.project_id, owner_id)
        result = connection.execute("UPDATE chats SET project_id=%s,updated_at=now() WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (payload.project_id, session_id, owner_id))
        if result.rowcount != 1:
            raise user_error(404, "SESSION_NOT_FOUND")
        connection.execute("""INSERT INTO project_documents (owner_id,project_id,document_id,display_name)
            SELECT %s,%s,dv.document_id,COALESCE(NULLIF(btrim(d.title), ''), 'Tài liệu chưa đặt tên')
              FROM chat_documents cd
              JOIN document_versions dv ON dv.id=cd.document_version_id
              JOIN documents d ON d.id=dv.document_id AND d.owner_id=%s
             WHERE cd.chat_id=%s
            ON CONFLICT (project_id,document_id) DO NOTHING""", (owner_id, payload.project_id, owner_id, session_id))
    return {"session_id": str(session_id), "project_id": str(payload.project_id)}


@router.patch("/projects/{project_id}/documents/{document_id}")
def update_project_document(project_id: UUID, document_id: UUID, payload: ProjectDocumentUpdateRequest, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        _project(connection, project_id, owner_id)
        linked = connection.execute("SELECT version FROM project_documents WHERE project_id=%s AND document_id=%s AND owner_id=%s", (project_id, document_id, owner_id)).fetchone()
        if linked is None:
            raise user_error(404, "PROJECT_DOCUMENT_NOT_FOUND")
        if int(linked["version"]) != payload.expected_version:
            raise user_error(409, "PROJECT_DOCUMENT_REVISION_CONFLICT")
        if payload.folder_id and connection.execute("SELECT id FROM folders WHERE id=%s AND project_id=%s AND owner_id=%s AND deleted_at IS NULL", (payload.folder_id, project_id, owner_id)).fetchone() is None:
            raise user_error(422, "INVALID_FOLDER_PARENT")
        row = connection.execute("""UPDATE project_documents SET folder_id=%s,display_name=COALESCE(%s,display_name),version=version+1
            WHERE project_id=%s AND document_id=%s AND owner_id=%s AND version=%s
            RETURNING project_id,document_id,folder_id,display_name,version""", (payload.folder_id, payload.display_name.strip() if payload.display_name else None, project_id, document_id, owner_id, payload.expected_version)).fetchone()
    return {"document": dict(row)}


@router.get("/projects/{project_id}/folders")
def list_folders(project_id: UUID, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        rows = connection.execute("SELECT id,parent_id,name,normalized_name,sort_order,version,created_at,updated_at FROM folders WHERE project_id=%s AND owner_id=%s AND deleted_at IS NULL ORDER BY parent_id NULLS FIRST,sort_order,name", (project_id, owner_id)).fetchall()
    return {"project_id": str(project_id), "folders": [dict(row) for row in rows]}


@router.post("/projects/{project_id}/folders", status_code=201)
def create_folder(project_id: UUID, payload: FolderCreateRequest, request: Request):
    owner_id = owner_id_for_request(request)
    normalized = _normalize(payload.name)
    with _connection() as connection:
        project = connection.execute("SELECT id FROM projects WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (project_id, owner_id)).fetchone()
        if project is None:
            raise user_error(404, "PROJECT_NOT_FOUND")
        if payload.parent_id:
            parent = connection.execute("SELECT id FROM folders WHERE id=%s AND project_id=%s AND owner_id=%s AND deleted_at IS NULL", (payload.parent_id, project_id, owner_id)).fetchone()
            if parent is None:
                raise user_error(422, "INVALID_FOLDER_PARENT")
        try:
            row = connection.execute("INSERT INTO folders (owner_id,project_id,parent_id,name,normalized_name) VALUES (%s,%s,%s,%s,%s) RETURNING *", (owner_id, project_id, payload.parent_id, payload.name.strip(), normalized)).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise user_error(409, "FOLDER_NAME_CONFLICT") from error
    return {"folder": dict(row)}


@router.patch("/folders/{folder_id}")
def update_folder(folder_id: UUID, payload: FolderUpdateRequest, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        current = connection.execute("SELECT * FROM folders WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (folder_id, owner_id)).fetchone()
        if current is None:
            raise user_error(404, "FOLDER_NOT_FOUND")
        if int(current["version"]) != payload.expected_version:
            raise user_error(409, "FOLDER_REVISION_CONFLICT")
        parent_id = payload.parent_id if "parent_id" in payload.model_fields_set else current["parent_id"]
        if parent_id == folder_id:
            raise user_error(422, "FOLDER_CYCLE")
        if parent_id:
            parent = connection.execute("SELECT id FROM folders WHERE id=%s AND project_id=%s AND owner_id=%s AND deleted_at IS NULL", (parent_id, current["project_id"], owner_id)).fetchone()
            if parent is None:
                raise user_error(422, "INVALID_FOLDER_PARENT")
        name = payload.name.strip() if payload.name is not None else current["name"]
        normalized = _normalize(name)
        try:
            row = connection.execute("UPDATE folders SET name=%s,normalized_name=%s,parent_id=%s,version=version+1,updated_at=now() WHERE id=%s AND owner_id=%s AND version=%s RETURNING *", (name, normalized, parent_id, folder_id, owner_id, payload.expected_version)).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise user_error(409, "FOLDER_NAME_CONFLICT") from error
        if row is None:
            raise user_error(409, "FOLDER_REVISION_CONFLICT")
    return {"folder": dict(row)}


@router.delete("/folders/{folder_id}")
def archive_folder(folder_id: UUID, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        result = connection.execute("UPDATE folders SET deleted_at=now(),version=version+1,updated_at=now() WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (folder_id, owner_id))
        if result.rowcount != 1:
            raise user_error(404, "FOLDER_NOT_FOUND")
    return {"folder_id": str(folder_id), "status": "archived"}
