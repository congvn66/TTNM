"""Read-only runtime capability checks.

The API has two different notions of health:

* liveness: the ASGI process is answering requests;
* readiness: the selected adapters and required optional dependencies can
  actually do their work.

This module deliberately checks imports/configuration only. It does not load
model weights or send a provider request, so it is safe to call from a health
endpoint. The CLI in ``scripts/check_integrations.py`` can opt into a live
OpenRouter request explicitly.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

from report_qa.config import settings


def _module(name: str) -> dict[str, Any]:
    """Return a stable, secret-free import status for one optional module."""

    available = importlib.util.find_spec(name) is not None
    return {"module": name, "status": "available" if available else "missing"}


def _pdf_extraction() -> dict[str, Any]:
    backend = os.getenv("PDF_EXTRACTION_BACKEND", "docling").strip().lower()
    if backend == "legacy":
        return {
            "selected": "legacy",
            "status": "available",
            "modules": [_module("pypdf"), _module("pymupdf")],
        }
    if backend != "docling":
        return {"selected": backend, "status": "invalid", "error_code": "PDF_BACKEND_INVALID"}
    modules = [_module("docling"), _module("pymupdf")]
    return {
        "selected": "docling",
        "status": "available" if all(item["status"] == "available" for item in modules) else "missing_dependency",
        "modules": modules,
    }


def _chart_reader() -> dict[str, Any]:
    backend = os.getenv("CHART_READER_BACKEND", "deplot").strip().lower()
    if backend in {"vector", "legacy", "pdf_vector"}:
        return {"selected": backend, "status": "available", "modules": [_module("pymupdf")]}
    if backend != "deplot":
        return {"selected": backend, "status": "invalid", "error_code": "CHART_BACKEND_INVALID"}
    modules = [_module("transformers"), _module("torch"), _module("PIL"), _module("pymupdf")]
    return {
        "selected": "deplot",
        "model": "google/deplot",
        "status": "available" if all(item["status"] == "available" for item in modules) else "missing_dependency",
        "modules": modules,
        "weights": "lazy (not loaded by readiness probe)",
    }


def _ai_provider() -> dict[str, Any]:
    mode = os.getenv("REPORT_QA_AI_MODE", "deterministic").strip().lower()
    if mode == "deterministic":
        return {"selected": mode, "status": "available", "network_probe": "not_run"}
    if mode == "openrouter":
        configured = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
        return {
            "selected": mode,
            "model": os.getenv("OPENROUTER_MODEL", "openai/gpt-6-luna"),
            "status": "configured" if configured else "missing_configuration",
            "network_probe": "not_run",
        }
    if mode == "gemini":
        configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
        return {
            "selected": mode,
            "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            "status": "configured" if configured else "missing_configuration",
            "network_probe": "not_run",
        }
    return {"selected": mode, "status": "invalid", "error_code": "AI_MODE_INVALID"}


def worker_status() -> dict[str, Any]:
    # With PostgreSQL every upload is a queued job (and answers too when ASYNC_ANSWER_JOBS is on).
    durable = settings.persistence_backend == "postgres"
    return {
        "mode": "durable_postgres" if durable else "compatibility_background_task",
        "status": "requires_external_worker" if durable else "available",
        "command": "scripts/start_worker.ps1 or scripts/start_worker.sh" if durable else None,
    }


def reextraction_status() -> dict[str, Any]:
    """Whether POST .../documents/{id}/extraction can re-read a stored PDF."""
    if settings.persistence_backend == "json":
        return {"status": "available"}
    # PostgreSQL keeps one immutable base extraction run per document version.
    return {"status": "unsupported", "error_code": "REEXTRACTION_NOT_SUPPORTED"}


def runtime_capabilities(*, database: dict[str, Any] | None = None, storage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a redacted capability document suitable for health/diagnostics."""

    return {
        "ai": _ai_provider(),
        "pdf_extraction": _pdf_extraction(),
        "chart_reader": _chart_reader(),
        "worker": worker_status(),
        "reextraction": reextraction_status(),
        "database": database or {"status": "not_probed"},
        "storage": storage or {"status": "not_probed"},
    }


def readiness(capabilities: dict[str, Any]) -> tuple[str, list[str]]:
    """Return ``ready``/``degraded`` and human-readable blocking checks."""

    checks: list[str] = []
    for key in ("pdf_extraction", "chart_reader", "database", "storage"):
        item = capabilities.get(key) or {}
        status = item.get("status")
        if key == "chart_reader" and status == "missing_dependency":
            # Chart reading is on-demand; a missing DePlot model must not make
            # text/table QA unavailable, but it is still visible to operators.
            continue
        if key == "database" and item.get("status") == "disabled":
            continue
        if key == "storage" and item.get("status") == "ok" and item.get("backend") == "local":
            continue
        if status not in {"ok", "available", "configured"}:
            checks.append(f"{key}:{status or 'unknown'}")
    ai = capabilities.get("ai") or {}
    if ai.get("status") == "missing_configuration":
        checks.append(f"ai:{ai.get('selected')}:missing_configuration")
    if ai.get("status") == "invalid":
        checks.append("ai:invalid")
    return ("ready" if not checks else "degraded", checks)


__all__ = ["readiness", "reextraction_status", "runtime_capabilities", "worker_status"]
