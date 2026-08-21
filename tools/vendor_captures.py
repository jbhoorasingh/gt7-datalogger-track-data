"""Vendor the gt-telemetry circuit captures that signatures.json is built from.

Upstream is https://github.com/zetetos/gt-telemetry (MIT), `data/circuits`:
84 files, one per GT7 configuration somebody has driven and recorded, each
holding the line the car took and how long it was.

**What is vendored is the measurements, not the raw lines.** The 84 files are
35 MB of coordinates sampled every few metres. What is needed is the bounding
box, the two endpoints, the length, the name — and the line itself, but only
coarsely: the app walks it on a 20 m grid to work out which way round a lap
went, so a point every 20 m in whole metres carries every bit of that answer
and a finer one carries bytes. Thinning is therefore not a compromise made for
size; it is the resolution the question has. It happens to take 35 MB to 350 kB.

The thinned line is kept in **driving order**, which is the one property that
must survive: a bounding box cannot tell a layout from its reverse — same box,
same length — and the order the road is driven in is what separates them. A
line sorted by position instead of travel would be worse than no line at all,
because it would produce a confident wrong answer instead of a decline.

The lines are still not vendored at full fidelity, and nothing here may draw
borders from them: a capture is one line down the middle of the road and
carries no width, so any edge derived from it would be invented, and invented
edges feed track-limits judging.

Each row keeps the sha256 of the upstream file it came from, so a later fetch
can prove which bytes produced the numbers, and `--check` can say whether
upstream has moved without anybody having to eyeball 84 files.

Vendoring rather than fetching at build time is what lets `build_signatures.py`
run offline and produce the same file every time — the same reason index.json
carries no timestamp.

    python tools/vendor_captures.py [--ref REF] [--check]
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / "vendor" / "circuits.json"

REPO = "zetetos/gt-telemetry"
SOURCE_PATH = "data/circuits"
LICENSE = "MIT"
FORMAT = "gt7-datalogger-capture-signatures"
VERSION = 2

# One point every 20 m, in whole metres. Mirrors the app's PATH_CELL_M: it
# indexes a path on a 20 m grid and looks in the neighbouring cells, so a
# closer spacing changes no answer it can give. Recorded in the manifest so
# build_signatures.py publishes the step it actually got rather than the step
# it assumes, and so changing it is visibly a re-vendor and not an edit.
PATH_STEP_M = 20

TIMEOUT_S = 180


def resolve_commit(ref: str) -> str:
    """The exact commit `ref` names, so the vendored numbers cite bytes."""
    url = f"https://api.github.com/repos/{REPO}/commits/{ref}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "gt7-datalogger-track-data",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)["sha"]


def fetch_circuits(commit: str) -> dict[str, bytes]:
    """Every `data/circuits/*.json` at `commit`, by filename."""
    url = f"https://codeload.github.com/{REPO}/tar.gz/{commit}"
    request = urllib.request.Request(url, headers={"User-Agent": "gt7-datalogger-track-data"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        archive = response.read()

    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            # <repo>-<commit>/data/circuits/<name>.json, and nothing deeper:
            # data/circuits/schema/ holds the JSON schema, not a circuit.
            parts = Path(member.name).parts
            if not member.isfile() or len(parts) != 4:
                continue
            if parts[1:3] != tuple(SOURCE_PATH.split("/")) or not parts[3].endswith(".json"):
                continue
            handle = tar.extractfile(member)
            if handle is not None:
                out[parts[3]] = handle.read()
    return out


def thin(xs: list[float], zs: list[float], step_m: int) -> list[list[int]]:
    """The line at one point every `step_m`, in whole metres, order preserved.

    Walks the line accumulating real distance rather than taking every nth
    point, because the recordings are sampled in time: a point every nth
    sample is dense on the straights, where nothing needs resolving, and
    sparse through the corners, where the path is doing its work.
    """
    out = [[round(xs[0]), round(zs[0])]]
    travelled = 0.0
    for i in range(1, len(xs)):
        travelled += math.dist((xs[i - 1], zs[i - 1]), (xs[i], zs[i]))
        if travelled < step_m:
            continue
        travelled = 0.0
        point = [round(xs[i]), round(zs[i])]
        # Whole metres can collapse two points onto one another. Never at a
        # 20 m step, but the step is a constant somebody may lower.
        if point != out[-1]:
            out.append(point)
    return out


def distil(filename: str, raw: bytes) -> dict[str, Any]:
    """One capture reduced to the numbers a signature is made of.

    `y` is dropped with the rest of the line: the app's signature is a
    bounding box in x/z, and its whole-lap test measures across the ground.
    """
    doc = json.loads(raw.decode("utf-8"))
    line = doc["coordinates"]["circuit"]
    if not line:
        raise ValueError(f"{filename}: coordinates.circuit is empty")
    xs = [float(p["x"]) for p in line]
    zs = [float(p["z"]) for p in line]
    return {
        "file": filename,
        "name": doc["name"],
        # Present on every file today, but the field is optional upstream and
        # the plain `name` is the fallback the schema documents.
        "variation_name": doc.get("variationName") or doc["name"],
        "length_m": float(doc["lengthMetres"]),
        "points": len(line),
        "min_x": min(xs), "max_x": max(xs),
        "min_z": min(zs), "max_z": max(zs),
        "start_x": xs[0], "start_z": zs[0],
        "end_x": xs[-1], "end_z": zs[-1],
        # Driving order, and the reason this file exists in this shape.
        "path": thin(xs, zs, PATH_STEP_M),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def build(ref: str) -> dict[str, Any]:
    commit = resolve_commit(ref)
    files = fetch_circuits(commit)
    if not files:
        raise SystemExit(f"no {SOURCE_PATH}/*.json found at {REPO}@{commit}")
    return {
        "format": FORMAT,
        "version": VERSION,
        "path_step_m": PATH_STEP_M,
        "source": {
            "repo": f"https://github.com/{REPO}",
            "path": SOURCE_PATH,
            "commit": commit,
            "license": LICENSE,
        },
        "captures": [distil(name, files[name]) for name in sorted(files)],
    }


def dumps(doc: dict[str, Any]) -> str:
    """The manifest as this repository stores it.

    Plain indent=1 puts every path coordinate on a line of its own — four
    lines per point, and this file is mostly path. One point per line instead,
    which is the same one-record-per-line rule canonical.py applies to a
    bundle's edges and for the same reasons: a diff that reads as the metres
    that changed, and a file git can delta.
    """
    marks: dict[str, str] = {}
    shallow = dict(doc)
    shallow["captures"] = rows = [dict(c) for c in doc["captures"]]
    for row in rows:
        key = f"@@{len(marks)}@@"
        marks[key] = ("[\n" + ",\n".join(f"    [{x}, {z}]" for x, z in row["path"])
                      + "\n   ]")
        row["path"] = key

    text = json.dumps(shallow, indent=1, ensure_ascii=False) + "\n"
    for key, rendered in marks.items():
        text = text.replace(f'"{key}"', rendered)
    return text


def main(argv: list[str]) -> int:
    ref = "main"
    if "--ref" in argv:
        ref = argv[argv.index("--ref") + 1]

    doc = build(ref)
    text = dumps(doc)
    captures = doc["captures"]
    points = sum(c["points"] for c in captures)
    kept = sum(len(c["path"]) for c in captures)

    if "--check" in argv:
        current = CAPTURES.read_text(encoding="utf-8") if CAPTURES.exists() else ""
        if current != text:
            print(f"vendor/circuits.json is stale against {REPO}@{doc['source']['commit'][:12]}"
                  " — run: python tools/vendor_captures.py")
            return 1
        print(f"vendor/circuits.json matches {REPO}@{doc['source']['commit'][:12]}")
        return 0

    CAPTURES.parent.mkdir(parents=True, exist_ok=True)
    CAPTURES.write_text(text, encoding="utf-8")
    print(f"vendor/circuits.json: {len(captures)} captures distilled from "
          f"{points:,} points to {kept:,} at one every {PATH_STEP_M} m, "
          f"{REPO}@{doc['source']['commit'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
