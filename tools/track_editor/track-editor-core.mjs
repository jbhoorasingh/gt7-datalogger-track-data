const FORMAT = "gt7-datalogger-track-bundle";
const VERSION = 4;
export const KINDS = ["wall", "runoff", "edge", "auto", "straddle"];
export const MANUAL_KINDS = ["wall", "runoff", "edge"];
const AUTO_KINDS = ["auto", "straddle"];
export const SIDES = ["L", "R"];

// bundle_format.py's own limits, repeated here so the editor refuses to build
// a document the repository would then reject.
export const GRID_M = 1.0;
export const MAX_POINTS = 50000;

const clone = (value) => {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
};

const finite = (value) => typeof value === "number" && Number.isFinite(value);
const integer = (value) => Number.isInteger(value);
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

function fail(message) {
  throw new Error(message);
}

function validatePosition(value, where) {
  if (!object(value) || !finite(value.x) || !finite(value.z)) {
    fail(`${where} must contain finite x and z coordinates`);
  }
}

function tally(bySource) {
  return Object.values(bySource).reduce((sum, entry) => sum + entry[0], 0);
}

export function resolveKind(votes) {
  for (const tier of [MANUAL_KINDS, AUTO_KINDS]) {
    const present = tier.filter((kind) => votes[kind] && Object.keys(votes[kind]).length);
    if (present.length) {
      return present.reduce((best, kind) => {
        const score = tally(votes[kind]);
        const bestScore = tally(votes[best]);
        return score > bestScore ? kind : best;
      });
    }
  }
  return "auto";
}

// Python's round(), used by bundle_format.edge_key(), breaks exact .5 ties
// toward the even integer. JavaScript's Math.round() does not.
export function roundGrid(value) {
  const lower = Math.floor(value);
  const fraction = value - lower;
  if (fraction < 0.5) return lower;
  if (fraction > 0.5) return lower + 1;
  return lower % 2 === 0 ? lower : lower + 1;
}

function validateMeta(meta) {
  if (!object(meta)) fail("meta must be an object");
  if (typeof meta.track !== "string" || !meta.track.trim()) fail("meta.track is missing or empty");
  if (typeof meta.updated_at !== "string" || !meta.updated_at) fail("meta.updated_at is missing");
  if (!object(meta.source_runs) || !Object.keys(meta.source_runs).length) {
    fail("meta.source_runs must contain at least one source");
  }
  let total = 0;
  for (const [source, runs] of Object.entries(meta.source_runs)) {
    if (!source) fail("meta.source_runs contains an empty source id");
    if (!integer(runs) || runs < 0) fail(`meta.source_runs[${JSON.stringify(source)}] is not a run count`);
    total += runs;
  }
  if (!integer(meta.runs) || meta.runs !== total) {
    fail(`meta.runs must equal the source run total (${total})`);
  }
  if (meta.official !== null && meta.official !== undefined) {
    if (!object(meta.official)) fail("meta.official must be an object or null");
    for (const field of ["official_id", "official_name", "track", "layout"]) {
      if (typeof meta.official[field] !== "string" || !meta.official[field]) {
        fail(`meta.official.${field} is missing or empty`);
      }
    }
    if (!integer(meta.official.turns) || meta.official.turns < 0) fail("meta.official.turns is invalid");
    if (!finite(meta.official.length_m) || meta.official.length_m <= 0) fail("meta.official.length_m is invalid");
    if (typeof meta.official.reverse !== "boolean") fail("meta.official.reverse must be true or false");
  }
}

function validateVotes(edge, index, sourceRuns) {
  const where = `edges[${index}]`;
  if (!object(edge.votes) || !Object.keys(edge.votes).length) fail(`${where}.votes is missing or empty`);
  for (const [kind, bySource] of Object.entries(edge.votes)) {
    if (!KINDS.includes(kind)) fail(`${where}.votes contains unknown kind ${JSON.stringify(kind)}`);
    if (!object(bySource) || !Object.keys(bySource).length) fail(`${where}.votes.${kind} is empty`);
    for (const [source, entry] of Object.entries(bySource)) {
      if (!(Array.isArray(entry) && entry.length === 2 && integer(entry[0]) && integer(entry[1]) && entry[0] >= 1 && entry[1] >= 0)) {
        fail(`${where}.votes.${kind}.${source} must be [count, last_run]`);
      }
      if (!(source in sourceRuns)) fail(`${where}.votes.${kind} cites unknown source ${JSON.stringify(source)}`);
      if (entry[1] > sourceRuns[source]) fail(`${where}.votes.${kind}.${source} exceeds that source's run count`);
    }
  }
  const resolved = resolveKind(edge.votes);
  if (edge.kind !== resolved) fail(`${where}.kind is ${JSON.stringify(edge.kind)}, but its votes resolve to ${JSON.stringify(resolved)}`);
}

function validateEdges(edges, sourceRuns) {
  if (!Array.isArray(edges)) fail("edges must be an array");
  if (edges.length > 50000) fail("edges contains more than 50,000 records");
  const seen = new Map();
  edges.forEach((edge, index) => {
    const where = `edges[${index}]`;
    if (!object(edge)) fail(`${where} must be an object`);
    for (const field of ["x", "z", "hx", "hz"]) {
      if (!finite(edge[field])) fail(`${where}.${field} must be a finite number`);
    }
    if (edge.y !== null && edge.y !== undefined && !finite(edge.y)) fail(`${where}.y must be a finite number or null`);
    if (edge.tw !== null && edge.tw !== undefined && (!finite(edge.tw) || edge.tw <= 0)) fail(`${where}.tw must be positive or null`);
    if (!integer(edge.run) || edge.run < 0) fail(`${where}.run must be a non-negative integer`);
    if (!SIDES.includes(edge.side)) fail(`${where}.side must be L or R`);
    if (!KINDS.includes(edge.kind)) fail(`${where}.kind is not supported`);
    if (Math.abs(Math.hypot(edge.hx, edge.hz) - 1) > 0.001) fail(`${where} heading must be a unit vector`);
    validateVotes(edge, index, sourceRuns);
    const key = `${roundGrid(edge.x)},${roundGrid(edge.z)},${edge.side}`;
    if (seen.has(key)) fail(`${where} repeats the metre already held by edges[${seen.get(key)}] (${key})`);
    seen.set(key, index);
  });
}

function validateFinish(items) {
  if (!Array.isArray(items)) fail("finish_crossings must be an array");
  if (items.length > 20) fail("finish_crossings contains more than 20 records");
  items.forEach((item, index) => {
    if (!object(item)) fail(`finish_crossings[${index}] must be an object`);
    for (const field of ["x", "z", "hx", "hz", "lap"]) {
      if (!finite(item[field])) fail(`finish_crossings[${index}].${field} must be finite`);
    }
  });
}

function validateCorners(items) {
  if (!Array.isArray(items)) fail("corners must be an array");
  const numbers = new Set();
  items.forEach((corner, index) => {
    const where = `corners[${index}]`;
    if (!object(corner)) fail(`${where} must be an object`);
    if (!integer(corner.n) || corner.n < 1 || numbers.has(corner.n)) fail(`${where}.n must be a unique positive integer`);
    numbers.add(corner.n);
    validatePosition(corner.apex, `${where}.apex`);
    for (const field of ["entry", "exit"]) {
      if (corner[field] !== null && corner[field] !== undefined) validatePosition(corner[field], `${where}.${field}`);
    }
    if (corner.direction !== null && corner.direction !== undefined && !["L", "R"].includes(corner.direction)) {
      fail(`${where}.direction must be L, R, or null`);
    }
    for (const field of ["name", "note"]) {
      if (corner[field] !== undefined && typeof corner[field] !== "string") fail(`${where}.${field} must be text`);
    }
  });
}

function validateSections(items) {
  if (!Array.isArray(items)) fail("sections must be an array");
  items.forEach((section, index) => {
    const where = `sections[${index}]`;
    if (!object(section)) fail(`${where} must be an object`);
    if (!integer(section.n) || section.n < 1) fail(`${where}.n must be a positive integer`);
    if (section.name !== undefined && typeof section.name !== "string") fail(`${where}.name must be text`);
  });
}

export function validateBundle(input) {
  if (!object(input)) fail("The selected file does not contain a bundle object");
  if (input.format !== FORMAT) fail(`format must be ${JSON.stringify(FORMAT)}`);
  if (input.version !== VERSION) fail(`Only bundle format v${VERSION} can be edited (found v${input.version})`);
  validateMeta(input.meta);
  validateEdges(input.edges, input.meta.source_runs);
  validateFinish(input.finish_crossings ?? []);
  validateCorners(input.corners ?? []);
  validateSections(input.sections ?? []);
  return input;
}

export function parseBundle(text) {
  let value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    fail(`Could not parse JSON: ${error.message}`);
  }
  validateBundle(value);
  return value;
}

export function correctedFilename(filename) {
  const clean = (filename || "track-bundle.json").split(/[\\/]/).pop();
  const stem = clean.toLowerCase().endsWith(".json") ? clean.slice(0, -5) : clean;
  return `${stem}.corrected.json`;
}

export class BundleEditorModel {
  constructor(document, filename = "track-bundle.json") {
    validateBundle(document);
    this.original = clone(document);
    this.document = clone(document);
    this.filename = filename;
    this.selected = new Set();
    this.history = [];
    this.future = [];
  }

  toggle(index) {
    if (!integer(index) || index < 0 || index >= this.document.edges.length) return false;
    if (this.selected.has(index)) this.selected.delete(index);
    else this.selected.add(index);
    return true;
  }

  select(indices, add = true) {
    for (const index of indices) {
      if (!integer(index) || index < 0 || index >= this.document.edges.length) continue;
      if (add) this.selected.add(index);
      else this.selected.delete(index);
    }
  }

  clearSelection() {
    this.selected.clear();
  }

  deleteSelected() {
    const indices = [...this.selected].sort((a, b) => a - b);
    if (!indices.length) return 0;
    const items = indices.map((index) => ({ index, edge: clone(this.document.edges[index]) }));
    for (const { index } of [...items].reverse()) this.document.edges.splice(index, 1);
    this.selected.clear();
    this.history.push({ type: "delete", items });
    this.future = [];
    return items.length;
  }

  relabelSelected(kind) {
    if (!MANUAL_KINDS.includes(kind)) fail("Points can only be relabeled as edge, wall, or runoff");
    const items = [];
    for (const index of [...this.selected].sort((a, b) => a - b)) {
      const edge = this.document.edges[index];
      const before = clone(edge);
      const merged = {};
      for (const bySource of Object.values(edge.votes)) {
        for (const [source, entry] of Object.entries(bySource)) {
          const held = merged[source];
          if (!held || entry[1] > held[1] || (entry[1] === held[1] && entry[0] > held[0])) {
            merged[source] = [...entry];
          }
        }
      }
      edge.kind = kind;
      edge.votes = { [kind]: merged };
      items.push({ index, before, after: clone(edge) });
    }
    if (!items.length) return 0;
    this.history.push({ type: "relabel", items });
    this.future = [];
    return items.length;
  }

  /**
   * Append drawn border records, filing them under their own source.
   *
   * `meta.runs` goes up by that source's run count, because it is defined as
   * the sum of `source_runs` and a bundle whose total disagrees with its own
   * sources is rejected by both this repository and the app. A drawn source
   * therefore shows up in the run count — which is the honest outcome: the
   * bundle really does now contain something that is not a lap.
   */
  addDrawn(edges, source, run = 1) {
    if (!edges.length) return 0;
    if (typeof source !== "string" || !source) fail("Drawn points need a source id");
    if (this.document.edges.length + edges.length > MAX_POINTS) {
      fail(`A bundle holds at most ${MAX_POINTS.toLocaleString()} records`);
    }
    const meta = this.document.meta;
    const before = { runs: meta.runs, source_runs: { ...meta.source_runs } };
    const sourceRuns = { ...meta.source_runs, [source]: Math.max(meta.source_runs[source] || 0, run) };
    const after = {
      runs: Object.values(sourceRuns).reduce((sum, count) => sum + count, 0),
      source_runs: sourceRuns,
    };
    const operation = {
      type: "draw",
      at: this.document.edges.length,
      edges: edges.map(clone),
      before,
      after,
    };
    this._apply(operation, true);
    this.history.push(operation);
    this.future = [];
    return edges.length;
  }

  /** Every source in this document that holds drawn rather than driven metres. */
  drawnSources() {
    const counts = new Map();
    for (const edge of this.document.edges) {
      for (const bySource of Object.values(edge.votes || {})) {
        for (const source of Object.keys(bySource)) {
          if (!source.startsWith(DRAWN_SOURCE_PREFIX)) continue;
          counts.set(source, (counts.get(source) || 0) + 1);
        }
      }
    }
    return [...counts].sort().map(([source, points]) => ({ source, points }));
  }

  _apply(operation, forward) {
    if (operation.type === "draw") {
      const meta = forward ? operation.after : operation.before;
      if (forward) this.document.edges.splice(operation.at, 0, ...operation.edges.map(clone));
      else this.document.edges.splice(operation.at, operation.edges.length);
      this.document.meta.source_runs = { ...meta.source_runs };
      this.document.meta.runs = meta.runs;
    } else if (operation.type === "delete") {
      if (forward) {
        for (const { index } of [...operation.items].reverse()) this.document.edges.splice(index, 1);
      } else {
        for (const { index, edge } of operation.items) this.document.edges.splice(index, 0, clone(edge));
      }
    } else if (operation.type === "relabel") {
      for (const item of operation.items) this.document.edges[item.index] = clone(forward ? item.after : item.before);
    }
    this.selected.clear();
  }

  undo() {
    const operation = this.history.pop();
    if (!operation) return false;
    this._apply(operation, false);
    this.future.push(operation);
    return true;
  }

  redo() {
    const operation = this.future.pop();
    if (!operation) return false;
    this._apply(operation, true);
    this.history.push(operation);
    return true;
  }

  reset() {
    this.document = clone(this.original);
    this.selected.clear();
    this.history = [];
    this.future = [];
  }

  exportDocument(now = new Date()) {
    const output = clone(this.document);
    output.meta.updated_at = now.toISOString();
    validateBundle(output);
    return output;
  }
}

// ---------------------------------------------------------------------------
// View, zoom and panning
//
// One world unit is one metre, so `scale` is pixels per metre throughout and
// the scale bar can be honest about distance. `baseScale` is whatever "fit the
// whole circuit" worked out to for the current canvas, and the zoom limits are
// multiples of it — a limit in absolute pixels-per-metre would mean something
// different on a 4 km circuit than on a kart track.
// ---------------------------------------------------------------------------

export const MIN_ZOOM = 0.25;   // × the fit scale
export const MAX_ZOOM = 400;    // ~4 cm per pixel on a typical canvas
export const ZOOM_PER_UNIT = 1.25;

// A wheel event's deltaY is not a distance. Chrome reports pixels, Firefox
// reports lines, some browsers report pages, and a trackpad reports single
// digits where a mouse notch reports ~120. Zooming by `deltaY` directly is
// why the same gesture crawls in one browser and lurches in another; every
// entry point converts to *zoom units* first, where one unit is one notch of
// a mouse wheel and one unit is exactly what the +/− buttons do.
const WHEEL_LINE_PX = 16;
const WHEEL_PIXELS_PER_UNIT = 120;
// Pinch-to-zoom arrives as ctrl+wheel with much smaller deltas than a notch.
const PINCH_PIXELS_PER_UNIT = 40;
// Trackpad momentum can deliver a single enormous event. Without a ceiling
// one flick crosses the whole zoom range.
const MAX_UNITS_PER_EVENT = 3;

export function boundsOf(points) {
  // A loop rather than Math.min(...array): a maxed-out bundle is 50,000
  // records, and spreading that many arguments is how you get a stack
  // overflow on the one file large enough to matter.
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  let seen = 0;
  for (const point of points) {
    if (!Number.isFinite(point.x) || !Number.isFinite(point.z)) continue;
    if (point.x < minX) minX = point.x;
    if (point.x > maxX) maxX = point.x;
    if (point.z < minZ) minZ = point.z;
    if (point.z > maxZ) maxZ = point.z;
    seen += 1;
  }
  return seen ? { minX, maxX, minZ, maxZ } : null;
}

export function viewForBounds(bounds, width, height, padding = 32, baseScale = null) {
  if (!bounds) return { centerX: 0, centerZ: 0, scale: 1, baseScale: baseScale ?? 1 };
  const scale = Math.min(
    Math.max(1, width - padding * 2) / (bounds.maxX - bounds.minX || 1),
    Math.max(1, height - padding * 2) / (bounds.maxZ - bounds.minZ || 1),
  );
  return {
    centerX: (bounds.minX + bounds.maxX) / 2,
    centerZ: (bounds.minZ + bounds.maxZ) / 2,
    scale,
    baseScale: baseScale ?? scale,
  };
}

export function createView(edges, width, height, padding = 32) {
  if (!edges.length) return { centerX: 0, centerZ: 0, scale: 1, baseScale: 1 };
  return viewForBounds(boundsOf(edges), width, height, padding);
}

export function clampScale(view, scale) {
  const base = view.baseScale || view.scale || 1;
  return Math.min(Math.max(scale, base * MIN_ZOOM), base * MAX_ZOOM);
}

/** How many notches of zoom one wheel event asks for, whatever it measured in. */
export function wheelZoomUnits(event, viewportHeight = 800) {
  let pixels = event.deltaY;
  if (!Number.isFinite(pixels)) return 0;
  const mode = event.deltaMode ?? 0;
  if (mode === 1) pixels *= WHEEL_LINE_PX;
  else if (mode === 2) pixels *= viewportHeight;
  const perUnit = event.ctrlKey ? PINCH_PIXELS_PER_UNIT : WHEEL_PIXELS_PER_UNIT;
  // Negated so that one unit means one notch *in*, whichever way the wheel
  // reports it. Every caller — wheel, buttons, keys — then speaks the same
  // sign, and the + button cannot end up zooming out.
  const units = -pixels / perUnit;
  return Math.max(-MAX_UNITS_PER_EVENT, Math.min(MAX_UNITS_PER_EVENT, units));
}

/** Positive units zoom in, one notch at a time: exactly 1.25× each. */
export function zoomFactor(units) {
  return ZOOM_PER_UNIT ** units;
}

/** Zoom about a screen point, keeping the metre under it exactly where it is. */
export function zoomView(view, anchor, factor, width, height) {
  const world = screenToWorld(anchor, view, width, height);
  const scale = clampScale(view, view.scale * factor);
  return {
    ...view,
    scale,
    centerX: world.x - (anchor.x - width / 2) / scale,
    centerZ: world.z - (anchor.y - height / 2) / scale,
  };
}

export function panView(view, dxScreen, dyScreen) {
  return {
    ...view,
    centerX: view.centerX - dxScreen / view.scale,
    centerZ: view.centerZ - dyScreen / view.scale,
  };
}

/**
 * Keep the circuit reachable. Panning is otherwise unbounded, and a track
 * dragged off the edge of a black canvas looks exactly like a track that
 * failed to load — the reason "where did it go" is the second thing anyone
 * asks about this editor.
 */
export function clampView(view, bounds, width, height, keepPx = 80) {
  if (!bounds) return view;
  const halfW = width / 2 / view.scale;
  const halfZ = height / 2 / view.scale;
  const slackX = Math.max(0, halfW - keepPx / view.scale);
  const slackZ = Math.max(0, halfZ - keepPx / view.scale);
  return {
    ...view,
    centerX: Math.min(Math.max(view.centerX, bounds.minX - slackX), bounds.maxX + slackX),
    centerZ: Math.min(Math.max(view.centerZ, bounds.minZ - slackZ), bounds.maxZ + slackZ),
  };
}

/** The longest round number of metres that fits in `maxPixels` on screen. */
export function scaleBar(view, maxPixels = 140) {
  let best = { metres: 0.01, pixels: 0.01 * view.scale };
  for (let exponent = -2; exponent <= 5; exponent += 1) {
    for (const step of [1, 2, 5]) {
      const metres = Number((step * 10 ** exponent).toPrecision(2));
      const pixels = metres * view.scale;
      if (pixels <= maxPixels) best = { metres, pixels };
    }
  }
  const label = best.metres >= 1000
    ? `${best.metres / 1000} km`
    : `${best.metres} m`;
  return { ...best, label };
}

export function worldToScreen(point, view, width, height) {
  return {
    x: width / 2 + (point.x - view.centerX) * view.scale,
    // Match the logger's map convention: game z increases toward screen-bottom.
    y: height / 2 + (point.z - view.centerZ) * view.scale,
  };
}

export function screenToWorld(point, view, width, height) {
  return {
    x: view.centerX + (point.x - width / 2) / view.scale,
    z: view.centerZ + (point.y - height / 2) / view.scale,
  };
}

export function edgeVisible(edge, filters) {
  return filters.sides.has(edge.side) && filters.kinds.has(edge.kind);
}

export function nearestVisibleEdge(edges, filters, view, width, height, point, maxDistance = 10) {
  let bestIndex = -1;
  let bestSquared = maxDistance * maxDistance;
  edges.forEach((edge, index) => {
    if (!edgeVisible(edge, filters)) return;
    const screen = worldToScreen(edge, view, width, height);
    const squared = (screen.x - point.x) ** 2 + (screen.y - point.y) ** 2;
    if (squared <= bestSquared) {
      bestSquared = squared;
      bestIndex = index;
    }
  });
  return bestIndex;
}

/** Ray-crossing test, in screen space so a lasso means what it looked like. */
export function pointInPolygon(point, polygon) {
  if (!Array.isArray(polygon) || polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i], b = polygon[j];
    const straddles = (a.y > point.y) !== (b.y > point.y);
    if (!straddles) continue;
    const crossing = a.x + ((point.y - a.y) / (b.y - a.y)) * (b.x - a.x);
    if (point.x < crossing) inside = !inside;
  }
  return inside;
}

export function edgesInPolygon(edges, filters, view, width, height, polygon) {
  const found = [];
  if (!Array.isArray(polygon) || polygon.length < 3) return found;
  const box = boundsOf(polygon.map((point) => ({ x: point.x, z: point.y })));
  edges.forEach((edge, index) => {
    if (!edgeVisible(edge, filters)) return;
    const screen = worldToScreen(edge, view, width, height);
    // Cheap rejection first: a lasso is usually far smaller than the circuit.
    if (screen.x < box.minX || screen.x > box.maxX || screen.y < box.minZ || screen.y > box.maxZ) return;
    if (pointInPolygon(screen, polygon)) found.push(index);
  });
  return found;
}

export function edgesWithinRadius(edges, filters, view, width, height, point, radius) {
  const found = [];
  const limit = radius * radius;
  edges.forEach((edge, index) => {
    if (!edgeVisible(edge, filters)) return;
    const screen = worldToScreen(edge, view, width, height);
    if ((screen.x - point.x) ** 2 + (screen.y - point.y) ** 2 <= limit) found.push(index);
  });
  return found;
}

// ---------------------------------------------------------------------------
// Drawing
//
// Everything below turns a path the user drew into border records. That is a
// different kind of thing from everything else in a bundle: an edge record is
// normally evidence that somebody drove past that metre, and a drawn one is
// somebody's opinion about where the road is. The format has nowhere to say
// so, and inventing a field the app does not read would only hide the problem
// in a place nothing checks.
//
// What it does have is per-source vote counting, so drawn points are filed
// under a source of their own — `drawn-` and eight hex digits, which no
// installation id looks like. A merge then treats them as one contributor's
// view rather than folding them into anybody's laps, and a reviewer reading
// the diff can see at a glance which metres were driven and which were drawn.
// ---------------------------------------------------------------------------

export const DRAWN_SOURCE_PREFIX = "drawn-";

const round3 = (value) => Number(value.toFixed(3));
const round5 = (value) => Number(value.toFixed(5));

function randomHex(length) {
  const bytes = new Uint8Array(Math.ceil(length / 2));
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, length);
}

/**
 * The source id drawn points belong to in this document — an existing one if
 * this bundle has been drawn on before, so a second editing session adds
 * metres to that contributor rather than inventing another one.
 */
export function drawnSourceId(document, make = () => DRAWN_SOURCE_PREFIX + randomHex(8)) {
  const existing = Object.keys(document?.meta?.source_runs || {})
    .filter((source) => source.startsWith(DRAWN_SOURCE_PREFIX))
    .sort();
  return existing[0] || make();
}

/** The run ordinal drawn points cite: an existing source keeps its count. */
export function drawnRun(document, source) {
  const runs = document?.meta?.source_runs || {};
  return Math.max(1, Number.isInteger(runs[source]) ? runs[source] : 0);
}

/**
 * A centripetal-ish Catmull-Rom spline through the anchors, so a curve passes
 * through the points that were clicked instead of near them. Endpoints are
 * duplicated rather than extrapolated: a drawn border should not overshoot
 * past where somebody stopped drawing it.
 */
export function catmullRomPath(anchors, samplesPerSegment = 16) {
  const points = anchors.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.z));
  if (points.length < 3) return points.map((point) => ({ x: point.x, z: point.z }));
  const samples = Math.max(2, Math.round(samplesPerSegment));
  const at = (index) => points[Math.min(Math.max(index, 0), points.length - 1)];
  const path = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = at(i - 1), p1 = at(i), p2 = at(i + 1), p3 = at(i + 2);
    for (let step = 0; step < samples; step += 1) {
      const t = step / samples;
      const t2 = t * t;
      const t3 = t2 * t;
      path.push({
        x: 0.5 * ((2 * p1.x) + (-p0.x + p2.x) * t
          + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2
          + (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3),
        z: 0.5 * ((2 * p1.z) + (-p0.z + p2.z) * t
          + (2 * p0.z - 5 * p1.z + 4 * p2.z - p3.z) * t2
          + (-p0.z + 3 * p1.z - 3 * p2.z + p3.z) * t3),
      });
    }
  }
  path.push({ x: points[points.length - 1].x, z: points[points.length - 1].z });
  return path;
}

/**
 * Walk a polyline emitting a point every `spacing` metres, with the unit
 * tangent at each. Spacing carries across segment joins, so a path made of
 * many short segments does not bunch points up at every corner.
 */
export function resamplePath(path, spacing = GRID_M) {
  const step = spacing > 0 ? spacing : GRID_M;
  const points = [];
  for (const point of path || []) {
    if (!Number.isFinite(point?.x) || !Number.isFinite(point?.z)) continue;
    const last = points[points.length - 1];
    if (!last || Math.hypot(point.x - last.x, point.z - last.z) > 1e-9) {
      points.push({ x: point.x, z: point.z });
    }
  }
  if (!points.length) return [];
  if (points.length === 1) return [{ ...points[0], hx: 1, hz: 0 }];

  const out = [];
  let offset = 0;  // distance into the next segment where the next sample falls
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i], b = points[i + 1];
    const dx = b.x - a.x, dz = b.z - a.z;
    const length = Math.hypot(dx, dz);
    const hx = dx / length, hz = dz / length;
    for (let d = offset; d < length; d += step) {
      out.push({ x: a.x + hx * d, z: a.z + hz * d, hx, hz });
    }
    offset = Math.max(0, Math.ceil((length - offset) / step) * step + offset - length);
  }
  const last = points[points.length - 1];
  const prev = points[points.length - 2];
  const dx = last.x - prev.x, dz = last.z - prev.z;
  const length = Math.hypot(dx, dz) || 1;
  out.push({ x: last.x, z: last.z, hx: dx / length, hz: dz / length });
  return out;
}

/**
 * Border records for a drawn path.
 *
 * Anything landing on a metre the bundle already holds is dropped rather than
 * replacing it: a surveyed metre is a measurement and a drawn one is not, so
 * drawing over the road you already have must never overwrite it. Elevation
 * and track width stay null, because nobody drew those.
 */
export function pathToEdges(path, {
  side = "L",
  kind = "edge",
  source,
  run = 1,
  existing = [],
  spacing = GRID_M,
  limit = MAX_POINTS,
} = {}) {
  if (!MANUAL_KINDS.includes(kind)) fail("Drawn points must be edge, wall, or runoff");
  if (!SIDES.includes(side)) fail("Drawn points must be on the L or R side");
  if (typeof source !== "string" || !source) fail("Drawn points need a source id");
  if (!integer(run) || run < 1) fail("Drawn points need a run ordinal of at least 1");

  const taken = new Set();
  for (const edge of existing) taken.add(`${roundGrid(edge.x)},${roundGrid(edge.z)},${edge.side}`);
  const room = Math.max(0, limit - existing.length);

  const edges = [];
  let skipped = 0;
  for (const sample of resamplePath(path, spacing)) {
    if (edges.length >= room) break;
    // Round first, then key: the stored coordinate is what the repository and
    // the app will key on, and 3 dp is occasionally enough to cross a cell.
    const x = round3(sample.x);
    const z = round3(sample.z);
    const key = `${roundGrid(x)},${roundGrid(z)},${side}`;
    if (taken.has(key)) {
      skipped += 1;
      continue;
    }
    taken.add(key);
    edges.push({
      x,
      z,
      y: null,
      hx: round5(sample.hx),
      hz: round5(sample.hz),
      side,
      kind,
      votes: { [kind]: { [source]: [1, run] } },
      run,
      tw: null,
    });
  }
  return { edges, skipped, truncated: edges.length >= room };
}

// ---------------------------------------------------------------------------
// Connectors
//
// A surveyed border is not one continuous line: it has gaps wherever nobody
// drove, and bridging one is the commonest repair there is. Two clicks — a
// record either side of the gap — should be enough.
//
// A straight chord between them is almost never right, and the bundle already
// holds what is needed to do better: every edge record carries `hx`/`hz`, the
// unit heading of the car when that metre was seen. A cubic Hermite using
// those headings as its end tangents leaves the first record along the road
// and arrives at the second along the road, so the join curves the way the
// circuit curves instead of cutting the corner.
// ---------------------------------------------------------------------------

/** How far the ends are pinned when pushing: the first and last 12% cannot move. */
const PINNED_END = 0.12;

function endTangent(edge, direction, chord, tension) {
  let hx = edge.hx;
  let hz = edge.hz;
  const along = hx * direction.x + hz * direction.z;
  // The stored heading is the direction of travel, and a gap can be picked
  // from either end, so point it at the other record rather than away.
  if (along < 0) {
    hx = -hx;
    hz = -hz;
  }
  // A heading nearly perpendicular to the gap says nothing useful about how to
  // leave it, and using it anyway throws the curve into a loop. Fall back to
  // the straight line, which is at least defensible.
  if (Math.abs(along) < 0.2) {
    hx = direction.x;
    hz = direction.z;
  }
  const scale = chord * tension;
  return { x: hx * scale, z: hz * scale };
}

/**
 * The path bridging two border records.
 *
 * `tension` 0 is the straight line between them; 1 follows their headings out
 * as far as the gap is wide. The samples are not evenly spaced — resamplePath
 * fixes that on the way to records.
 */
export function connectorPath(a, b, { tension = 0.5, samples = 64 } = {}) {
  if (!a || !b) return [];
  const chord = Math.hypot(b.x - a.x, b.z - a.z);
  if (!(chord > 0)) return [{ x: a.x, z: a.z }];
  const direction = { x: (b.x - a.x) / chord, z: (b.z - a.z) / chord };
  const held = Math.min(Math.max(tension, 0), 1);
  const m0 = endTangent(a, direction, chord, held);
  const m1 = endTangent(b, direction, chord, held);
  const steps = Math.max(2, Math.round(samples));
  const path = [];
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    const t2 = t * t;
    const t3 = t2 * t;
    const h00 = 2 * t3 - 3 * t2 + 1;
    const h10 = t3 - 2 * t2 + t;
    const h01 = -2 * t3 + 3 * t2;
    const h11 = t3 - t2;
    path.push({
      x: h00 * a.x + h10 * m0.x + h01 * b.x + h11 * m1.x,
      z: h00 * a.z + h10 * m0.z + h01 * b.z + h11 * m1.z,
    });
  }
  return path;
}

/**
 * Push a path around under the cursor, like a smudge brush.
 *
 * A Hermite curve is a guess about a stretch of road nobody drove; being able
 * to shove it into shape is what makes it usable rather than merely plausible.
 * The falloff is a raised cosine, and both ends are pinned — they sit on real
 * surveyed records, and moving those would break the join the connector exists
 * to make.
 */
export function smudgePath(path, at, delta, radius) {
  const reach = Math.max(1e-6, radius);
  const last = path.length - 1;
  if (last < 1) return path.map((point) => ({ ...point }));
  return path.map((point, index) => {
    const distance = Math.hypot(point.x - at.x, point.z - at.z);
    if (distance >= reach) return { ...point };
    const t = index / last;
    const near = 0.5 * (1 + Math.cos(Math.PI * (distance / reach)));
    const ends = Math.min(1, t / PINNED_END) * Math.min(1, (1 - t) / PINNED_END);
    const weight = near * ends;
    return { x: point.x + delta.x * weight, z: point.z + delta.z * weight };
  });
}

/** How long a path is on the ground, for saying what a gap actually measures. */
export function pathLength(path) {
  let total = 0;
  for (let i = 1; i < path.length; i += 1) {
    total += Math.hypot(path[i].x - path[i - 1].x, path[i].z - path[i - 1].z);
  }
  return total;
}
