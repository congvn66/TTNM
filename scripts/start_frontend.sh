#!/usr/bin/env bash
# Start the web app on http://127.0.0.1:4173 (or WEB_PORT). It talks to the API on port 8000 (or API_PORT).
set -euo pipefail
cd "$(dirname "$0")/../apps/web"
export VITE_API_URL="${VITE_API_URL:-http://127.0.0.1:${API_PORT:-8000}}"
[ -d node_modules ] || npm install
exec npm run dev -- --host 127.0.0.1 --port "${WEB_PORT:-4173}" --strictPort
