"""Check the repo-root .env before starting the app. Prints which settings are set, never their values.

Usage: .venv/bin/python scripts/check_env.py   (Windows: .venv\\Scripts\\python.exe scripts\\check_env.py)
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def main() -> int:
    if not ENV_FILE.exists():
        print(f"Missing {ENV_FILE}. Copy .env.example to .env and fill it in (see docs/SETUP.md).")
        return 1
    env = {key: (value or "").strip() for key, value in dotenv_values(ENV_FILE).items()}
    problems: list[str] = []

    def need(key: str, why: str) -> None:
        print(f"  {'set    ' if env.get(key) else 'MISSING'} {key}  ({why})")
        if not env.get(key):
            problems.append(key)

    ai_mode = env.get("REPORT_QA_AI_MODE", "")
    print("AI")
    need("REPORT_QA_AI_MODE", "gemini or openrouter")
    if ai_mode == "gemini":
        need("GEMINI_API_KEY", "Google AI Studio key")
    elif ai_mode == "openrouter":
        need("OPENROUTER_API_KEY", "OpenRouter key")
    elif ai_mode:
        problems.append("REPORT_QA_AI_MODE")
        print(f"  REPORT_QA_AI_MODE must be gemini or openrouter, not {ai_mode!r}")

    print("Database")
    if env.get("PERSISTENCE_BACKEND", "json") == "postgres":
        need("DATABASE_URL", "Supabase connection string")
        url = env.get("DATABASE_URL", "")
        if url:
            parts = urlsplit(url)
            if parts.scheme not in {"postgresql", "postgres", "postgresql+psycopg"}:
                problems.append("DATABASE_URL")
                print(f"  DATABASE_URL must start with postgresql://, not {parts.scheme}://")
            elif parts.port == 6543:
                print("  note: port 6543 is Supabase's transaction pooler. Use the session pooler (port 5432) instead.")
    else:
        print("  PERSISTENCE_BACKEND is json: data stays in runtime/ on this computer")

    print("File storage")
    if env.get("STORAGE_BACKEND", "local") == "r2":
        for key in ("R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
            need(key, "Cloudflare R2")
    else:
        print("  STORAGE_BACKEND is local: PDFs stay in runtime/ on this computer")

    print("Login")
    print(f"  AUTH_REQUIRED={env.get('AUTH_REQUIRED', 'false')}")
    if env.get("AUTH_REQUIRED", "false").lower() == "true" and env.get("PERSISTENCE_BACKEND", "json") != "postgres":
        problems.append("AUTH_REQUIRED")
        print("  Login needs PERSISTENCE_BACKEND=postgres (accounts live in the database)")

    print("OK" if not problems else f"Fix: {', '.join(dict.fromkeys(problems))}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
