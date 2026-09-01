from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .registry import ToolArgument, ToolOption, ToolRegistry, ToolSpec


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _tool_main_runner(module_name: str):
    def run(argv: list[str]) -> int:
        if str(TOOLS) not in sys.path:
            sys.path.insert(0, str(TOOLS))
        module = importlib.import_module(module_name)
        if module_name == "check_app_agrees":
            if argv:
                print(f"{module_name} takes no arguments", file=sys.stderr)
                return 2
            return int(module.main())
        return int(module.main(argv))

    return run


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="pull-from-app",
            title="Pull from your app",
            description="Browse a running GT7 Datalogger and merge its surveyed tracks into tracks/.",
            when="You have driven a circuit and want that survey in this repository.",
            group="collect",
            runner=_tool_main_runner("pull_from_app"),
            arguments=(
                ToolArgument(
                    name="base",
                    label="App address",
                    help="Where the datalogger is listening.",
                    default="http://localhost:8000",
                    placeholder="http://localhost:8000",
                    emit_default_with_options=True,
                ),
            ),
            options=(
                ToolOption(
                    name="listing",
                    flag="--list",
                    kind="flag",
                    label="Only show what the app has",
                    help="List the app's tracks and write nothing.",
                    default=False,
                ),
                ToolOption(
                    name="only",
                    flag="--only",
                    kind="value",
                    label="Just one track",
                    help="Pull only bundles whose slug contains this.",
                    metavar="SLUG",
                ),
                ToolOption(
                    name="token",
                    flag="--token",
                    kind="value",
                    label="Admin token",
                    help="Only needed if your app has one set.",
                    metavar="TOKEN",
                    secret=True,
                ),
            ),
            mutates=True,
            long_running=True,
            next_steps=("build-index", "build-signatures", "validate"),
        )
    )
    registry.register(
        ToolSpec(
            id="add-bundle",
            title="Add an exported file",
            description="Validate and merge exported bundle files into tracks/.",
            when="Somebody sent you a bundle, or you exported one to disk.",
            group="collect",
            runner=_tool_main_runner("add_bundle"),
            arguments=(
                ToolArgument(
                    name="paths",
                    label="Bundle files",
                    help="Bundle JSON files to add.",
                    placeholder="~/Downloads/deep-forest-raceway.json",
                    multiple=True,
                ),
            ),
            options=(
                ToolOption(
                    name="from_app",
                    flag="--from-app",
                    kind="optional_value",
                    label="Take them from a running app instead",
                    help="Fetch every bundle from an app; the same job "
                         "'Pull from your app' does with a listing first.",
                    metavar="BASE",
                ),
            ),
            mutates=True,
            next_steps=("build-index", "build-signatures", "validate"),
        )
    )
    registry.register(
        ToolSpec(
            id="build-index",
            title="Rebuild index.json",
            description="Generate or check index.json from catalog/ and tracks/.",
            when="After anything lands in tracks/.",
            group="build",
            runner=_tool_main_runner("build_index"),
            options=(
                ToolOption(
                    name="check",
                    flag="--check",
                    kind="flag",
                    label="Check only, write nothing",
                    help="Fail if the committed file is out of date.",
                    default=False,
                ),
            ),
            mutates=True,
            next_steps=("build-signatures",),
        )
    )
    registry.register(
        ToolSpec(
            id="build-signatures",
            title="Rebuild signatures.json",
            description="Generate or check signatures.json from surveys and captures.",
            when="After anything lands in tracks/, so the app can name the circuit.",
            group="build",
            runner=_tool_main_runner("build_signatures"),
            options=(
                ToolOption(
                    name="check",
                    flag="--check",
                    kind="flag",
                    label="Check only, write nothing",
                    help="Fail if the committed file is out of date.",
                    default=False,
                ),
            ),
            mutates=True,
            next_steps=("validate",),
        )
    )
    registry.register(
        ToolSpec(
            id="validate",
            title="Validate everything",
            description="Check bundle format, names, official IDs, and canonical form.",
            when="Before you open a pull request. This is what CI runs.",
            group="check",
            runner=_tool_main_runner("validate"),
            options=(
                ToolOption(
                    name="fix",
                    flag="--fix",
                    kind="flag",
                    label="Rewrite files into canonical form",
                    help="Fix formatting problems in place instead of reporting them.",
                    default=False,
                ),
            ),
            mutates=True,
        )
    )
    registry.register(
        ToolSpec(
            id="check-app-agrees",
            title="Check the app still agrees",
            description="Ask the app validator whether every shipped bundle is unchanged.",
            when="Rarely, by hand — CI runs it against the app's default branch.",
            group="check",
            runner=_tool_main_runner("check_app_agrees"),
            long_running=True,
        )
    )
    registry.register(
        ToolSpec(
            id="vendor-captures",
            title="Refresh vendored captures",
            description="Refresh or check vendored gt-telemetry capture measurements.",
            when="Rarely, by hand — a weekly workflow already does this.",
            group="build",
            runner=_tool_main_runner("vendor_captures"),
            options=(
                ToolOption(
                    name="ref",
                    flag="--ref",
                    kind="value",
                    label="Upstream git ref",
                    help="Vendor a specific upstream revision.",
                    metavar="REF",
                ),
                ToolOption(
                    name="check",
                    flag="--check",
                    kind="flag",
                    label="Check only, write nothing",
                    help="Fail if the committed manifest is out of date.",
                    default=False,
                ),
            ),
            mutates=True,
            long_running=True,
            next_steps=("build-signatures",),
        )
    )
    registry.register(
        ToolSpec(
            id="import-into-app",
            title="Push into your app",
            description="POST repository bundles into a running GT7 Datalogger app.",
            when="You want this pack's surveys in your own datalogger.",
            group="app",
            runner=_tool_main_runner("import_into_app"),
            arguments=(
                ToolArgument(
                    name="base",
                    label="App address",
                    help="Where the datalogger is listening.",
                    default="http://localhost:8000",
                    placeholder="http://localhost:8000",
                    emit_default_with_options=True,
                ),
            ),
            options=(
                ToolOption(
                    name="only",
                    flag="--only",
                    kind="value",
                    label="Just one track",
                    help="Import only bundles whose slug contains this.",
                    metavar="SLUG",
                ),
                ToolOption(
                    name="token",
                    flag="--token",
                    kind="value",
                    label="Admin token",
                    help="Only needed if your app has one set.",
                    metavar="TOKEN",
                    secret=True,
                ),
            ),
            long_running=True,
        )
    )
    registry.register(
        ToolSpec(
            id="track-editor",
            title="Track Editor",
            description="Launch the existing local track bundle editor.",
            group="collect",
            runner=_tool_main_runner("track_editor"),
            options=(
                ToolOption(
                    name="port",
                    flag="--port",
                    kind="int",
                    label="Port",
                    help="Loopback port; 0 chooses an available port.",
                    metavar="PORT",
                ),
                ToolOption(
                    name="no_browser",
                    flag="--no-browser",
                    kind="flag",
                    label="Do not open a browser",
                    help="Print the URL instead.",
                    default=False,
                ),
            ),
            long_running=True,
            gui_visible=False,
        )
    )
    return registry
