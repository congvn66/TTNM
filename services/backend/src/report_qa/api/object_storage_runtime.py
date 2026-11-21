"""Cloudflare R2 runtime bridge with a local, disposable processing cache."""

from __future__ import annotations

from pathlib import Path

from report_qa.config import settings
from report_qa.infrastructure.object_storage import ObjectStorageError, build_object_storage

from .session_storage import document_path, extraction_path


object_storage = build_object_storage(settings)


def uses_remote_object_storage() -> bool:
    return settings.storage_backend == "r2"


def pdf_storage_key(document_id: str) -> str:
    return f"documents/{document_id}.pdf"


def extraction_storage_key(extraction_name: str) -> str:
    return f"extractions/{Path(extraction_name).name}"


def cache_pdf(storage_name: str) -> Path:
    path = document_path(storage_name)
    if uses_remote_object_storage() and not path.exists():
        object_storage.download_file(storage_name, path)
    return path


def cache_extraction(extraction_name: str) -> Path:
    path = extraction_path(extraction_name)
    if uses_remote_object_storage() and not path.exists():
        object_storage.download_file(extraction_storage_key(extraction_name), path)
    return path


def persist_pdf_cache(storage_name: str, path: Path) -> None:
    if uses_remote_object_storage():
        object_storage.upload_file(storage_name, path, content_type="application/pdf")


def persist_extraction_cache(extraction_name: str, path: Path) -> None:
    if uses_remote_object_storage():
        object_storage.upload_file(extraction_storage_key(extraction_name), path, content_type="application/json")


def storage_health() -> dict[str, object]:
    return object_storage.health()


__all__ = [
    "ObjectStorageError",
    "cache_extraction",
    "cache_pdf",
    "extraction_storage_key",
    "pdf_storage_key",
    "persist_extraction_cache",
    "persist_pdf_cache",
    "storage_health",
    "uses_remote_object_storage",
]
