from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .dashboard import DASHBOARD_HTML
from .registry import ToolRegistry, ToolSpec, ToolValidationError
from .tools import ROOT, TOOLS, default_registry

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import bundle_format as track_bundle  # noqa: E402
from app_client import AppError, fetch_bundle, list_bundles, normalise_base  # noqa: E402


class RunRequest(BaseModel):
    tool: str
    arguments: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class SaveRequest(BaseModel):
    """A bundle document the editor wants merged into tracks/."""

    document: dict[str, Any]


class ThreadSafeText(io.TextIOBase):
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        with self._lock:
            self._chunks.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def value(self) -> str:
        with self._lock:
            return "".join(self._chunks)


@dataclass
class RunRecord:
    id: str
    tool: str
    argv: list[str]
    status: str = "queued"
    exit_code: int | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    stdout: ThreadSafeText = field(default_factory=ThreadSafeText)
    stderr: ThreadSafeText = field(default_factory=ThreadSafeText)
    # Run once the tool has finished, whatever it exited with. The editor's
    # save writes the document to a temporary file to hand to add-bundle; this
    # is what takes it away again.
    cleanup: Callable[[], None] | None = None

    def as_dict(self) -> dict[str, Any]:
        duration = None
        if self.started_at is not None:
            duration = (self.ended_at or time.time()) - self.started_at
        return {
            "id": self.id,
            "tool": self.tool,
            "argv": self.argv,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_s": round(duration, 3) if duration is not None else None,
            "stdout": self.stdout.value(),
            "stderr": self.stderr.value(),
        }


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.Lock()
        self._worker_lock = threading.Lock()

    def start(
        self,
        spec: ToolSpec,
        argv: list[str],
        cleanup: Callable[[], None] | None = None,
    ) -> RunRecord:
        record = RunRecord(id=uuid.uuid4().hex[:12], tool=spec.id, argv=argv, cleanup=cleanup)
        with self._lock:
            self._runs[record.id] = record
        thread = threading.Thread(target=self._execute, args=(record, spec), daemon=True)
        thread.start()
        return record

    def get(self, run_id: str) -> RunRecord:
        with self._lock:
            try:
                return self._runs[run_id]
            except KeyError as exc:
                raise KeyError(f"unknown run: {run_id}") from exc

    def all(self) -> list[RunRecord]:
        with self._lock:
            return sorted(self._runs.values(), key=lambda run: run.created_at, reverse=True)

    def _execute(self, record: RunRecord, spec: ToolSpec) -> None:
        with self._worker_lock:
            record.status = "running"
            record.started_at = time.time()
            code = 1
            try:
                with (
                    contextlib.redirect_stdout(record.stdout),
                    contextlib.redirect_stderr(record.stderr),
                ):
                    code = spec.invoke_argv(record.argv)
            except SystemExit as exc:
                code = int(exc.code or 0) if isinstance(exc.code, int) else 1
            except Exception:
                traceback.print_exc(file=record.stderr)
                code = 1
            finally:
                record.exit_code = code
                record.status = "succeeded" if code == 0 else "failed"
                record.ended_at = time.time()
                if record.cleanup is not None:
                    try:
                        record.cleanup()
                    except OSError:
                        pass  # a leftover temp file is not worth failing a run over


def create_app(
    *,
    registry: ToolRegistry | None = None,
    store: RunStore | None = None,
) -> FastAPI:
    app = FastAPI(
        title="GT7 Track Tools",
        docs_url=None,
        redoc_url=None,
    )
    app.state.registry = registry or default_registry()
    app.state.runs = store or RunStore()

    @app.middleware("http")
    async def no_store_local_assets(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.mount(
        "/tools/track_editor",
        StaticFiles(directory=TOOLS / "track_editor"),
        name="track-editor",
    )
    app.mount("/tracks", StaticFiles(directory=ROOT / "tracks"), name="tracks")

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return DASHBOARD_HTML

    @app.get("/index.json")
    def track_index() -> FileResponse:
        return FileResponse(ROOT / "index.json", media_type="application/json")

    @app.get("/api/tools")
    def list_tools() -> dict[str, Any]:
        return {
            "tools": app.state.registry.as_dicts(gui_visible=True),
            "groups": app.state.registry.groups(gui_visible=True),
        }

    # --- a running datalogger, read-only ---------------------------------
    #
    # The browser cannot fetch the app directly: a page on loopback reading
    # http://gt7.local:8000 is cross-origin, and the datalogger is under no
    # obligation to allow it. These two routes do it server-side. They only
    # ever GET, so nothing here can change somebody's live survey — pushing
    # back is still the `import-into-app` command, which you have to choose.
    #
    # The admin token comes from this process's environment rather than from
    # the request, so it stays out of URLs, logs and browser history.

    def _app_token() -> str:
        return os.environ.get("GT7_ADMIN_TOKEN", "")

    @app.get("/api/app/tracks")
    def app_tracks(base: str = "") -> Any:
        try:
            root = normalise_base(base)
            return {"base": root, "tracks": list_bundles(root, _app_token())}
        except AppError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.get("/api/app/tracks/{slug}")
    def app_track(slug: str, base: str = "") -> Any:
        try:
            return fetch_bundle(normalise_base(base), slug, _app_token())
        except AppError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        """What this server can do, for a page that may be served by either.

        The editor is served both from here and from the standard-library
        server in `tools/track_editor.py`, which has no write endpoints at
        all. Rather than shipping two editors, the page asks — and hides the
        controls this server does not back.
        """
        return {"save_to_tracks": True, "browse_app": True}

    @app.post("/api/tracks", status_code=202)
    def save_track(request: SaveRequest) -> dict[str, Any]:
        """Merge an edited bundle into tracks/, exactly as add-bundle would.

        Not a second implementation of the merge: the document goes to a
        temporary file and then through the registered `add-bundle` tool, so
        an editor save and a typed `gt7-tracks add-bundle` are the same run,
        show the same output, and appear in the same run log. That is what
        stops the editor's "save" and the repository's "add" from drifting
        into two different ideas of what merging means.
        """
        try:
            document = track_bundle.validate_document(request.document)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not (document["meta"].get("official") or {}).get("official_id"):
            raise HTTPException(
                status_code=400,
                detail="This bundle names no official GT7 configuration, so there is "
                       "nowhere to file it. Confirm the layout in the app's Tracks "
                       "view and export again.",
            )

        directory = Path(tempfile.mkdtemp(prefix="gt7-editor-save-"))
        path = directory / "edited-bundle.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        spec = app.state.registry.get("add-bundle")
        record = app.state.runs.start(
            spec,
            spec.build_argv(arguments=[str(path)]),
            cleanup=lambda: shutil.rmtree(directory, ignore_errors=True),
        )
        return {"run": record.as_dict()}

    @app.get("/api/runs")
    def list_runs() -> dict[str, Any]:
        return {"runs": [run.as_dict() for run in app.state.runs.all()]}

    @app.post("/api/runs", status_code=202)
    def start_run(request: RunRequest) -> dict[str, Any]:
        try:
            spec = app.state.registry.get(request.tool)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            argv = spec.build_argv(arguments=request.arguments, options=request.options)
        except ToolValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record = app.state.runs.start(spec, argv)
        return {"run": record.as_dict()}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            record = app.state.runs.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"run": record.as_dict()}

    return app


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_gui(*, port: int = 8766, open_browser: bool = True) -> int:
    import uvicorn

    if port < 0 or port > 65535:
        print("port must be between 0 and 65535", file=sys.stderr)
        return 2
    actual_port = _available_port() if port == 0 else port
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"GT7 track tools: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=actual_port, log_level="info")
    return 0
