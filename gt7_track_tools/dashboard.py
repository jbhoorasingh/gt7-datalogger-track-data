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
      padding: 1rem 1.5rem;
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
    body {
      height: 100vh;
      display: grid;
      /* An explicit full-width column. Without one the single column is `auto`,
         which sizes to its content — and the editor view's only content is an
         iframe, whose intrinsic width is 300px. The whole page then collapsed
         to that, header and all, and the editor showed as a sliver. */
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto minmax(0, 1fr);
      overflow: hidden;
    }
    main {
      min-width: 0;
      min-height: 0;
      padding: 1rem;
    }
    .view { height: 100%; min-width: 0; min-height: 0; }
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
    .tool p.when { color: #9fb4c8; }
    .tool p.when::before { content: "When: "; color: var(--accent-2); }
    .group-heading {
      display: flex;
      align-items: baseline;
      gap: 0.6rem;
      margin: 1.1rem 0 0.55rem;
      color: var(--accent);
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .group-heading:first-child { margin-top: 0; }
    .group-heading::after { content: ""; flex: 1; height: 1px; background: var(--line); }
    .hint {
      color: #657386;
      font: 0.68rem/1.3 ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
    }
    .field-help { color: #7d8b9d; font-size: 0.68rem; }
    .next-steps {
      grid-column: 1 / -1;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.4rem;
      margin-top: 0.55rem;
      padding-top: 0.55rem;
      border-top: 1px dashed var(--line);
      color: var(--dim);
      font-size: 0.75rem;
    }
    .next-steps button { min-height: 1.9rem; padding: 0.25rem 0.55rem; font-size: 0.75rem; }
    .app-panel { margin-bottom: 0.75rem; }
    .app-intro { margin: 0.35rem 0 0.6rem; color: var(--dim); font-size: 0.8rem; }
    .app-panel .field-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.4rem; }
    .app-list {
      max-height: 15rem;
      overflow: auto;
      margin-top: 0.6rem;
      border: 1px solid var(--line);
      border-radius: 0.55rem;
      background: #0c1219;
    }
    .app-row {
      display: grid;
      grid-template-columns: 1rem minmax(0, 1fr);
      gap: 0.5rem;
      align-items: start;
      padding: 0.5rem 0.6rem;
      border-bottom: 1px solid var(--line);
      font-size: 0.8rem;
      cursor: pointer;
    }
    .app-row:last-child { border-bottom: 0; }
    .app-row input { width: 1rem; min-height: 1rem; margin: 0.15rem 0 0; accent-color: var(--accent-2); }
    .app-row b { display: block; font-weight: 600; }
    .app-row small { color: var(--dim); font-variant-numeric: tabular-nums; }
    .app-row.blocked b { color: #9aa7b6; }
    .app-row .why { color: var(--warn); }
    .app-actions { display: flex; gap: 0.45rem; margin-top: 0.6rem; }
    .app-actions .primary { flex: 1; }
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
    .latest-log {
      min-height: 12rem;
      max-height: 38vh;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 0.65rem;
      background: #070a0f;
      margin: 0.75rem 0 0.65rem;
    }
    .latest-log-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.65rem;
      align-items: center;
      padding: 0.65rem 0.75rem;
      border-bottom: 1px solid var(--line);
      background: #0c1219;
    }
    .latest-log-head strong {
      display: block;
      color: #c8d2df;
      font-size: 0.82rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .latest-log-head span {
      display: block;
      color: var(--dim);
      font: 0.72rem/1.35 ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .latest-log pre {
      border-top: 0;
      max-height: none;
      min-height: 8rem;
    }
    .empty-log {
      margin: 0;
      padding: 3rem 1rem;
      text-align: center;
      color: var(--dim);
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
    /* Same trap one level down: a bare `display: grid` around an iframe sizes
       its column to the iframe's intrinsic width. */
    .editor-layout {
      height: 100%;
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: minmax(0, 1fr);
    }
    .editor-frame {
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 1px solid var(--line);
      border-radius: 0.8rem;
      background: #0c1219;
    }
    @media (max-width: 900px) {
      /* Stacked and scrolling is the right shape on a narrow window, so the
         page gets its scrollbar back here and only here. */
      body { height: auto; overflow: auto; }
      .app-header { grid-template-columns: 1fr; align-items: start; }
      .tools-layout { grid-template-columns: 1fr; height: auto; }
      .tools-column, .runs-column { overflow: visible; }
      .runs-column .panel { height: auto; }
      .editor-layout { height: auto; }
      .editor-frame { height: 78vh; min-height: 30rem; }
    }
  </style>
</head>
<body>
  <header class="app-header">
    <div>
      <p class="eyebrow">Local tool</p>
      <h1>GT7 Track Tools</h1>
      <p class="intro">Pull surveyed tracks out of your own datalogger, rebuild what depends on them, and repair bundle geometry — all from one loopback session.</p>
    </div>
    <nav class="tabs" aria-label="Tool views">
      <button class="tab" type="button" data-view="tools" aria-selected="true">Commands</button>
      <button class="tab" type="button" data-view="editor" aria-selected="false">Track editor</button>
    </nav>
  </header>
  <main>
    <section id="tools-view" class="view tools-layout">
      <div class="tools-column">
        <section class="panel app-panel">
          <h2>Your datalogger</h2>
          <p class="app-intro">Browse a running app and pull the tracks you want. Reading only — nothing here changes your live survey.</p>
          <div class="field-row">
            <input id="app-base" type="url" value="http://localhost:8000" placeholder="http://gt7.local:8000" aria-label="App address">
            <button id="app-connect" type="button">Connect</button>
          </div>
          <p id="app-status" class="status"></p>
          <div id="app-list" class="app-list" hidden></div>
          <div id="app-actions" class="app-actions" hidden>
            <button id="app-pull" class="primary" type="button" disabled>Pull selected</button>
            <button id="app-all" type="button">Select all</button>
          </div>
        </section>
        <div id="tools"></div>
      </div>
      <section class="runs-column">
        <div class="panel">
          <div class="run-head">
            <h2>Runs</h2>
            <button id="refresh" type="button">Refresh</button>
          </div>
          <div id="latest-log" class="latest-log" aria-live="polite">
            <p class="empty-log">Run a command to see stdout and stderr here.</p>
          </div>
          <div id="runs" class="run-list"></div>
        </div>
      </section>
    </section>
    <section id="editor-view" class="view editor-layout" hidden>
      <iframe
        id="track-editor-frame"
        class="editor-frame"
        title="Track bundle editor"
        src="/tools/track_editor/track-editor.html?v=side-cues"
      ></iframe>
    </section>
  </main>
  <script>
    const toolsEl = document.querySelector("#tools");
    const runsEl = document.querySelector("#runs");
    const latestLogEl = document.querySelector("#latest-log");
    let polling = null;
    let toolsById = {};
    // run id -> what to do once that run finishes. This is how a card knows
    // to offer "now rebuild the index" only after the thing that made the
    // index stale actually succeeded.
    const awaiting = new Map();

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

    // Every field says what it is in words, with the flag it becomes shown
    // beside it. The flag still matters — a GUI run and a typed run must be
    // the same run — but "--check" is a fact about argparse, not a label.
    function fieldTitle(option) {
      return `${escapeHtml(option.label)} <span class="hint">${escapeHtml(option.flag)}</span>`;
    }

    function fieldHelp(text) {
      return text ? `<span class="field-help">${escapeHtml(text)}</span>` : "";
    }

    function optionInput(tool, option) {
      const id = `${tool.id}-${option.name}`;
      const label = document.createElement("label");
      label.dataset.option = option.name;
      label.dataset.kind = option.kind;
      if (option.kind === "flag") {
        label.className = "check";
        label.innerHTML = `<input id="${id}" type="checkbox"><span>${fieldTitle(option)}</span>`;
        label.title = option.help || "";
      } else if (option.kind === "optional_value") {
        label.innerHTML = `<span>${fieldTitle(option)}</span>`
          + `<span class="optional-row"><input data-enable type="checkbox" title="Use the default"><input data-value id="${id}" type="text" placeholder="${escapeHtml(option.metavar || "")}"></span>`
          + fieldHelp(option.help);
      } else {
        const type = option.secret ? "password" : "text";
        label.innerHTML = `<span>${fieldTitle(option)}</span>`
          + `<input id="${id}" type="${type}" placeholder="${escapeHtml(option.metavar || "")}">`
          + fieldHelp(option.help);
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
            ${tool.when ? `<p class="when">${escapeHtml(tool.when)}</p>` : ""}
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
        const placeholder = argument.placeholder || (argument.multiple ? "one path per space" : "");
        label.innerHTML = `<span>${escapeHtml(argument.label)}</span>`
          + `<input type="text" placeholder="${escapeHtml(placeholder)}">`
          + fieldHelp(argument.help);
        fields.appendChild(label);
      }
      for (const option of tool.options) fields.appendChild(optionInput(tool, option));
      node.appendChild(fields);

      const actions = document.createElement("div");
      actions.className = "tool-actions";
      const button = document.createElement("button");
      button.className = "primary run-button";
      button.textContent = "Run";
      const status = document.createElement("div");
      status.className = "status";
      const nextSteps = document.createElement("div");
      nextSteps.className = "next-steps";
      nextSteps.hidden = true;
      actions.append(button, status, nextSteps);
      node.appendChild(actions);
      node.dataset.toolId = tool.id;

      function offerNextSteps(run) {
        const steps = (tool.next_steps || []).filter((id) => toolsById[id]);
        if (run.status !== "succeeded" || !steps.length) {
          nextSteps.hidden = true;
          return;
        }
        nextSteps.replaceChildren();
        const label = document.createElement("span");
        label.textContent = "That made these stale:";
        nextSteps.append(label);
        for (const id of steps) {
          const step = document.createElement("button");
          step.textContent = toolsById[id].title;
          step.addEventListener("click", () => {
            nextSteps.hidden = true;
            runToolById(id);
          });
          nextSteps.append(step);
        }
        nextSteps.hidden = false;
      }

      button.addEventListener("click", async () => {
        button.disabled = true;
        status.textContent = "Starting";
        nextSteps.hidden = true;
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
          const {run} = await jsonFetch("/api/runs", {
            method: "POST",
            body: JSON.stringify({tool: tool.id, arguments: argumentsList, options}),
          });
          status.textContent = "Queued";
          awaiting.set(run.id, (finished) => {
            status.textContent = finished.status === "succeeded"
              ? `Done in ${finished.duration_s}s`
              : `Failed (exit ${finished.exit_code}) — the log is on the right`;
            offerNextSteps(finished);
          });
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

    function runToolById(id) {
      const card = toolsEl.querySelector(`[data-tool-id="${CSS.escape(id)}"]`);
      if (!card) return;
      card.scrollIntoView({block: "nearest", behavior: "smooth"});
      card.querySelector(".run-button").click();
    }

    async function loadTools() {
      const {tools, groups} = await jsonFetch("/api/tools");
      toolsById = Object.fromEntries(tools.map((tool) => [tool.id, tool]));
      const nodes = [];
      // Grouped in the order the work happens. Alphabetical put "Add Bundle"
      // above "Build Index" by luck rather than by meaning, and put the two
      // commands that talk to somebody's live app in among the ones that
      // rewrite files here.
      for (const group of groups || []) {
        const heading = document.createElement("h2");
        heading.className = "group-heading";
        heading.textContent = group.title;
        nodes.push(heading);
        nodes.push(...tools.filter((tool) => tool.group === group.id).map(toolCard));
      }
      const grouped = new Set((groups || []).map((group) => group.id));
      nodes.push(...tools.filter((tool) => !grouped.has(tool.group)).map(toolCard));
      toolsEl.replaceChildren(...nodes);
    }

    function runLog(run) {
      return [run.stdout, run.stderr ? "\n[stderr]\n" + run.stderr : ""].join("");
    }

    function renderRuns(runs) {
      if (!runs.length) {
        latestLogEl.innerHTML = '<p class="empty-log">Run a command to see stdout and stderr here.</p>';
      } else {
        const latest = runs[0];
        const log = runLog(latest) || "No output yet.";
        latestLogEl.innerHTML = `
          <div class="latest-log-head">
            <span>
              <strong>Latest Log</strong>
              <span>${escapeHtml(latest.tool)} ${escapeHtml(latest.argv.join(" "))}</span>
            </span>
            <span class="state ${latest.status}">${latest.status}${latest.exit_code === null ? "" : ` ${latest.exit_code}`}${latest.duration_s === null ? "" : ` | ${latest.duration_s}s`}</span>
          </div>
          <pre>${escapeHtml(log)}</pre>
        `;
      }
      runsEl.replaceChildren(...runs.map((run, index) => {
        const details = document.createElement("details");
        details.className = "run";
        if (index === 0) details.open = true;
        const log = runLog(run);
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
      for (const run of runs) {
        if (run.status !== "succeeded" && run.status !== "failed") continue;
        const settle = awaiting.get(run.id);
        if (!settle) continue;
        awaiting.delete(run.id);
        settle(run);
      }
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
    // --- your datalogger, browsed rather than typed --------------------
    //
    // The same job as `pull-from-app`, and it runs that exact tool: the
    // difference is that you pick from a list instead of running it once to
    // read the log and again with --only.

    const appBaseEl = document.querySelector("#app-base");
    const appStatusEl = document.querySelector("#app-status");
    const appListEl = document.querySelector("#app-list");
    const appActionsEl = document.querySelector("#app-actions");
    const appPullEl = document.querySelector("#app-pull");

    function appSelection() {
      return [...appListEl.querySelectorAll("input:checked")].map((input) => input.value);
    }

    function syncAppActions() {
      const chosen = appSelection().length;
      appPullEl.disabled = chosen === 0;
      appPullEl.textContent = chosen
        ? `Pull ${chosen} track${chosen === 1 ? "" : "s"}`
        : "Pull selected";
    }

    function renderAppTracks(tracks) {
      appListEl.replaceChildren(...tracks.map((track) => {
        const row = document.createElement("label");
        // A bundle whose layout the app has not confirmed cannot be filed
        // here, so it is shown and disabled rather than quietly missing.
        const blocked = !track.official_id;
        row.className = `app-row${blocked ? " blocked" : ""}`;
        const facts = [
          track.points ? `${track.points.toLocaleString()} m` : "no border yet",
          track.runs ? `${track.runs} run${track.runs === 1 ? "" : "s"}` : "",
          track.updated_at ? track.updated_at.slice(0, 10) : "",
        ].filter(Boolean).join(" · ");
        row.innerHTML = `
          <input type="checkbox" value="${escapeHtml(track.slug)}"${blocked ? " disabled" : ""}>
          <span>
            <b>${escapeHtml(track.official_name || track.track || track.slug)}</b>
            <small>${escapeHtml(facts)}</small>
            ${blocked ? '<small class="why">Confirm its layout in the app before it can be filed here.</small>' : ""}
          </span>
        `;
        row.querySelector("input").addEventListener("change", syncAppActions);
        return row;
      }));
      appListEl.hidden = tracks.length === 0;
      appActionsEl.hidden = tracks.length === 0;
      syncAppActions();
    }

    async function connectToApp() {
      const base = appBaseEl.value.trim();
      appStatusEl.textContent = "Connecting…";
      appListEl.hidden = true;
      appActionsEl.hidden = true;
      try {
        const data = await jsonFetch(`/api/app/tracks?base=${encodeURIComponent(base)}`);
        renderAppTracks(data.tracks || []);
        appStatusEl.textContent = data.tracks.length
          ? `${data.tracks.length} track${data.tracks.length === 1 ? "" : "s"} on ${data.base}.`
          : `${data.base} has no track bundles yet.`;
      } catch (error) {
        appStatusEl.textContent = error.message;
      }
    }

    async function pullSelected() {
      const slugs = appSelection();
      const base = appBaseEl.value.trim();
      if (!slugs.length) return;
      appPullEl.disabled = true;
      try {
        // One run per track, each with the real argv you would have typed.
        for (const slug of slugs) {
          await jsonFetch("/api/runs", {
            method: "POST",
            body: JSON.stringify({
              tool: "pull-from-app",
              arguments: [base],
              options: {only: slug},
            }),
          });
        }
        appStatusEl.textContent = `Pulling ${slugs.length} track(s) — see Runs.`;
        await refreshRuns();
        startPolling();
      } catch (error) {
        appStatusEl.textContent = error.message;
      } finally {
        syncAppActions();
      }
    }

    document.querySelector("#app-connect").addEventListener("click", connectToApp);
    appBaseEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); connectToApp(); }
    });
    appPullEl.addEventListener("click", pullSelected);
    document.querySelector("#app-all").addEventListener("click", () => {
      const inputs = [...appListEl.querySelectorAll("input:not(:disabled)")];
      const turnOn = inputs.some((input) => !input.checked);
      inputs.forEach((input) => { input.checked = turnOn; });
      syncAppActions();
    });

    document.querySelector("#refresh").addEventListener("click", refreshRuns);

    loadTools().then(refreshRuns).then((active) => { if (active) startPolling(); });
  </script>
</body>
</html>
"""
