// Visual inspection of a surveyed track: what has actually been mapped, and
// where the holes are. No build step and no dependencies — the page is served
// straight out of the repository, so anyone reviewing a contribution can look
// at it before merging.

const KIND_COLOR = {
  wall: "#ef4444",
  runoff: "#a855f7",
  edge: null, // an ordinary edge takes its side's colour
  auto: null,
  straddle: null,
};
const SIDE_COLOR = { L: "#60a5fa", R: "#f472b6" };
const APEX = "#facc15";
const FINISH = "#e5e7eb";
// A seed path is ONE recorded lap down the middle of the road. It gets its own
// colour and a single thin stroke so it cannot be mistaken for a survey: the
// borders are two coloured edges of a known width, and this knows no width at
// all. Drawing it in the border colours would claim a survey that does not
// exist.
const SEED = "#f59e0b";

const list = document.getElementById("list");
const search = document.getElementById("search");
const coverage = document.getElementById("coverage");
const detail = document.getElementById("detail");
const empty = document.getElementById("empty");
const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");

let index = null;
// official_id -> seed row. The signatures carry a thinned racing line for
// circuits nobody here has surveyed, which is the only shape those have.
let seeds = new Map();
let seedStepM = 20;
let selected = null;

const seedPath = (cfg) => seeds.get(cfg.official_id)?.path ?? null;

const fmt = (n) => n.toLocaleString();

function stat(text, tone) {
  const el = document.createElement("span");
  el.textContent = text;
  if (tone) el.className = tone;
  return el;
}

function render() {
  const q = search.value.trim().toLowerCase();
  list.innerHTML = "";
  const rows = index.configurations.filter((c) => {
    const shape = !c.bundle && seedPath(c);
    if (coverage.value === "surveyed" && !c.bundle) return false;
    if (coverage.value === "shape" && !shape) return false;
    if (coverage.value === "nothing" && (c.bundle || shape)) return false;
    if (!q) return true;
    return `${c.official_name} ${c.country}`.toLowerCase().includes(q);
  });
  for (const cfg of rows) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    const shape = !cfg.bundle && seedPath(cfg);
    button.className = cfg.bundle ? "" : shape ? "unsurveyed shape-only" : "unsurveyed";
    if (selected && selected.official_id === cfg.official_id) {
      button.setAttribute("aria-current", "true");
    }
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = cfg.official_name;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = cfg.bundle
      ? `${fmt(cfg.bundle.points)} m mapped · ${cfg.bundle.runs} run(s) · ` +
        `${cfg.bundle.corners}/${cfg.turns} corners`
      : shape
        ? `shape only · ${cfg.turns} turns · ${fmt(cfg.length_m)} m`
        : `not surveyed · ${cfg.turns} turns · ${fmt(cfg.length_m)} m`;
    button.append(name, meta);
    button.disabled = !cfg.bundle && !shape;
    button.addEventListener("click", () => select(cfg));
    li.append(button);
    list.append(li);
  }
  if (rows.length === 0) {
    const li = document.createElement("li");
    li.innerHTML = '<div style="padding:.7rem" class="dim">Nothing matches.</div>';
    list.append(li);
  }
}

async function select(cfg) {
  selected = cfg;
  render();
  empty.hidden = true;
  detail.hidden = false;
  document.getElementById("track-name").textContent = cfg.official_name;
  document.getElementById("track-official").textContent =
    `${cfg.country} · ${cfg.turns} turns · ${fmt(cfg.length_m)} m` +
    (cfg.elevation_m ? ` · ${cfg.elevation_m} m elevation` : "");

  const surveyed = Boolean(cfg.bundle);
  document.getElementById("legend-survey").hidden = !surveyed;
  document.getElementById("legend-seed").hidden = surveyed;
  document.getElementById("download-line").hidden = !surveyed;
  document.getElementById("stats").innerHTML = "";
  if (surveyed) await showBundle(cfg);
  else showSeed(cfg);
}

async function showBundle(cfg) {
  document.getElementById("download").href = `./${cfg.bundle.file}`;
  document.getElementById("hint").textContent = "loading bundle…";

  const stats = document.getElementById("stats");
  const b = cfg.bundle;
  stats.append(
    stat(`${fmt(b.points)} m of border`),
    stat(`${b.runs} run${b.runs === 1 ? "" : "s"}`),
    stat(`${b.sources} source${b.sources === 1 ? "" : "s"}`),
    // Elevation only fills in by re-driving, so a low number is a fact about
    // the data's age, not a fault in it.
    stat(`${b.elevation_pct}% elevation`, b.elevation_pct < 50 ? "warn" : "good"),
    stat(b.finish_crossings ? "finish line located" : "no finish line",
         b.finish_crossings ? "good" : "warn"),
    stat(`${b.corners}/${cfg.turns} corners labelled`,
         cfg.turns && b.corners >= cfg.turns ? "good" : null),
  );

  const doc = await (await fetch(`./${cfg.bundle.file}`)).json();
  drawBundle(doc);
  document.getElementById("hint").textContent =
    `${fmt(doc.edges.length)} border records, one per metre per side. ` +
    `Colour shows what the metre is: hand-marked walls and run-off limits ` +
    `outrank anything the surface data inferred.`;
}

function showSeed(cfg) {
  const seed = seeds.get(cfg.official_id);
  document.getElementById("stats").append(
    stat("shape only — not surveyed", "warn"),
    stat(`${fmt(seed.path.length)} points, one every ${seedStepM} m`),
    stat(seed.provenance === "survey" ? "line borrowed from a recording"
                                      : "one recorded lap"),
  );
  drawSeed(seed.path);
  // Say what is missing, not just that something is. Somebody looking at this
  // shape should not come away thinking the circuit is covered.
  document.getElementById("hint").textContent =
    "One recorded lap down the middle of the road, thinned to a point every " +
    `${seedStepM} m and kept in the order it was driven. It is enough for the ` +
    "app to recognise the circuit and tell it from its reverse, and it is not a " +
    "survey: the road's edges, its width, its walls and run-off, and every " +
    "corner name are all still unknown here.";
}

function projector(xs, zs) {
  const w = canvas.width;
  const pad = 24;
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minZ = Math.min(...zs), maxZ = Math.max(...zs);
  // One scale for both axes, or the circuit renders out of shape.
  const scale = Math.min((w - pad * 2) / (maxX - minX || 1),
                         (w - pad * 2) / (maxZ - minZ || 1));
  const ox = (w - (maxX - minX) * scale) / 2;
  const oz = (w - (maxZ - minZ) * scale) / 2;
  ctx.clearRect(0, 0, w, w);
  return [
    (x) => ox + (x - minX) * scale,
    // z is inverted, matching how the game (and the app's map) draws it.
    (z) => w - (oz + (z - minZ) * scale),
  ];
}

function drawBundle(doc) {
  const [px, pz] = projector(doc.edges.map((e) => e.x), doc.edges.map((e) => e.z));

  for (const e of doc.edges) {
    ctx.fillStyle = KIND_COLOR[e.kind] ?? SIDE_COLOR[e.side] ?? "#6b7280";
    ctx.fillRect(px(e.x) - 1, pz(e.z) - 1, 2, 2);
  }

  for (const c of doc.finish_crossings.slice(0, 1)) {
    ctx.fillStyle = FINISH;
    ctx.beginPath();
    ctx.arc(px(c.x), pz(c.z), 5, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.font = "bold 12px ui-sans-serif, system-ui, sans-serif";
  ctx.textAlign = "center";
  for (const corner of doc.corners) {
    const x = px(corner.apex.x);
    const z = pz(corner.apex.z);
    ctx.fillStyle = APEX;
    ctx.beginPath();
    ctx.arc(x, z, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#e5e7eb";
    ctx.fillText(corner.name ? `${corner.n} ${corner.name}` : corner.n, x, z - 9);
  }
}

// Arrowheads round the lap. The path's order is the thing that tells a layout
// from its reverse, so a drawing that shows the shape and hides the direction
// would leave out the half that is new.
const SEED_ARROWS = 8;

function drawSeed(path) {
  const [px, pz] = projector(path.map((p) => p[0]), path.map((p) => p[1]));

  // One thin closed stroke, never two coloured edges: this line has no width
  // and must not suggest one.
  ctx.strokeStyle = SEED;
  ctx.lineWidth = 1.5;
  ctx.lineJoin = "round";
  ctx.beginPath();
  path.forEach(([x, z], i) => {
    const [cx, cz] = [px(x), pz(z)];
    if (i === 0) ctx.moveTo(cx, cz);
    else ctx.lineTo(cx, cz);
  });
  ctx.closePath();
  ctx.stroke();

  ctx.fillStyle = SEED;
  const every = Math.max(1, Math.floor(path.length / SEED_ARROWS));
  for (let i = 0; i < path.length; i += every) {
    const [ax, az] = path[i];
    const [bx, bz] = path[(i + 1) % path.length];
    const [x, z] = [px(ax), pz(az)];
    const angle = Math.atan2(pz(bz) - z, px(bx) - x);
    ctx.save();
    ctx.translate(x, z);
    ctx.rotate(angle);
    ctx.beginPath();
    ctx.moveTo(6, 0);
    ctx.lineTo(-3, 3.5);
    ctx.lineTo(-3, -3.5);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // Where the recording started. Not a located start/finish line — the app's
  // finish detection is a survey's job — so it takes the neutral marker.
  ctx.fillStyle = FINISH;
  ctx.beginPath();
  ctx.arc(px(path[0][0]), pz(path[0][1]), 5, 0, Math.PI * 2);
  ctx.fill();
}

async function main() {
  const [indexDoc, signatures] = await Promise.all([
    (await fetch("./index.json")).json(),
    // Optional on purpose: the page is served straight out of the repository
    // and must still work for somebody who has only rebuilt the index.
    fetch("./signatures.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  index = indexDoc;
  if (signatures) {
    seeds = new Map(signatures.signatures.map((row) => [row.official_id, row]));
    seedStepM = signatures.counts.path_step_m;
  }

  const c = index.counts;
  const shapes = index.configurations.filter((x) => !x.bundle && seedPath(x)).length;
  document.getElementById("summary").textContent =
    `${c.surveyed} of ${c.configurations} configurations surveyed · ` +
    `${fmt(c.points)} m of border · ${c.corners_labelled} corners labelled` +
    (shapes ? ` · ${shapes} more with a recorded shape and no survey` : "");
  search.addEventListener("input", render);
  coverage.addEventListener("change", render);
  render();
  const first = index.configurations.find((x) => x.bundle);
  if (first) select(first);
}

main();
