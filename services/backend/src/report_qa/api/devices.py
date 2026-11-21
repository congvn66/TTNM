"""Owner-scoped device/session management for the account security screen."""

from __future__ import annotations

import hashlib
import os
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from psycopg.rows import dict_row

from report_qa.config import settings
from .auth import SESSION_COOKIE, _connection, _csrf_guard, _token_hash, current_user


router = APIRouter(prefix="/api/v1/auth", tags=["auth-sessions"])


def _ip_hash(request: Request) -> str | None:
    address = request.client.host if request.client else None
    if not address:
        return None
    salt = os.getenv("AUTH_IP_HASH_SALT", "sourcelens-dev-only").encode("utf-8")
    return hashlib.sha256(salt + address.encode("utf-8")).hexdigest()


def _public_session(row: dict, current: bool = False) -> dict:
    return {
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "last_seen_at": row["last_seen_at"].isoformat() if row.get("last_seen_at") and hasattr(row["last_seen_at"], "isoformat") else row.get("last_seen_at"),
        "expires_at": row["expires_at"].isoformat() if hasattr(row["expires_at"], "isoformat") else str(row["expires_at"]),
        "user_agent": row.get("user_agent") or "Thiết bị không xác định",
        "current": current,
        "revoked": row.get("revoked_at") is not None,
    }


@router.get("/sessions")
def list_auth_sessions(request: Request):
    user = current_user(request, required=True)
    token = request.cookies.get(SESSION_COOKIE)
    current_hash = _token_hash(token) if token else None
    try:
        with _connection() as connection:
            rows = connection.execute(
                """SELECT id,token_hash,created_at,last_seen_at,expires_at,revoked_at,user_agent
                     FROM auth_sessions
                    WHERE user_id=%s AND expires_at>now() AND revoked_at IS NULL
                    ORDER BY COALESCE(last_seen_at,created_at) DESC""",
                (UUID(str(user["id"])),),
            ).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể tải danh sách thiết bị lúc này."}) from exc
    return {"sessions": [_public_session(dict(row), bool(current_hash and row["token_hash"] == current_hash)) for row in rows]}


@router.delete("/sessions/{session_id}")
def revoke_auth_session(session_id: UUID, request: Request, response: Response):
    _csrf_guard(request)
    user = current_user(request, required=True)
    token = request.cookies.get(SESSION_COOKIE)
    current_hash = _token_hash(token) if token else None
    try:
        with _connection() as connection:
            row = connection.execute(
                """UPDATE auth_sessions SET revoked_at=now()
                    WHERE id=%s AND user_id=%s AND revoked_at IS NULL
                RETURNING id,token_hash""",
                (session_id, UUID(str(user["id"]))),
            ).fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể thu hồi thiết bị lúc này."}) from exc
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "AUTH_SESSION_NOT_FOUND", "message": "Không tìm thấy phiên đăng nhập."})
    if current_hash and row["token_hash"] == current_hash:
        response.delete_cookie(SESSION_COOKIE, path="/")
    return {"session_id": str(session_id), "revoked": True, "current": bool(current_hash and row["token_hash"] == current_hash)}


@router.post("/sessions/revoke-others")
def revoke_other_auth_sessions(request: Request):
    _csrf_guard(request)
    user = current_user(request, required=True)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED", "message": "Vui lòng đăng nhập."})
    try:
        with _connection() as connection:
            result = connection.execute(
                """UPDATE auth_sessions SET revoked_at=now()
                    WHERE user_id=%s AND token_hash<>%s AND revoked_at IS NULL""",
                (UUID(str(user["id"])), _token_hash(token)),
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể thu hồi các thiết bị khác lúc này."}) from exc
    return {"revoked_count": result.rowcount}


__all__ = ["router"]
