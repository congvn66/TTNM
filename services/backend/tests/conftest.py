"""Shared test setup.

Point the session runtime at a throwaway directory before any test imports
``report_qa.api``: otherwise the API tests read and rewrite the developer's
real runtime/sessions.json, racing a dev server that uses the same file.
"""

import os
import tempfile

os.environ.setdefault("REPORT_QA_RUNTIME_DIR", tempfile.mkdtemp(prefix="report-qa-test-runtime-"))
