#!/usr/bin/env bash
# Start the background worker (needed only when ASYNC_ANSWER_JOBS=true, Postgres only).
set -euo pipefail
. "$(dirname "$0")/_env.sh"
exec "$PYTHON" -m report_qa.worker.runner "$@"
