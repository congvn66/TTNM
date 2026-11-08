"""Connectivity check for the PostgreSQL cutover milestone.

Usage:
  $env:PERSISTENCE_BACKEND='postgres'
  python scripts/check_postgres.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "backend" / "src"))

from report_qa.config import settings
from report_qa.infrastructure.postgres import postgres_health


result = postgres_health()
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
if settings.persistence_backend == "postgres" and result.get("status") != "ok":
    raise SystemExit(1)
