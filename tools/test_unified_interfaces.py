from __future__ import annotations

import contextlib
import io
import json
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
                else (ToolArgument("base", emit_default_with_options=True),)
                if tool_id == "pull-from-app"
                else (),
                options=(
                    ToolOption("from_app", "--from-app", "optional_value"),
                )
                if tool_id == "add-bundle"
                else (
                    ToolOption("listing", "--list", "flag", default=False),
                    ToolOption("only", "--only", "value"),
                    ToolOption("token", "--token", "value", secret=True),
                )
                if tool_id == "pull-from-app"
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

    def test_every_field_is_labelled_in_words_as_well_as_in_flags(self) -> None:
        # A form whose fields are called "paths" and "--check" is a form that
        # assumes you already know the script it stands for.
        for tool in default_registry().as_dicts(gui_visible=True):
            self.assertTrue(tool["when"], f"{tool['id']} does not say when to use it")
            for field in tool["arguments"] + tool["options"]:
                self.assertTrue(field["label"], f"{tool['id']}.{field['name']} has no label")
                self.assertNotEqual(
                    field["label"], field["name"],
                    f"{tool['id']}.{field['name']} is labelled with its own variable name",
                )
            for option in tool["options"]:
                self.assertNotEqual(
                    option["label"], option["flag"],
                    f"{tool['id']} labels a field with the raw flag {option['flag']}",
                )
                self.assertTrue(option["help"], f"{tool['id']}.{option['name']} has no help")

    def test_tools_are_grouped_in_the_order_the_work_happens(self) -> None:
        registry = default_registry()
        groups = [group["id"] for group in registry.groups(gui_visible=True)]
        tools = registry.as_dicts(gui_visible=True)

        self.assertEqual(groups, ["collect", "build", "check", "app"])
        for tool in tools:
            self.assertIn(tool["group"], groups, f"{tool['id']} is in no group")
        # as_dicts orders by group first, so the GUI can render them in one pass.
        seen = [groups.index(tool["group"]) for tool in tools]
        self.assertEqual(seen, sorted(seen))

    def test_getting_data_says_what_it_made_stale(self) -> None:
        registry = default_registry()
        by_id = {tool["id"]: tool for tool in registry.as_dicts(gui_visible=True)}

        for tool_id in ("add-bundle", "pull-from-app"):
            self.assertEqual(
                by_id[tool_id]["next_steps"],
                ["build-index", "build-signatures", "validate"],
                f"{tool_id} does not say what to run next",
            )
        self.assertEqual(by_id["build-index"]["next_steps"], ["build-signatures"])
        for tool in by_id.values():
            for step in tool["next_steps"]:
                self.assertIn(step, by_id, f"{tool['id']} points at a tool the GUI cannot run")


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

    def test_pull_from_app_listing_dispatches_to_the_registry(self) -> None:
        registry, calls = fake_registry("pull-from-app")
        runner = CliRunner()

        with mock.patch.object(cli, "_registry", registry):
            result = runner.invoke(cli.app, ["pull-from-app", "http://gt7.local:8000", "--list"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(calls, [("pull-from-app", ["http://gt7.local:8000", "--list"])])

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

    def test_lists_tool_groups_so_the_dashboard_can_order_them(self) -> None:
        app = create_app(registry=default_registry())

        with TestClient(app) as client:
            payload = client.get("/api/tools").json()

        self.assertEqual(
            [group["id"] for group in payload["groups"]],
            ["collect", "build", "check", "app"],
        )
        self.assertTrue(all(group["title"] for group in payload["groups"]))

    def test_reaching_an_app_that_is_not_there_explains_itself(self) -> None:
        app = create_app(registry=default_registry())

        with TestClient(app) as client:
            unreachable = client.get("/api/app/tracks", params={"base": "http://127.0.0.1:1"})
            nonsense = client.get("/api/app/tracks", params={"base": "file:///etc/passwd"})

        self.assertEqual(unreachable.status_code, 502)
        self.assertIn("cannot reach", unreachable.json()["detail"])
        self.assertEqual(nonsense.status_code, 502)
        self.assertIn("http(s)", nonsense.json()["detail"])

    def test_announces_what_this_server_can_do(self) -> None:
        # The editor page is served by two servers; only this one writes.
        app = create_app(registry=default_registry())

        with TestClient(app) as client:
            capabilities = client.get("/api/capabilities").json()

        self.assertTrue(capabilities["save_to_tracks"])

    def test_saving_a_bundle_runs_the_registered_add_bundle_tool(self) -> None:
        # An editor save and a typed `gt7-tracks add-bundle` must be one code
        # path, or the merge rules drift into two ideas of what merging means.
        registry = ToolRegistry()
        seen: list[list[str]] = []

        def run(argv: list[str]) -> int:
            seen.append(argv)
            print("wrote tracks/daytona-tri-oval.json")
            return 0

        registry.register(
            ToolSpec(id="add-bundle", title="Add", description="add", runner=run,
                     arguments=(ToolArgument("paths", multiple=True),))
        )
        document = json.loads((ROOT / "tracks" / "daytona-tri-oval.json").read_text())

        with TestClient(create_app(registry=registry)) as client:
            response = client.post("/api/tracks", json={"document": document})
            self.assertEqual(response.status_code, 202)
            run_id = response.json()["run"]["id"]
            finished = self.wait_for_run(client, run_id)

        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(len(seen), 1)
        saved = Path(seen[0][0])
        self.assertEqual(saved.suffix, ".json")
        # The temporary file the document travelled in is cleaned up after.
        self.assertFalse(saved.exists(), "the save left a temporary file behind")

    def test_saving_refuses_what_the_repository_could_not_file(self) -> None:
        app = create_app(registry=default_registry())
        document = json.loads((ROOT / "tracks" / "daytona-tri-oval.json").read_text())
        unplaceable = {**document, "meta": {**document["meta"], "official": None}}

        with TestClient(app) as client:
            malformed = client.post("/api/tracks", json={"document": {"nope": True}})
            no_layout = client.post("/api/tracks", json={"document": unplaceable})

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(no_layout.status_code, 400)
        self.assertIn("official", no_layout.json()["detail"])

    def test_the_app_routes_only_read(self) -> None:
        app = create_app(registry=default_registry())

        with TestClient(app) as client:
            for method in ("post", "put", "delete"):
                response = getattr(client, method)("/api/app/tracks")
                self.assertEqual(response.status_code, 405, method)

    def test_dashboard_offers_the_app_browser_and_the_editor(self) -> None:
        with self.make_client() as client:
            html = client.get("/").text

        # Browsing the app is a panel you pick from, not a command you run
        # twice — once to read the log, once with --only.
        self.assertIn('id="app-connect"', html)
        self.assertIn('id="app-pull"', html)
        self.assertIn('id="app-list"', html)

    def test_dashboard_embeds_the_track_editor(self) -> None:
        with self.make_client() as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="track-editor-frame"', html)
        self.assertIn('id="latest-log"', html)
        self.assertIn('src="/tools/track_editor/track-editor.html?v=side-cues"', html)
        self.assertNotIn("launch-editor", html)

    def test_the_editor_tab_is_the_editor_and_nothing_else(self) -> None:
        # The editor carries its own bar; a second one above the frame said the
        # same things again and cost a whole row.
        with self.make_client() as client:
            html = client.get("/").text

        self.assertNotIn('id="reload-editor"', html)
        self.assertNotIn("editor-toolbar", html)

    def test_the_editor_view_cannot_collapse_to_an_iframe_width(self) -> None:
        # A grid whose column is `auto` sizes to its content, and the editor
        # view's only content is an iframe — intrinsic width 300px. Without an
        # explicit column the whole page shrank to that, header and all.
        with self.make_client() as client:
            html = client.get("/").text

        self.assertIn("grid-template-columns: minmax(0, 1fr);", html)

    def test_the_shell_does_not_assume_how_tall_its_own_header_is(self) -> None:
        # `height: calc(100vh - 7.25rem)` was a guess. A wrapped intro line made
        # the header taller than that, so `main` overflowed, the page scrolled,
        # and the editor frame — with its popovers — went below the fold.
        with self.make_client() as client:
            html = client.get("/").text

        self.assertNotIn("calc(100vh - 7.25rem)", html)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr);", html)

    def test_serves_editor_assets_and_repository_data_from_the_gui_app(self) -> None:
        with self.make_client() as client:
            editor = client.get("/tools/track_editor/track-editor.html")
            editor_css = client.get("/tools/track_editor/track-editor.css")
            editor_js = client.get("/tools/track_editor/track-editor.mjs")
            index = client.get("/index.json")
            bundle = client.get("/tracks/daytona-tri-oval.json")

        self.assertEqual(editor.status_code, 200)
        self.assertIn("Track bundle editor", editor.text)
        self.assertIn("./track-editor.css?v=side-cues", editor.text)
        self.assertIn("./track-editor.mjs?v=side-cues", editor.text)
        self.assertEqual(editor_css.status_code, 200)
        self.assertEqual(editor_css.headers["cache-control"], "no-store")
        self.assertIn("[hidden] { display: none !important; }", editor_css.text)
        # The tool strip is hidden until a bundle is open, and a hidden grid
        # item creates no track. Left to flow, the workspace slid into the
        # `auto` row and had no height at all until a track was loaded — so
        # the empty state, and the Open dialog with it, collapsed to a sliver.
        self.assertIn(".workspace { grid-row: 3; }", editor_css.text)
        self.assertIn("grid-template-rows: auto auto minmax(0, 1fr);", editor_css.text)
        self.assertEqual(editor_js.status_code, 200)
        self.assertIn('emptyState.style.display = "none";', editor_js.text)
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


class CacheBusterTests(unittest.TestCase):
    """Every asset the editor pulls must carry the same version string.

    The core module used to be imported at a bare URL while the page and its
    entry module carried one. A browser holding an older core then linked the
    new entry module against exports that copy did not have; the module never
    ran, and every listener in it was silently dead — including the one behind
    the Open dialog. A stale asset must be impossible, not merely unlikely.
    """

    EDITOR = ROOT / "tools" / "track_editor"

    def versions(self) -> dict[str, set[str]]:
        import re

        pattern = re.compile(r"\?v=([a-z0-9-]+)")
        sources = {
            "editor page": (self.EDITOR / "track-editor.html").read_text(encoding="utf-8"),
            "editor module": (self.EDITOR / "track-editor.mjs").read_text(encoding="utf-8"),
            "dashboard iframe": (ROOT / "gt7_track_tools" / "dashboard.py").read_text(encoding="utf-8"),
        }
        return {name: set(pattern.findall(text)) for name, text in sources.items()}

    def test_every_reference_uses_one_version(self) -> None:
        found = self.versions()

        for name, versions in found.items():
            self.assertTrue(versions, f"{name} carries no ?v= cache-buster at all")
        every = set().union(*found.values())
        self.assertEqual(
            len(every), 1,
            f"the editor's assets disagree about their version: {found}",
        )

    def test_the_core_module_is_versioned_too(self) -> None:
        module = (self.EDITOR / "track-editor.mjs").read_text(encoding="utf-8")

        self.assertIn('from "./track-editor-core.mjs?v=', module)
        self.assertNotIn('from "./track-editor-core.mjs"', module)


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
