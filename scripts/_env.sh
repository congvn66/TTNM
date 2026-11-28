# Shared by the start scripts: load the repo-root .env and find Python.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -f "$ROOT/.env" ]; then
  echo "Missing $ROOT/.env. Copy .env.example to .env and fill it in (see docs/SETUP.md)." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. "$ROOT/.env"
set +a
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  echo "Missing $PYTHON. Create it with: python3.12 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi
export PYTHONPATH="$ROOT/services/backend/src"
