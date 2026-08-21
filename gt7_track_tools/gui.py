from __future__ import annotations

import contextlib
import io
import socket
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .registry import ToolRegistry, ToolSpec, ToolValidationError
from .tools import default_registry


TERMINAL_STATUSES = {"succeeded", "failed"}


class RunRequest(BaseModel):
    tool: str
    arguments: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class TrackEditorRequest(BaseModel):
    port: int = 0


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

    def start(self, spec: ToolSpec, argv: list[str]) -> RunRecord:
        record = RunRecord(id=uuid.uuid4().hex[:12], tool=spec.id, argv=argv)
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


class TrackEditorLauncher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._url = ""

    def launch(self, port: int = 0) -> str:
        if port < 0 or port > 65535:
            raise ValueError("port must be between 0 and 65535")
        with self._lock:
            if self._server is not None and self._thread is not None and self._thread.is_alive():
                return self._url

            from .tools import TOOLS

            if str(TOOLS) not in sys.path:
                sys.path.insert(0, str(TOOLS))
            import track_editor

            self._server = track_editor.create_server(port)
            self._url = track_editor.editor_url(self._server)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            return self._url

    def close(self) -> None:
        with self._lock:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
            self._server = None
            self._thread = None
            self._url = ""


def create_app(
    *,
    registry: ToolRegistry | None = None,
    store: RunStore | None = None,
    track_editor: TrackEditorLauncher | None = None,
) -> FastAPI:
    launcher = track_editor or TrackEditorLauncher()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            launcher.close()

    app = FastAPI(
        title="GT7 Track Tools",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.registry = registry or default_registry()
    app.state.runs = store or RunStore()
    app.state.track_editor = launcher

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return DASHBOARD_HTML

    @app.get("/api/tools")
    def list_tools() -> dict[str, Any]:
        return {"tools": app.state.registry.as_dicts(gui_visible=True)}

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

    @app.post("/api/track-editor")
    def launch_track_editor(request: TrackEditorRequest) -> dict[str, str]:
        try:
            url = app.state.track_editor.launch(request.port)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"url": url}

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


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GT7 Track Tools</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #d7dde8;
      --blue: #2458d3;
      --teal: #0f766e;
      --amber: #b45309;
      --red: #b42318;
      --code: #101828;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 22px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { font-size: 20px; margin: 0; letter-spacing: 0; }
    main {
      display: grid;
      grid-template-columns: minmax(320px, 460px) minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
    }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
    button {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      min-height: 34px;
      padding: 6px 10px;
    }
    button.primary { background: var(--blue); border-color: var(--blue); color: white; }
    button:disabled { cursor: not-allowed; opacity: .55; }
    .column { display: grid; gap: 12px; align-content: start; }
    .tool, .run-panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .tool h2, .run-panel h2 {
      font-size: 15px;
      margin: 0 0 4px;
      letter-spacing: 0;
    }
    .tool p {
      color: var(--muted);
      margin: 0 0 12px;
    }
    label {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
      margin: 8px 0;
    }
    input {
      width: 100%;
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 8px;
      color: var(--text);
      font: inherit;
    }
    label.check {
      grid-template-columns: 18px 1fr;
      align-items: center;
      color: var(--text);
      font-size: 13px;
    }
    label.check input { width: 16px; min-height: 16px; }
    .optional-row {
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr);
      gap: 6px;
      align-items: center;
    }
    .optional-row input[type="checkbox"] { width: 16px; min-height: 16px; }
    .meta {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin: 8px 0 12px;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      padding: 2px 8px;
      font-size: 12px;
    }
    .pill.write { color: var(--amber); border-color: #f2c078; }
    .pill.long { color: var(--teal); border-color: #8fd0c6; }
    .status {
      color: var(--muted);
      font-size: 12px;
      min-height: 18px;
      margin-top: 8px;
    }
    .run-head {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      border-bottom: 1px solid var(--line);
      padding-bottom: 12px;
      margin-bottom: 12px;
    }
    .run-list {
      display: grid;
      gap: 10px;
    }
    .run {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      overflow: hidden;
    }
    .run summary {
      cursor: pointer;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding: 10px;
    }
    .run pre {
      margin: 0;
      padding: 10px;
      overflow: auto;
      max-height: 360px;
      background: var(--code);
      color: #e7edf8;
      font: 12px/1.45 ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .state { font-weight: 650; }
    .state.succeeded { color: var(--teal); }
    .state.failed { color: var(--red); }
    .state.running, .state.queued { color: var(--blue); }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; padding: 12px; }
      header { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <h1>GT7 Track Tools</h1>
    <div class="toolbar">
      <button id="launch-editor">Track editor</button>
      <button id="refresh">Refresh</button>
    </div>
  </header>
  <main>
    <section class="column" id="tools"></section>
    <section class="run-panel">
      <div class="run-head">
        <h2>Runs</h2>
        <span id="run-count" class="pill">0</span>
      </div>
      <div id="runs" class="run-list"></div>
    </section>
  </main>
  <script>
    const toolsEl = document.querySelector("#tools");
    const runsEl = document.querySelector("#runs");
    const runCountEl = document.querySelector("#run-count");
    let polling = null;

    async function jsonFetch(url, options = {}) {
      const response = await fetch(url, {
        headers: {"Content-Type": "application/json"},
        ...options,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || response.statusText);
      return data;
    }

    function optionInput(tool, option) {
      const id = `${tool.id}-${option.name}`;
      const label = document.createElement("label");
      label.dataset.option = option.name;
      label.dataset.kind = option.kind;
      if (option.kind === "flag") {
        label.className = "check";
        label.innerHTML = `<input id="${id}" type="checkbox"><span>${option.flag}</span>`;
      } else if (option.kind === "optional_value") {
        label.innerHTML = `<span>${option.flag}</span><span class="optional-row"><input data-enable type="checkbox" title="use default"><input data-value id="${id}" type="text" placeholder="${option.metavar || ""}"></span>`;
      } else {
        label.innerHTML = `<span>${option.flag}</span><input id="${id}" ${option.secret ? "type=\"password\"" : "type=\"text\""} placeholder="${option.metavar || ""}">`;
      }
      return label;
    }

    function toolCard(tool) {
      const node = document.createElement("article");
      node.className = "tool";
      node.innerHTML = `
        <h2>${tool.title}</h2>
        <p>${tool.description}</p>
        <div class="meta">
          ${tool.mutates ? "<span class=\"pill write\">writes when not checking</span>" : "<span class=\"pill\">read-only</span>"}
          ${tool.long_running ? "<span class=\"pill long\">long-running</span>" : ""}
        </div>
      `;
      for (const argument of tool.arguments) {
        const label = document.createElement("label");
        label.dataset.argument = argument.name;
        label.dataset.multiple = argument.multiple ? "true" : "false";
        label.innerHTML = `<span>${argument.name}</span><input type="text" placeholder="${argument.multiple ? "space-separated values" : (argument.default || "")}">`;
        node.appendChild(label);
      }
      for (const option of tool.options) node.appendChild(optionInput(tool, option));
      const button = document.createElement("button");
      button.className = "primary";
      button.textContent = "Run";
      const status = document.createElement("div");
      status.className = "status";
      button.addEventListener("click", async () => {
        button.disabled = true;
        status.textContent = "Starting";
        try {
          const argumentsList = [];
          for (const field of node.querySelectorAll("[data-argument]")) {
            const value = field.querySelector("input").value.trim();
            if (!value) continue;
            if (field.dataset.multiple === "true") argumentsList.push(...value.split(/\s+/));
            else argumentsList.push(value);
          }
          const options = {};
          for (const field of node.querySelectorAll("[data-option]")) {
            const name = field.dataset.option;
            const kind = field.dataset.kind;
            const input = field.querySelector("input");
            if (kind === "flag") {
              if (input.checked) options[name] = true;
            } else if (kind === "optional_value") {
              const enabled = field.querySelector("[data-enable]").checked;
              const value = field.querySelector("[data-value]").value.trim();
              if (enabled || value) options[name] = value || true;
            } else if (input.value.trim()) {
              options[name] = input.value.trim();
            }
          }
          await jsonFetch("/api/runs", {
            method: "POST",
            body: JSON.stringify({tool: tool.id, arguments: argumentsList, options}),
          });
          status.textContent = "Queued";
          await refreshRuns();
          startPolling();
        } catch (error) {
          status.textContent = error.message;
        } finally {
          button.disabled = false;
        }
      });
      node.appendChild(button);
      node.appendChild(status);
      return node;
    }

    async function loadTools() {
      const {tools} = await jsonFetch("/api/tools");
      toolsEl.replaceChildren(...tools.map(toolCard));
    }

    function renderRuns(runs) {
      runCountEl.textContent = String(runs.length);
      runsEl.replaceChildren(...runs.map((run, index) => {
        const details = document.createElement("details");
        details.className = "run";
        if (index === 0) details.open = true;
        const log = [run.stdout, run.stderr ? "\n[stderr]\n" + run.stderr : ""].join("");
        details.innerHTML = `
          <summary>
            <span>${run.tool} <span class="pill">${run.argv.join(" ") || "default"}</span></span>
            <span class="state ${run.status}">${run.status}${run.exit_code === null ? "" : ` ${run.exit_code}`}${run.duration_s === null ? "" : ` | ${run.duration_s}s`}</span>
          </summary>
          <pre>${log.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])) || "No output yet."}</pre>
        `;
        return details;
      }));
    }

    async function refreshRuns() {
      const {runs} = await jsonFetch("/api/runs");
      renderRuns(runs);
      return runs.some(run => run.status === "queued" || run.status === "running");
    }

    function startPolling() {
      if (polling) return;
      polling = setInterval(async () => {
        try {
          if (!await refreshRuns()) {
            clearInterval(polling);
            polling = null;
          }
        } catch {
          clearInterval(polling);
          polling = null;
        }
      }, 1000);
    }

    document.querySelector("#refresh").addEventListener("click", refreshRuns);
    document.querySelector("#launch-editor").addEventListener("click", async () => {
      const {url} = await jsonFetch("/api/track-editor", {method: "POST", body: JSON.stringify({port: 0})});
      window.open(url, "_blank", "noopener");
    });

    loadTools().then(refreshRuns).then(active => { if (active) startPolling(); });
  </script>
</body>
</html>
"""
