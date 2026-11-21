"""Small connectivity probe used by readiness checks and migration smoke tests."""

from __future__ import annotations

from typing import Any

from report_qa.config import settings


def postgres_health() -> dict[str, Any]:
    """Return a redacted DB probe; never include credentials in the result."""
    if settings.persistence_backend != "postgres":
        return {"configured": False, "status": "disabled", "backend": "json"}
    try:
        import psycopg

        # psycopg accepts the SQLAlchemy URL after removing the dialect prefix.
        dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(dsn, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_schema()")
                database, schema = cursor.fetchone()
        return {"configured": True, "status": "ok", "backend": "postgres", "database": database, "schema": schema}
    except ModuleNotFoundError:
        return {"configured": True, "status": "missing_driver", "backend": "postgres", "error_code": "POSTGRES_DRIVER_MISSING"}
    except Exception as exc:  # pragma: no cover - depends on external service
        return {"configured": True, "status": "unavailable", "backend": "postgres", "error_code": type(exc).__name__}
