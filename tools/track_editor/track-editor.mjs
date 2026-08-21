import {
  BundleEditorModel,
  KINDS,
  correctedFilename,
  createView,
  edgeVisible,
  edgesWithinRadius,
  nearestVisibleEdge,
  parseBundle,
  screenToWorld,
  worldToScreen,
} from "./track-editor-core.mjs";

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

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const canvas = $("#track-canvas");
const ctx = canvas.getContext("2d");
const canvasShell = $("#canvas-shell");

let model = null;
let view = null;
let logicalWidth = 1;
let logicalHeight = 1;
let activeTool = "select";
let pointer = null;
let messageTimer = null;

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

function fitView() {
  if (!model) return;
  view = createView(model.document.edges, logicalWidth, logicalHeight, 38);
  draw();
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
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
  else draw();
}

function drawPoint(screen, color, size) {
  ctx.fillStyle = color;
  ctx.fillRect(screen.x - size / 2, screen.y - size / 2, size, size);
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

  model.document.edges.forEach((edge, index) => {
    if (!edgeVisible(edge, filters)) return;
    const screen = worldToScreen(edge, view, logicalWidth, logicalHeight);
    if (screen.x < -4 || screen.y < -4 || screen.x > logicalWidth + 4 || screen.y > logicalHeight + 4) return;
    const color = COLORS[edge.kind] || COLORS[edge.side] || "#64748b";
    drawPoint(screen, color, view.scale > 2 ? 2.6 : 2);
    if (model.selected.has(index)) {
      ctx.strokeStyle = SELECTED;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(screen.x - 3.5, screen.y - 3.5, 7, 7);
    }
  });

  if (pointer && ["brush-add", "brush-remove"].includes(activeTool)) {
    ctx.strokeStyle = activeTool === "brush-add" ? "#6ee7c7" : "#fb7185";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(pointer.x, pointer.y, Number($("#brush-size").value), 0, Math.PI * 2);
    ctx.stroke();
  }
}

function updateUi() {
  if (!model) return;
  const selected = model.selected.size;
  $("#document-name").textContent = model.document.meta.track;
  $("#document-count").textContent = `${model.document.edges.length.toLocaleString()} points · ${selected.toLocaleString()} selected`;
  $("#selected-count").textContent = selected.toLocaleString();
  $("#clear-selection").disabled = selected === 0;
  $("#delete-selection").disabled = selected === 0;
  $("#relabel").disabled = selected === 0;
  $("#undo").disabled = model.history.length === 0;
  $("#redo").disabled = model.future.length === 0;
}

function loadDocument(document, filename) {
  model = new BundleEditorModel(document, filename);
  view = null;
  const emptyState = $("#empty-state");
  emptyState.hidden = true;
  emptyState.style.display = "none";
  canvasShell.hidden = false;
  $("#editing-controls").hidden = false;
  $("#document-summary").hidden = false;
  resizeCanvas();
  fitView();
  updateUi();
  showMessage(`Loaded ${model.document.meta.track} with ${model.document.edges.length.toLocaleString()} points.`);
}

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
      const option = document.createElement("option");
      option.value = configuration.bundle.file;
      option.textContent = configuration.official_name;
      select.append(option);
    }
  } catch (error) {
    safeError(new Error(`Repository track list unavailable: ${error.message}`));
  }
}

function applyBrush(point) {
  if (!model || !view) return;
  const indices = edgesWithinRadius(
    model.document.edges, filters, view, logicalWidth, logicalHeight,
    point, Number($("#brush-size").value),
  );
  model.select(indices, activeTool === "brush-add");
  updateUi();
  draw();
}

canvas.addEventListener("pointerdown", (event) => {
  if (!model || !view) return;
  const point = canvasPoint(event);
  pointer = { ...point, id: event.pointerId, lastX: point.x, lastY: point.y, dragging: true };
  canvas.setPointerCapture(event.pointerId);
  if (event.button === 1 || activeTool === "pan") {
    pointer.panning = true;
    canvas.style.cursor = "grabbing";
  } else if (activeTool === "select") {
    const index = nearestVisibleEdge(model.document.edges, filters, view, logicalWidth, logicalHeight, point, 10);
    if (index >= 0) model.toggle(index);
    updateUi();
    draw();
  } else if (["brush-add", "brush-remove"].includes(activeTool)) {
    applyBrush(point);
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
    view.centerX -= (point.x - pointer.lastX) / view.scale;
    view.centerZ -= (point.y - pointer.lastY) / view.scale;
    pointer.lastX = point.x;
    pointer.lastY = point.y;
    draw();
  } else if (pointer.dragging && ["brush-add", "brush-remove"].includes(activeTool)) {
    applyBrush(point);
  } else {
    draw();
  }
});

function endPointer(event) {
  if (pointer && pointer.id === event.pointerId) {
    pointer.dragging = false;
    pointer.panning = false;
    canvas.style.cursor = activeTool === "pan" ? "grab" : "crosshair";
    draw();
  }
}
canvas.addEventListener("pointerup", endPointer);
canvas.addEventListener("pointercancel", endPointer);
canvas.addEventListener("pointerleave", () => { if (pointer && !pointer.dragging) { pointer = null; draw(); } });
canvas.addEventListener("contextmenu", (event) => event.preventDefault());

canvas.addEventListener("wheel", (event) => {
  if (!model || !view) return;
  event.preventDefault();
  const point = canvasPoint(event);
  const world = screenToWorld(point, view, logicalWidth, logicalHeight);
  const factor = Math.exp(-event.deltaY * 0.0015);
  const nextScale = Math.max(view.baseScale * 0.2, Math.min(view.baseScale * 150, view.scale * factor));
  view.scale = nextScale;
  view.centerX = world.x - (point.x - logicalWidth / 2) / nextScale;
  view.centerZ = world.z - (point.y - logicalHeight / 2) / nextScale;
  draw();
}, { passive: false });

$("#track-select").addEventListener("change", () => {
  $("#load-track").disabled = !$("#track-select").value;
});
$("#load-track").addEventListener("click", loadRepositoryTrack);
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

$$('[data-tool]').forEach((button) => button.addEventListener("click", () => {
  activeTool = button.dataset.tool;
  $$('[data-tool]').forEach((candidate) => {
    const active = candidate === button;
    candidate.classList.toggle("active", active);
    candidate.setAttribute("aria-pressed", String(active));
  });
  canvas.style.cursor = activeTool === "pan" ? "grab" : "crosshair";
  draw();
}));

$("#brush-size").addEventListener("input", (event) => {
  $("#brush-output").value = `${event.target.value} px`;
  draw();
});

$$('[data-side], [data-kind]').forEach((input) => input.addEventListener("change", () => {
  const collection = input.dataset.side ? filters.sides : filters.kinds;
  const value = input.dataset.side || input.dataset.kind;
  if (input.checked) collection.add(value);
  else collection.delete(value);
  draw();
}));

$("#fit-view").addEventListener("click", fitView);
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
$("#reset").addEventListener("click", () => { model.reset(); fitView(); updateUi(); showMessage("Restored the originally loaded bundle."); });
$("#download").addEventListener("click", () => {
  try {
    const output = model.exportDocument();
    const blob = new Blob([JSON.stringify(output)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = correctedFilename(model.filename);
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showMessage(`Downloaded ${link.download}.`);
  } catch (error) { safeError(error); }
});

window.addEventListener("keydown", (event) => {
  if (!model || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  const command = event.ctrlKey || event.metaKey;
  if (command && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) model.redo(); else model.undo();
    updateUi(); draw();
  } else if (command && event.key.toLowerCase() === "y") {
    event.preventDefault(); model.redo(); updateUi(); draw();
  } else if (event.key === "Escape") {
    model.clearSelection(); updateUi(); draw();
  } else if (event.key === "Delete" || event.key === "Backspace") {
    if (model.selected.size) { event.preventDefault(); model.deleteSelected(); updateUi(); draw(); }
  }
});

new ResizeObserver(resizeCanvas).observe(canvasShell);
loadTrackList();
