"""Typed runtime configuration for the persistence cutover.

The JSON adapter remains the safe default for offline tests. Setting
``PERSISTENCE_BACKEND=postgres`` is deliberately fail-fast: the API must not
silently continue writing JSON when a PostgreSQL cutover was requested.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    persistence_backend: str
    database_url: str
    minio_endpoint: str
    minio_bucket: str

    @classmethod
    def from_env(cls) -> "Settings":
        backend = os.getenv("PERSISTENCE_BACKEND", "json").strip().lower()
        if backend not in {"json", "postgres"}:
            raise RuntimeError("PERSISTENCE_BACKEND must be 'json' or 'postgres'")
        return cls(
            persistence_backend=backend,
            database_url=os.getenv("DATABASE_URL", "postgresql+psycopg://sourcelens:sourcelens-dev-only@127.0.0.1:5432/sourcelens"),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", "http://127.0.0.1:9000"),
            minio_bucket=os.getenv("MINIO_BUCKET", "sourcelens"),
        )


settings = Settings.from_env()


def postgres_configured() -> bool:
    return settings.persistence_backend == "postgres"
