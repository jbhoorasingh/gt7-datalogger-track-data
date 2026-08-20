import test from "node:test";
import assert from "node:assert/strict";

import {
  BundleEditorModel,
  correctedFilename,
  createView,
  edgesWithinRadius,
  nearestVisibleEdge,
  parseBundle,
  roundGrid,
  screenToWorld,
  validateBundle,
  worldToScreen,
} from "./track-editor-core.mjs";


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
  const model = new BundleEditorModel(bundle(), "daytona-road-course.json");
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
  assert.equal(correctedFilename("daytona-road-course.json"), "daytona-road-course.corrected.json");
});

test("screen transforms round-trip and selection honors filters", () => {
  const edges = [edge(0, 0, "L"), edge(10, 0, "R")];
  const view = createView(edges, 200, 100, 10);
  const screen = worldToScreen(edges[0], view, 200, 100);
  const world = screenToWorld(screen, view, 200, 100);
  assert.ok(Math.abs(world.x - edges[0].x) < 1e-9);
  assert.ok(Math.abs(world.z - edges[0].z) < 1e-9);

  const filters = { sides: new Set(["L"]), kinds: new Set(["edge"]) };
  assert.equal(nearestVisibleEdge(edges, filters, view, 200, 100, screen, 5), 0);
  const rightScreen = worldToScreen(edges[1], view, 200, 100);
  assert.equal(nearestVisibleEdge(edges, filters, view, 200, 100, rightScreen, 5), -1);
  assert.deepEqual(edgesWithinRadius(edges, filters, view, 200, 100, screen, 6), [0]);
});
