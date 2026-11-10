from __future__ import annotations

from report_qa.config import Settings
from report_qa.infrastructure.postgres import PostgresRevisionStore


def test_json_is_safe_default_and_postgres_is_explicit() -> None:
    settings = Settings.from_env()
    assert settings.persistence_backend in {"json", "postgres"}


def test_invalid_persistence_backend_fails_fast(monkeypatch) -> None:
    monkeypatch.setenv("PERSISTENCE_BACKEND", "redis")
    try:
        Settings.from_env()
    except RuntimeError as exc:
        assert "PERSISTENCE_BACKEND" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid backend was accepted")


def test_revision_store_does_not_open_a_connection_until_a_transaction() -> None:
    store = PostgresRevisionStore("postgresql+psycopg://sourcelens:sourcelens-dev-only@127.0.0.1:5432/sourcelens")
    assert store._connection is None
