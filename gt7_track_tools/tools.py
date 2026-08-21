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
            id="add-bundle",
            title="Add Bundle",
            description="Validate and merge exported bundle files into tracks/.",
            runner=_tool_main_runner("add_bundle"),
            arguments=(
                ToolArgument(
                    name="paths",
                    help="Bundle JSON files to add.",
                    multiple=True,
                ),
            ),
            options=(
                ToolOption(
                    name="from_app",
                    flag="--from-app",
                    kind="optional_value",
                    help="Fetch bundles from a running app; value is the app base URL.",
                    metavar="BASE",
                ),
            ),
            mutates=True,
        )
    )
    registry.register(
        ToolSpec(
            id="build-index",
            title="Build Index",
            description="Generate or check index.json from catalog/ and tracks/.",
            runner=_tool_main_runner("build_index"),
            options=(
                ToolOption(
                    name="check",
                    flag="--check",
                    kind="flag",
                    help="Check the committed file without writing.",
                    default=False,
                ),
            ),
            mutates=True,
        )
    )
    registry.register(
        ToolSpec(
            id="build-signatures",
            title="Build Signatures",
            description="Generate or check signatures.json from surveys and captures.",
            runner=_tool_main_runner("build_signatures"),
            options=(
                ToolOption(
                    name="check",
                    flag="--check",
                    kind="flag",
                    help="Check the committed file without writing.",
                    default=False,
                ),
            ),
            mutates=True,
        )
    )
    registry.register(
        ToolSpec(
            id="validate",
            title="Validate Bundles",
            description="Check bundle format, names, official IDs, and canonical form.",
            runner=_tool_main_runner("validate"),
            options=(
                ToolOption(
                    name="fix",
                    flag="--fix",
                    kind="flag",
                    help="Rewrite bundles into canonical form where needed.",
                    default=False,
                ),
            ),
            mutates=True,
        )
    )
    registry.register(
        ToolSpec(
            id="vendor-captures",
            title="Vendor Captures",
            description="Refresh or check vendored gt-telemetry capture measurements.",
            runner=_tool_main_runner("vendor_captures"),
            options=(
                ToolOption(
                    name="ref",
                    flag="--ref",
                    kind="value",
                    help="Upstream git ref to vendor.",
                    metavar="REF",
                ),
                ToolOption(
                    name="check",
                    flag="--check",
                    kind="flag",
                    help="Check the committed manifest without writing.",
                    default=False,
                ),
            ),
            mutates=True,
            long_running=True,
        )
    )
    registry.register(
        ToolSpec(
            id="import-into-app",
            title="Import Into App",
            description="POST repository bundles into a running GT7 Datalogger app.",
            runner=_tool_main_runner("import_into_app"),
            arguments=(
                ToolArgument(
                    name="base",
                    help="App base URL.",
                    default="http://localhost:8000",
                    emit_default_with_options=True,
                ),
            ),
            options=(
                ToolOption(
                    name="only",
                    flag="--only",
                    kind="value",
                    help="Import only bundles whose slug contains this value.",
                    metavar="SLUG",
                ),
                ToolOption(
                    name="token",
                    flag="--token",
                    kind="value",
                    help="Admin API token.",
                    metavar="TOKEN",
                    secret=True,
                ),
            ),
            long_running=True,
        )
    )
    registry.register(
        ToolSpec(
            id="check-app-agrees",
            title="Check App Agrees",
            description="Ask the app validator whether every shipped bundle is unchanged.",
            runner=_tool_main_runner("check_app_agrees"),
            long_running=True,
        )
    )
    registry.register(
        ToolSpec(
            id="track-editor",
            title="Track Editor",
            description="Launch the existing local read-only track bundle editor.",
            runner=_tool_main_runner("track_editor"),
            options=(
                ToolOption(
                    name="port",
                    flag="--port",
                    kind="int",
                    help="Loopback port; 0 chooses an available port.",
                    metavar="PORT",
                ),
                ToolOption(
                    name="no_browser",
                    flag="--no-browser",
                    kind="flag",
                    help="Print the URL without opening a browser.",
                    default=False,
                ),
            ),
            long_running=True,
        )
    )
    return registry
