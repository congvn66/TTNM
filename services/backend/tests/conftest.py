from __future__ import annotations

import os


# Tests must never call a real provider merely because a developer has a key
# in the workspace .env. Live AI is exercised by a separate opt-in smoke run.
os.environ.setdefault("REPORT_QA_AI_MODE", "deterministic")
