r"""Check the real adapter chain without exposing secrets.

Default usage performs read-only capability/configuration checks and probes the
configured PostgreSQL/R2 endpoints. It does not spend AI tokens. Opt into a
provider call with ``--live-ai`` and a real PDF extraction with ``--pdf``.

Examples (PowerShell, repository root)::

    .\.venv\Scripts\python.exe scripts\check_integrations.py
    .\.venv\Scripts\python.exe scripts\check_integrations.py --live-ai
    .\.venv\Scripts\python.exe scripts\check_integrations.py --pdf .\file.pdf

Exit code is non-zero when a selected/required adapter is not ready. The
command prints JSON only; credentials and provider response bodies are never
printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "services" / "backend" / "src"
sys.path.insert(0, str(SRC))


def _load_env() -> None:
    """Load the repository .env without overwriting exported values."""

    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


def _safe_error(exc: BaseException) -> dict[str, str]:
    return {"error_code": type(exc).__name__, "message": str(exc)[:240]}


def _live_ai() -> dict[str, object]:
    from report_qa.api.ai_provider import ProviderError, live_provider

    provider = live_provider()
    if provider is None:
        return {"status": "skipped", "reason": "REPORT_QA_AI_MODE is deterministic"}
    started = time.perf_counter()
    try:
        answer = provider.answer(
            "Nêu ngắn gọn doanh thu trong context.",
            [{"page": 1, "text": "Doanh thu trong Quý 1/2026 là 120 tỷ đồng."}],
        )
    except ProviderError as exc:
        return {"status": "failed", "code": exc.code, "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
    except Exception as exc:  # pragma: no cover - external provider/runtime
        return {"status": "failed", **_safe_error(exc), "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
    return {
        "status": "ok",
        "provider": answer.provider,
        "model": answer.model,
        "cited_pages": answer.cited_pages,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _extract(pdf: Path) -> dict[str, object]:
    from report_qa.application.evidence_extraction import extract_pdf_artifact

    if not pdf.is_file():
        return {"status": "failed", "code": "PDF_NOT_FOUND"}
    started = time.perf_counter()
    try:
        artifact = extract_pdf_artifact(pdf, f"integration-check-{uuid4()}")
    except Exception as exc:  # pragma: no cover - optional dependency path
        return {"status": "failed", **_safe_error(exc), "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
    batch = artifact.get("evidence_batch") or {}
    return {
        "status": "ok",
        "provider": artifact.get("extraction_provider", "legacy"),
        "pages": len(artifact.get("pages") or []),
        "evidence_count": len(batch.get("evidences") or []),
        "warnings": len(batch.get("warnings") or []),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-ai", action="store_true", help="Send one minimal structured request to the configured AI provider.")
    parser.add_argument("--pdf", type=Path, help="Run the selected PDF extractor on this file.")
    args = parser.parse_args()
    _load_env()

    from report_qa.config import settings
    from report_qa.infrastructure.integrations import readiness, runtime_capabilities
    from report_qa.infrastructure.object_storage import ObjectStorageError, build_object_storage
    from report_qa.infrastructure.postgres import postgres_health

    database = postgres_health()
    try:
        storage = build_object_storage(settings).health()
    except ObjectStorageError as exc:
        storage = {"backend": settings.storage_backend, "configured": False, "status": "invalid_configuration", **_safe_error(exc)}
    capabilities = runtime_capabilities(database=database, storage=storage)
    state, blockers = readiness(capabilities)
    result: dict[str, object] = {
        "status": state,
        "blockers": blockers,
        "capabilities": capabilities,
    }
    if args.live_ai:
        result["live_ai"] = _live_ai()
        if result["live_ai"].get("status") != "ok":
            blockers.append("live_ai:failed")
    if args.pdf:
        result["pdf_run"] = _extract(args.pdf)
        if result["pdf_run"].get("status") != "ok":
            blockers.append("pdf_run:failed")
    result["status"] = "ready" if not blockers else "degraded"
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
