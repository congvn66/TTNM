"""PostgreSQL-backed email/password sessions.

The product uses opaque HttpOnly cookies.  The API never returns a bearer
token to the browser and only stores a SHA-256 digest of the cookie value.
The small scrypt fallback keeps the offline test environment usable; the
production dependency is Argon2id (``argon2-cffi``) when installed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from report_qa.config import settings


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])
SESSION_COOKIE = "sourcelens_session"
DEMO_OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=8, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ProfilePatch(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class PreferencesPatch(BaseModel):
    theme: str = Field(pattern="^(light|dark|system)$")
    locale: str = Field(default="vi-VN", min_length=2, max_length=20)
    default_answer_style: str = Field(default="grounded", min_length=1, max_length=40)


def _dsn() -> str:
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _require_postgres() -> None:
    if settings.persistence_backend != "postgres":
        raise HTTPException(status_code=503, detail={"code": "AUTH_REQUIRES_POSTGRES", "message": "Authentication cần PostgreSQL để lưu session bền vững."})


def _normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=422, detail={"code": "INVALID_EMAIL", "message": "Email không hợp lệ."})
    return email


def _hash_password(password: str) -> str:
    try:
        from argon2 import PasswordHasher  # type: ignore
        return "argon2$" + PasswordHasher().hash(password)
    except ImportError:
        # Local environments do not always install the optional auth extra.
        # scrypt is a memory-hard, stdlib fallback and is clearly versioned.
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return "scrypt$v1$16384$8$1$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def _verify_password(password: str, encoded: str) -> bool:
    try:
        if encoded.startswith("argon2$"):
            from argon2 import PasswordHasher  # type: ignore
            try:
                PasswordHasher().verify(encoded.removeprefix("argon2$"), password)
                return True
            except Exception:
                return False
        parts = encoded.split("$")
        if len(parts) != 7 or parts[:2] != ["scrypt", "v1"]:
            return False
        _, _, n, r, p, salt_text, digest_text = parts
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, OSError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(row["id"]), "email": row["email"], "display_name": row["display_name"], "email_verified": False}


def _csrf_guard(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = {"http://127.0.0.1:4173", "http://localhost:4173"}
    configured = os.getenv("WEB_ORIGINS", "")
    allowed.update(item.strip().rstrip("/") for item in configured.split(",") if item.strip())
    if origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=403, detail={"code": "CSRF_ORIGIN_REJECTED", "message": "Origin không được phép."})


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.auth_session_days * 86400,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _create_session(connection: Any, user_id: UUID, *, revoke_token: str | None = None) -> tuple[str, datetime]:
    if revoke_token:
        connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL", (_token_hash(revoke_token),))
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.auth_session_days)
    connection.execute("INSERT INTO auth_sessions (user_id,token_hash,expires_at,last_seen_at) VALUES (%s,%s,%s,now())", (user_id, _token_hash(token), expires_at))
    return token, expires_at


def _connection():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(_dsn(), row_factory=dict_row)


def _user_from_request(request: Request) -> dict[str, Any] | None:
    if settings.persistence_backend != "postgres":
        return None
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        with _connection() as connection:
            row = connection.execute(
                """SELECT u.id,u.email,u.display_name FROM auth_sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>now() AND u.deleted_at IS NULL""",
                (_token_hash(token),),
            ).fetchone()
            if row:
                connection.execute("UPDATE auth_sessions SET last_seen_at=now() WHERE token_hash=%s", (_token_hash(token),))
                return dict(row)
    except Exception as exc:
        # A stale token is a normal 401; a database outage must remain
        # observable as 503 rather than silently looking like a logout.
        raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể kiểm tra phiên đăng nhập lúc này."}) from exc
    return None


def current_user(request: Request, *, required: bool = True) -> dict[str, Any] | None:
    user = _user_from_request(request)
    if user:
        return user
    if required or settings.auth_required:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED", "message": "Vui lòng đăng nhập."}, headers={"WWW-Authenticate": "Cookie"})
    return None


def owner_id_for_request(request: Request) -> UUID:
    # Only the in-process worker adapter sets this private request-state
    # marker. A network client can forge headers but cannot populate state.
    internal_owner = getattr(request.state, "internal_owner_id", None)
    if request.headers.get("x-worker-job") == "1" and internal_owner:
        try:
            return UUID(str(internal_owner))
        except ValueError:
            pass
    user = current_user(request, required=False)
    if user:
        return UUID(str(user["id"]))
    if settings.auth_required:
        current_user(request, required=True)
    return DEMO_OWNER_ID


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    _require_postgres()
    _csrf_guard(request)
    email = _normalize_email(payload.email)
    password_hash = _hash_password(payload.password)
    try:
        with _connection() as connection:
            with connection.transaction():
                if connection.execute("SELECT 1 FROM users WHERE normalized_email=%s AND deleted_at IS NULL", (email,)).fetchone():
                    raise HTTPException(status_code=409, detail={"code": "EMAIL_ALREADY_REGISTERED", "message": "Không thể tạo tài khoản với thông tin này."})
                user_id = uuid4()
                row = connection.execute("INSERT INTO users (id,email,normalized_email,password_hash,display_name) VALUES (%s,%s,%s,%s,%s) RETURNING id,email,display_name", (user_id, email, email, password_hash, payload.display_name.strip())).fetchone()
                token, _ = _create_session(connection, user_id)
        _set_session_cookie(response, token)
        return {"user": _public_user(dict(row)), "authenticated": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể tạo tài khoản lúc này."}) from exc


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    _require_postgres()
    _csrf_guard(request)
    email = _normalize_email(payload.email)
    try:
        with _connection() as connection:
            row = connection.execute("SELECT id,email,display_name,password_hash FROM users WHERE normalized_email=%s AND deleted_at IS NULL", (email,)).fetchone()
            if not row or not _verify_password(payload.password, row["password_hash"]):
                raise HTTPException(status_code=401, detail={"code": "INVALID_CREDENTIALS", "message": "Email hoặc mật khẩu không đúng."})
            with connection.transaction():
                token, _ = _create_session(connection, row["id"], revoke_token=request.cookies.get(SESSION_COOKIE))
        _set_session_cookie(response, token)
        return {"user": _public_user(dict(row)), "authenticated": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể đăng nhập lúc này."}) from exc


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    _require_postgres()
    _csrf_guard(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            with _connection() as connection:
                connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL", (_token_hash(token),))
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể đăng xuất lúc này."}) from exc
    _clear_session_cookie(response)
    return {"authenticated": False}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    _require_postgres()
    user = current_user(request, required=True)
    return {"user": _public_user(user or {}), "authenticated": True}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request) -> dict[str, Any]:
    """Always return an accepted response; only the dev mail adapter reveals a token."""
    _require_postgres()
    _csrf_guard(request)
    email = _normalize_email(payload.email)
    token = secrets.token_urlsafe(36)
    with _connection() as connection:
        row = connection.execute("SELECT id FROM users WHERE normalized_email=%s AND deleted_at IS NULL", (email,)).fetchone()
        if row:
            with connection.transaction():
                connection.execute("DELETE FROM account_tokens WHERE user_id=%s AND purpose='reset_password' AND used_at IS NULL", (row["id"],))
                connection.execute("INSERT INTO account_tokens (user_id,token_hash,purpose,expires_at) VALUES (%s,%s,'reset_password',now()+interval '30 minutes')", (row["id"], _token_hash(token)))
    result: dict[str, Any] = {"accepted": True}
    if os.getenv("AUTH_EXPOSE_RESET_TOKEN", "false").strip().lower() in {"1", "true", "yes", "on"} and row:
        result["dev_token"] = token
    return result


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, response: Response) -> dict[str, Any]:
    _require_postgres()
    _csrf_guard(request)
    password_hash = _hash_password(payload.password)
    try:
        with _connection() as connection:
            with connection.transaction():
                row = connection.execute("""SELECT u.id,u.email,u.display_name FROM account_tokens t JOIN users u ON u.id=t.user_id
                    WHERE t.token_hash=%s AND t.purpose='reset_password' AND t.used_at IS NULL AND t.expires_at>now() AND u.deleted_at IS NULL""", (_token_hash(payload.token),)).fetchone()
                if not row:
                    raise HTTPException(status_code=400, detail={"code": "RESET_TOKEN_INVALID", "message": "Liên kết đặt lại không hợp lệ hoặc đã hết hạn."})
                connection.execute("UPDATE users SET password_hash=%s,updated_at=now() WHERE id=%s", (password_hash, row["id"]))
                connection.execute("UPDATE account_tokens SET used_at=now() WHERE token_hash=%s", (_token_hash(payload.token),))
                connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (row["id"],))
                session_token, _ = _create_session(connection, row["id"])
        _set_session_cookie(response, session_token)
        return {"user": _public_user(dict(row)), "authenticated": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể đặt lại mật khẩu lúc này."}) from exc


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, response: Response) -> dict[str, Any]:
    """Change the password and revoke every other active session."""

    _require_postgres()
    _csrf_guard(request)
    user = current_user(request, required=True)
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=422, detail={"code": "PASSWORD_UNCHANGED", "message": "Mật khẩu mới phải khác mật khẩu hiện tại."})
    token = request.cookies.get(SESSION_COOKIE)
    password_hash = _hash_password(payload.new_password)
    try:
        with _connection() as connection:
            with connection.transaction():
                row = connection.execute("SELECT password_hash FROM users WHERE id=%s AND deleted_at IS NULL", (user["id"],)).fetchone()
                if not row or not _verify_password(payload.current_password, row["password_hash"]):
                    raise HTTPException(status_code=401, detail={"code": "CURRENT_PASSWORD_INVALID", "message": "Mật khẩu hiện tại không đúng."})
                connection.execute("UPDATE users SET password_hash=%s,updated_at=now() WHERE id=%s", (password_hash, user["id"]))
                if token:
                    connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND token_hash<>%s AND revoked_at IS NULL", (user["id"], _token_hash(token)))
                else:
                    connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (user["id"],))
        return {"changed": True, "user": _public_user(user)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "AUTH_DATABASE_UNAVAILABLE", "message": "Không thể đổi mật khẩu lúc này."}) from exc


@settings_router.get("/profile")
def profile(request: Request) -> dict[str, Any]:
    _require_postgres()
    user = current_user(request, required=True)
    return {"user": _public_user(user or {})}


@settings_router.patch("/profile")
def patch_profile(payload: ProfilePatch, request: Request) -> dict[str, Any]:
    _require_postgres()
    _csrf_guard(request)
    user = current_user(request, required=True)
    with _connection() as connection:
        row = connection.execute("UPDATE users SET display_name=%s,updated_at=now() WHERE id=%s AND deleted_at IS NULL RETURNING id,email,display_name", (payload.display_name.strip(), user["id"])).fetchone()
    return {"user": _public_user(dict(row))}


@settings_router.get("/preferences")
def preferences(request: Request) -> dict[str, Any]:
    _require_postgres()
    user = current_user(request, required=True)
    with _connection() as connection:
        row = connection.execute("SELECT theme,locale,default_answer_style FROM user_preferences WHERE user_id=%s", (user["id"],)).fetchone()
    return {"preferences": dict(row) if row else {"theme": "system", "locale": "vi-VN", "default_answer_style": "grounded"}}


@settings_router.patch("/preferences")
def patch_preferences(payload: PreferencesPatch, request: Request) -> dict[str, Any]:
    _require_postgres()
    _csrf_guard(request)
    user = current_user(request, required=True)
    with _connection() as connection:
        row = connection.execute("""INSERT INTO user_preferences (user_id,theme,locale,default_answer_style)
            VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET theme=EXCLUDED.theme,locale=EXCLUDED.locale,default_answer_style=EXCLUDED.default_answer_style,updated_at=now()
            RETURNING theme,locale,default_answer_style""", (user["id"], payload.theme, payload.locale, payload.default_answer_style)).fetchone()
    return {"preferences": dict(row)}


__all__ = ["DEMO_OWNER_ID", "SESSION_COOKIE", "current_user", "owner_id_for_request", "router", "settings_router"]
