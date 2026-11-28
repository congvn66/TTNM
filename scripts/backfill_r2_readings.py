"""Store finished readings in R2 under their final name (one-off repair).

Before the fix in complete_document_extraction, a worker uploaded a reading to
R2 only under its first name (<document>.<run>.json), while PostgreSQL asks for
<version>.json. An API on another machine could then not open the report. This
copies every local reading named <version>.json that R2 does not have yet.

Usage (loads the repo-root .env through the start-script helper):
  bash -c '. scripts/_env.sh && "$PYTHON" scripts/backfill_r2_readings.py [--dry-run]'
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "backend" / "src"))

from report_qa.api.object_storage_runtime import extraction_storage_key, object_storage, uses_remote_object_storage  # noqa: E402
from report_qa.api.session_storage import EXTRACTION_ROOT  # noqa: E402

VERSION_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$")


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if not uses_remote_object_storage():
        print("STORAGE_BACKEND is not r2: nothing to do.")
        return 0
    names = sorted(path.name for path in EXTRACTION_ROOT.glob("*.json") if VERSION_NAME.match(path.name))
    present = uploaded = 0
    with tempfile.TemporaryDirectory() as folder:
        for name in names:
            try:
                object_storage.download_file(extraction_storage_key(name), Path(folder) / name)
                present += 1
                continue
            except Exception:  # not in R2 yet
                pass
            if not dry_run:
                object_storage.upload_file(extraction_storage_key(name), EXTRACTION_ROOT / name, content_type="application/json")
            uploaded += 1
    print(f"{len(names)} local readings: {present} already in R2, {uploaded} {'to upload (dry run)' if dry_run else 'uploaded'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
