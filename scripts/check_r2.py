"""Read-only Cloudflare R2 readiness probe.

Run after exporting .env into the current shell:
  python scripts/check_r2.py
"""

from __future__ import annotations

import json
import sys

from report_qa.config import settings
from report_qa.infrastructure.object_storage import ObjectStorageError, build_object_storage


def main() -> int:
    if settings.storage_backend != "r2":
        print(json.dumps({"backend": settings.storage_backend, "status": "disabled", "message": "Set STORAGE_BACKEND=r2 first."}))
        return 2
    try:
        result = build_object_storage(settings).health()
    except ObjectStorageError as exc:
        print(json.dumps({"backend": "r2", "status": "invalid_configuration", "message": str(exc)}))
        return 2
    print(json.dumps(result))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
