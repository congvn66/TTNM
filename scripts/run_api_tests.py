"""Run the HTTP session/document integration contract."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    return subprocess.call([sys.executable, "-m", "pytest", "services/backend/tests/integration/test_session_api.py", "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
