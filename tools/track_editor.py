"""Launch the local, read-only track bundle editor.

Usage:
    python tools/track_editor.py
    python tools/track_editor.py --no-browser
    python tools/track_editor.py --port 8765

The browser edits an in-memory copy and downloads corrected bundles.  This
server deliberately implements no write endpoints.
"""

from __future__ import annotations

import argparse
import functools
import http.server
from pathlib import Path
import socketserver
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
EDITOR_PATH = "/tools/track_editor/track-editor.html"


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
