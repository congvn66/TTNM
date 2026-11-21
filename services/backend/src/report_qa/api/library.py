"""Minimal owner-scoped folder commands for the document library."""

from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from report_qa.config import settings
from .auth import owner_id_for_request


router = APIRouter(prefix="/api/v1", tags=["library"])
RUNTIME_OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")


class FolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = None


class FolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: UUID | None = None
    expected_version: int = Field(default=1, ge=1)


def _connection():
    if settings.persistence_backend != "postgres":
        raise HTTPException(status_code=503, detail={"code": "LIBRARY_REQUIRES_POSTGRES", "message": "Library cần PostgreSQL."})
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


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
            raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "project not found"})
        if payload.parent_id:
            parent = connection.execute("SELECT id FROM folders WHERE id=%s AND project_id=%s AND owner_id=%s AND deleted_at IS NULL", (payload.parent_id, project_id, owner_id)).fetchone()
            if parent is None:
                raise HTTPException(status_code=422, detail={"code": "INVALID_FOLDER_PARENT", "message": "parent folder is not in this project"})
        try:
            row = connection.execute("INSERT INTO folders (owner_id,project_id,parent_id,name,normalized_name) VALUES (%s,%s,%s,%s,%s) RETURNING *", (owner_id, project_id, payload.parent_id, payload.name.strip(), normalized)).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise HTTPException(status_code=409, detail={"code": "FOLDER_NAME_CONFLICT", "message": "folder name already exists"}) from error
    return {"folder": dict(row)}


@router.patch("/folders/{folder_id}")
def update_folder(folder_id: UUID, payload: FolderUpdateRequest, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        current = connection.execute("SELECT * FROM folders WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (folder_id, owner_id)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail={"code": "FOLDER_NOT_FOUND", "message": "folder not found"})
        if int(current["version"]) != payload.expected_version:
            raise HTTPException(status_code=409, detail={"code": "FOLDER_REVISION_CONFLICT", "message": "folder changed; reload before editing"})
        parent_id = payload.parent_id if "parent_id" in payload.model_fields_set else current["parent_id"]
        if parent_id == folder_id:
            raise HTTPException(status_code=422, detail={"code": "FOLDER_CYCLE", "message": "folder cannot be its own parent"})
        if parent_id:
            parent = connection.execute("SELECT id FROM folders WHERE id=%s AND project_id=%s AND owner_id=%s AND deleted_at IS NULL", (parent_id, current["project_id"], owner_id)).fetchone()
            if parent is None:
                raise HTTPException(status_code=422, detail={"code": "INVALID_FOLDER_PARENT", "message": "parent folder is not in this project"})
        name = payload.name.strip() if payload.name is not None else current["name"]
        normalized = _normalize(name)
        try:
            row = connection.execute("UPDATE folders SET name=%s,normalized_name=%s,parent_id=%s,version=version+1,updated_at=now() WHERE id=%s AND owner_id=%s AND version=%s RETURNING *", (name, normalized, parent_id, folder_id, owner_id, payload.expected_version)).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise HTTPException(status_code=409, detail={"code": "FOLDER_NAME_CONFLICT", "message": "folder name already exists"}) from error
        if row is None:
            raise HTTPException(status_code=409, detail={"code": "FOLDER_REVISION_CONFLICT", "message": "folder changed; reload before editing"})
    return {"folder": dict(row)}


@router.delete("/folders/{folder_id}")
def archive_folder(folder_id: UUID, request: Request):
    owner_id = owner_id_for_request(request)
    with _connection() as connection:
        result = connection.execute("UPDATE folders SET deleted_at=now(),version=version+1,updated_at=now() WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (folder_id, owner_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={"code": "FOLDER_NOT_FOUND", "message": "folder not found"})
    return {"folder_id": str(folder_id), "status": "archived"}
