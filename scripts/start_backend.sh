#!/usr/bin/env bash
# Start the API on http://127.0.0.1:8000 (or API_PORT) with the settings in .env.
set -euo pipefail
. "$(dirname "$0")/_env.sh"
exec "$PYTHON" -m uvicorn report_qa.api.main:app --app-dir "$ROOT/services/backend/src" --host 127.0.0.1 --port "${API_PORT:-8000}" "$@"
