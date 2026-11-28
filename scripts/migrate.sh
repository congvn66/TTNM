#!/usr/bin/env bash
# Create or update the database tables in DATABASE_URL (safe to run again).
set -euo pipefail
. "$(dirname "$0")/_env.sh"
cd "$ROOT/services/backend"
exec "$PYTHON" -m alembic upgrade head
