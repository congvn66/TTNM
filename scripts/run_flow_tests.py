from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_mock_data import main as generate_mock_data  # noqa: E402
from scripts.check_design_consistency import check_all as check_design  # noqa: E402
from scripts.validate_mock_data import validate_all  # noqa: E402


def main() -> int:
    generate_mock_data()
    design = check_design()
    print(f"Validated design consistency: {design}")
    counts = validate_all()
    print(f"Validated mock data: {counts}")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py", top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
