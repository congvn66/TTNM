"""Serve the buildless web demo with explicit UTF-8 response headers."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "apps" / "web"
PORT = 4173


class Utf8StaticHandler(SimpleHTTPRequestHandler):
    """Serve HTML, CSS and ESM files as UTF-8 instead of platform-default text."""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }


def main() -> None:
    handler = partial(Utf8StaticHandler, directory=str(WEB_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    print(f"Web demo: http://127.0.0.1:{PORT} (UTF-8 headers enabled)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb demo stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
