"""Corrections to a circuit's survey: what a person decided the evidence gets wrong.

A bundle is evidence, and evidence only ever adds up: `add_bundle.merge_into`
folds a new survey into the old one cell by cell and removes nothing. That is
the right rule for laps and the wrong one for mistakes. A pit wall recorded as
the right-hand border is in the file for good — and deleting it from the file
does not help, because a datalogger uploads its *whole* local bundle on every
autosave, so the next time that contributor drives the circuit the merge puts
every deleted metre straight back.

So a correction is never made to the evidence. It is kept beside it, in
`corrections/<slug>.json`, and applied to what is *derived* from the evidence —
the geometry the merge job compiles and the sync service publishes — which is
exactly how the corroboration policy already treats a lone voter's wall. The
bundle keeps every record anybody ever surveyed; a correction is one reviewed,
revertible file that says which of them the map should not draw, and taking
it away brings them back the same night.

Two things can be said:

  * **`exclude`** — areas of ground, each a polygon in world metres with the
    sides it applies to, inside which border records are not compiled. An
    area and not a list of cells, because a survey jitters: next week's pit
    wall lands in the cells next door, and a list of last week's cells would
    leak. `y` bounds an area to one road level where a circuit crosses over
    itself; a record with no elevation is on every level. `only_drawn` limits
    an area to records nobody drove — how a drawn bridge is taken back without
    hiding the real border when somebody finally surveys it.
  * **`compile.smooth_borders`** — this circuit's answer to whether its
    borders are smoothed, over the service-wide `compile.smooth_borders`
    switch. `null` follows the switch.

  * **`draw`** — border records somebody DREW: a bridge across a gap, a kerb
    nobody drove. The same shape as a bundle's records, every vote under a
    `drawn-` source, and compiled with the evidence as though they were in
    it. They are here and not in the bundle because the bundle is what the
    datalogger imports, and its validator takes a source id to be hex — a
    bundle carrying `drawn-524eff6e` is refused whole. The first two edits
    ever merged put drawn records in their bundles; `main` went red on "the
    app still accepts what we ship" and the pack shipped two circuits no app
    would load. A drawn border is an opinion about the evidence, and this is
    the file for opinions. A surveyed record in the same metre wins: a drawn
    record never replaces a driven one.

Standard library only, like everything else in this repository's toolchain.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

FORMAT = "gt7-datalogger-track-corrections"
VERSION = 1
DIRECTORY = "corrections"

SIDES = ("L", "R")
DRAWN_SOURCE_PREFIX = "drawn-"

# Generous for a circuit and small enough that a file of them is still
# something a person can review in a pull request.
MAX_AREAS = 200
MIN_POLYGON_POINTS = 3
MAX_POLYGON_POINTS = 200
MAX_REASON = 280
MAX_NAME = 80
MAX_DRAWN = 15_000
GRID_M = 1.0  # bundle_format's, and the editor's: one record a metre a side
LEVEL_SEP_M = 3.0  # bundle_format's: further apart in height is another road
MANUAL_KINDS = ("wall", "runoff", "edge")  # what somebody can say lies beyond a border
DRAWN_KEYS = ("x", "z", "y", "hx", "hz", "side", "kind", "votes", "run", "tw")
# A circuit is a few kilometres across. A coordinate out here is a typo or a
# unit mistake, and an area that size would hide a whole survey.
MAX_COORDINATE_M = 50_000.0

HEADER_KEYS = ("format", "version", "official_id", "track", "compile")
AREA_KEYS = ("id", "sides", "polygon", "y", "only_drawn", "reason", "by", "at")


def empty(official_id: str, track: str) -> dict[str, Any]:
    """A circuit about which nothing has been decided."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "official_id": official_id,
        "track": track,
        "compile": {"smooth_borders": None},
        "exclude": [],
        "draw": [],
    }


def is_empty(doc: dict[str, Any] | None) -> bool:
    """Whether the document says anything at all. One that does not need not exist."""
    if not doc:
        return True
    return (not doc.get("exclude") and not doc.get("draw")
            and (doc.get("compile") or {}).get("smooth_borders") is None)


def _fail(message: str) -> None:
    raise ValueError(message)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value: Any, where: str, limit: int, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        _fail(f"{where} must be text")
    if required and not value.strip():
        _fail(f"{where} must not be empty")
    if len(value) > limit:
        _fail(f"{where} is longer than {limit} characters")
    if any(ord(ch) < 32 for ch in value):
        _fail(f"{where} must not contain control characters")
    return value


def _drawn(raw: Any, index: int) -> dict[str, Any]:
    where = f"draw[{index}]"
    if not isinstance(raw, dict):
        _fail(f"{where} must be an object")
    unknown = sorted(set(raw) - set(DRAWN_KEYS))
    if unknown:
        _fail(f"{where} has unknown key(s): {', '.join(unknown)}")
    for key in ("x", "z", "hx", "hz"):
        if not _finite(raw.get(key)):
            _fail(f"{where}.{key} must be a number")
    if abs(raw["x"]) > MAX_COORDINATE_M or abs(raw["z"]) > MAX_COORDINATE_M:
        _fail(f"{where} is not on any circuit")
    for key in ("y", "tw"):
        if raw.get(key) is not None and not _finite(raw[key]):
            _fail(f"{where}.{key} must be a number or null")
    if raw.get("side") not in SIDES:
        _fail(f"{where}.side must be L or R")
    kind = raw.get("kind")
    if kind not in MANUAL_KINDS:
        _fail(f"{where}.kind must be one of {', '.join(MANUAL_KINDS)}: nobody can infer a metre nobody drove")
    run = raw.get("run")
    if not isinstance(run, int) or isinstance(run, bool) or run < 1:
        _fail(f"{where}.run must be a whole number of at least 1")
    votes = raw.get("votes")
    if not isinstance(votes, dict) or set(votes) != {kind}:
        _fail(f"{where}.votes must vote for its own kind and no other")
    by_source = votes[kind]
    if not isinstance(by_source, dict) or not by_source:
        _fail(f"{where}.votes names nobody")
    for source, entry in by_source.items():
        # The whole reason this list exists. A record under anybody's
        # installation id is a lap, and laps are not written here.
        if not isinstance(source, str) or not source.startswith(DRAWN_SOURCE_PREFIX):
            _fail(f"{where} is filed under {source!r}: only a {DRAWN_SOURCE_PREFIX} source may be drawn")
        if (not isinstance(entry, list) or len(entry) != 2
                or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in entry)):
            _fail(f"{where}.votes[{kind!r}][{source!r}] must be [count, run]")
    return {key: raw.get(key) for key in DRAWN_KEYS}


def _area(raw: Any, index: int) -> dict[str, Any]:
    where = f"exclude[{index}]"
    if not isinstance(raw, dict):
        _fail(f"{where} must be an object")
    unknown = sorted(set(raw) - set(AREA_KEYS))
    if unknown:
        _fail(f"{where} has unknown key(s): {', '.join(unknown)}")

    area_id = _text(raw.get("id"), f"{where}.id", 40, required=True)

    sides = raw.get("sides")
    if not isinstance(sides, list) or not sides:
        _fail(f"{where}.sides must list at least one of L, R")
    if any(side not in SIDES for side in sides) or len(set(sides)) != len(sides):
        _fail(f"{where}.sides may only hold L and R, once each")

    polygon = raw.get("polygon")
    if not isinstance(polygon, list) or not (MIN_POLYGON_POINTS <= len(polygon) <= MAX_POLYGON_POINTS):
        _fail(f"{where}.polygon must have {MIN_POLYGON_POINTS} to {MAX_POLYGON_POINTS} points")
    points: list[list[float]] = []
    for k, point in enumerate(polygon):
        if (not isinstance(point, list) or len(point) != 2
                or not all(_finite(v) and abs(v) <= MAX_COORDINATE_M for v in point)):
            _fail(f"{where}.polygon[{k}] must be [x, z] in metres")
        points.append([float(point[0]), float(point[1])])
    if abs(polygon_area(points)) < 1e-6:
        _fail(f"{where}.polygon encloses no ground")

    levels = raw.get("y")
    if levels is not None:
        if (not isinstance(levels, list) or len(levels) != 2
                or not all(_finite(v) for v in levels) or levels[0] > levels[1]):
            _fail(f"{where}.y must be null or [lowest, highest] elevation in metres")
        levels = [float(levels[0]), float(levels[1])]

    only_drawn = raw.get("only_drawn", False)
    if not isinstance(only_drawn, bool):
        _fail(f"{where}.only_drawn must be true or false")

    return {
        "id": area_id,
        "sides": [side for side in SIDES if side in sides],
        "polygon": points,
        "y": levels,
        "only_drawn": only_drawn,
        # The reason is required: an area with none is a hole in the map that
        # nobody can later judge whether to keep.
        "reason": _text(raw.get("reason"), f"{where}.reason", MAX_REASON, required=True),
        "by": _text(raw.get("by"), f"{where}.by", MAX_NAME),
        "at": _text(raw.get("at"), f"{where}.at", 40),
    }


def validate(raw: Any) -> dict[str, Any]:
    """The document, normalised, or a ValueError a person can act on."""
    if not isinstance(raw, dict):
        _fail("a corrections document must be a JSON object")
    if raw.get("format") != FORMAT:
        _fail(f"format must be {FORMAT}")
    if raw.get("version") != VERSION:
        _fail(f"version must be {VERSION}")
    unknown = sorted(set(raw) - set(HEADER_KEYS) - {"exclude", "draw"})
    if unknown:
        _fail(f"unknown key(s): {', '.join(unknown)}")

    official_id = _text(raw.get("official_id"), "official_id", 32, required=True)
    track = _text(raw.get("track"), "track", 200, required=True)

    compile_block = raw.get("compile", {"smooth_borders": None})
    if not isinstance(compile_block, dict) or set(compile_block) - {"smooth_borders"}:
        _fail("compile may only hold smooth_borders")
    smooth = compile_block.get("smooth_borders")
    if smooth is not None and not isinstance(smooth, bool):
        # "off" is truthy. A circuit whose owner wrote it would go on being
        # smoothed, which is the opposite of what they asked for.
        _fail("compile.smooth_borders must be true, false or null")

    areas_raw = raw.get("exclude", [])
    if not isinstance(areas_raw, list) or len(areas_raw) > MAX_AREAS:
        _fail(f"exclude must be a list of at most {MAX_AREAS} areas")
    areas = [_area(area, index) for index, area in enumerate(areas_raw)]
    ids = [area["id"] for area in areas]
    if len(set(ids)) != len(ids):
        _fail("every exclude area needs an id of its own")

    drawn_raw = raw.get("draw", [])
    if not isinstance(drawn_raw, list) or len(drawn_raw) > MAX_DRAWN:
        _fail(f"draw must be a list of at most {MAX_DRAWN} records")
    drawn = [_drawn(record, index) for index, record in enumerate(drawn_raw)]
    cells = [cell_of(record) for record in drawn]
    if len(set(cells)) != len(cells):
        _fail("draw holds two records for one metre of one side")

    return {
        "format": FORMAT,
        "version": VERSION,
        "official_id": official_id,
        "track": track,
        "compile": {"smooth_borders": smooth},
        "exclude": areas,
        # By position, as a bundle's records are: a pull request that draws a
        # bridge shows the bridge, not a reshuffle.
        "draw": sorted(drawn, key=lambda r: (r["x"], r["z"], r["side"])),
    }


# ── canonical form ─────────────────────────────────────────────────────────


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def dumps(doc: dict[str, Any]) -> str:
    """One area per line and keys in a fixed order, for the reason `canonical`
    gives for bundles: a pull request that adds an area shows one added line."""
    doc = validate(doc)
    lines = ["{"]
    for key in HEADER_KEYS:
        lines.append(f"{_compact(key)}:{_compact(doc[key])},")
    areas = [_compact({key: area[key] for key in AREA_KEYS}) for area in doc["exclude"]]
    drawn = [_compact({key: record[key] for key in DRAWN_KEYS}) for record in doc["draw"]]
    for name, rows, last in (("exclude", areas, False), ("draw", drawn, True)):
        body = "[\n  " + ",\n  ".join(rows) + "\n]" if rows else "[]"
        lines.append(f"{_compact(name)}:{body}" + ("" if last else ","))
    lines.append("}")
    return "\n".join(lines) + "\n"


# ── what a correction does ─────────────────────────────────────────────────


def cell_of(record: dict[str, Any]) -> tuple[int, int, str]:
    """The metre of one side a record occupies — bundle_format.edge_key's rule."""
    return (round(record["x"] / GRID_M), round(record["z"] / GRID_M), record["side"])


def same_level(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """bundle_format's: the same road unless both know their height and differ."""
    ya, yb = a.get("y"), b.get("y")
    return ya is None or yb is None or abs(ya - yb) <= LEVEL_SEP_M


def with_drawn(held: list[dict[str, Any]], more: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What is drawn already, and what an edit draws: what is there stays, and
    a second record for a metre that has one is dropped."""
    out = list(held)
    taken = {cell_of(record) for record in held}
    for record in more:
        if cell_of(record) not in taken:
            taken.add(cell_of(record))
            out.append({key: record.get(key) for key in DRAWN_KEYS})
    return out


def polygon_area(polygon: list[list[float]]) -> float:
    """Signed, by the shoelace rule. Zero is a line or a point."""
    total = 0.0
    for (ax, az), (bx, bz) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        total += ax * bz - bx * az
    return total / 2


def point_in_polygon(x: float, z: float, polygon: list[list[float]]) -> bool:
    """Ray crossing, the same test the editor's lasso uses on screen."""
    inside = False
    j = len(polygon) - 1
    for i, (ax, az) in enumerate(polygon):
        bx, bz = polygon[j]
        if (az > z) != (bz > z):
            crossing = ax + ((z - az) / (bz - az)) * (bx - ax)
            if x < crossing:
                inside = not inside
        j = i
    return inside


def _drawn_only(edge: dict[str, Any]) -> bool:
    sources = {source for by_source in (edge.get("votes") or {}).values() for source in by_source}
    return bool(sources) and all(source.startswith(DRAWN_SOURCE_PREFIX) for source in sources)


def excludes(area: dict[str, Any], edge: dict[str, Any]) -> bool:
    """Whether this area keeps this record out of the compiled geometry."""
    if edge.get("side") not in area["sides"]:
        return False
    levels = area.get("y")
    elevation = edge.get("y")
    # A record without an elevation is on every level: an area drawn round a
    # bridge must still catch the metre recorded before elevation existed.
    if levels is not None and elevation is not None and not (levels[0] <= elevation <= levels[1]):
        return False
    if area.get("only_drawn") and not _drawn_only(edge):
        return False
    return point_in_polygon(edge["x"], edge["z"], area["polygon"])


def excluded(edges: list[dict[str, Any]], doc: dict[str, Any] | None) -> list[int]:
    """Indices of the records the corrections keep out, in order."""
    areas = (doc or {}).get("exclude") or []
    if not areas:
        return []
    return [i for i, edge in enumerate(edges) if any(excludes(area, edge) for area in areas)]


def apply(bundle: dict[str, Any], doc: dict[str, Any] | None) -> dict[str, Any]:
    """The bundle as the compiler should see it. Never the bundle itself.

    What comes back is not a valid bundle to write anywhere — its run counts
    no longer follow from its records — and is not meant to be: like
    `sync_job.publishable_copy`, it exists to be compiled and thrown away.
    """
    edges = bundle.get("edges") or []
    drop = set(excluded(edges, doc))
    drawn = (doc or {}).get("draw") or []
    if not drop and not drawn:
        return bundle
    kept = [edge for i, edge in enumerate(edges) if i not in drop]

    # What was drawn goes in with the evidence, unless an area keeps it out —
    # `only_drawn` is how a bridge is taken back — or somebody has since
    # driven that metre: a drawn record never replaces a driven one.
    surveyed: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    for edge in edges:
        surveyed.setdefault(cell_of(edge), []).append(edge)
    hidden = set(excluded(drawn, doc))
    for i, record in enumerate(drawn):
        if i in hidden:
            continue
        if any(same_level(record, edge) for edge in surveyed.get(cell_of(record), ())):
            continue
        kept.append(copy.deepcopy(record))

    out = copy.copy(bundle)
    out["edges"] = kept
    return out


def smooth_override(doc: dict[str, Any] | None) -> bool | None:
    """This circuit's own answer about smoothing, or None to follow the service."""
    value = ((doc or {}).get("compile") or {}).get("smooth_borders")
    return value if isinstance(value, bool) else None
