"""Launch the local, read-only track bundle editor.

Usage:
    python tools/track_editor.py
    python tools/track_editor.py --no-browser
    python tools/track_editor.py --port 8765

The browser edits an in-memory copy and downloads corrected bundles.  This
server deliberately implements no write endpoints.

It does answer two read-only ones, `/api/app/tracks` and
`/api/app/tracks/<slug>`, which fetch from a running datalogger on the page's
behalf.  The page cannot do that itself: a browser will not read
`http://gt7.local:8000` from a page served on loopback unless the app sends
CORS headers for it, and asking every datalogger to open itself up to any
local page so that this editor works would be the wrong trade.  Proxying keeps
the relaxation here, on one process the user started, for two GET routes.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
from pathlib import Path
import socketserver
import sys
import urllib.parse
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_client import AppError, fetch_bundle, list_bundles, normalise_base  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
EDITOR_PATH = "/tools/track_editor/track-editor.html"
APP_PREFIX = "/api/app/tracks"


class ReadOnlyHandler(http.server.SimpleHTTPRequestHandler):
    """Serve repository files while explicitly rejecting mutation verbs."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _read_only(self) -> None:
        self.send_error(405, "The track editor server is read-only")

    do_POST = _read_only
    do_PUT = _read_only
    do_PATCH = _read_only
    do_DELETE = _read_only

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        path, _, query = self.path.partition("?")
        if path == APP_PREFIX or path.startswith(f"{APP_PREFIX}/"):
            self._proxy_app(path, query)
            return
        super().do_GET()

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy_app(self, path: str, query: str) -> None:
        # The token is read from this process's environment rather than taken
        # from the query string: a URL is logged, kept in history and shown in
        # a referrer, and an admin token should be in none of those.
        token = os.environ.get("GT7_ADMIN_TOKEN", "")
        base = urllib.parse.parse_qs(query).get("base", [""])[0]
        slug = path[len(APP_PREFIX):].lstrip("/")
        try:
            root = normalise_base(base)
            if not slug:
                self._json(200, {"base": root, "tracks": list_bundles(root, token)})
            else:
                self._json(200, fetch_bundle(root, urllib.parse.unquote(slug), token))
        except AppError as exc:
            self._json(502, {"detail": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        # Keep normal use quiet; parse errors and tracebacks still reach stderr.
        return


class EditorServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(port: int = 0) -> EditorServer:
    """Bind a read-only server to loopback; port 0 selects an available port."""
    handler = functools.partial(ReadOnlyHandler, directory=str(ROOT))
    return EditorServer(("127.0.0.1", port), handler)


def editor_url(server: EditorServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}{EDITOR_PATH}"


def run(*, port: int = 0, open_browser: bool = True) -> int:
    server = create_server(port)
    url = editor_url(server)
    print(f"Track editor: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTrack editor stopped.")
    finally:
        server.server_close()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        choices=range(0, 65536),
        metavar="PORT",
        help="loopback port (default: choose an available port)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="print the editor URL without opening a browser",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
