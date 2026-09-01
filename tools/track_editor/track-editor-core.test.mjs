import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  BundleEditorModel,
  MAX_ZOOM,
  MIN_ZOOM,
  boundsOf,
  catmullRomPath,
  clampView,
  connectorPath,
  correctedFilename,
  createView,
  drawnRun,
  drawnSourceId,
  edgesInPolygon,
  edgesWithinRadius,
  nearestVisibleEdge,
  parseBundle,
  pathLength,
  pathToEdges,
  resamplePath,
  roundGrid,
  scaleBar,
  screenToWorld,
  smudgePath,
  validateBundle,
  wheelZoomUnits,
  worldToScreen,
  zoomFactor,
  zoomView,
} from "./track-editor-core.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TRACKS = path.resolve(HERE, "../../tracks");

function randomRepositoryTrack() {
  const files = fs.readdirSync(TRACKS).filter((name) => name.endsWith(".json"));
  assert.ok(files.length > 0, "the repository must contain at least one track bundle");
  return path.join(TRACKS, files[Math.floor(Math.random() * files.length)]);
}


function edge(x, z, side = "L", kind = "edge", votes = null) {
  return {
    x, z, y: 1.2, hx: 1, hz: 0, side, kind,
    votes: votes || { [kind]: { source: [1, 1] } },
    run: 1, tw: 1.5,
  };
}

function bundle(edges = [edge(0, 0), edge(2, 0, "R", "wall")]) {
  return {
    format: "gt7-datalogger-track-bundle",
    version: 4,
    meta: {
      track: "Test Course",
      runs: 1,
      source_runs: { source: 1 },
      updated_at: "2026-01-01T00:00:00Z",
      official: null,
      preserved: "metadata",
    },
    edges,
    finish_crossings: [{ x: 1, z: 0, hx: 1, hz: 0, lap: 2 }],
    corners: [],
    sections: [],
    extension: { preserved: true },
  };
}

test("parseBundle explains invalid JSON and unsupported versions", () => {
  assert.throws(() => parseBundle("{"), /Could not parse JSON/);
  const old = bundle();
  old.version = 3;
  assert.throws(() => validateBundle(old), /Only bundle format v4/);
});

test("validation rejects invalid votes and duplicate metre-side identities", () => {
  const badVotes = bundle();
  badVotes.edges[0].votes.edge.source = [0, 1];
  assert.throws(() => validateBundle(badVotes), /must be \[count, last_run\]/);

  const duplicate = bundle([edge(0.1, 0.1), edge(0.2, 0.2)]);
  assert.throws(() => validateBundle(duplicate), /repeats the metre/);
});

test("roundGrid matches Python half-even behavior", () => {
  assert.equal(roundGrid(0.5), 0);
  assert.equal(roundGrid(1.5), 2);
  assert.equal(roundGrid(-0.5), 0);
  assert.equal(roundGrid(-1.5), -2);
});

test("deletion is reversible and redoable", () => {
  const model = new BundleEditorModel(bundle());
  model.select([0]);
  assert.equal(model.deleteSelected(), 1);
  assert.equal(model.document.edges.length, 1);
  assert.equal(model.document.edges[0].side, "R");
  assert.equal(model.selected.size, 0);

  assert.equal(model.undo(), true);
  assert.equal(model.document.edges.length, 2);
  assert.equal(model.document.edges[0].side, "L");
  assert.equal(model.redo(), true);
  assert.equal(model.document.edges.length, 1);
});

test("relabeling moves and safely merges source vote snapshots", () => {
  const document = bundle([
    edge(0, 0, "L", "wall", {
      wall: { source: [1, 1] },
      auto: { source: [3, 1] },
    }),
  ]);
  const model = new BundleEditorModel(document);
  model.select([0]);
  assert.equal(model.relabelSelected("runoff"), 1);
  assert.equal(model.document.edges[0].kind, "runoff");
  assert.deepEqual(model.document.edges[0].votes, { runoff: { source: [3, 1] } });

  model.undo();
  assert.deepEqual(model.document.edges[0].votes, document.edges[0].votes);
  model.redo();
  assert.equal(model.document.edges[0].kind, "runoff");
});

test("reset restores the input and export preserves unknown fields", () => {
  const model = new BundleEditorModel(bundle(), "test-course.json");
  model.select([0]);
  model.deleteSelected();
  model.reset();
  assert.equal(model.document.edges.length, 2);
  assert.equal(model.history.length, 0);

  const when = new Date("2026-08-19T22:00:00.000Z");
  const output = model.exportDocument(when);
  assert.equal(output.meta.updated_at, when.toISOString());
  assert.equal(output.meta.preserved, "metadata");
  assert.deepEqual(output.extension, { preserved: true });
  assert.equal(correctedFilename("test-course.json"), "test-course.corrected.json");
});

test("a random repository track loads and exports as compact valid JSON", (context) => {
  const filename = randomRepositoryTrack();
  const source = fs.readFileSync(filename, "utf8");
  const document = parseBundle(source);
  const model = new BundleEditorModel(document, path.basename(filename));
  const serialized = JSON.stringify(model.exportDocument(new Date("2026-08-20T00:00:00.000Z")));
  const exported = parseBundle(serialized);

  context.diagnostic(`tested ${path.basename(filename)} (${exported.edges.length.toLocaleString()} points)`);
  assert.equal(serialized.includes("\n"), false);
  assert.equal(exported.edges.length, document.edges.length);
  // JSON.stringify normalizes the IEEE-754 value -0 to 0. Compare against the
  // source after the same JSON round trip so that harmless sign bit is ignored.
  assert.deepEqual(exported.edges, JSON.parse(JSON.stringify(document.edges)));
  assert.equal(correctedFilename(path.basename(filename)).endsWith(".corrected.json"), true);
});

test("screen transforms round-trip and selection honors filters", () => {
  const edges = [edge(0, 0, "L"), edge(10, 0, "R")];
  const view = createView(edges, 200, 100, 10);
  const screen = worldToScreen(edges[0], view, 200, 100);
  const rightScreen = worldToScreen(edges[1], view, 200, 100);
  const lowerScreen = worldToScreen({ x: edges[0].x, z: edges[0].z + 1 }, view, 200, 100);
  assert.ok(rightScreen.x > screen.x, "increasing game x must move screen-right");
  assert.ok(lowerScreen.y > screen.y, "increasing game z must move screen-down, matching the logger");
  const world = screenToWorld(screen, view, 200, 100);
  assert.ok(Math.abs(world.x - edges[0].x) < 1e-9);
  assert.ok(Math.abs(world.z - edges[0].z) < 1e-9);

  const filters = { sides: new Set(["L"]), kinds: new Set(["edge"]) };
  assert.equal(nearestVisibleEdge(edges, filters, view, 200, 100, screen, 5), 0);
  assert.equal(nearestVisibleEdge(edges, filters, view, 200, 100, rightScreen, 5), -1);
  assert.deepEqual(edgesWithinRadius(edges, filters, view, 200, 100, screen, 6), [0]);
});

test("wheel zoom is measured in notches, whatever the browser reported", () => {
  // Chrome-style pixels, Firefox-style lines and a page scroll all describe
  // roughly one notch, and all three must zoom by roughly the same amount.
  // Scrolling down is one notch out, so all three are -1-ish.
  const pixels = wheelZoomUnits({ deltaY: 120, deltaMode: 0 }, 800);
  const lines = wheelZoomUnits({ deltaY: 3, deltaMode: 1 }, 800);
  const pages = wheelZoomUnits({ deltaY: 1, deltaMode: 2 }, 120);

  assert.equal(pixels, -1);
  assert.ok(lines < -0.3 && lines > -1, `lines gave ${lines}`);
  assert.equal(pages, -1);
  assert.ok(wheelZoomUnits({ deltaY: -120, deltaMode: 0 }, 800) > 0, "scrolling up zooms in");

  // A trackpad flick can deliver one enormous event; it must not cross the
  // whole zoom range in one go.
  assert.equal(wheelZoomUnits({ deltaY: 99999, deltaMode: 0 }, 800), -3);
  assert.equal(wheelZoomUnits({ deltaY: -99999, deltaMode: 0 }, 800), 3);
  // Pinch-to-zoom arrives as ctrl+wheel with far smaller deltas.
  assert.ok(Math.abs(wheelZoomUnits({ deltaY: 40, deltaMode: 0, ctrlKey: true }, 800))
    > Math.abs(wheelZoomUnits({ deltaY: 40, deltaMode: 0 }, 800)));
  assert.equal(wheelZoomUnits({ deltaY: Number.NaN, deltaMode: 0 }, 800), 0);
});

test("zooming holds the metre under the cursor exactly still", () => {
  const view = createView([edge(0, 0), edge(200, 120)], 800, 600);
  const anchor = { x: 610, y: 145 };
  const before = screenToWorld(anchor, view, 800, 600);

  let after = view;
  for (const units of [1, 1, -1, 2, -3, 0.4]) {
    after = zoomView(after, anchor, zoomFactor(units), 800, 600);
    const world = screenToWorld(anchor, after, 800, 600);
    assert.ok(Math.abs(world.x - before.x) < 1e-9, `x drifted to ${world.x}`);
    assert.ok(Math.abs(world.z - before.z) < 1e-9, `z drifted to ${world.z}`);
  }
  assert.ok(after.scale !== view.scale);
});

test("zoom stays inside its limits and one notch is 1.25x", () => {
  const view = createView([edge(0, 0), edge(200, 120)], 800, 600);
  const anchor = { x: 400, y: 300 };

  const inOne = zoomView(view, anchor, zoomFactor(1), 800, 600);
  assert.ok(Math.abs(inOne.scale / view.scale - 1.25) < 1e-9);

  let far = view;
  for (let i = 0; i < 200; i += 1) far = zoomView(far, anchor, zoomFactor(1), 800, 600);
  assert.equal(far.scale, view.baseScale * MAX_ZOOM);

  let near = view;
  for (let i = 0; i < 200; i += 1) near = zoomView(near, anchor, zoomFactor(-1), 800, 600);
  assert.equal(near.scale, view.baseScale * MIN_ZOOM);
});

test("panning cannot lose the circuit off the edge of the canvas", () => {
  const edges = [edge(0, 0), edge(200, 120)];
  const bounds = boundsOf(edges);
  const view = { ...createView(edges, 800, 600), scale: 40, baseScale: 4 };

  const runaway = clampView({ ...view, centerX: 1e6, centerZ: -1e6 }, bounds, 800, 600);

  // At most half a screen of empty space past the edge, never a runaway.
  assert.ok(runaway.centerX <= bounds.maxX + 400 / view.scale);
  assert.ok(runaway.centerZ >= bounds.minZ - 300 / view.scale);
  // Any real point can still be centred; it is only empty space that is fenced.
  const centred = clampView({ ...view, centerX: 200, centerZ: 120 }, bounds, 800, 600);
  assert.equal(centred.centerX, 200);
  assert.equal(centred.centerZ, 120);
});

test("the scale bar is a round number of metres that fits", () => {
  for (const scale of [0.3, 1, 4.7, 22, 180]) {
    const bar = scaleBar({ scale }, 140);
    assert.ok(bar.pixels <= 140, `${bar.metres} m was ${bar.pixels} px`);
    assert.ok(bar.pixels > 140 / 5, `${bar.metres} m wasted the bar at ${bar.pixels} px`);
    assert.match(bar.label, /^[\d.]+ (m|km)$/);
  }
});

test("a lasso selects what it encircled and nothing else", () => {
  const edges = [edge(0, 0), edge(10, 0), edge(100, 100)];
  const view = createView(edges, 400, 400);
  const filters = { sides: new Set(["L", "R"]), kinds: new Set(["edge", "wall"]) };
  const around = (point, radius) => [
    { x: point.x - radius, y: point.y - radius },
    { x: point.x + radius, y: point.y - radius },
    { x: point.x + radius, y: point.y + radius },
    { x: point.x - radius, y: point.y + radius },
  ];

  const first = worldToScreen(edges[0], view, 400, 400);
  assert.deepEqual(edgesInPolygon(edges, filters, view, 400, 400, around(first, 4)), [0]);
  assert.deepEqual(edgesInPolygon(edges, filters, view, 400, 400, around(first, 1e4)), [0, 1, 2]);
  assert.deepEqual(edgesInPolygon(edges, filters, view, 400, 400, []), []);
});

test("resampling walks a path at a fixed spacing with unit tangents", () => {
  const straight = resamplePath([{ x: 0, z: 0 }, { x: 10, z: 0 }], 2);

  assert.deepEqual(straight.map((point) => point.x), [0, 2, 4, 6, 8, 10]);
  for (const point of straight) {
    assert.equal(point.z, 0);
    assert.ok(Math.abs(Math.hypot(point.hx, point.hz) - 1) < 1e-9);
  }

  // Spacing carries over a join rather than restarting at every corner.
  const cornered = resamplePath([{ x: 0, z: 0 }, { x: 3, z: 0 }, { x: 3, z: 3 }], 2);
  const gaps = cornered.slice(1).map((point, index) =>
    Math.hypot(point.x - cornered[index].x, point.z - cornered[index].z));
  for (const gap of gaps) assert.ok(gap <= 2 + 1e-9, `a ${gap} m gap appeared`);

  assert.deepEqual(resamplePath([], 1), []);
  assert.deepEqual(resamplePath([{ x: 1, z: 2 }], 1), [{ x: 1, z: 2, hx: 1, hz: 0 }]);
  // A duplicated click must not become a zero-length segment and a NaN tangent.
  for (const point of resamplePath([{ x: 0, z: 0 }, { x: 0, z: 0 }, { x: 4, z: 0 }], 1)) {
    assert.ok(Number.isFinite(point.hx) && Number.isFinite(point.hz));
  }
});

test("a curve passes through the points that were clicked", () => {
  const anchors = [{ x: 0, z: 0 }, { x: 10, z: 8 }, { x: 20, z: 0 }, { x: 30, z: 8 }];
  const path = catmullRomPath(anchors, 12);

  for (const anchor of anchors) {
    const nearest = Math.min(...path.map((point) => Math.hypot(point.x - anchor.x, point.z - anchor.z)));
    assert.ok(nearest < 1e-9, `the curve missed ${JSON.stringify(anchor)} by ${nearest}`);
  }
  // Two points cannot bend, and one point is not a path.
  assert.equal(catmullRomPath([{ x: 0, z: 0 }, { x: 5, z: 5 }], 12).length, 2);
});

test("drawn points are valid records filed under a source of their own", () => {
  const document = bundle();
  const model = new BundleEditorModel(document);
  const source = drawnSourceId(model.document);
  assert.match(source, /^drawn-[0-9a-f]{8}$/);

  const { edges } = pathToEdges([{ x: 100, z: 100 }, { x: 140, z: 100 }], {
    side: "R", kind: "wall", source, run: drawnRun(model.document, source),
    existing: model.document.edges,
  });

  assert.equal(edges.length, 41);
  assert.equal(model.addDrawn(edges, source, 1), 41);
  assert.equal(model.document.meta.source_runs[source], 1);
  assert.equal(model.document.meta.runs, 2, "the drawn source is counted, not hidden");
  assert.deepEqual(model.drawnSources(), [{ source, points: 41 }]);
  // exportDocument revalidates, so this asserts the whole document is legal.
  const exported = model.exportDocument();
  assert.equal(exported.edges.length, document.edges.length + 41);
  for (const drawn of exported.edges.filter((item) => item.votes.wall?.[source])) {
    assert.equal(drawn.y, null);
    assert.equal(drawn.tw, null);
    assert.equal(drawn.kind, "wall");
    assert.equal(drawn.side, "R");
  }
});

test("drawing never overwrites a metre the bundle already surveyed", () => {
  const model = new BundleEditorModel(bundle([edge(0, 0), edge(1, 0), edge(2, 0)]));
  const source = drawnSourceId(model.document);

  const result = pathToEdges([{ x: 0, z: 0 }, { x: 5, z: 0 }], {
    side: "L", kind: "edge", source, run: 1, existing: model.document.edges,
  });

  assert.equal(result.skipped, 3, "the three surveyed metres were left alone");
  assert.deepEqual(result.edges.map((item) => item.x), [3, 4, 5]);
  assert.equal(model.addDrawn(result.edges, source, 1), 3);
  model.exportDocument();  // throws if two records claim one metre
});

test("a second drawing session reuses the source rather than inventing one", () => {
  const model = new BundleEditorModel(bundle());
  const draw = (from, to) => {
    // What the editor does: ask the document, so an id it already holds wins.
    const source = drawnSourceId(model.document);
    const { edges } = pathToEdges([from, to], {
      side: "R", kind: "edge", source, run: drawnRun(model.document, source),
      existing: model.document.edges,
    });
    model.addDrawn(edges, source, drawnRun(model.document, source));
    return source;
  };

  const first = draw({ x: 100, z: 0 }, { x: 105, z: 0 });
  const second = draw({ x: 200, z: 0 }, { x: 205, z: 0 });

  assert.equal(second, first);
  assert.equal(Object.keys(model.document.meta.source_runs).length, 2);
  assert.equal(model.document.meta.runs, 2);
});

test("undo takes back drawn points and the run count they added", () => {
  const model = new BundleEditorModel(bundle());
  const before = JSON.parse(JSON.stringify(model.document));
  const source = drawnSourceId(model.document);
  const { edges } = pathToEdges([{ x: 50, z: 50 }, { x: 60, z: 50 }], {
    side: "L", kind: "edge", source, run: 1, existing: model.document.edges,
  });
  model.addDrawn(edges, source, 1);

  model.undo();
  assert.deepEqual(model.document, before);
  model.redo();
  assert.equal(model.document.edges.length, before.edges.length + edges.length);
  assert.equal(model.document.meta.runs, 2);
  model.undo();
  assert.deepEqual(model.document, before);
});

test("pathToEdges refuses what the format would not store", () => {
  const source = "drawn-abcdef01";
  const path = [{ x: 0, z: 0 }, { x: 5, z: 0 }];
  assert.throws(() => pathToEdges(path, { kind: "auto", source }), /edge, wall, or runoff/);
  assert.throws(() => pathToEdges(path, { side: "X", source }), /L or R/);
  assert.throws(() => pathToEdges(path, { source: "" }), /source id/);
  assert.throws(() => pathToEdges(path, { source, run: 0 }), /run ordinal/);

  const capped = pathToEdges([{ x: 0, z: 0 }, { x: 100, z: 0 }], { source, limit: 4 });
  assert.equal(capped.edges.length, 4);
  assert.equal(capped.truncated, true);
});

test("editing keeps the authored work the survey did not produce", () => {
  // Corners and sections are typed by a person, and the editor has no UI for
  // them at all — which is exactly how they get dropped by a round trip that
  // rebuilds the document instead of carrying it.
  const document = bundle();
  document.corners = [{ n: 1, name: "Hairpin", direction: "L", apex: { x: 1, z: 2 } }];
  document.sections = [{ n: 1, name: "Sector 1" }];
  const model = new BundleEditorModel(document);

  const source = drawnSourceId(model.document);
  const { edges } = pathToEdges([{ x: 300, z: 300 }, { x: 310, z: 300 }], {
    side: "L", kind: "edge", source, run: 1, existing: model.document.edges,
  });
  model.addDrawn(edges, source, 1);
  model.select([0], true);
  model.relabelSelected("wall");
  const exported = model.exportDocument();

  assert.deepEqual(exported.corners, document.corners);
  assert.deepEqual(exported.sections, document.sections);
  // ...and the fields no part of this editor knows about.
  assert.deepEqual(exported.extension, { preserved: true });
  assert.equal(exported.meta.preserved, "metadata");
});

test("a connector leaves and arrives along the road, not across it", () => {
  // Two records either side of a gap, both heading east; the road bulges north
  // between them. A chord would cut the corner.
  const a = { x: 0, z: 0, hx: 1, hz: 0 };
  const b = { x: 100, z: 0, hx: 1, hz: 0 };
  const curved = connectorPath(a, b, { tension: 0.5, samples: 40 });

  assert.equal(curved[0].x, 0);
  assert.equal(curved[curved.length - 1].x, 100);
  // Leaving A the path must run east, matching the heading.
  const step = { x: curved[1].x - curved[0].x, z: curved[1].z - curved[0].z };
  assert.ok(step.x > 0 && Math.abs(step.z) < 1e-9, `left A as ${JSON.stringify(step)}`);

  // Headings that turn: the curve must bow the way they point. (Square-across
  // headings are a different case — see the fallback test below.)
  const r = Math.SQRT1_2;
  const north = connectorPath(
    { x: 0, z: 0, hx: r, hz: -r }, { x: 100, z: 0, hx: r, hz: r },
    { tension: 0.6, samples: 40 },
  );
  const mid = north[Math.floor(north.length / 2)];
  assert.ok(mid.z < -5, `the curve did not follow the headings (mid z ${mid.z})`);
});

test("a connector reads the heading from whichever end you picked first", () => {
  // Same gap, records picked in the other order: the stored heading points
  // away from the other end, and using it raw would loop the curve backwards.
  const forward = connectorPath({ x: 0, z: 0, hx: 1, hz: 0 }, { x: 60, z: 0, hx: 1, hz: 0 }, { tension: 0.7 });
  const backward = connectorPath({ x: 60, z: 0, hx: 1, hz: 0 }, { x: 0, z: 0, hx: 1, hz: 0 }, { tension: 0.7 });

  for (const path of [forward, backward]) {
    const xs = path.map((point) => point.x);
    const monotonic = xs.every((x, i) => i === 0 || (xs[1] > xs[0] ? x >= xs[i - 1] - 1e-9 : x <= xs[i - 1] + 1e-9));
    assert.ok(monotonic, "the curve doubled back on itself");
  }
});

test("tension 0 is the straight line between the two records", () => {
  const path = connectorPath({ x: 0, z: 0, hx: 0, hz: 1 }, { x: 50, z: 50, hx: 0, hz: -1 }, { tension: 0, samples: 20 });

  for (const point of path) {
    // Every sample sits on the chord z = x.
    assert.ok(Math.abs(point.z - point.x) < 1e-9, `${JSON.stringify(point)} left the chord`);
  }
});

test("a heading square across the gap falls back to the straight line", () => {
  // A record whose heading is perpendicular to the gap says nothing about how
  // to leave it; honouring it anyway throws the curve into a loop.
  const path = connectorPath({ x: 0, z: 0, hx: 0, hz: 1 }, { x: 40, z: 0, hx: 0, hz: 1 }, { tension: 1, samples: 24 });
  const xs = path.map((point) => point.x);

  assert.ok(xs.every((x, i) => i === 0 || x >= xs[i - 1] - 1e-9), "the curve looped");
  assert.ok(Math.max(...path.map((p) => Math.abs(p.z))) < 1e-6, "the curve wandered off the chord");
});

test("pushing a connector moves the middle and pins the ends", () => {
  const path = connectorPath({ x: 0, z: 0, hx: 1, hz: 0 }, { x: 100, z: 0, hx: 1, hz: 0 }, { tension: 0, samples: 40 });
  const first = path[0], last = path[path.length - 1];

  const pushed = smudgePath(path, { x: 50, z: 0 }, { x: 0, z: -20 }, 30);

  assert.deepEqual({ x: pushed[0].x, z: pushed[0].z }, { x: first.x, z: first.z });
  assert.deepEqual(
    { x: pushed[pushed.length - 1].x, z: pushed[pushed.length - 1].z },
    { x: last.x, z: last.z },
  );
  const mid = pushed[Math.floor(pushed.length / 2)];
  assert.ok(mid.z < -18, `the middle barely moved (${mid.z})`);
  // Outside the reach nothing moves at all.
  assert.ok(Math.abs(pushed[1].z) < 1e-9, "a point beyond the radius was dragged");
});

test("a pushed connector still becomes valid records", () => {
  const model = new BundleEditorModel(bundle([
    edge(0, 0, "L", "wall"), edge(60, 0, "L", "wall"),
  ]));
  const [a, b] = model.document.edges;
  const pushed = smudgePath(
    connectorPath(a, b, { tension: 0.5 }), { x: 30, z: 0 }, { x: 0, z: -8 }, 25,
  );
  const source = drawnSourceId(model.document);

  const { edges, skipped } = pathToEdges(pushed, {
    side: "L", kind: "wall", source, run: 1, existing: model.document.edges,
  });

  assert.ok(edges.length > 40, `only ${edges.length} records for a 60 m gap`);
  // Samples landing on a metre that is already spoken for are dropped — by the
  // two anchors, and by each other where the pushed curve runs steeply.
  assert.ok(skipped >= 2, `expected the anchors to be skipped, got ${skipped}`);
  const anchors = new Set(["0,0,L", "60,0,L"]);
  for (const drawn of edges) {
    assert.ok(!anchors.has(`${roundGrid(drawn.x)},${roundGrid(drawn.z)},L`),
      "a drawn record landed on one of the surveyed anchors");
  }
  model.addDrawn(edges, source, 1);
  model.exportDocument();  // throws if anything about them is not legal v4
  assert.deepEqual(model.document.edges.slice(0, 2), [a, b], "the anchors were altered");
  assert.ok(Math.round(pathLength(pushed)) > 60, "the pushed path should be longer than the chord");
});
