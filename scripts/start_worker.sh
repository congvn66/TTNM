#!/usr/bin/env bash
# Start the background worker (needed only when ASYNC_ANSWER_JOBS=true, Postgres only).
# A worker whose running job is cancelled exits with code 75 (runner.CANCELLED_EXIT_CODE)
# to stop that work at once; it is started again here.
set -uo pipefail
. "$(dirname "$0")/_env.sh"
child=""
trap '[ -n "$child" ] && kill -TERM "$child" 2>/dev/null; wait "$child" 2>/dev/null; exit 143' TERM INT
while true; do
  "$PYTHON" -m report_qa.worker.runner "$@" &
  child=$!
  wait "$child"
  code=$?
  [ "$code" -eq 75 ] || exit "$code"
  echo "worker: its job was cancelled; starting again"
done
