"""Generate signatures.json: enough geometry to name a circuit from one lap.

The app cannot name a circuit until a human names it, so a new install
identifies nothing and everything hanging off the circuit name — outline,
corner labels, category bests — stays empty. This file closes that hole with
geometry computed offline, and the app ships a vendored copy, so its shape is
a published contract rather than an internal detail.

A signature is length, a bounding box, **and the racing line in driving
order**. The line is not decoration. A box and a length recognise a circuit
and cannot tell a layout from its reverse, which has exactly the same box and
exactly the same length — measured against 896 real laps that misfiled 10 Deep
Forest Reverse laps as Deep Forest Raceway, where they pooled with 6 genuine
forward laps and competed for the same personal best. 36 of the seeded
configurations have a reverse twin, so it was structural. The order the road is
driven in is the one thing a bounding box discards and the one thing that
separates the pair, which is why `path` is ordered by travel and never by
position.

Two sources, in order of preference:

1. **This repository's own bundles.** Real surveyed road edges, and a
   `meta.official` a human confirmed, so no name matching is involved. The
   only things a bundle cannot give are how far a car drives round it and
   which way — edges are road borders, sorted by position, not a driven line.
2. **The vendored gt-telemetry captures** (`vendor/circuits.json`) for
   everything else: one recorded line per configuration, whose own measured
   length is what a lap's `dist` counts and whose order is the direction it
   was driven.

Like index.json it carries no timestamp and is a pure function of its inputs,
so CI can regenerate it and fail the build when the committed copy is stale.

    python tools/build_signatures.py [--check]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_index import configurations  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "tracks.json"
TRACKS = ROOT / "tracks"
CAPTURES = ROOT / "vendor" / "circuits.json"
SIGNATURES = ROOT / "signatures.json"

# Mirrored from the app's backend/app/processing/tracks.py. Copied rather than
# imported because this repository has no dependency on the app and should not
# grow one to build a data file — but they are the same numbers, and they must
# be kept in step: a signature this file calls unambiguous is one the app will
# resolve to a name, and the app is where these were calibrated.
LENGTH_TOLERANCE = 0.04  # 4 % lap-length difference (racing line varies)
CENTER_TOLERANCE_M = 120.0
EXTENT_TOLERANCE = 0.20
ROUTE_CLOSE_M = 60.0
ROUTE_CLOSE_FRACTION = 0.05
PATH_CELL_M = 20.0

# A path shorter than this tells the app nothing — it refuses to read direction
# from one (tracks.travel_direction, `total < 8`) — so shipping one would be
# bytes pretending to be evidence. Nothing here comes close: the shortest is
# Northern Isle Speedway at 48 points.
MIN_PATH_POINTS = 8

# How closely a surveyed edge's heading must line up with the borrowed line's
# direction to count as agreeing. 0.5 is 60 degrees: generous, because the
# question is "does this line run the same way round" and not "how well does
# it fit", and a racing line cuts corners the road's own heading does not.
HEADING_AGREES = 0.5

# Upstream misspellings, mapped by hand. Each is confirmed independently of the
# name, by the capture's length agreeing with the catalog's to within 1.2 %.
#
# A table rather than another rule in normalise(): these are data errors in
# somebody else's repository, they may be corrected there at any time, and a
# table makes that visible as a row that stops matching. A clever regex would
# absorb the fix silently and go on quietly mapping a name that no longer
# exists onto a circuit.
CAPTURE_NAME_FIXES = {
    "Circuit Giles-Villeneuve": "Circuit Gilles-Villeneuve",
    "Circuit de Saint-Croix - A": "Circuit de Sainte-Croix - A",
    "Circuit de Saint-Croix - B": "Circuit de Sainte-Croix - B",
    "Circuit de Saint-Croix - C": "Circuit de Sainte-Croix - C",
    "Nürburgring Nordeschleife": "Nürburgring Nordschleife",
    "Watkins Glen International": "Watkins Glen Short Course",
}

# `catalog_length_disagrees`: the capture's measured lap and the catalog's
# published figure differ by more than the app will tolerate. Advisory only —
# see flag_length() for why neither one gets corrected.
# `length_from_catalog`: a surveyed configuration with no usable capture, so
# the length is the published figure and not a driven distance.
# `path_heading_disagrees`: a borrowed line runs against the survey it was
# borrowed for. See survey_rows() — the row keeps its box and loses its path.
FLAG_LENGTH_DISAGREES = "catalog_length_disagrees"
FLAG_LENGTH_FROM_CATALOG = "length_from_catalog"
FLAG_PATH_HEADING_DISAGREES = "path_heading_disagrees"

ROW_KEYS = ("official_id", "official_name", "length_m",
            "min_x", "max_x", "min_z", "max_z",
            "provenance", "path", "reverse", "ambiguous_with", "flags")


def normalise(name: str) -> str:
    """A circuit name reduced to what two spellings of it have in common."""
    name = name.lower().replace("center", "centre").replace("race track", "racing circuit")
    return "".join(c for c in name if c.isalnum())


def closes(capture: dict[str, Any]) -> float:
    """How far the recorded line ends from where it started, in metres."""
    return math.dist(
        (capture["start_x"], capture["start_z"]),
        (capture["end_x"], capture["end_z"]),
    )


def is_whole_lap(capture: dict[str, Any]) -> bool:
    """Did this recording go all the way round?

    Seven of the 84 did not. A fragment's `lengthMetres` is the length of the
    fragment and its bounding box is the fragment's box wearing a circuit's
    name, so both numbers are wrong in a way that reads as right. The test and
    its thresholds are the app's own is_whole_lap.
    """
    return closes(capture) <= max(ROUTE_CLOSE_M, capture["length_m"] * ROUTE_CLOSE_FRACTION)


def matches(sig: dict[str, Any], track: dict[str, Any]) -> bool:
    """The app's own matcher: could a lap shaped like `sig` be `track`?

    Deliberately not symmetric, because the app's is not: the tolerances are
    fractions of the stored row's length and extent. `ambiguous_with` reads
    the way the app asks the question — a lap that looks like this row, tried
    against every other row.

    Note this is still the box-and-length matcher, so it says nothing about
    direction. That is correct: `ambiguous_with` records rows the app cannot
    separate on geometry, and direction is applied afterwards, to a row it
    has already settled on.
    """
    if track["length_m"] <= 0 or sig["length_m"] <= 0:
        return False
    if abs(sig["length_m"] - track["length_m"]) / track["length_m"] > LENGTH_TOLERANCE:
        return False
    for lo, hi in (("min_x", "max_x"), ("min_z", "max_z")):
        sig_centre = (sig[lo] + sig[hi]) / 2
        trk_centre = (track[lo] + track[hi]) / 2
        if abs(sig_centre - trk_centre) > CENTER_TOLERANCE_M:
            return False
    for lo, hi in (("min_x", "max_x"), ("min_z", "max_z")):
        sig_extent, trk_extent = sig[hi] - sig[lo], track[hi] - track[lo]
        if trk_extent > 0 and abs(sig_extent - trk_extent) / trk_extent > EXTENT_TOLERANCE:
            return False
    return True


def box(points: list[dict[str, Any]]) -> dict[str, float]:
    xs = [p["x"] for p in points]
    zs = [p["z"] for p in points]
    return {
        "min_x": round(min(xs), 1), "max_x": round(max(xs), 1),
        "min_z": round(min(zs), 1), "max_z": round(max(zs), 1),
    }


def reverse_twins(catalog: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Each configuration's reverse twin, by the forward configuration's id.

    Named exactly the way build_index.configurations() names it, because the
    index and the signatures have to agree about what a reverse layout is
    called — the app writes this name straight onto a session.
    """
    out: dict[str, dict[str, str]] = {}
    for track in catalog.get("tracks", []):
        for lay in track.get("layouts", []):
            reverse = lay.get("reverse")
            if not reverse or not reverse.get("official_id"):
                continue
            out[lay.get("official_id", "")] = {
                "official_id": reverse["official_id"],
                "official_name": f"{lay.get('official_name', lay['name'])} (Reverse)",
            }
    return out


def capture_rows(captures: list[dict[str, Any]], by_name: dict[str, dict[str, Any]],
                 ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Signatures from the vendored captures, and the ones that were dropped.

    An unmapped capture is a build failure, not a skip: a name that no longer
    resolves is either a new configuration worth a row or an upstream rename
    worth a line in CAPTURE_NAME_FIXES, and both are decisions for a person.
    """
    rows: dict[str, dict[str, Any]] = {}
    dropped: list[dict[str, Any]] = []
    unmapped: list[str] = []

    for capture in captures:
        name = capture["variation_name"]
        name = CAPTURE_NAME_FIXES.get(name, name)
        config = by_name.get(normalise(name))
        if config is None:
            unmapped.append(f"{capture['file']}: {capture['variation_name']!r}")
            continue
        if not is_whole_lap(capture):
            dropped.append({
                "file": capture["file"],
                "official_id": config["official_id"],
                "official_name": config["official_name"],
                "closes_at_m": round(closes(capture), 1),
                "length_m": capture["length_m"],
            })
            continue
        row = {
            "official_id": config["official_id"],
            "official_name": config["official_name"],
            "length_m": float(capture["length_m"]),
            "min_x": round(capture["min_x"], 1), "max_x": round(capture["max_x"], 1),
            "min_z": round(capture["min_z"], 1), "max_z": round(capture["max_z"], 1),
            "provenance": "capture",
        }
        path = [tuple(p) for p in capture["path"]]
        if len(path) >= MIN_PATH_POINTS:
            row["path"] = path
        rows[config["official_id"]] = row

    if unmapped:
        raise SystemExit(
            "captures that match no configuration in catalog/tracks.json:\n  "
            + "\n  ".join(unmapped)
            + "\n\nAdd the catalog name to CAPTURE_NAME_FIXES in tools/build_signatures.py,"
              "\nor add the configuration to the catalog. Do not skip it."
        )
    return rows, dropped


def heading_agreement(edges: list[dict[str, Any]],
                      path: list[tuple[int, int]]) -> tuple[int, int]:
    """How many surveyed edges run the same way as `path`, and how many do not.

    Every edge record carries `hx`/`hz`, the heading the car was travelling
    when it was surveyed, so a bundle knows which way round its road goes even
    though its records are sorted by position. Comparing that against the line
    about to be borrowed is what catches a capture of the *reverse* layout
    being attached to a forward row — which is the exact misfiling this whole
    revision exists to stop, so it is worth the few milliseconds.

    Edges with no path point nearby are not counted: an outer wall across a
    wide run-off is genuinely far from the racing line and has no opinion.
    """
    total = len(path)
    if total < MIN_PATH_POINTS:
        return 0, 0
    grid: dict[tuple[int, int], list[int]] = {}
    for i, (px, pz) in enumerate(path):
        grid.setdefault(
            (math.floor(px / PATH_CELL_M), math.floor(pz / PATH_CELL_M)), []
        ).append(i)

    agree = disagree = 0
    for edge in edges:
        hx, hz = edge.get("hx"), edge.get("hz")
        if hx is None or hz is None:
            continue
        ex, ez = edge["x"], edge["z"]
        cx, cz = math.floor(ex / PATH_CELL_M), math.floor(ez / PATH_CELL_M)
        near = [j for a in (-1, 0, 1) for b in (-1, 0, 1)
                for j in grid.get((cx + a, cz + b), ())]
        if not near:
            continue
        i = min(near, key=lambda j: (path[j][0] - ex) ** 2 + (path[j][1] - ez) ** 2)
        # Central difference, wrapping: the line is a closed lap, so the point
        # before the first is the last one.
        ax, az = path[(i - 1) % total]
        bx, bz = path[(i + 1) % total]
        tx, tz = bx - ax, bz - az
        scale = math.hypot(tx, tz)
        if scale == 0:
            continue
        along = (hx * tx + hz * tz) / scale
        if along >= HEADING_AGREES:
            agree += 1
        elif along <= -HEADING_AGREES:
            disagree += 1
    return agree, disagree


def survey_rows(captures: dict[str, dict[str, Any]],
                by_id: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Signatures from this repository's own bundles, which outrank captures.

    A bundle is the surveyed road rather than one line through it, and its
    configuration was confirmed by a human, so the box is both better measured
    and not matched by name. Two things still have to come from a capture:

    * **Length**, because a bundle's edges are borders and the distance round
      a border is not the distance a car drives.
    * **The path**, because a bundle is edge records sorted by position — it
      is not a line down the road and has no travel order to read. The
      capture's line is borrowed purely as direction evidence, and checked
      against the bundle's own headings before it is trusted.

    With no capture to borrow from, the row ships with no path at all. The app
    then declines to judge direction for it, which is the conservative answer
    and the one the first version of this file gave for every row.
    """
    rows: dict[str, dict[str, Any]] = {}
    for path_file in sorted(TRACKS.glob("*.json")):
        doc = json.loads(path_file.read_text(encoding="utf-8"))
        official = doc["meta"].get("official") or {}
        official_id = official.get("official_id", "")
        if not official_id:
            continue  # validate.py is what refuses these; the index leaves them out too
        config = by_id.get(official_id)
        if config is None:
            raise SystemExit(
                f"{path_file.name}: official_id {official_id!r} is not in "
                "catalog/tracks.json. Run: python tools/validate.py"
            )
        # A reverse layout still gets no row of its own — not because it cannot
        # be told apart (with `path` it now can) but because the forward row
        # already carries it, in `reverse`, which is what the app reads. A
        # second row would be a second answer to a question already answered.
        # If a reverse bundle ever appears, the right handling is to let it
        # improve its forward twin's row, not to add one beside it; today none
        # exists, and the report says so rather than dropping it in silence.
        if config["reverse"]:
            continue

        capture = captures.get(official_id)
        flags: list[str] = []
        borrowed: list[tuple[int, int]] = []
        if capture is not None:
            length_m = capture["length_m"]
            borrowed = list(capture.get("path") or [])
        else:
            # The catalog rather than the bundle's copy of it: a bundle caches
            # what the catalog said when it was exported, and a row whose
            # length says "from catalog" should be the catalog's current
            # figure, not a snapshot of an older one.
            length_m = float(config.get("length_m") or 0)
            flags.append(FLAG_LENGTH_FROM_CATALOG)

        row = {
            "official_id": official_id,
            # Likewise the name: official_id is the key, and the catalog is
            # what the app will be showing beside it.
            "official_name": config["official_name"],
            "length_m": length_m,
            **box(doc["edges"]),
            "provenance": "survey",
            "flags": flags,
        }
        if borrowed:
            agree, disagree = heading_agreement(doc["edges"], borrowed)
            row["heading_check"] = (agree, disagree)
            if disagree > agree:
                # Loudly, and without picking one: the survey says the road
                # runs one way and the borrowed line runs the other, and
                # guessing here is how reverse laps got misfiled in the first
                # place. The row keeps its box and loses only its path, so the
                # app declines direction rather than answering wrongly.
                flags.append(FLAG_PATH_HEADING_DISAGREES)
            else:
                row["path"] = borrowed
        rows[official_id] = row
    return rows


def flag_length(row: dict[str, Any], catalog_length_m: float) -> list[str]:
    """Advisory markers on a row's length. Never a correction.

    Where a measured lap and a published figure disagree it is not obvious
    which is wrong — Lago Maggiore Centre's capture closes to within a metre,
    so it is a clean whole lap, and a racing line cannot be 15 % longer than
    its own circuit, which points at the catalog. That is a judgement for a
    human, and the flag is how it reaches one.
    """
    flags = list(row.get("flags", []))
    if FLAG_LENGTH_FROM_CATALOG in flags or catalog_length_m <= 0:
        return flags
    if abs(row["length_m"] - catalog_length_m) / catalog_length_m > LENGTH_TOLERANCE:
        flags.append(FLAG_LENGTH_DISAGREES)
    return flags


def build() -> dict[str, Any]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    configs = configurations(catalog)
    by_id = {c["official_id"]: c for c in configs}
    twins = reverse_twins(catalog)
    # Reverse layouts are kept out of name matching: they share a forward
    # twin's box and length exactly, and no capture is of one, so a name that
    # normalised onto a reverse layout would be a mis-match. They are not
    # missing from the file — every forward row names its twin in `reverse`.
    by_name: dict[str, dict[str, Any]] = {}
    for config in configs:
        if not config["reverse"]:
            by_name.setdefault(normalise(config["official_name"]), config)

    vendored = json.loads(CAPTURES.read_text(encoding="utf-8"))
    from_capture, dropped = capture_rows(vendored["captures"], by_name)
    rows = {**from_capture, **survey_rows(from_capture, by_id)}

    checks = {}
    for official_id, row in rows.items():
        row["flags"] = flag_length(row, float(by_id[official_id].get("length_m") or 0))
        row["reverse"] = twins.get(official_id)
        check = row.pop("heading_check", None)
        if check:
            checks[official_id] = check

    ordered = sorted(rows.values(), key=lambda r: r["official_name"])
    for row in ordered:
        row["ambiguous_with"] = sorted(
            other["official_id"] for other in ordered
            if other is not row and matches(row, other)
        )
        # Rebuilt in contract order, so the file reads the same way every time
        # regardless of which source filled a field in.
        for key in ROW_KEYS:
            if key in row:
                row[key] = row.pop(key)

    return {
        "format": "gt7-datalogger-track-signatures",
        "version": 1,
        "counts": {
            "configurations": len(configs),
            "with_signature": len(ordered),
            "from_survey": sum(1 for r in ordered if r["provenance"] == "survey"),
            "from_capture": sum(1 for r in ordered if r["provenance"] == "capture"),
            "with_path": sum(1 for r in ordered if r.get("path")),
            "with_reverse_twin": sum(1 for r in ordered if r["reverse"]),
            "path_step_m": vendored["path_step_m"],
            "ambiguous": sum(1 for r in ordered if r["ambiguous_with"]),
            "flagged": sum(1 for r in ordered if r["flags"]),
            # A reverse layout gets no row of its own because its forward twin
            # already names it, so 78-of-121 is not 43 configurations missing.
            "reverse_layouts": sum(1 for c in configs if c["reverse"]),
        },
        "dropped_captures": sorted(dropped, key=lambda d: -d["closes_at_m"]),
        "signatures": ordered,
        "heading_checks": checks,
    }


def dumps(doc: dict[str, Any]) -> str:
    """The file as this repository stores it.

    Plain indent=1 puts every path coordinate on a line of its own — four
    lines per point, and this file is mostly path. One point per line instead,
    which is the same rule canonical.py applies to a bundle's edges and for
    the same reasons: a diff that reads as the metres that changed, and a file
    git can delta.
    """
    marks: dict[str, str] = {}

    def mark(rendered: str) -> str:
        key = f"@@{len(marks)}@@"
        marks[key] = rendered
        return key

    shallow = dict(doc)
    shallow.pop("heading_checks", None)
    shallow["signatures"] = rows = [dict(r) for r in doc["signatures"]]
    for row in rows:
        if row.get("path"):
            row["path"] = mark(
                "[\n" + ",\n".join(f"    [{x}, {z}]" for x, z in row["path"]) + "\n   ]"
            )
        if row.get("reverse"):
            row["reverse"] = mark(json.dumps(row["reverse"], ensure_ascii=False))

    text = json.dumps(shallow, indent=1, ensure_ascii=False) + "\n"
    for key, rendered in marks.items():
        text = text.replace(f'"{key}"', rendered)
    return text


def report(doc: dict[str, Any]) -> None:
    """What the run decided, on every run — including the parts that are gaps.

    A dropped capture that is only visible as a missing row reads as "we
    covered everything" when we did not, and a collision that is only visible
    as an empty name in the app reads as a bug rather than as the refusal it
    is meant to be.
    """
    counts = doc["counts"]
    names = {r["official_id"]: r["official_name"] for r in doc["signatures"]}
    print(f"signatures.json: {counts['with_signature']}/{counts['configurations']} "
          f"configurations ({counts['from_survey']} surveyed, "
          f"{counts['from_capture']} from capture), "
          f"{counts['with_path']} with a path at one point every "
          f"{counts['path_step_m']} m, "
          f"{counts['with_reverse_twin']} naming a reverse twin")
    print(f"  {counts['reverse_layouts']} reverse layouts get no row of their own — "
          f"their forward twin carries them")

    if doc["heading_checks"]:
        print("\nborrowed lines checked against the survey's own headings:")
        for official_id, (agree, disagree) in sorted(
                doc["heading_checks"].items(), key=lambda kv: names[kv[0]]):
            verdict = "AGAINST THE SURVEY" if disagree > agree else "same way round"
            print(f"  {names[official_id]:<52} {agree:>5} agree, {disagree:>4} disagree "
                  f"— {verdict}")

    if doc["dropped_captures"]:
        print(f"\ndropped {len(doc['dropped_captures'])} capture(s) — not whole laps, so "
              f"their length and box are a fragment's:")
        for drop in doc["dropped_captures"]:
            print(f"  {drop['official_name']:<52} ends {drop['closes_at_m']:>7.1f} m "
                  f"from its start (of {drop['length_m']:,.0f} m)")

    flagged = [r for r in doc["signatures"] if r["flags"]]
    if flagged:
        print(f"\n{len(flagged)} row(s) flagged for review:")
        for row in flagged:
            print(f"  {row['official_name']:<52} {', '.join(row['flags'])} "
                  f"({row['length_m']:,.0f} m)")

    ambiguous = [r for r in doc["signatures"] if r["ambiguous_with"]]
    if ambiguous:
        print(f"\n{len(ambiguous)} row(s) a lap cannot be told apart from on geometry — "
              f"the app refuses rather than guesses:")
        for row in ambiguous:
            others = ", ".join(names[o] for o in row["ambiguous_with"])
            print(f"  {row['official_name']:<52} also matches {others}")


def main(argv: list[str]) -> int:
    doc = build()
    text = dumps(doc)
    report(doc)
    if "--check" in argv:
        current = SIGNATURES.read_text(encoding="utf-8") if SIGNATURES.exists() else ""
        if current != text:
            print("\nsignatures.json is stale — run: python tools/build_signatures.py")
            return 1
        print("\nsignatures.json is up to date")
        return 0
    SIGNATURES.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
