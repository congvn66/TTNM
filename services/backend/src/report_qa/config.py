"""Typed runtime configuration for the persistence cutover.

The JSON adapter remains the safe default for offline tests. Setting
``PERSISTENCE_BACKEND=postgres`` is deliberately fail-fast: the API must not
silently continue writing JSON when a PostgreSQL cutover was requested.
"""

from __future__ import annotations


import os
from dataclasses import dataclass


# The project every account starts with. The first name is used for new ones; the older
# names (one misspelt by migration 0006) still find projects made before 0009 renamed them.
DEFAULT_PROJECT_NAMES = ("Báo cáo của tôi", "Workspace cá nhân", "Workspace \u00e1 nh\u00e2n")


def psycopg_url(url: str) -> str:
    """The URL psycopg connects with. DATABASE_URL may be written either way:
    "postgresql://" (Supabase's form) or SQLAlchemy's "postgresql+psycopg://"."""
    url = url.strip()
    for prefix in ("postgresql+psycopg://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


@dataclass(frozen=True, slots=True)
class Settings:
    persistence_backend: str
    database_url: str
    storage_backend: str
    r2_endpoint: str
    r2_bucket: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_region: str
    auth_required: bool
    auth_cookie_secure: bool
    auth_session_days: int
    async_answer_jobs: bool
    max_parallel_extractions: int

    @classmethod
    def from_env(cls) -> "Settings":
        backend = os.getenv("PERSISTENCE_BACKEND", "json").strip().lower()
        if backend not in {"json", "postgres"}:
            raise RuntimeError("PERSISTENCE_BACKEND must be 'json' or 'postgres'")
        storage_backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
        if storage_backend not in {"local", "r2"}:
            raise RuntimeError("STORAGE_BACKEND must be 'local' or 'r2'")
        max_parallel_extractions = os.getenv("REPORT_QA_MAX_PARALLEL_EXTRACTIONS", "2").strip()
        if not max_parallel_extractions.isdigit() or int(max_parallel_extractions) < 1:
            raise RuntimeError("REPORT_QA_MAX_PARALLEL_EXTRACTIONS must be a whole number of at least 1")
        return cls(
            persistence_backend=backend,
            database_url=psycopg_url(os.getenv("DATABASE_URL", "postgresql://sourcelens:sourcelens-dev-only@127.0.0.1:5432/sourcelens")),
            storage_backend=storage_backend,
            r2_endpoint=os.getenv("R2_ENDPOINT", "").strip(),
            r2_bucket=os.getenv("R2_BUCKET", "").strip(),
            r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID", "").strip(),
            r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
            r2_region=os.getenv("R2_REGION", "auto").strip() or "auto",
            auth_required=os.getenv("AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"},
            auth_cookie_secure=os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"},
            auth_session_days=max(1, min(90, int(os.getenv("AUTH_SESSION_DAYS", "30")))),
            async_answer_jobs=os.getenv("ASYNC_ANSWER_JOBS", "false").strip().lower() in {"1", "true", "yes", "on"},
            max_parallel_extractions=int(max_parallel_extractions),
        )


settings = Settings.from_env()


def postgres_configured() -> bool:
    return settings.persistence_backend == "postgres"


def r2_configured() -> bool:
    return settings.storage_backend == "r2"
