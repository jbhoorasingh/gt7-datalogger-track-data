const FORMAT = "gt7-datalogger-track-bundle";
const VERSION = 4;
export const KINDS = ["wall", "runoff", "edge", "auto", "straddle"];
export const MANUAL_KINDS = ["wall", "runoff", "edge"];
const AUTO_KINDS = ["auto", "straddle"];
const SIDES = ["L", "R"];

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

  _apply(operation, forward) {
    if (operation.type === "delete") {
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

export function createView(edges, width, height, padding = 32) {
  if (!edges.length) return { centerX: 0, centerZ: 0, scale: 1, baseScale: 1 };
  const xs = edges.map((edge) => edge.x);
  const zs = edges.map((edge) => edge.z);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minZ = Math.min(...zs), maxZ = Math.max(...zs);
  const scale = Math.min(
    Math.max(1, width - padding * 2) / (maxX - minX || 1),
    Math.max(1, height - padding * 2) / (maxZ - minZ || 1),
  );
  return { centerX: (minX + maxX) / 2, centerZ: (minZ + maxZ) / 2, scale, baseScale: scale };
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
