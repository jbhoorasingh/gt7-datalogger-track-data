from __future__ import annotations


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GT7 Track Tools</title>
  <style>
    :root {
      --bg: #090d12;
      --panel: #121820;
      --panel-2: #18212c;
      --line: #273342;
      --ink: #e8edf3;
      --dim: #92a0b2;
      --accent: #6ee7c7;
      --accent-2: #2dd4bf;
      --danger: #fb7185;
      --warn: #f59e0b;
      --ok: #22c55e;
      color-scheme: dark;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 85% -10%, rgba(45, 212, 191, 0.09), transparent 32rem),
        var(--bg);
      color: var(--ink);
      font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    }
    button, input, select { font: inherit; }
    button, input { border-radius: 0.45rem; }
    button {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--ink);
      min-height: 2.25rem;
      padding: 0.48rem 0.7rem;
      cursor: pointer;
    }
    button:hover:not(:disabled) { border-color: #466078; background: #1d2936; }
    button:focus-visible, input:focus-visible, iframe:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
    button:disabled { cursor: not-allowed; opacity: 0.42; }
    .primary {
      color: #071410;
      background: var(--accent);
      border-color: var(--accent);
      font-weight: 700;
    }
    .primary:hover:not(:disabled) { background: #8aecd4; border-color: #8aecd4; }
    .app-header {
      min-height: 7.25rem;
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--line);
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 1rem;
      align-items: end;
    }
    .eyebrow {
      margin: 0 0 0.1rem;
      color: var(--accent);
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    h1 { margin: 0; font-size: 1.5rem; letter-spacing: 0; }
    .intro { margin: 0.2rem 0 0; color: var(--dim); max-width: 58ch; }
    .tabs {
      display: inline-flex;
      gap: 0.35rem;
      padding: 0.25rem;
      border: 1px solid var(--line);
      border-radius: 0.65rem;
      background: rgba(18, 24, 32, 0.94);
    }
    .tab {
      border-radius: 0.45rem;
      border-color: transparent;
      background: transparent;
      color: var(--dim);
    }
    .tab[aria-selected="true"] {
      color: #071410;
      background: var(--accent);
      border-color: var(--accent);
      font-weight: 700;
    }
    main {
      height: calc(100vh - 7.25rem);
      min-height: 32rem;
      padding: 1rem;
    }
    .view { height: 100%; }
    .view[hidden] { display: none; }
    .tools-layout {
      display: grid;
      grid-template-columns: minmax(20rem, 28rem) minmax(0, 1fr);
      gap: 1rem;
      height: 100%;
      min-height: 0;
    }
    .tools-column, .runs-column {
      min-height: 0;
      overflow: auto;
      padding-right: 0.15rem;
    }
    .panel {
      background: rgba(18, 24, 32, 0.94);
      border: 1px solid var(--line);
      border-radius: 0.7rem;
      padding: 0.85rem;
    }
    .tool {
      background: rgba(18, 24, 32, 0.94);
      border: 1px solid var(--line);
      border-radius: 0.7rem;
      padding: 0.85rem;
      margin-bottom: 0.75rem;
    }
    .tool-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.6rem;
      align-items: start;
      margin-bottom: 0.5rem;
    }
    .tool h2, .panel h2 {
      margin: 0;
      font-size: 0.82rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #c8d2df;
    }
    .tool p {
      margin: 0.3rem 0 0;
      color: var(--dim);
      font-size: 0.8rem;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 1.35rem;
      padding: 0.12rem 0.5rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--dim);
      font-size: 0.7rem;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .pill.write { color: #fbbf24; border-color: #6b4d1d; }
    .pill.long { color: var(--accent); border-color: #246b61; }
    .field-grid {
      display: grid;
      gap: 0.5rem;
      margin: 0.65rem 0;
    }
    label {
      display: grid;
      gap: 0.25rem;
      color: var(--dim);
      font-size: 0.76rem;
    }
    input {
      min-width: 0;
      width: 100%;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--ink);
      padding: 0.48rem 0.55rem;
    }
    label.check {
      grid-template-columns: 1rem minmax(0, 1fr);
      align-items: center;
      color: #c3ccd8;
      font-size: 0.8rem;
    }
    label.check input { width: 1rem; min-height: 1rem; margin: 0; accent-color: var(--accent-2); }
    .optional-row {
      display: grid;
      grid-template-columns: 1rem minmax(0, 1fr);
      gap: 0.45rem;
      align-items: center;
    }
    .optional-row input[type="checkbox"] {
      width: 1rem;
      min-height: 1rem;
      margin: 0;
      accent-color: var(--accent-2);
    }
    .tool-actions {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 0.65rem;
      align-items: center;
      margin-top: 0.65rem;
      padding-top: 0.65rem;
      border-top: 1px solid var(--line);
    }
    .status {
      min-height: 1.2rem;
      color: var(--dim);
      font-size: 0.75rem;
      overflow-wrap: anywhere;
    }
    .runs-column .panel {
      height: 100%;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .run-head {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 0.75rem;
      align-items: center;
      padding-bottom: 0.7rem;
      border-bottom: 1px solid var(--line);
    }
    .run-list {
      min-height: 0;
      overflow: auto;
      padding-top: 0.7rem;
    }
    .run {
      border: 1px solid var(--line);
      border-radius: 0.65rem;
      background: #0c1219;
      overflow: hidden;
      margin-bottom: 0.65rem;
    }
    .run summary {
      cursor: pointer;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.65rem;
      padding: 0.7rem;
    }
    .argv {
      display: block;
      margin-top: 0.25rem;
      color: var(--dim);
      font: 0.72rem/1.35 ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .state { font-weight: 700; }
    .state.succeeded { color: var(--ok); }
    .state.failed { color: var(--danger); }
    .state.running, .state.queued { color: var(--accent); }
    pre {
      margin: 0;
      padding: 0.75rem;
      max-height: 28rem;
      overflow: auto;
      border-top: 1px solid var(--line);
      background: #070a0f;
      color: #dbe4ee;
      font: 0.76rem/1.45 ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .editor-layout {
      height: 100%;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 0.75rem;
    }
    .editor-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      flex-wrap: wrap;
    }
    .editor-frame {
      width: 100%;
      height: 100%;
      min-height: 28rem;
      border: 1px solid var(--line);
      border-radius: 0.8rem;
      background: #0c1219;
    }
    @media (max-width: 900px) {
      .app-header { min-height: auto; grid-template-columns: 1fr; align-items: start; }
      main { height: auto; min-height: 0; }
      .tools-layout { grid-template-columns: 1fr; height: auto; }
      .tools-column, .runs-column { overflow: visible; }
      .runs-column .panel { height: auto; }
      .editor-frame { height: 72vh; }
    }
  </style>
</head>
<body>
  <header class="app-header">
    <div>
      <p class="eyebrow">Local tool</p>
      <h1>GT7 Track Tools</h1>
      <p class="intro">Run repository maintenance commands and repair bundle geometry from the same loopback session.</p>
    </div>
    <nav class="tabs" aria-label="Tool views">
      <button class="tab" type="button" data-view="tools" aria-selected="true">Commands</button>
      <button class="tab" type="button" data-view="editor" aria-selected="false">Track editor</button>
    </nav>
  </header>
  <main>
    <section id="tools-view" class="view tools-layout">
      <div class="tools-column" id="tools"></div>
      <section class="runs-column">
        <div class="panel">
          <div class="run-head">
            <h2>Runs</h2>
            <button id="refresh" type="button">Refresh</button>
          </div>
          <div id="runs" class="run-list"></div>
        </div>
      </section>
    </section>
    <section id="editor-view" class="view editor-layout" hidden>
      <div class="panel editor-toolbar">
        <div>
          <h2>Track Bundle Editor</h2>
        </div>
        <button id="reload-editor" type="button">Reload editor</button>
      </div>
      <iframe
        id="track-editor-frame"
        class="editor-frame"
        title="Track bundle editor"
        src="/tools/track_editor/track-editor.html"
      ></iframe>
    </section>
  </main>
  <script>
    const toolsEl = document.querySelector("#tools");
    const runsEl = document.querySelector("#runs");
    const editorFrame = document.querySelector("#track-editor-frame");
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

    function escapeHtml(value) {
      return String(value).replace(/[&<>]/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[char]));
    }

    function setView(name) {
      document.querySelectorAll(".tab").forEach((tab) => {
        tab.setAttribute("aria-selected", String(tab.dataset.view === name));
      });
      document.querySelector("#tools-view").hidden = name !== "tools";
      document.querySelector("#editor-view").hidden = name !== "editor";
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
        <div class="tool-head">
          <div>
            <h2>${escapeHtml(tool.title)}</h2>
            <p>${escapeHtml(tool.description)}</p>
          </div>
          <span class="pill ${tool.mutates ? "write" : ""}">${tool.mutates ? "writes" : "read-only"}</span>
        </div>
        ${tool.long_running ? "<span class=\"pill long\">long-running</span>" : ""}
      `;
      const fields = document.createElement("div");
      fields.className = "field-grid";
      for (const argument of tool.arguments) {
        const label = document.createElement("label");
        label.dataset.argument = argument.name;
        label.dataset.multiple = argument.multiple ? "true" : "false";
        label.innerHTML = `<span>${escapeHtml(argument.name)}</span><input type="text" placeholder="${argument.multiple ? "space-separated values" : (argument.default || "")}">`;
        fields.appendChild(label);
      }
      for (const option of tool.options) fields.appendChild(optionInput(tool, option));
      node.appendChild(fields);

      const actions = document.createElement("div");
      actions.className = "tool-actions";
      const button = document.createElement("button");
      button.className = "primary";
      button.textContent = "Run";
      const status = document.createElement("div");
      status.className = "status";
      actions.append(button, status);
      node.appendChild(actions);

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
      return node;
    }

    async function loadTools() {
      const {tools} = await jsonFetch("/api/tools");
      toolsEl.replaceChildren(...tools.map(toolCard));
    }

    function renderRuns(runs) {
      runsEl.replaceChildren(...runs.map((run, index) => {
        const details = document.createElement("details");
        details.className = "run";
        if (index === 0) details.open = true;
        const log = [run.stdout, run.stderr ? "\n[stderr]\n" + run.stderr : ""].join("");
        details.innerHTML = `
          <summary>
            <span>
              ${escapeHtml(run.tool)}
              <span class="argv">${escapeHtml(run.argv.join(" ") || "default")}</span>
            </span>
            <span class="state ${run.status}">${run.status}${run.exit_code === null ? "" : ` ${run.exit_code}`}${run.duration_s === null ? "" : ` | ${run.duration_s}s`}</span>
          </summary>
          <pre>${escapeHtml(log) || "No output yet."}</pre>
        `;
        return details;
      }));
    }

    async function refreshRuns() {
      const {runs} = await jsonFetch("/api/runs");
      renderRuns(runs);
      return runs.some((run) => run.status === "queued" || run.status === "running");
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

    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => setView(tab.dataset.view));
    });
    document.querySelector("#refresh").addEventListener("click", refreshRuns);
    document.querySelector("#reload-editor").addEventListener("click", () => {
      editorFrame.contentWindow?.location.reload();
    });

    loadTools().then(refreshRuns).then((active) => { if (active) startPolling(); });
  </script>
</body>
</html>
"""
