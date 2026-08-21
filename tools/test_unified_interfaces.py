from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import time
import unittest
import warnings
from unittest import mock

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gt7_track_tools import cli  # noqa: E402
from gt7_track_tools.gui import create_app  # noqa: E402
from gt7_track_tools.registry import (  # noqa: E402
    ToolArgument,
    ToolOption,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
)
from gt7_track_tools.tools import default_registry  # noqa: E402


def fake_registry(*tool_ids: str):
    calls: list[tuple[str, list[str]]] = []
    registry = ToolRegistry()

    def register(tool_id: str) -> None:
        def run(argv: list[str]) -> int:
            calls.append((tool_id, argv))
            print(f"{tool_id}: {' '.join(argv)}")
            return 0

        registry.register(
            ToolSpec(
                id=tool_id,
                title=tool_id,
                description="test tool",
                runner=run,
                arguments=(ToolArgument("paths", multiple=True),)
                if tool_id == "add-bundle"
                else (),
                options=(
                    ToolOption("from_app", "--from-app", "optional_value"),
                )
                if tool_id == "add-bundle"
                else (
                    ToolOption("check", "--check", "flag", default=False),
                )
                if tool_id == "build-index"
                else (),
            )
        )

    for tool_id in tool_ids:
        register(tool_id)
    return registry, calls


class RegistryTests(unittest.TestCase):
    def test_builds_argv_from_registered_arguments_and_options(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                id="sample",
                title="Sample",
                description="sample",
                runner=lambda argv: 0,
                arguments=(ToolArgument("path"),),
                options=(
                    ToolOption("check", "--check", "flag", default=False),
                    ToolOption("ref", "--ref", "value"),
                ),
            )
        )

        argv = registry.get("sample").build_argv(
            arguments=["in.json"], options={"check": True, "ref": "main"}
        )

        self.assertEqual(argv, ["in.json", "--check", "--ref", "main"])

    def test_rejects_unknown_options(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(id="sample", title="Sample", description="sample", runner=lambda argv: 0)
        )

        with self.assertRaises(ToolValidationError):
            registry.get("sample").build_argv(options={"nope": True})

    def test_emits_default_argument_when_option_values_need_existing_script_order(self) -> None:
        spec = ToolSpec(
            id="import-into-app",
            title="Import",
            description="import",
            runner=lambda argv: 0,
            arguments=(
                ToolArgument(
                    "base",
                    default="http://localhost:8000",
                    emit_default_with_options=True,
                ),
            ),
            options=(ToolOption("token", "--token", "value"),),
        )

        self.assertEqual(
            spec.build_argv(options={"token": "secret"}),
            ["http://localhost:8000", "--token", "secret"],
        )

    def test_default_gui_tools_hide_the_separate_track_editor_launcher(self) -> None:
        ids = [tool["id"] for tool in default_registry().as_dicts(gui_visible=True)]

        self.assertNotIn("track-editor", ids)
        self.assertIn("validate", ids)


class CliDispatchTests(unittest.TestCase):
    def test_build_index_dispatches_to_registry(self) -> None:
        registry, calls = fake_registry("build-index")
        runner = CliRunner()

        with mock.patch.object(cli, "_registry", registry):
            result = runner.invoke(cli.app, ["build-index", "--check"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(calls, [("build-index", ["--check"])])

    def test_add_bundle_from_app_keeps_existing_optional_base_behavior(self) -> None:
        registry, calls = fake_registry("add-bundle")
        runner = CliRunner()

        with mock.patch.object(cli, "_registry", registry):
            result = runner.invoke(cli.app, ["add-bundle", "--from-app", "http://gt7.local:8000"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(calls, [("add-bundle", ["--from-app", "http://gt7.local:8000"])])

    def test_add_bundle_from_app_can_use_script_default_base(self) -> None:
        registry, calls = fake_registry("add-bundle")
        runner = CliRunner()

        with mock.patch.object(cli, "_registry", registry):
            result = runner.invoke(cli.app, ["add-bundle", "--from-app"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(calls, [("add-bundle", ["--from-app"])])


class FastApiTests(unittest.TestCase):
    def make_client(self) -> TestClient:
        registry = ToolRegistry()

        def run(argv: list[str]) -> int:
            print("stdout: " + " ".join(argv))
            print("stderr: ok", file=sys.stderr)
            return 0

        registry.register(
            ToolSpec(
                id="build-index",
                title="Build Index",
                description="check index",
                runner=run,
                options=(ToolOption("check", "--check", "flag", default=False),),
            )
        )
        return TestClient(create_app(registry=registry))

    def wait_for_run(self, client: TestClient, run_id: str) -> dict:
        for _ in range(50):
            run = client.get(f"/api/runs/{run_id}").json()["run"]
            if run["status"] in {"succeeded", "failed"}:
                return run
            time.sleep(0.02)
        self.fail(f"run did not finish: {run_id}")

    def test_lists_tools(self) -> None:
        with self.make_client() as client:
            response = client.get("/api/tools")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tools"][0]["id"], "build-index")

    def test_dashboard_embeds_the_track_editor(self) -> None:
        with self.make_client() as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="track-editor-frame"', html)
        self.assertIn('src="/tools/track_editor/track-editor.html"', html)
        self.assertNotIn("launch-editor", html)

    def test_serves_editor_assets_and_repository_data_from_the_gui_app(self) -> None:
        with self.make_client() as client:
            editor = client.get("/tools/track_editor/track-editor.html")
            index = client.get("/index.json")
            bundle = client.get("/tracks/daytona-tri-oval.json")

        self.assertEqual(editor.status_code, 200)
        self.assertIn("Track bundle editor", editor.text)
        self.assertEqual(index.status_code, 200)
        self.assertEqual(index.json()["format"], "gt7-datalogger-track-index")
        self.assertEqual(bundle.status_code, 200)
        self.assertEqual(bundle.json()["format"], "gt7-datalogger-track-bundle")

    def test_starts_run_and_returns_logs(self) -> None:
        with self.make_client() as client:
            response = client.post(
                "/api/runs",
                json={"tool": "build-index", "options": {"check": True}},
            )
            self.assertEqual(response.status_code, 202)
            run_id = response.json()["run"]["id"]
            run = self.wait_for_run(client, run_id)

        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["exit_code"], 0)
        self.assertIn("--check", run["stdout"])
        self.assertIn("stderr: ok", run["stderr"])

    def test_rejects_unknown_tool(self) -> None:
        with self.make_client() as client:
            response = client.post("/api/runs", json={"tool": "missing"})

        self.assertEqual(response.status_code, 404)

    def test_rejects_unknown_option(self) -> None:
        with self.make_client() as client:
            response = client.post(
                "/api/runs",
                json={"tool": "build-index", "options": {"write": True}},
            )

        self.assertEqual(response.status_code, 400)


class DataGuardTests(unittest.TestCase):
    SNAPSHOT_PATHS = (
        ROOT / "catalog" / "tracks.json",
        ROOT / "index.json",
        ROOT / "signatures.json",
        ROOT / "tracks" / "daytona-tri-oval.json",
        ROOT / "vendor" / "circuits.json",
    )

    def snapshot(self) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in self.SNAPSHOT_PATHS}

    def test_cli_check_path_does_not_rewrite_data_files(self) -> None:
        before = self.snapshot()
        runner = CliRunner()

        result = runner.invoke(cli.app, ["build-index", "--check"])

        self.assertIn(result.exit_code, (0, 1), result.output)
        self.assertEqual(self.snapshot(), before)

    def test_gui_read_only_path_does_not_rewrite_data_files(self) -> None:
        before = self.snapshot()
        app = create_app(registry=default_registry())

        with TestClient(app) as client:
            response = client.post("/api/runs", json={"tool": "validate"})
            self.assertEqual(response.status_code, 202)
            run_id = response.json()["run"]["id"]
            for _ in range(100):
                run = client.get(f"/api/runs/{run_id}").json()["run"]
                if run["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.05)
            else:
                self.fail("validate run did not finish")

        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
