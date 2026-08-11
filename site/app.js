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

const list = document.getElementById("list");
const search = document.getElementById("search");
const onlySurveyed = document.getElementById("only-surveyed");
const detail = document.getElementById("detail");
const empty = document.getElementById("empty");
const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");

let index = null;
let selected = null;

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
    if (onlySurveyed.checked && !c.bundle) return false;
    if (!q) return true;
    return `${c.official_name} ${c.country}`.toLowerCase().includes(q);
  });
  for (const cfg of rows) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.className = cfg.bundle ? "" : "unsurveyed";
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
      : `not surveyed · ${cfg.turns} turns · ${fmt(cfg.length_m)} m`;
    button.append(name, meta);
    button.disabled = !cfg.bundle;
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
  document.getElementById("download").href = `./${cfg.bundle.file}`;
  document.getElementById("hint").textContent = "loading bundle…";

  const stats = document.getElementById("stats");
  stats.innerHTML = "";
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
  draw(doc);
  document.getElementById("hint").textContent =
    `${fmt(doc.edges.length)} border records, one per metre per side. ` +
    `Colour shows what the metre is: hand-marked walls and run-off limits ` +
    `outrank anything the surface data inferred.`;
}

function draw(doc) {
  const w = canvas.width;
  const pad = 24;
  ctx.clearRect(0, 0, w, w);

  const xs = doc.edges.map((e) => e.x);
  const zs = doc.edges.map((e) => e.z);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minZ = Math.min(...zs), maxZ = Math.max(...zs);
  // One scale for both axes, or the circuit renders out of shape.
  const scale = Math.min((w - pad * 2) / (maxX - minX || 1),
                         (w - pad * 2) / (maxZ - minZ || 1));
  const ox = (w - (maxX - minX) * scale) / 2;
  const oz = (w - (maxZ - minZ) * scale) / 2;
  // z is inverted, matching how the game (and the app's map) draws it.
  const px = (x) => ox + (x - minX) * scale;
  const pz = (z) => w - (oz + (z - minZ) * scale);

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

async function main() {
  index = await (await fetch("./index.json")).json();
  const c = index.counts;
  document.getElementById("summary").textContent =
    `${c.surveyed} of ${c.configurations} configurations surveyed · ` +
    `${fmt(c.points)} m of border · ${c.corners_labelled} corners labelled`;
  search.addEventListener("input", render);
  onlySurveyed.addEventListener("change", render);
  render();
  const first = index.configurations.find((x) => x.bundle);
  if (first) select(first);
}

main();
