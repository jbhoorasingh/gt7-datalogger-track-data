"""Tests for talking to a running datalogger.

These run against a stub app on loopback rather than a real datalogger, so
they check what this repository does with the answers — including the answers
a wrong URL gives, which is what most people will hit first.

    python tools/test_app_client.py
"""

from __future__ import annotations

import contextlib
import http.server
import io
import json
import sys
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pull_from_app  # noqa: E402
import track_editor  # noqa: E402
from app_client import AppError, fetch_bundle, list_bundles, normalise_base  # noqa: E402

LISTING = [
    {"slug": "deep-forest-raceway", "track": "Deep Forest Raceway", "points": 4414,
     "runs": 5, "official": {"official_id": "0457d4", "official_name": "Deep Forest Raceway"}},
    {"slug": "unconfirmed-thing", "track": "Something", "points": 12},
    {"slug": "../../etc/passwd", "track": "nope"},
    "not a row",
]

BUNDLE = {"format": "gt7-datalogger-track-bundle", "version": 4, "edges": []}


class StubApp(http.server.BaseHTTPRequestHandler):
    """Enough of the datalogger's read API to answer these tests."""

    protocol_version = "HTTP/1.1"
    require_token = False

    def log_message(self, *args: object) -> None:
        return

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if type(self).require_token and self.headers.get("X-API-Key") != "sesame":
            self._send(401, {"detail": "no"})
        elif self.path == "/api/track-bundles":
            self._send(200, LISTING)
        elif self.path == "/api/track-bundles/deep-forest-raceway":
            self._send(200, BUNDLE)
        elif self.path.startswith("/not-json"):
            body = b"<html>hello</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(404, {"detail": "unknown"})


@contextlib.contextmanager
def stub_app(require_token: bool = False):
    StubApp.require_token = require_token
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StubApp)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        StubApp.require_token = False


class BaseUrlTests(unittest.TestCase):
    def test_fills_in_the_obvious_parts(self) -> None:
        self.assertEqual(normalise_base(None), "http://localhost:8000")
        self.assertEqual(normalise_base("  "), "http://localhost:8000")
        self.assertEqual(normalise_base("gt7.local:8000"), "http://gt7.local:8000")
        self.assertEqual(normalise_base("http://gt7.local:8000/"), "http://gt7.local:8000")
        self.assertEqual(normalise_base("https://gt7.local/"), "https://gt7.local")

    def test_refuses_what_is_not_an_app_address(self) -> None:
        for bad in ("file:///etc/passwd", "ftp://host/", "http://", "http://host:notaport"):
            with self.assertRaises(AppError, msg=bad):
                normalise_base(bad)

    def test_refuses_credentials_in_the_url(self) -> None:
        # A token in a URL ends up in logs, history and referrers.
        with self.assertRaises(AppError) as caught:
            normalise_base("http://admin:hunter2@gt7.local:8000")
        self.assertIn("GT7_ADMIN_TOKEN", str(caught.exception))

    def test_refuses_a_query_string(self) -> None:
        with self.assertRaises(AppError):
            normalise_base("http://gt7.local:8000/?x=1")


class ListingTests(unittest.TestCase):
    def test_reads_the_listing_and_drops_what_it_cannot_use(self) -> None:
        with stub_app() as base:
            rows = list_bundles(base)

        slugs = [row["slug"] for row in rows]
        self.assertEqual(slugs, ["deep-forest-raceway", "unconfirmed-thing"])
        self.assertNotIn("../../etc/passwd", slugs, "a slug is not a path")
        confirmed = rows[0]
        self.assertEqual(confirmed["points"], 4414)
        self.assertEqual(confirmed["official_id"], "0457d4")
        self.assertEqual(rows[1]["official_id"], "", "an unconfirmed layout is still listed")

    def test_fetches_one_bundle(self) -> None:
        with stub_app() as base:
            self.assertEqual(fetch_bundle(base, "deep-forest-raceway"), BUNDLE)

    def test_refuses_a_slug_that_is_a_path(self) -> None:
        with stub_app() as base:
            for bad in ("../secrets", "a/b", "", "HELLO"):
                with self.assertRaises(AppError, msg=bad):
                    fetch_bundle(base, bad)

    def test_says_which_way_the_token_is_wrong(self) -> None:
        with stub_app(require_token=True) as base:
            with self.assertRaises(AppError) as caught:
                list_bundles(base)
            self.assertIn("GT7_ADMIN_TOKEN", str(caught.exception))
            self.assertEqual(len(list_bundles(base, "sesame")), 2)

    def test_explains_an_address_that_is_not_the_datalogger(self) -> None:
        with stub_app() as base:
            with self.assertRaises(AppError) as caught:
                list_bundles(f"{base}/not-json")
        self.assertIn("datalogger", str(caught.exception))

    def test_explains_a_refused_connection(self) -> None:
        # Port 1 on loopback: nothing is listening, and nothing should be.
        with self.assertRaises(AppError) as caught:
            list_bundles("http://127.0.0.1:1")
        self.assertIn("cannot reach", str(caught.exception))


class PullTests(unittest.TestCase):
    def run_pull(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pull_from_app.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_list_shows_everything_and_writes_nothing(self) -> None:
        tracks = Path(pull_from_app.ROOT) / "tracks"
        before = {path: path.read_bytes() for path in tracks.glob("*.json")}

        with stub_app() as base:
            code, out, _ = self.run_pull([base, "--list"])

        self.assertEqual(code, 0)
        self.assertIn("deep-forest-raceway", out)
        self.assertIn("layout not confirmed", out)
        self.assertIn("Nothing was written", out)
        self.assertEqual({path: path.read_bytes() for path in tracks.glob("*.json")}, before)

    def test_only_narrows_the_listing(self) -> None:
        with stub_app() as base:
            code, out, _ = self.run_pull([base, "--list", "--only", "deep-forest"])

        self.assertEqual(code, 0)
        self.assertIn("deep-forest-raceway", out)
        self.assertNotIn("unconfirmed-thing", out)

    def test_reports_an_app_it_cannot_reach(self) -> None:
        code, _, err = self.run_pull(["http://127.0.0.1:1", "--list"])

        self.assertEqual(code, 1)
        self.assertIn("cannot reach", err)


class EditorProxyTests(unittest.TestCase):
    """The editor server's two read-only routes onto a running app."""

    @contextlib.contextmanager
    def editor(self):
        server = track_editor.create_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()

    def get(self, url: str):
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_lists_and_fetches_through_the_editor_server(self) -> None:
        import urllib.parse

        with stub_app() as app_base, self.editor() as editor_base:
            quoted = urllib.parse.quote(app_base, safe="")
            status, listing = self.get(f"{editor_base}/api/app/tracks?base={quoted}")
            self.assertEqual(status, 200)
            self.assertEqual(listing["base"], app_base)
            self.assertEqual(len(listing["tracks"]), 2)

            status, bundle = self.get(
                f"{editor_base}/api/app/tracks/deep-forest-raceway?base={quoted}")
            self.assertEqual(status, 200)
            self.assertEqual(bundle, BUNDLE)

    def test_a_bad_address_is_an_explanation_not_a_traceback(self) -> None:
        with self.editor() as editor_base:
            status, body = self.get(f"{editor_base}/api/app/tracks?base=file:///etc/passwd")

        self.assertEqual(status, 502)
        self.assertIn("http(s)", body["detail"])

    def test_the_proxy_is_still_read_only(self) -> None:
        import urllib.error
        import urllib.request

        with self.editor() as editor_base:
            request = urllib.request.Request(
                f"{editor_base}/api/app/tracks", data=b"{}", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)

        self.assertEqual(caught.exception.code, 405)


if __name__ == "__main__":
    unittest.main()
