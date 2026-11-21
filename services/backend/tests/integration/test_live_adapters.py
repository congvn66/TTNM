"""Opt-in smoke tests for the real external adapters.

These tests are intentionally skipped during the normal offline suite. Run
with ``SOURCELENS_LIVE_INTEGRATION=1`` only in an environment containing real
PostgreSQL, Cloudflare R2 and AI credentials.
"""

from __future__ import annotations

import os

import pytest


LIVE = os.getenv("SOURCELENS_LIVE_INTEGRATION", "").strip().lower() in {"1", "true", "yes", "on"}
pytestmark = pytest.mark.skipif(not LIVE, reason="SOURCELENS_LIVE_INTEGRATION is not enabled")


def test_live_postgres_and_r2_health() -> None:
    from report_qa.config import settings
    from report_qa.infrastructure.object_storage import build_object_storage
    from report_qa.infrastructure.postgres import postgres_health

    database = postgres_health()
    assert database.get("status") == "ok", database
    storage = build_object_storage(settings).health()
    assert storage.get("status") == "ok", storage


def test_live_ai_structured_answer() -> None:
    from report_qa.api.ai_provider import ProviderError, live_provider, provider_mode

    provider = live_provider()
    if provider is None:
        pytest.fail(f"REPORT_QA_AI_MODE={provider_mode()!r} does not select a live provider")
    try:
        result = provider.answer(
            "Nêu giá trị doanh thu trong context.",
            [{"page": 1, "text": "Doanh thu Quý 1/2026 là 120 tỷ đồng."}],
        )
    except ProviderError as error:
        pytest.fail(f"live provider failed: {error.code}")
    assert result.structured and result.cited_pages == [1]
