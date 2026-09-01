from __future__ import annotations

from typing import Optional

import typer

from .registry import ToolValidationError
from .tools import default_registry


app = typer.Typer(
    no_args_is_help=True,
    help="Unified local tools for GT7 datalogger track data.",
)
_registry = default_registry()


def _run(
    tool_id: str,
    *,
    arguments: list[str] | None = None,
    options: dict[str, object] | None = None,
) -> None:
    try:
        code = _registry.get(tool_id).run(arguments=arguments or [], options=options or {})
    except ToolValidationError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    raise typer.Exit(code)


@app.command("add-bundle")
def add_bundle(
    paths: list[str] = typer.Argument(None, help="Bundle JSON files, or app base URL with --from-app."),
    from_app: bool = typer.Option(False, "--from-app", help="Fetch bundles from a running app."),
) -> None:
    args = list(paths or [])
    options: dict[str, object] = {}
    if from_app:
        if len(args) > 1:
            typer.secho("--from-app accepts at most one app base URL", err=True, fg=typer.colors.RED)
            raise typer.Exit(2)
        options["from_app"] = args[0] if args else True
        args = []
    _run("add-bundle", arguments=args, options=options)


@app.command("pull-from-app")
def pull_from_app(
    base: Optional[str] = typer.Argument(None, help="App base URL."),
    listing: bool = typer.Option(False, "--list", help="Show what the app has and write nothing."),
    only: Optional[str] = typer.Option(None, "--only", help="Pull only matching bundle slugs."),
    token: Optional[str] = typer.Option(None, "--token", help="Admin API token."),
) -> None:
    """Browse a running datalogger and merge its surveyed tracks into tracks/."""
    options: dict[str, object] = {"listing": listing}
    if only is not None:
        options["only"] = only
    if token is not None:
        options["token"] = token
    _run("pull-from-app", arguments=[base] if base else [], options=options)


@app.command("build-index")
def build_index(
    check: bool = typer.Option(False, "--check", help="Check index.json without writing."),
) -> None:
    _run("build-index", options={"check": check})


@app.command("build-signatures")
def build_signatures(
    check: bool = typer.Option(False, "--check", help="Check signatures.json without writing."),
) -> None:
    _run("build-signatures", options={"check": check})


@app.command("validate")
def validate(
    fix: bool = typer.Option(False, "--fix", help="Rewrite bundles into canonical form."),
) -> None:
    _run("validate", options={"fix": fix})


@app.command("vendor-captures")
def vendor_captures(
    ref: Optional[str] = typer.Option(None, "--ref", help="Upstream git ref to vendor."),
    check: bool = typer.Option(False, "--check", help="Check vendor/circuits.json without writing."),
) -> None:
    options: dict[str, object] = {"check": check}
    if ref is not None:
        options["ref"] = ref
    _run("vendor-captures", options=options)


@app.command("import-into-app")
def import_into_app(
    base: Optional[str] = typer.Argument(None, help="App base URL."),
    only: Optional[str] = typer.Option(None, "--only", help="Only import matching bundle slugs."),
    token: Optional[str] = typer.Option(None, "--token", help="Admin API token."),
) -> None:
    options: dict[str, object] = {}
    if only is not None:
        options["only"] = only
    if token is not None:
        options["token"] = token
    _run("import-into-app", arguments=[base] if base else [], options=options)


@app.command("check-app-agrees")
def check_app_agrees() -> None:
    _run("check-app-agrees")


@app.command("track-editor")
def track_editor(
    port: Optional[int] = typer.Option(None, "--port", min=0, max=65535, help="Loopback port."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the URL without opening a browser."),
) -> None:
    options: dict[str, object] = {"no_browser": no_browser}
    if port is not None:
        options["port"] = port
    _run("track-editor", options=options)


@app.command("gui")
def gui(
    port: int = typer.Option(8766, "--port", min=0, max=65535, help="Loopback port."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the URL without opening a browser."),
) -> None:
    from .gui import run_gui

    raise typer.Exit(run_gui(port=port, open_browser=not no_browser))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
