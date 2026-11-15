"""Run backend unit/contract tests with the repository virtualenv when present."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_python() -> str:
    """Prefer the checked-in development environment over system Python.

    Calling this script as ``python scripts/...`` must not silently run a
    different interpreter that lacks the PDF/OCR dependencies declared by the
    project. When no local virtualenv exists, fall back to the caller.
    """
    virtualenv_python = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if virtualenv_python.exists() and virtualenv_python.resolve() != Path(sys.executable).resolve():
        return str(virtualenv_python)
    return sys.executable


if __name__ == "__main__":
    result = subprocess.call(
        [
            test_python(),
            "-m",
            "pytest",
            "services/backend/tests/unit",
            "services/backend/tests/contract",
            "-q",
        ]
    )
    raise SystemExit(result)
