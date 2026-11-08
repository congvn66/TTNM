"""Run the dependency-free backend data-flow skeleton tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "backend" / "src"))
sys.path.insert(0, str(ROOT / "services" / "backend" / "tests"))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(str(ROOT / "services" / "backend" / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)

