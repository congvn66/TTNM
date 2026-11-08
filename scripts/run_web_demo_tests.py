"""Source, UTF-8 and production-build checks for the SourceLens React UI."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
FILES = (WEB / "index.html", WEB / "package.json", WEB / "src" / "main.jsx", WEB / "src" / "App.jsx", WEB / "src" / "app.css", WEB / "src" / "trace.css", WEB / "README.md", ROOT / "doc" / "frontend-demo.md")
MARKERS = {
    WEB / "index.html": ("SourceLens", "/src/main.jsx"),
    WEB / "package.json": ('"react"', '"pdfjs-dist"', '"vite"'),
    WEB / "src" / "App.jsx": ("pdfjs.getDocument({ url: fileUrl })", "relativeFileUrl", "/api/v1/sessions", "messages/", "Data flow", "structured_answer", "StructuredAnswer", "claims", "evidence_quotes", "pdf-text-layer", "evidence-hit", "context_manifest", "pendingMessages", "Đang tạo câu trả lời", "100 * 1024 * 1024", "SourceLens"),
    WEB / "src" / "app.css": (".session-sidebar", ".pdf-viewport", ".chat-column"),
}
SUSPECT_MOJIBAKE = ("Ãƒ", "Ã„", "ï¿½")


def main() -> int:
    for path in FILES:
        text = path.read_text(encoding="utf-8", errors="strict")
        if any(token in text for token in SUSPECT_MOJIBAKE):
            raise AssertionError(f"possible mojibake in {path.relative_to(ROOT)}")
        for marker in MARKERS.get(path, ()):
            if marker not in text:
                raise AssertionError(f"missing {marker!r} in {path.relative_to(ROOT)}")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        raise RuntimeError("npm is required to build the React application")
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True)
    output = WEB / "dist" / "index.html"
    if not output.exists() or "SourceLens" not in output.read_text(encoding="utf-8"):
        raise AssertionError("Vite output is missing the SourceLens entry point")
    print(f"SourceLens React checks: pass ({len(FILES)} UTF-8 files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
