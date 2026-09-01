import {
  BundleEditorModel,
  GRID_M,
  KINDS,
  MANUAL_KINDS,
  boundsOf,
  catmullRomPath,
  clampScale,
  clampView,
  connectorPath,
  correctedFilename,
  createView,
  drawnRun,
  drawnSourceId,
  edgeVisible,
  edgesInPolygon,
  edgesWithinRadius,
  nearestVisibleEdge,
  parseBundle,
  pathLength,
  pathToEdges,
  scaleBar,
  screenToWorld,
  smudgePath,
  viewForBounds,
  wheelZoomUnits,
  worldToScreen,
  zoomFactor,
  zoomView,
// Versioned like the page and this module. Without it the core sits at a
// stable URL while its importer moves: a browser holding an older copy links
// this module against exports that copy does not have, the module never runs,
// and every listener in it — the Open dialog included — is silently dead.
} from "./track-editor-core.mjs?v=side-cues";

const COLORS = {
  L: "#60a5fa",
  R: "#f472b6",
  wall: "#fb7185",
  runoff: "#c084fc",
  auto: "#94a3b8",
  straddle: "#f59e0b",
};
const SELECTED = "#f8fafc";
const FINISH = "#2dd4bf";
const DRAWING = "#6ee7c7";
const LASSO = "#93c5fd";

const DRAW_TOOLS = new Set(["pen", "curve", "freehand", "connect"]);
const BRUSH_TOOLS = new Set(["brush"]);

const HELP = {
  select: "Click a point to select · Shift-drag or middle-drag to pan · wheel to zoom · double-click to zoom in",
  lasso: "Drag a loop around the points you want · Shift to add to the selection",
  brush: "Drag to paint a selection · hold Shift to unselect · the radius is in metres",
  pen: "Click to place corners of a straight border · double-click or Enter to add · Backspace undoes a corner",
  curve: "Click through the shape of the border · double-click or Enter to add · Backspace undoes a point",
  freehand: "Drag to trace the border · release, then Enter to add",
  connect: "Click a record either side of a gap · then drag the curve to push it into shape · Enter to add",
  pan: "Drag to move · wheel to zoom · double-click to zoom in",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const canvas = $("#track-canvas");
const ctx = canvas.getContext("2d");
const canvasShell = $("#canvas-shell");

let model = null;
let view = null;
let trackBounds = null;
let logicalWidth = 1;
let logicalHeight = 1;
let activeTool = "select";
let pointer = null;
let messageTimer = null;
let lasso = null;      // screen points of the loop being dragged
let sketch = null;     // pen/curve/freehand: { anchors: [world points], freehand: bool }
// connect: { a, b, path } — two surveyed records and the curve bridging them.
let connector = null;
// One drawn-source id for as long as this document is open. Asking for a
// fresh one per frame would put a different id in the preview's votes than
// the one the commit registers, and the download would then be rejected for
// citing a source that is not in meta.source_runs.
let drawSource = null;
let appTracks = [];
// Whether the server behind this page can merge a document into tracks/.
let canSave = false;

const filters = {
  sides: new Set(["L", "R"]),
  kinds: new Set(KINDS),
};

function showMessage(text, error = false) {
  const el = $("#message");
  el.textContent = text;
  el.className = `message${error ? " error" : ""}`;
  el.hidden = false;
  clearTimeout(messageTimer);
  messageTimer = setTimeout(() => { el.hidden = true; }, error ? 8000 : 3500);
}

function safeError(error) {
  showMessage(error instanceof Error ? error.message : String(error), true);
}

function canvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function worldPoint(event) {
  return screenToWorld(canvasPoint(event), view, logicalWidth, logicalHeight);
}

// --- view -----------------------------------------------------------------

function setView(next) {
  view = clampView(next, trackBounds, logicalWidth, logicalHeight);
  updateZoomUi();
  draw();
}

function fitView() {
  if (!model) return;
  // Refit rebuilds baseScale too, so the zoom limits stay relative to what
  // "the whole circuit on screen" means at the canvas's current size.
  view = createView(model.document.edges, logicalWidth, logicalHeight, 38);
  updateZoomUi();
  draw();
}

function zoomBy(units, anchor = null) {
  if (!model || !view) return;
  const at = anchor || { x: logicalWidth / 2, y: logicalHeight / 2 };
  setView(zoomView(view, at, zoomFactor(units), logicalWidth, logicalHeight));
}

function zoomToSelection() {
  if (!model || !model.selected.size) return;
  const points = [...model.selected].map((index) => model.document.edges[index]);
  const bounds = boundsOf(points);
  if (!bounds) return;
  const padded = {
    minX: bounds.minX - 12, maxX: bounds.maxX + 12,
    minZ: bounds.minZ - 12, maxZ: bounds.maxZ + 12,
  };
  setView(viewForBounds(padded, logicalWidth, logicalHeight, 38, view.baseScale));
}

function updateZoomUi() {
  if (!view) return;
  const relative = view.scale / (view.baseScale || view.scale);
  $("#zoom-readout").value = relative >= 10
    ? `${Math.round(relative)}×`
    : `${Math.round(relative * 100)}%`;
  const bar = scaleBar(view);
  $("#scale-bar-rule").style.width = `${Math.round(bar.pixels)}px`;
  $("#scale-bar-label").textContent = bar.label;
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  // A background tab, a collapsed panel or an ancestor that is still
  // `display: none` all measure about nothing. Fitting a 4 km circuit into
  // one pixel gives a scale of ~0.0003 px/m, and since the view is only ever
  // rebuilt on a resize, nothing afterwards puts it right: the track is drawn
  // sub-pixel, the scale bar reads in hundreds of kilometres, and no click
  // lands on anything. Wait for a real size instead.
  if (rect.width < 2 || rect.height < 2) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  logicalWidth = Math.max(1, rect.width);
  logicalHeight = Math.max(1, rect.height);
  const width = Math.round(logicalWidth * dpr);
  const height = Math.round(logicalHeight * dpr);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (model && !view) fitView();
  else if (view && model) {
    // The canvas changed size, so "fit" means something else now. Hold the
    // zoom *relative to fit* rather than the absolute pixels-per-metre: at
    // 100% you stay fitted when the window grows, and at 4× you stay at 4×.
    // Holding the absolute scale instead is why a freshly loaded track drew
    // at a fifth of the canvas — the first measurement happened before the
    // canvas had been laid out, and nothing corrected it afterwards.
    const relative = view.scale / (view.baseScale || view.scale);
    const refit = createView(model.document.edges, logicalWidth, logicalHeight, 38);
    view.baseScale = refit.baseScale;
    view.scale = clampScale(view, refit.baseScale * relative);
    updateZoomUi();
    draw();
  } else draw();
}

// --- drawing --------------------------------------------------------------

function drawSpacing() {
  return Number($("#draw-spacing").value) || GRID_M;
}

function sketchPath() {
  if (connector) return connector.path;
  if (!sketch || !sketch.anchors.length) return [];
  if (sketch.freehand || activeTool !== "curve") return sketch.anchors;
  return catmullRomPath(sketch.anchors);
}

function hasSketch() {
  return Boolean(connector || (sketch && sketch.anchors.length));
}

function connectTension() {
  return (Number($("#connect-tension").value) || 0) / 100;
}

function pushRadius() {
  return Math.max(1, Number($("#connect-push").value) || 12);
}

/**
 * Rebuild the bridge from its two anchors.
 *
 * Any push the user has already made is discarded — the curve is a function of
 * the two records and the tension, and pretending a reshaped path could also
 * follow a moved slider would mean silently keeping half of each.
 */
function rebuildConnector() {
  if (!connector) return;
  connector.path = connectorPath(connector.a, connector.b, { tension: connectTension() });
}

function pickConnectorEnd(index) {
  const edge = model.document.edges[index];
  if (!connector || connector.b) {
    connector = { a: edge, b: null, path: [] };
    showMessage(`Anchored on a ${edge.side === "L" ? "left" : "right"}-side ${edge.kind} record. Now pick the far side of the gap.`);
    return;
  }
  if (edge === connector.a) return;
  if (edge.side !== connector.a.side) {
    // Bridging the left border to the right one would draw a line across the
    // road and file it as one border. That is never a repair.
    showMessage("Both records must be on the same side of the road.", true);
    return;
  }
  connector.b = edge;
  rebuildConnector();
  // The bridge inherits what it is joining; a surveyed metre whose kind was
  // inferred rather than marked becomes a plain edge.
  $("#draw-side").value = connector.a.side;
  const kind = [connector.a.kind, connector.b.kind].find((k) => MANUAL_KINDS.includes(k));
  $("#draw-kind").value = kind || "edge";
  showMessage(`Bridging ${Math.round(pathLength(connector.path))} m. Drag the curve to push it into shape.`);
}

/** The records the current sketch would add, recomputed for the preview. */
function sketchEdges() {
  if (!model || !hasSketch()) return null;
  const path = sketchPath();
  if (path.length < 2) return null;
  try {
    return pathToEdges(path, {
      side: $("#draw-side").value,
      kind: $("#draw-kind").value,
      source: drawSource,
      run: drawnRun(model.document, drawSource),
      existing: model.document.edges,
      spacing: drawSpacing(),
    });
  } catch {
    return null;
  }
}

function startSketch(freehand) {
  sketch = { anchors: [], freehand };
}

function cancelSketch() {
  sketch = null;
  connector = null;
  updateDrawUi();
  draw();
}

function commitSketch() {
  if (!model || !hasSketch()) return;
  const result = sketchEdges();
  if (!result || !result.edges.length) {
    showMessage("Nothing to add — that path lands entirely on metres this bundle already has.", true);
    return;
  }
  try {
    const added = model.addDrawn(result.edges, drawSource, drawnRun(model.document, drawSource));
    sketch = null;
    connector = null;
    const skipped = result.skipped
      ? `, ${result.skipped.toLocaleString()} skipped where the bundle already had that metre`
      : "";
    showMessage(`Added ${added.toLocaleString()} drawn point${added === 1 ? "" : "s"} as ${drawSource}${skipped}.`);
  } catch (error) {
    safeError(error);
  }
  updateUi();
  draw();
}

const SIDE_NAME = { L: "Left side", R: "Right side" };

function updateDrawUi() {
  const drawing = DRAW_TOOLS.has(activeTool);
  const connecting = activeTool === "connect";
  $("#draw-controls").hidden = !drawing;
  $("#draw-provenance").hidden = !drawing;
  $("#brush-controls").hidden = !BRUSH_TOOLS.has(activeTool);
  $("#connect-controls").hidden = !connecting;
  // A connector's side is not a choice: it can only join a border to itself,
  // and both anchors are surveyed records that already say which side they
  // are. So it reports the side rather than asking for it.
  $("#draw-side").hidden = connecting;
  if (connecting) {
    // Known from the first anchor, which is also when it starts mattering:
    // the second click is refused if it is on the other border.
    $("#connect-side").value = connector
      ? SIDE_NAME[connector.a.side]
      : "Pick two records";
  }
  if (!drawing) return;
  const result = sketchEdges();
  const count = result ? result.edges.length : 0;
  $("#draw-commit").disabled = count === 0;
  $("#draw-cancel").disabled = !hasSketch();
  $("#draw-commit").textContent = count
    ? `Add ${count.toLocaleString()} point${count === 1 ? "" : "s"}`
    : "Add points";

  if (!model) return;
  const known = model.drawnSources();
  const held = known.reduce((sum, item) => sum + item.points, 0);
  const provenance = held
    ? `Drawn metres are not evidence. This bundle already holds ${held.toLocaleString()} of them under ${known.map((item) => item.source).join(", ")}.`
    : `Drawn metres are not evidence: they go in under a source of their own (${drawSource}), which adds one run to this bundle's count.`;
  let sketching = "";
  if (connector && connector.b) {
    sketching = ` — bridging ${Math.round(pathLength(connector.path))} m`;
  } else if (connector) {
    sketching = " — pick the record on the far side of the gap";
  } else if (sketch && sketch.anchors.length) {
    sketching = ` — ${sketch.anchors.length} placed${result && result.skipped ? `, ${result.skipped} already surveyed` : ""}`;
  }
  $("#draw-provenance").textContent = provenance + sketching;
}

// --- rendering ------------------------------------------------------------

/**
 * Colour is already spoken for: a wall is red on either side of the road, and
 * only a plain `edge` ever falls through to the side's own blue or pink. So
 * side is drawn as a shape instead — squares on the left, circles on the
 * right — which survives every kind and reads at any zoom the points are big
 * enough to see.
 */
function drawPoint(screen, color, size, side) {
  ctx.fillStyle = color;
  if (side === "R") {
    ctx.beginPath();
    ctx.arc(screen.x, screen.y, size / 2, 0, Math.PI * 2);
    ctx.fill();
    return;
  }
  ctx.fillRect(screen.x - size / 2, screen.y - size / 2, size, size);
}

function strokePath(points, color, dash = []) {
  if (points.length < 2) return;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.setLineDash(dash);
  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();
  ctx.restore();
}

function draw() {
  ctx.clearRect(0, 0, logicalWidth, logicalHeight);
  if (!model || !view) return;

  for (const crossing of model.document.finish_crossings || []) {
    const screen = worldToScreen(crossing, view, logicalWidth, logicalHeight);
    ctx.strokeStyle = FINISH;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(screen.x, screen.y, 6, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Points grow with zoom so that, far in, a metre reads as a metre rather
  // than as the same 2 px dot it was when the whole circuit was on screen.
  const size = Math.max(2, Math.min(7, view.scale * 0.5));
  // Zoomed in on one border, the other one is just more dots. While a tool
  // that writes to a particular side is live, everything on the other side
  // steps back so there is no doubt which border you are working on.
  const workingSide = DRAW_TOOLS.has(activeTool) ? $("#draw-side").value : null;
  let alpha = 1;
  model.document.edges.forEach((edge, index) => {
    if (!edgeVisible(edge, filters)) return;
    const screen = worldToScreen(edge, view, logicalWidth, logicalHeight);
    if (screen.x < -4 || screen.y < -4 || screen.x > logicalWidth + 4 || screen.y > logicalHeight + 4) return;
    const wanted = workingSide && edge.side !== workingSide ? 0.22 : 1;
    if (wanted !== alpha) {
      alpha = wanted;
      ctx.globalAlpha = alpha;
    }
    const color = COLORS[edge.kind] || COLORS[edge.side] || "#64748b";
    drawPoint(screen, color, size, edge.side);
    if (model.selected.has(index)) {
      ctx.strokeStyle = SELECTED;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(screen.x - size / 2 - 2, screen.y - size / 2 - 2, size + 4, size + 4);
    }
  });
  if (alpha !== 1) ctx.globalAlpha = 1;

  if (connector) {
    for (const anchor of [connector.a, connector.b]) {
      if (!anchor) continue;
      const at = worldToScreen(anchor, view, logicalWidth, logicalHeight);
      ctx.strokeStyle = DRAWING;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(at.x, at.y, 7, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (connector.b) {
      const screen = connector.path.map((point) => worldToScreen(point, view, logicalWidth, logicalHeight));
      strokePath(screen, DRAWING);
      const result = sketchEdges();
      const size = Math.max(2, Math.min(7, view.scale * 0.5));
      for (const edge of result ? result.edges : []) {
        drawPoint(worldToScreen(edge, view, logicalWidth, logicalHeight), DRAWING, size, edge.side);
      }
      // The push reach, so you can see what a drag is about to move.
      if (pointer) {
        ctx.save();
        ctx.strokeStyle = "rgba(110, 231, 199, 0.45)";
        ctx.setLineDash([3, 3]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(pointer.x, pointer.y, pushRadius() * view.scale, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }
  }

  if (sketch && sketch.anchors.length) {
    const screen = sketchPath().map((point) => worldToScreen(point, view, logicalWidth, logicalHeight));
    if (pointer && !sketch.freehand && screen.length) {
      strokePath([...screen, pointer], DRAWING, [4, 4]);
    }
    strokePath(screen, DRAWING);
    for (const anchor of sketch.anchors) {
      const at = worldToScreen(anchor, view, logicalWidth, logicalHeight);
      ctx.fillStyle = DRAWING;
      ctx.beginPath();
      ctx.arc(at.x, at.y, 3, 0, Math.PI * 2);
      ctx.fill();
    }
    const result = sketchEdges();
    for (const edge of result ? result.edges : []) {
      drawPoint(worldToScreen(edge, view, logicalWidth, logicalHeight), DRAWING, Math.max(2, size), edge.side);
    }
  }

  if (lasso && lasso.length > 1) {
    strokePath([...lasso, lasso[0]], LASSO, [5, 3]);
  }

  if (pointer && BRUSH_TOOLS.has(activeTool)) {
    const radius = brushRadiusPixels();
    ctx.strokeStyle = pointer.subtracting ? "#fb7185" : "#6ee7c7";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(pointer.x, pointer.y, radius, 0, Math.PI * 2);
    ctx.stroke();
    // Zoomed far out a 5 m brush is a 5 px dot, which is honest but hard to
    // read; the label says what it is either way.
    ctx.fillStyle = ctx.strokeStyle;
    ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    ctx.fillText(`${brushRadiusMetres()} m`, pointer.x + radius + 4, pointer.y - radius - 4);
  }
}

function updateUi() {
  if (!model) return;
  const selected = model.selected.size;
  const drawn = model.drawnSources().reduce((sum, item) => sum + item.points, 0);
  $("#document-name").textContent = model.document.meta.track;
  $("#document-count").textContent = `${model.document.edges.length.toLocaleString()} points`
    + (drawn ? ` · ${drawn.toLocaleString()} drawn` : "")
    + ` · ${selected.toLocaleString()} selected`;
  $("#selected-count").textContent = selected.toLocaleString();
  $("#selection-bar").hidden = selected === 0;
  $("#clear-selection").disabled = selected === 0;
  $("#delete-selection").disabled = selected === 0;
  $("#relabel").disabled = selected === 0;
  $("#zoom-selection").disabled = selected === 0;
  $("#undo").disabled = model.history.length === 0;
  $("#redo").disabled = model.future.length === 0;
  updateDrawUi();
}

function loadDocument(document, filename) {
  model = new BundleEditorModel(document, filename);
  view = null;
  sketch = null;
  connector = null;
  lasso = null;
  // Reuses this bundle's existing drawn source if it has one, so editing the
  // same track twice adds metres to that contributor rather than inventing
  // a second one that never drove anything either.
  drawSource = drawnSourceId(model.document);
  trackBounds = boundsOf(model.document.edges);
  const emptyState = $("#empty-state");
  emptyState.hidden = true;
  emptyState.style.display = "none";
  canvasShell.hidden = false;
  $("#editing-controls").hidden = false;
  $("#tool-strip").hidden = false;
  $("#document-summary").hidden = false;
  $("#save-to-tracks").hidden = !canSave;
  closePopovers();
  resizeCanvas();
  fitView();
  updateUi();
  showMessage(`Loaded ${model.document.meta.track} with ${model.document.edges.length.toLocaleString()} points.`);
}

// --- sources --------------------------------------------------------------

async function loadRepositoryTrack() {
  const path = $("#track-select").value;
  if (!path) return;
  try {
    const response = await fetch(`../../${path}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Could not load ${path} (${response.status})`);
    loadDocument(parseBundle(await response.text()), path.split("/").pop());
  } catch (error) {
    safeError(error);
  }
}

async function loadTrackList() {
  try {
    const response = await fetch("../../index.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Could not read index.json (${response.status})`);
    const index = await response.json();
    const select = $("#track-select");
    for (const configuration of index.configurations.filter((item) => item.bundle)) {
      const option = window.document.createElement("option");
      option.value = configuration.bundle.file;
      option.textContent = configuration.official_name;
      select.append(option);
    }
  } catch (error) {
    safeError(new Error(`Repository track list unavailable: ${error.message}`));
  }
}

/**
 * The app is asked through this server rather than from the page. A browser
 * would need the datalogger to send CORS headers for the fetch to be allowed
 * at all, and the local proxy also keeps the app's address out of the page's
 * origin history.
 */
async function connectToApp() {
  const base = $("#app-base").value.trim();
  const status = $("#app-status");
  const button = $("#app-connect");
  if (!base) return;
  button.disabled = true;
  status.textContent = "Connecting…";
  status.classList.remove("error");
  try {
    const response = await fetch(`../../api/app/tracks?base=${encodeURIComponent(base)}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `The app answered ${response.status}`);
    appTracks = data.tracks || [];
    const select = $("#app-select");
    select.replaceChildren();
    for (const track of appTracks) {
      const option = window.document.createElement("option");
      option.value = track.slug;
      option.textContent = track.official_name || track.track || track.slug;
      if (track.points) option.textContent += ` — ${track.points.toLocaleString()} m`;
      select.append(option);
    }
    $("#app-picker").hidden = appTracks.length === 0;
    $("#app-load").disabled = appTracks.length === 0;
    status.textContent = appTracks.length
      ? `${appTracks.length} surveyed track${appTracks.length === 1 ? "" : "s"} on ${data.base}.`
      : `${data.base} has no track bundles yet.`;
  } catch (error) {
    appTracks = [];
    $("#app-picker").hidden = true;
    status.textContent = error instanceof Error ? error.message : String(error);
    status.classList.add("error");
  } finally {
    button.disabled = false;
  }
}

async function loadFromApp() {
  const slug = $("#app-select").value;
  const base = $("#app-base").value.trim();
  if (!slug) return;
  try {
    const url = `../../api/app/tracks/${encodeURIComponent(slug)}?base=${encodeURIComponent(base)}`;
    const response = await fetch(url, { cache: "no-store" });
    const text = await response.text();
    if (!response.ok) {
      let detail = `The app answered ${response.status}`;
      try { detail = JSON.parse(text).detail || detail; } catch { /* not JSON */ }
      throw new Error(detail);
    }
    loadDocument(parseBundle(text), `${slug}.json`);
  } catch (error) {
    safeError(error);
  }
}

// --- popovers -------------------------------------------------------------

const POPOVERS = [["#open-toggle", "#open-panel"], ["#layers-toggle", "#layers-panel"]];

function closePopovers(except = null) {
  for (const [toggle, panel] of POPOVERS) {
    if (panel === except) continue;
    $(panel).hidden = true;
    $(toggle).setAttribute("aria-expanded", "false");
  }
}

function togglePopover(toggle, panel) {
  const open = $(panel).hidden;
  closePopovers(open ? panel : null);
  $(panel).hidden = !open;
  $(toggle).setAttribute("aria-expanded", String(open));
}

// --- saving ---------------------------------------------------------------

/**
 * The editor is served by two servers: the GUI, which runs tools and writes,
 * and the standard-library one in `track_editor.py`, which has no write
 * endpoints at all. Rather than ship two editors, ask which one this is.
 */
async function detectCapabilities() {
  try {
    const response = await fetch("../../api/capabilities", { cache: "no-store" });
    if (!response.ok) return;
    const capabilities = await response.json();
    canSave = Boolean(capabilities.save_to_tracks);
  } catch {
    canSave = false;  // the read-only server does not answer that route
  }
  // This resolves after the page is interactive, so a document opened in the
  // meantime still gets the button.
  $("#save-to-tracks").hidden = !(canSave && model);
}

async function waitForRun(id) {
  for (let attempt = 0; attempt < 480; attempt += 1) {
    const response = await fetch(`../../api/runs/${encodeURIComponent(id)}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Lost track of the merge (${response.status})`);
    const { run } = await response.json();
    if (run.status === "succeeded" || run.status === "failed") return run;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("The merge did not finish. Check the Runs panel.");
}

/**
 * Merge this document into `tracks/` without a download and a second command.
 *
 * The server hands it to the registered `add-bundle` tool rather than merging
 * it itself, so saving from here and typing `gt7-tracks add-bundle` are one
 * code path with one set of merge rules — and the save shows up in the run log
 * next to everything else.
 */
async function saveIntoTracks() {
  if (!model) return;
  const button = $("#save-to-tracks");
  button.disabled = true;
  try {
    const payload = model.exportDocument();
    const response = await fetch("../../api/tracks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document: payload }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `The server answered ${response.status}`);
    showMessage(`Merging ${model.document.meta.track} into tracks/…`);
    const run = await waitForRun(data.run.id);
    const lines = (run.stdout || "").split("\n").map((line) => line.trim()).filter(Boolean);
    if (run.status !== "succeeded") {
      throw new Error((run.stderr || lines.join(" ") || "the merge failed").trim());
    }
    const wrote = lines.filter((line) => line.startsWith("wrote") || line.startsWith("merging"));
    showMessage(`Saved. ${wrote.join(" · ")} — now rebuild the index and the signatures.`);
  } catch (error) {
    safeError(error);
  } finally {
    button.disabled = false;
  }
}

// --- selection ------------------------------------------------------------

/**
 * The brush radius is metres of road, not pixels of screen.
 *
 * A screen radius means the brush grabs a different amount of circuit at
 * every zoom level, and at "fit the whole track" an 18 px brush was an 18 m
 * one — it swallowed both borders and twelve metres of run-off either side
 * when you meant to touch one edge. Metres are what the rest of this editor
 * already speaks: the scale bar, the draw spacing, the dedup grid.
 */
function brushRadiusMetres() {
  return Math.max(0.5, Number($("#brush-size").value) || 5);
}

function brushRadiusPixels() {
  return brushRadiusMetres() * (view ? view.scale : 1);
}

function applyBrush(point, add) {
  if (!model || !view) return;
  const indices = edgesWithinRadius(
    model.document.edges, filters, view, logicalWidth, logicalHeight,
    point, brushRadiusPixels(),
  );
  model.select(indices, add);
  updateUi();
  draw();
}

function applyLasso(add) {
  if (!model || !view || !lasso || lasso.length < 3) return;
  const indices = edgesInPolygon(model.document.edges, filters, view, logicalWidth, logicalHeight, lasso);
  if (!add) model.clearSelection();
  model.select(indices, true);
  showMessage(`Lasso selected ${indices.length.toLocaleString()} point${indices.length === 1 ? "" : "s"}.`);
}

// --- pointer --------------------------------------------------------------

canvas.addEventListener("pointerdown", (event) => {
  if (!model || !view) return;
  const point = canvasPoint(event);
  pointer = { ...point, id: event.pointerId, lastX: point.x, lastY: point.y, dragging: true };
  // Capture is an optimisation — it keeps a drag alive when the cursor
  // leaves the canvas. A browser that refuses it must not take the tool
  // down with it.
  try { canvas.setPointerCapture(event.pointerId); } catch { /* drag still works */ }

  const wantsPan = event.button === 1 || activeTool === "pan" || event.shiftKey && activeTool === "select";
  if (wantsPan) {
    pointer.panning = true;
    canvas.style.cursor = "grabbing";
    return;
  }
  if (event.button !== 0) return;

  if (activeTool === "select") {
    const index = nearestVisibleEdge(model.document.edges, filters, view, logicalWidth, logicalHeight, point, 10);
    if (index >= 0) model.toggle(index);
    updateUi();
    draw();
  } else if (BRUSH_TOOLS.has(activeTool)) {
    pointer.subtracting = event.shiftKey;
    applyBrush(point, !event.shiftKey);
  } else if (activeTool === "lasso") {
    lasso = [point];
    pointer.lassoAdds = event.shiftKey;
  } else if (activeTool === "connect") {
    if (connector && connector.b) {
      // Both ends are down, so a drag is a push rather than a pick.
      pointer.pushing = true;
      pointer.lastWorld = worldPoint(event);
      return;
    }
    const index = nearestVisibleEdge(model.document.edges, filters, view, logicalWidth, logicalHeight, point, 12);
    if (index >= 0) pickConnectorEnd(index);
    else showMessage("Click on a surveyed record — the connector anchors to two of them.", true);
    updateDrawUi();
    draw();
  } else if (activeTool === "freehand") {
    startSketch(true);
    sketch.anchors.push(worldPoint(event));
  } else if (DRAW_TOOLS.has(activeTool)) {
    if (!sketch) startSketch(false);
    sketch.anchors.push(worldPoint(event));
    updateDrawUi();
    draw();
  }
});

canvas.addEventListener("pointermove", (event) => {
  const point = canvasPoint(event);
  if (!pointer || pointer.id !== event.pointerId) {
    pointer = { ...point, id: event.pointerId, dragging: false };
    draw();
    return;
  }
  pointer.x = point.x;
  pointer.y = point.y;
  if (pointer.dragging && pointer.panning) {
    setView({
      ...view,
      centerX: view.centerX - (point.x - pointer.lastX) / view.scale,
      centerZ: view.centerZ - (point.y - pointer.lastY) / view.scale,
    });
    pointer.lastX = point.x;
    pointer.lastY = point.y;
  } else if (pointer.dragging && BRUSH_TOOLS.has(activeTool)) {
    pointer.subtracting = event.shiftKey;
    applyBrush(point, !event.shiftKey);
  } else if (pointer.dragging && activeTool === "lasso" && lasso) {
    const last = lasso[lasso.length - 1];
    if (Math.hypot(point.x - last.x, point.y - last.y) > 3) lasso.push({ ...point });
    draw();
  } else if (pointer.dragging && pointer.pushing && connector) {
    const world = screenToWorld(point, view, logicalWidth, logicalHeight);
    connector.path = smudgePath(
      connector.path, world,
      { x: world.x - pointer.lastWorld.x, z: world.z - pointer.lastWorld.z },
      pushRadius(),
    );
    pointer.lastWorld = world;
    updateDrawUi();
    draw();
  } else if (pointer.dragging && activeTool === "freehand" && sketch) {
    const world = screenToWorld(point, view, logicalWidth, logicalHeight);
    const last = sketch.anchors[sketch.anchors.length - 1];
    if (!last || Math.hypot(world.x - last.x, world.z - last.z) > drawSpacing() / 2) {
      sketch.anchors.push(world);
      updateDrawUi();
    }
    draw();
  } else {
    draw();
  }
});

function endPointer(event) {
  if (!pointer || pointer.id !== event.pointerId) return;
  if (activeTool === "lasso" && lasso) {
    applyLasso(pointer.lassoAdds);
    lasso = null;
    updateUi();
  }
  pointer.dragging = false;
  pointer.panning = false;
  pointer.pushing = false;
  canvas.style.cursor = activeTool === "pan" ? "grab" : "crosshair";
  updateDrawUi();
  draw();
}
canvas.addEventListener("pointerup", endPointer);
canvas.addEventListener("pointercancel", endPointer);
canvas.addEventListener("pointerleave", () => { if (pointer && !pointer.dragging) { pointer = null; draw(); } });
canvas.addEventListener("contextmenu", (event) => event.preventDefault());

canvas.addEventListener("dblclick", (event) => {
  if (!model || !view) return;
  event.preventDefault();
  if (DRAW_TOOLS.has(activeTool) && hasSketch()) {
    commitSketch();
    return;
  }
  zoomBy(event.altKey ? -2 : 2, canvasPoint(event));
});

canvas.addEventListener("wheel", (event) => {
  if (!model || !view) return;
  event.preventDefault();
  const units = wheelZoomUnits(event, logicalHeight);
  if (!units) return;
  setView(zoomView(view, canvasPoint(event), zoomFactor(units), logicalWidth, logicalHeight));
}, { passive: false });

// --- controls -------------------------------------------------------------

function selectTool(name) {
  if (!DRAW_TOOLS.has(name)) { sketch = null; connector = null; }
  // The connector is its own thing; leaving it for the pen would carry two
  // anchors into a tool that has no idea what to do with them.
  if (name !== "connect") connector = null;
  if (name === "connect") sketch = null;
  activeTool = name;
  $$('[data-tool]').forEach((candidate) => {
    const active = candidate.dataset.tool === name;
    candidate.classList.toggle("active", active);
    candidate.setAttribute("aria-pressed", String(active));
  });
  canvas.style.cursor = name === "pan" ? "grab" : "crosshair";
  $("#canvas-help").textContent = HELP[name] || "";
  updateDrawUi();
  draw();
}

for (const [toggle, panel] of POPOVERS) {
  $(toggle).addEventListener("click", (event) => {
    event.stopPropagation();
    togglePopover(toggle, panel);
  });
  $(panel).addEventListener("click", (event) => event.stopPropagation());
}
$("#empty-open").addEventListener("click", (event) => {
  event.stopPropagation();
  togglePopover("#open-toggle", "#open-panel");
});
document.addEventListener("click", () => closePopovers());
$("#save-to-tracks").addEventListener("click", saveIntoTracks);

$("#track-select").addEventListener("change", () => {
  $("#load-track").disabled = !$("#track-select").value;
});
$("#load-track").addEventListener("click", loadRepositoryTrack);
$("#app-connect").addEventListener("click", connectToApp);
$("#app-base").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); connectToApp(); }
});
$("#app-load").addEventListener("click", loadFromApp);
$("#file-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    loadDocument(parseBundle(await file.text()), file.name);
  } catch (error) {
    safeError(error);
  } finally {
    event.target.value = "";
  }
});

$$('[data-tool]').forEach((button) => button.addEventListener("click", () => selectTool(button.dataset.tool)));

$("#brush-size").addEventListener("input", (event) => {
  $("#brush-output").value = `${event.target.value} m`;
  draw();
});
$("#draw-spacing").addEventListener("input", (event) => {
  $("#draw-spacing-output").value = `${event.target.value} m`;
  updateDrawUi();
  draw();
});
$("#connect-tension").addEventListener("input", (event) => {
  $("#connect-tension-output").value = `${event.target.value}%`;
  rebuildConnector();
  updateDrawUi();
  draw();
});
$("#connect-push").addEventListener("input", (event) => {
  $("#connect-push-output").value = `${event.target.value} m`;
  draw();
});
$("#draw-side").addEventListener("change", () => { updateDrawUi(); draw(); });
$("#draw-kind").addEventListener("change", () => { updateDrawUi(); draw(); });
$("#draw-commit").addEventListener("click", commitSketch);
$("#draw-cancel").addEventListener("click", cancelSketch);

$$('[data-side], [data-kind]').forEach((input) => input.addEventListener("change", () => {
  const collection = input.dataset.side ? filters.sides : filters.kinds;
  const value = input.dataset.side || input.dataset.kind;
  if (input.checked) collection.add(value);
  else collection.delete(value);
  draw();
}));

$("#fit-view").addEventListener("click", fitView);
$("#zoom-in").addEventListener("click", () => zoomBy(1));
$("#zoom-out").addEventListener("click", () => zoomBy(-1));
$("#zoom-selection").addEventListener("click", zoomToSelection);
$("#clear-selection").addEventListener("click", () => { model.clearSelection(); updateUi(); draw(); });
$("#delete-selection").addEventListener("click", () => {
  const count = model.deleteSelected();
  updateUi(); draw();
  showMessage(`Deleted ${count.toLocaleString()} point${count === 1 ? "" : "s"}. Undo is available.`);
});
$("#relabel").addEventListener("click", () => {
  try {
    const kind = $("#relabel-kind").value;
    const count = model.relabelSelected(kind);
    updateUi(); draw();
    showMessage(`Relabeled ${count.toLocaleString()} point${count === 1 ? "" : "s"} as ${kind}.`);
  } catch (error) { safeError(error); }
});
$("#undo").addEventListener("click", () => { model.undo(); updateUi(); draw(); });
$("#redo").addEventListener("click", () => { model.redo(); updateUi(); draw(); });
$("#reset").addEventListener("click", () => {
  model.reset();
  sketch = null;
  connector = null;
  trackBounds = boundsOf(model.document.edges);
  fitView();
  updateUi();
  showMessage("Restored the originally loaded bundle.");
});
$("#download").addEventListener("click", () => {
  try {
    const output = model.exportDocument();
    const blob = new Blob([JSON.stringify(output)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = window.document.createElement("a");
    link.href = url;
    link.download = correctedFilename(model.filename);
    window.document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showMessage(`Downloaded ${link.download}.`);
  } catch (error) { safeError(error); }
});

const TOOL_KEYS = { v: "select", l: "lasso", b: "brush", p: "pen", c: "curve", f: "freehand", k: "connect", h: "pan" };

window.addEventListener("keydown", (event) => {
  if (!model || ["INPUT", "SELECT", "TEXTAREA"].includes(window.document.activeElement?.tagName)) return;
  const command = event.ctrlKey || event.metaKey;

  if (command && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) model.redo(); else model.undo();
    updateUi(); draw();
    return;
  }
  if (command && event.key.toLowerCase() === "y") {
    event.preventDefault(); model.redo(); updateUi(); draw();
    return;
  }
  if (command) return;

  if (event.key === "Enter" && hasSketch()) {
    event.preventDefault();
    commitSketch();
  } else if (event.key === "Escape") {
    const wasOpen = POPOVERS.some(([, panel]) => !$(panel).hidden);
    closePopovers();
    if (wasOpen) return;
    if (hasSketch()) cancelSketch();
    else { model.clearSelection(); updateUi(); draw(); }
  } else if (event.key === "Backspace" && connector) {
    event.preventDefault();
    // Step back one anchor rather than losing the whole bridge.
    connector = connector.b ? { a: connector.a, b: null, path: [] } : null;
    updateDrawUi();
    draw();
  } else if (event.key === "Backspace" && sketch && sketch.anchors.length) {
    event.preventDefault();
    sketch.anchors.pop();
    updateDrawUi();
    draw();
  } else if (event.key === "Delete" || event.key === "Backspace") {
    if (model.selected.size) { event.preventDefault(); model.deleteSelected(); updateUi(); draw(); }
  } else if (event.key === "+" || event.key === "=") {
    event.preventDefault(); zoomBy(1);
  } else if (event.key === "-" || event.key === "_") {
    event.preventDefault(); zoomBy(-1);
  } else if (event.key === "0") {
    event.preventDefault(); fitView();
  } else if (TOOL_KEYS[event.key]) {
    selectTool(TOOL_KEYS[event.key]);
  }
});

new ResizeObserver(resizeCanvas).observe(canvasShell);
// A backstop for the cases a ResizeObserver on the shell can miss — the
// window itself changing while the editor sits in a hidden tab or an iframe
// whose box did not change, and the first paint after becoming visible.
window.addEventListener("resize", resizeCanvas);
document.addEventListener("visibilitychange", () => { if (!document.hidden) resizeCanvas(); });
selectTool("select");
loadTrackList();
detectCapabilities();
