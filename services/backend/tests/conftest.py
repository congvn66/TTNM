from __future__ import annotations

import os
import tempfile
from pathlib import Path


# Point the session runtime at a throwaway directory before any test imports
# ``report_qa.api``: otherwise the API tests read and rewrite the developer's
# real runtime/sessions.json, racing a dev server that uses the same file.
if not os.getenv("SOURCELENS_RUNTIME_ROOT"):
    os.environ.setdefault("REPORT_QA_RUNTIME_DIR", tempfile.mkdtemp(prefix="report-qa-test-runtime-"))


# Tests must never call a real provider merely because a developer has a key
# in the workspace .env. Live AI is exercised by a separate opt-in smoke run.
_live = os.getenv("SOURCELENS_LIVE_INTEGRATION", "").strip().lower() in {"1", "true", "yes", "on"}
if _live:
    # The application intentionally does not load .env implicitly. For the
    # opt-in smoke suite only, mirror the CLI helper and load unset values so
    # `SOURCELENS_LIVE_INTEGRATION=1 pytest ...` is sufficient.
    _root = Path(__file__).resolve().parents[3]
    _env_file = _root / ".env"
    if _env_file.is_file():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _name, _value = _line.split("=", 1)
                os.environ.setdefault(_name.strip(), _value.strip().strip('"').strip("'"))
else:
    os.environ.setdefault("REPORT_QA_AI_MODE", "deterministic")
