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

from report_qa.config import DEFAULT_PROJECT_NAMES, settings
from .user_messages import error_detail, user_error


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])
SESSION_COOKIE = "sourcelens_session"
DEMO_OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# Guests use the app before they have an account. Their reports are kept this many days.
GUEST_DAYS = 7
GUEST_UPLOADS_PER_DAY = 3
GUESTS_PER_ADDRESS_PER_HOUR = 30
GUEST_NAME = "Khách"
# Every table with an owner_id column; signing in moves a guest's rows to the account.
OWNER_TABLES = ("projects", "folders", "chats", "documents", "project_documents", "jobs", "message_pins", "request_keys")


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
    return settings.database_url


def _require_postgres() -> None:
    if settings.persistence_backend != "postgres":
        raise user_error(503, "AUTH_REQUIRES_POSTGRES")


def _normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if not EMAIL_RE.fullmatch(email):
        raise user_error(422, "INVALID_EMAIL")
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
    expires = row.get("guest_expires_at")
    return {"id": str(row["id"]), "email": row["email"], "display_name": row["display_name"], "email_verified": False,
            "is_guest": bool(row.get("is_guest")), "guest_expires_at": expires.isoformat() if hasattr(expires, "isoformat") else expires}


def web_origins() -> list[str]:
    """Web addresses allowed to call the API (CORS and the login CSRF check): the dev web plus WEB_ORIGINS."""
    allowed = ["http://127.0.0.1:4173", "http://localhost:4173"]
    configured = os.getenv("WEB_ORIGINS", "")
    allowed += [item.strip().rstrip("/") for item in configured.split(",") if item.strip()]
    return list(dict.fromkeys(allowed))


def _csrf_guard(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    if origin.rstrip("/") not in web_origins():
        raise user_error(403, "CSRF_ORIGIN_REJECTED")


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


def _request_ip_hash(request: Request) -> str | None:
    address = request.client.host if request.client else None
    if not address:
        return None
    salt = os.getenv("AUTH_IP_HASH_SALT", "sourcelens-dev-only").encode("utf-8")
    return hashlib.sha256(salt + address.encode("utf-8")).hexdigest()


def _create_session(connection: Any, user_id: UUID, *, revoke_token: str | None = None, request: Request | None = None) -> tuple[str, datetime]:
    if revoke_token:
        connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL", (_token_hash(revoke_token),))
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.auth_session_days)
    user_agent = (request.headers.get("user-agent") if request else None) or None
    connection.execute("INSERT INTO auth_sessions (user_id,token_hash,expires_at,last_seen_at,user_agent,ip_hash) VALUES (%s,%s,%s,now(),%s,%s)", (user_id, _token_hash(token), expires_at, user_agent[:512] if user_agent else None, _request_ip_hash(request) if request else None))
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
                """SELECT u.id,u.email,u.display_name,u.is_guest,u.guest_expires_at FROM auth_sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>now() AND u.deleted_at IS NULL""",
                (_token_hash(token),),
            ).fetchone()
            if row:
                connection.execute("UPDATE auth_sessions SET last_seen_at=now() WHERE token_hash=%s", (_token_hash(token),))
                return dict(row)
    except Exception as exc:
        # A stale token is a normal 401; a database outage must remain
        # observable as 503 rather than silently looking like a logout.
        raise user_error(503, "AUTH_DATABASE_UNAVAILABLE") from exc
    return None


def current_user(request: Request, *, required: bool = True) -> dict[str, Any] | None:
    user = _user_from_request(request)
    if user:
        return user
    if required or settings.auth_required:
        raise HTTPException(status_code=401, detail=error_detail("AUTH_REQUIRED"), headers={"WWW-Authenticate": "Cookie"})
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


def adopt_guest(connection: Any, guest_id: Any, user_id: Any) -> int:
    """Move a guest's reports to the account they signed in to; returns how many reports moved.

    One transaction with the owner pairs checked at commit (migration 0011). The
    order matters for the unique names: the guest's default project folds into
    the account's own and is archived first, folders and projects whose names the
    account already uses get " (2)", and only then do the owners change. If the
    move fails the sign-in still stands and the reports stay with the guest until
    they expire.
    """
    import logging
    try:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            count = connection.execute("SELECT count(*) AS n FROM documents WHERE owner_id=%s AND deleted_at IS NULL", (guest_id,)).fetchone()["n"]
            default = "SELECT id FROM projects WHERE owner_id=%s AND name = ANY(%s) AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
            target = connection.execute(default, (user_id, list(DEFAULT_PROJECT_NAMES))).fetchone()
            source = connection.execute(default, (guest_id, list(DEFAULT_PROJECT_NAMES))).fetchone()
            if target and source:
                connection.execute(
                    """UPDATE folders f SET name=f.name || ' (2)', normalized_name=f.normalized_name || ' (2)', updated_at=now()
                       WHERE f.project_id=%s AND f.deleted_at IS NULL AND EXISTS (
                         SELECT 1 FROM folders g WHERE g.project_id=%s AND g.deleted_at IS NULL
                           AND g.normalized_name=f.normalized_name AND g.parent_id IS NOT DISTINCT FROM f.parent_id)""",
                    (source["id"], target["id"]))
                for table in ("chats", "folders", "project_documents"):
                    connection.execute(f"UPDATE {table} SET project_id=%s WHERE project_id=%s", (target["id"], source["id"]))
                connection.execute("UPDATE projects SET deleted_at=now(),updated_at=now() WHERE id=%s", (source["id"],))
            connection.execute(
                """UPDATE projects p SET name=p.name || ' (2)', updated_at=now()
                   WHERE p.owner_id=%s AND p.deleted_at IS NULL AND EXISTS (
                     SELECT 1 FROM projects q WHERE q.owner_id=%s AND q.deleted_at IS NULL AND q.name=p.name)""",
                (guest_id, user_id))
            for table in OWNER_TABLES:
                connection.execute(f"UPDATE {table} SET owner_id=%s WHERE owner_id=%s", (user_id, guest_id))
            connection.execute("UPDATE users SET deleted_at=now(),updated_at=now() WHERE id=%s AND is_guest", (guest_id,))
        return int(count)
    except Exception:
        logging.getLogger(__name__).exception("GUEST_ADOPTION_FAILED guest=%s", guest_id)
        return 0


def guest_uploads_left(owner_id: UUID) -> int | None:
    """Uploads a guest may still make today; None for an account (no limit)."""
    if settings.persistence_backend != "postgres":
        return None
    with _connection() as connection:
        row = connection.execute("SELECT is_guest FROM users WHERE id=%s", (owner_id,)).fetchone()
        if not row or not row["is_guest"]:
            return None
        used = connection.execute("SELECT count(*) AS n FROM documents WHERE owner_id=%s AND created_at > now() - interval '1 day'", (owner_id,)).fetchone()["n"]
    return max(0, GUEST_UPLOADS_PER_DAY - int(used))


@router.post("/guest", status_code=status.HTTP_201_CREATED)
def start_guest(request: Request, response: Response) -> dict[str, Any]:
    """Start using SourceLens without an account. Called on the first upload, not on page view."""
    _require_postgres()
    _csrf_guard(request)
    existing = _user_from_request(request)
    if existing:
        return {"user": _public_user(existing), "authenticated": True}
    address = _request_ip_hash(request)
    try:
        with _connection() as connection:
            with connection.transaction():
                if address:
                    recent = connection.execute(
                        """SELECT count(*) AS n FROM auth_sessions s JOIN users u ON u.id=s.user_id
                           WHERE u.is_guest AND s.ip_hash=%s AND u.created_at > now() - interval '1 hour'""", (address,)).fetchone()["n"]
                    if recent >= GUESTS_PER_ADDRESS_PER_HOUR:
                        raise user_error(429, "GUEST_LIMIT")
                user_id = uuid4()
                row = connection.execute(
                    """INSERT INTO users (id,email,normalized_email,password_hash,display_name,is_guest,guest_expires_at)
                       VALUES (%s,'',%s,'!',%s,true,now() + %s * interval '1 day') RETURNING id,email,display_name,is_guest,guest_expires_at""",
                    (user_id, f"guest:{user_id}", GUEST_NAME, GUEST_DAYS)).fetchone()
                token, _ = _create_session(connection, user_id, request=request)
        _set_session_cookie(response, token)
        return {"user": _public_user(dict(row)), "authenticated": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise user_error(503, "AUTH_DATABASE_UNAVAILABLE") from exc


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    _require_postgres()
    _csrf_guard(request)
    email = _normalize_email(payload.email)
    password_hash = _hash_password(payload.password)
    guest = _user_from_request(request)
    guest = guest if guest and guest.get("is_guest") else None
    try:
        with _connection() as connection:
            with connection.transaction():
                if connection.execute("SELECT 1 FROM users WHERE normalized_email=%s AND deleted_at IS NULL", (email,)).fetchone():
                    raise user_error(409, "EMAIL_ALREADY_REGISTERED")
                if guest:
                    # The guest becomes the account: same id, so every report stays where it is.
                    user_id = guest["id"]
                    row = connection.execute(
                        """UPDATE users SET email=%s,normalized_email=%s,password_hash=%s,display_name=%s,is_guest=false,guest_expires_at=NULL,updated_at=now()
                           WHERE id=%s AND is_guest RETURNING id,email,display_name,is_guest,guest_expires_at""",
                        (email, email, password_hash, payload.display_name.strip(), user_id)).fetchone()
                else:
                    user_id = uuid4()
                    row = connection.execute("INSERT INTO users (id,email,normalized_email,password_hash,display_name) VALUES (%s,%s,%s,%s,%s) RETURNING id,email,display_name,is_guest,guest_expires_at", (user_id, email, email, password_hash, payload.display_name.strip())).fetchone()
                # A new session id after the account changes (OWASP); the guest's cookie stops working.
                token, _ = _create_session(connection, user_id, revoke_token=request.cookies.get(SESSION_COOKIE), request=request)
        _set_session_cookie(response, token)
        return {"user": _public_user(dict(row)), "authenticated": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise user_error(503, "AUTH_DATABASE_UNAVAILABLE") from exc


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    _require_postgres()
    _csrf_guard(request)
    email = _normalize_email(payload.email)
    guest = _user_from_request(request)
    guest = guest if guest and guest.get("is_guest") else None
    try:
        with _connection() as connection:
            row = connection.execute("SELECT id,email,display_name,password_hash,is_guest,guest_expires_at FROM users WHERE normalized_email=%s AND deleted_at IS NULL AND NOT is_guest", (email,)).fetchone()
            if not row or not _verify_password(payload.password, row["password_hash"]):
                raise user_error(401, "INVALID_CREDENTIALS")
            with connection.transaction():
                token, _ = _create_session(connection, row["id"], revoke_token=request.cookies.get(SESSION_COOKIE), request=request)
            moved = adopt_guest(connection, guest["id"], row["id"]) if guest else 0
        _set_session_cookie(response, token)
        return {"user": _public_user(dict(row)), "authenticated": True, "moved_reports": moved}
    except HTTPException:
        raise
    except Exception as exc:
        raise user_error(503, "AUTH_DATABASE_UNAVAILABLE") from exc


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
            raise user_error(503, "AUTH_DATABASE_UNAVAILABLE") from exc
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
                    raise user_error(400, "RESET_TOKEN_INVALID")
                connection.execute("UPDATE users SET password_hash=%s,updated_at=now() WHERE id=%s", (password_hash, row["id"]))
                connection.execute("UPDATE account_tokens SET used_at=now() WHERE token_hash=%s", (_token_hash(payload.token),))
                connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (row["id"],))
            session_token, _ = _create_session(connection, row["id"], request=request)
        _set_session_cookie(response, session_token)
        return {"user": _public_user(dict(row)), "authenticated": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise user_error(503, "AUTH_DATABASE_UNAVAILABLE") from exc


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, response: Response) -> dict[str, Any]:
    """Change the password and revoke every other active session."""

    _require_postgres()
    _csrf_guard(request)
    user = current_user(request, required=True)
    if payload.current_password == payload.new_password:
        raise user_error(422, "PASSWORD_UNCHANGED")
    token = request.cookies.get(SESSION_COOKIE)
    password_hash = _hash_password(payload.new_password)
    try:
        with _connection() as connection:
            with connection.transaction():
                row = connection.execute("SELECT password_hash FROM users WHERE id=%s AND deleted_at IS NULL", (user["id"],)).fetchone()
                if not row or not _verify_password(payload.current_password, row["password_hash"]):
                    raise user_error(401, "CURRENT_PASSWORD_INVALID")
                connection.execute("UPDATE users SET password_hash=%s,updated_at=now() WHERE id=%s", (password_hash, user["id"]))
                if token:
                    connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND token_hash<>%s AND revoked_at IS NULL", (user["id"], _token_hash(token)))
                else:
                    connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (user["id"],))
        return {"changed": True, "user": _public_user(user)}
    except HTTPException:
        raise
    except Exception as exc:
        raise user_error(503, "AUTH_DATABASE_UNAVAILABLE") from exc


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
