from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import random
import sys
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import track_editor  # noqa: E402


class LauncherTests(unittest.TestCase):
    def test_server_binds_to_loopback_and_selects_a_port(self) -> None:
        server = track_editor.create_server()
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertGreater(server.server_address[1], 0)
            self.assertEqual(
                track_editor.editor_url(server),
                f"http://127.0.0.1:{server.server_address[1]}/tools/track_editor/track-editor.html",
            )
        finally:
            server.server_close()

    def test_server_serves_repo_and_rejects_writes(self) -> None:
        server = track_editor.create_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        track = random.choice(sorted((track_editor.ROOT / "tracks").glob("*.json")))
        try:
            with urllib.request.urlopen(
                f"{base}/tools/track_editor/track-editor.html"
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"Track bundle editor", response.read())

            with urllib.request.urlopen(f"{base}/tracks/{track.name}") as response:
                bundle = json.load(response)
                self.assertEqual(bundle["format"], "gt7-datalogger-track-bundle")
                self.assertGreater(len(bundle["edges"]), 0)

            request = urllib.request.Request(
                f"{base}/tracks/not-written.json", data=b"{}", method="POST"
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request)
            self.assertEqual(raised.exception.code, 405)
            self.assertFalse((track_editor.ROOT / "tracks" / "not-written.json").exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_cli_options(self) -> None:
        args = track_editor.parse_args(["--port", "8765", "--no-browser"])
        self.assertEqual(args.port, 8765)
        self.assertTrue(args.no_browser)

    def test_run_opens_browser_and_closes_after_interrupt(self) -> None:
        class FakeServer:
            server_address = ("127.0.0.1", 4321)

            def __init__(self) -> None:
                self.closed = False

            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def server_close(self) -> None:
                self.closed = True

        server = FakeServer()
        with (
            mock.patch.object(track_editor, "create_server", return_value=server),
            mock.patch.object(track_editor.webbrowser, "open") as browser,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = track_editor.run(port=0, open_browser=True)

        self.assertEqual(result, 0)
        self.assertTrue(server.closed)
        browser.assert_called_once_with(
            "http://127.0.0.1:4321/tools/track_editor/track-editor.html"
        )


if __name__ == "__main__":
    unittest.main()
