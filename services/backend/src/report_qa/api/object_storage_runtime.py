"""Cloudflare R2 runtime bridge with a local, disposable processing cache."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

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


def read_extraction(extraction_name: str) -> dict[str, Any]:
    """The parsed artifact of a reading, shared by every request: callers must not change it.

    An artifact file is written once per reading and never changed, so it is
    parsed once (a large one is 20+ MB of JSON). The key holds the file's
    modification time and size, so a replaced file is parsed again.
    """
    path = cache_extraction(extraction_name)
    stat = path.stat()
    return _parsed(str(path), stat.st_mtime_ns, stat.st_size)


# A large artifact takes about 130 MB parsed; the readings in use are few.
@lru_cache(maxsize=4)
def _parsed(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


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
    "read_extraction",
    "extraction_storage_key",
    "pdf_storage_key",
    "persist_extraction_cache",
    "persist_pdf_cache",
    "storage_health",
    "uses_remote_object_storage",
]
