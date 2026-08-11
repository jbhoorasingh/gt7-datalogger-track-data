"""The track bundle format, version 4 — as defined by THIS repository.

The original plan was to defer to the app's own validator, on the principle
that a second implementation would drift from what the datalogger accepts.
The principle is right and the premise was wrong: the app has no validator to
import, and — the part that settles it — the app has no v4. It reads and
writes v3, and v3 cannot describe what a shared repository needs:

  * **Votes are keyed by source first.** In v3 a cell's votes are
    `{kind: [count, last_run]}`, counted per run. Run ordinals are local to
    one installation, so two people's counts are not comparable and merging
    their bundles silently invents agreement. v4 keys them
    `{kind: {source_id: [count, last_run]}}`, which is what makes a merge
    between two contributors mean anything.
  * **`meta.source_runs`** — `{source_id: runs}`, with `meta.runs` their sum.
    v3 records one installation's run count, which stops being a fact about
    the circuit the moment a second person contributes.
  * **`meta.official`** — the confirmed GT7 configuration. Nothing files a
    bundle without it, because a typed track name cannot place one.
  * **`corners` and `sections`** — authored rather than surveyed, so they are
    kept through a merge instead of being recomputed from evidence.

So the format lives here, and this module is its definition: the constants,
the vote-resolution rule, the merge, and the validator. The app can still
load a v4 document's geometry; it is the vote structure it does not yet
understand.

What this checks is the format. What `validate.py` checks on top of it is
this repository's policy — a confirmed layout that exists in the catalog, a
matching filename, canonical on-disk form.
"""

from __future__ import annotations

import math
from typing import Any

BUNDLE_FORMAT = "gt7-datalogger-track-bundle"
BUNDLE_VERSION = 4

GRID_M = 1.0  # dedup cell: one record per metre per side
MAX_POINTS = 50_000
MAX_FINISH_CROSSINGS = 20

# Resolution order, unchanged from v3: manual marks beat automatic inference
# outright rather than by majority, because the surface chars are blind to
# walls and paved run-off. Majority applies within a tier.
MANUAL_KINDS = ("wall", "runoff", "edge")  # driver-declared
AUTO_KINDS = ("auto", "straddle")  # inferred; "auto" is transition-derived
KIND_ORDER = MANUAL_KINDS + AUTO_KINDS

SIDES = ("L", "R")
DIRECTIONS = ("left", "right")

# Headings are unit vectors stored to 5 dp, so honest rounding moves the
# magnitude by ~1e-5. A thousandth fails a vector that was never normalised
# without quibbling over the last decimal place.
HEADING_TOLERANCE = 1e-3

# A contributor can act on a handful of problems; four thousand identical
# ones are a wall of text that buries the first.
MAX_REPORTED = 6


def edge_key(e: dict[str, Any]) -> tuple[int, int, str]:
    """One record per metre per side — kind is voted on, not part of identity."""
    return (round(e["x"] / GRID_M), round(e["z"] / GRID_M), e["side"])


def tally(source_votes: dict[str, list[int]]) -> int:
    """A kind's total support across every source that has evidenced it."""
    return sum(entry[0] for entry in source_votes.values())


def resolve_kind(votes: dict[str, dict[str, list[int]]]) -> str:
    """The kind a cell's votes settle on: manual tier first, then majority."""
    for tier in (MANUAL_KINDS, AUTO_KINDS):
        present = [k for k in tier if votes.get(k)]
        if present:
            return max(present, key=lambda k: (tally(votes[k]), -KIND_ORDER.index(k)))
    return "auto"  # unreachable for well-formed records; never crash a load


def merge_edges(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union on the dedup grid, combining votes; existing geometry wins.

    Where the app merges a *live run's* evidence into a stored bundle and so
    increments a count per run, this merges two stored documents. A per-source
    entry is a cumulative snapshot, not a delta, so the later one supersedes
    the earlier rather than adding to it — which is what makes contributing
    the same export twice a no-op instead of a doubling.

    Records in `existing` are mutated; records copied out of `new` are never
    aliased.
    """
    merged = list(existing)
    index = {edge_key(e): e for e in existing}
    for e in new:
        key = edge_key(e)
        cur = index.get(key)
        if cur is None:
            if len(merged) >= MAX_POINTS:
                continue
            copy = {**e, "votes": {kind: {src: list(v) for src, v in sources.items()}
                                   for kind, sources in e["votes"].items()}}
            index[key] = copy
            merged.append(copy)
            continue
        # Elevation backfill: a metre first mapped before v3 has no `y`, and
        # the next pass over it supplies one. Geometry otherwise stays
        # first-seen, but a null is not a measurement to defend.
        if cur.get("y") is None and e.get("y") is not None:
            cur["y"] = e["y"]
        for kind, sources in e["votes"].items():
            held = cur["votes"].setdefault(kind, {})
            for source, entry in sources.items():
                prior = held.get(source)
                if prior is None or (entry[1], entry[0]) > (prior[1], prior[0]):
                    held[source] = list(entry)
        cur["kind"] = resolve_kind(cur["votes"])
    return merged


def merge_finish(
    existing: list[dict[str, float]], new: list[dict[str, float]]
) -> list[dict[str, float]]:
    merged = list(existing)
    seen = {(round(c["x"]), round(c["z"])) for c in existing}
    for c in new:
        key = (round(c["x"]), round(c["z"]))
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
    return merged[-MAX_FINISH_CROSSINGS:]


# --- validation ---------------------------------------------------------------


def _is_number(value: Any) -> bool:
    # bool is an int in Python, and a heading of True is not a heading.
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _point(value: Any) -> bool:
    return isinstance(value, dict) and _is_number(value.get("x")) \
        and _is_number(value.get("z"))


def _fail(problems: list[str], message: str) -> None:
    """Record a problem, but stop building strings once the report is full."""
    if len(problems) <= MAX_REPORTED:
        problems.append(message)


def _check_meta(meta: Any, problems: list[str]) -> None:
    if not isinstance(meta, dict):
        _fail(problems, "meta is not an object")
        return
    if not isinstance(meta.get("track"), str) or not meta["track"].strip():
        _fail(problems, "meta.track is missing or empty")
    if not isinstance(meta.get("updated_at"), str) or not meta["updated_at"]:
        _fail(problems, "meta.updated_at is missing")

    sources = meta.get("source_runs")
    if not isinstance(sources, dict) or not sources:
        _fail(problems, "meta.source_runs is missing or empty — a v4 bundle "
                        "records which installation's runs its votes came from")
        return
    for source, count in sources.items():
        if not isinstance(source, str) or not source:
            _fail(problems, f"meta.source_runs has an unusable source id {source!r}")
        if not _is_int(count) or count < 0:
            _fail(problems, f"meta.source_runs[{source!r}] is {count!r}, "
                            "which is not a run count")

    total = sum(c for c in sources.values() if _is_int(c))
    if _is_int(meta.get("runs")) and meta["runs"] != total:
        # Not pedantry: meta.runs is the number the index and the site quote,
        # and a bundle whose total disagrees with its own sources has been
        # hand-edited somewhere that the vote counts probably were too.
        _fail(problems, f"meta.runs is {meta['runs']} but its sources total "
                        f"{total}")
    elif not _is_int(meta.get("runs")):
        _fail(problems, "meta.runs is missing")

    official = meta.get("official")
    if official is None:
        return  # allowed by the format; validate.py enforces the repo's policy
    if not isinstance(official, dict):
        _fail(problems, "meta.official is not an object")
        return
    for field in ("official_id", "official_name", "track", "layout"):
        if not isinstance(official.get(field), str) or not official[field]:
            _fail(problems, f"meta.official.{field} is missing or empty")
    if not _is_int(official.get("turns")) or official["turns"] < 0:
        _fail(problems, "meta.official.turns is not a turn count")
    if not _is_number(official.get("length_m")) or official["length_m"] <= 0:
        _fail(problems, "meta.official.length_m is not a length")
    if not isinstance(official.get("reverse"), bool):
        _fail(problems, "meta.official.reverse is not true or false")


def _check_edge(
    e: Any, where: str, sources: dict[str, Any] | None, problems: list[str]
) -> None:
    """`sources` is None when meta.source_runs was itself unusable, in which
    case provenance is not cross-checked — one bad meta must not reappear as
    a complaint against every record that cites it."""
    if not isinstance(e, dict):
        _fail(problems, f"{where} is not an object")
        return
    for field in ("x", "z", "hx", "hz"):
        if not _is_number(e.get(field)):
            _fail(problems, f"{where}: {field} is {e.get(field)!r}, not a number")
            return
    if e.get("y") is not None and not _is_number(e["y"]):
        _fail(problems, f"{where}: y is {e['y']!r} — a number or null")
    if e.get("tw") is not None and (not _is_number(e["tw"]) or e["tw"] <= 0):
        _fail(problems, f"{where}: tw is {e['tw']!r} — a positive width or null")
    if not _is_int(e.get("run")) or e["run"] < 0:
        _fail(problems, f"{where}: run is {e.get('run')!r}, not a run ordinal")
    if e.get("side") not in SIDES:
        _fail(problems, f"{where}: side is {e.get('side')!r}, not one of "
                        f"{'/'.join(SIDES)}")
    if e.get("kind") not in KIND_ORDER:
        _fail(problems, f"{where}: kind is {e.get('kind')!r}, not one of "
                        f"{', '.join(KIND_ORDER)}")

    magnitude = math.hypot(e["hx"], e["hz"])
    if abs(magnitude - 1.0) > HEADING_TOLERANCE:
        _fail(problems, f"{where}: heading ({e['hx']}, {e['hz']}) has magnitude "
                        f"{magnitude:.4f} — it should be a unit vector")

    votes = e.get("votes")
    if not isinstance(votes, dict) or not votes:
        _fail(problems, f"{where}: votes is missing or empty — every record is "
                        "evidenced by at least one source")
        return
    sound = True
    for kind, by_source in votes.items():
        if kind not in KIND_ORDER:
            _fail(problems, f"{where}: votes for unknown kind {kind!r}")
            sound = False
            continue
        if not isinstance(by_source, dict) or not by_source:
            # The v3 shape lands exactly here, so say what it looks like.
            _fail(problems, f"{where}: votes[{kind!r}] is {by_source!r} — v4 "
                            "keys votes by source: {source_id: [count, last_run]}")
            sound = False
            continue
        for source, entry in by_source.items():
            if not (isinstance(entry, list) and len(entry) == 2
                    and all(_is_int(v) for v in entry)
                    and entry[0] >= 1 and entry[1] >= 0):
                _fail(problems, f"{where}: votes[{kind!r}][{source!r}] is "
                                f"{entry!r}, not [count, last_run]")
                sound = False
                continue
            if sources is None:
                continue
            if source not in sources:
                _fail(problems, f"{where}: votes[{kind!r}] cites source "
                                f"{source!r}, which meta.source_runs does not list")
                sound = False
            elif _is_int(sources.get(source)) and entry[1] > sources[source]:
                _fail(problems, f"{where}: votes[{kind!r}][{source!r}] was last "
                                f"seen on run {entry[1]}, but that source has "
                                f"only {sources[source]} run(s)")
                sound = False

    # Only meaningful once the votes themselves are sound.
    if sound and e.get("kind") in KIND_ORDER and e["kind"] != resolve_kind(votes):
        _fail(problems, f"{where}: kind is {e['kind']!r}, but its votes resolve "
                        f"to {resolve_kind(votes)!r}")


def _check_edges(
    edges: Any, sources: dict[str, Any] | None, problems: list[str]
) -> None:
    if not isinstance(edges, list):
        _fail(problems, "edges is not an array")
        return
    if len(edges) > MAX_POINTS:
        _fail(problems, f"{len(edges):,} edge records — the format holds at most "
                        f"{MAX_POINTS:,}")
    seen: dict[tuple[int, int, str], int] = {}
    for i, e in enumerate(edges):
        before = len(problems)
        _check_edge(e, f"edges[{i}]", sources, problems)
        if len(problems) != before:
            continue  # its geometry is already in question; don't key on it
        key = edge_key(e)
        first = seen.get(key)
        if first is not None:
            # Two records for one metre of one side is the contradiction the
            # voting grid exists to prevent; a consumer would draw both.
            _fail(problems, f"edges[{i}] repeats the metre already held by "
                            f"edges[{first}] ({key[0]}, {key[1]}, {key[2]})")
        else:
            seen[key] = i


def _check_finish(crossings: Any, problems: list[str]) -> None:
    if not isinstance(crossings, list):
        _fail(problems, "finish_crossings is not an array")
        return
    if len(crossings) > MAX_FINISH_CROSSINGS:
        _fail(problems, f"{len(crossings)} finish crossings — the format keeps "
                        f"at most {MAX_FINISH_CROSSINGS}")
    for i, c in enumerate(crossings):
        if not isinstance(c, dict):
            _fail(problems, f"finish_crossings[{i}] is not an object")
            continue
        for field in ("x", "z", "hx", "hz", "lap"):
            if not _is_number(c.get(field)):
                _fail(problems, f"finish_crossings[{i}]: {field} is "
                                f"{c.get(field)!r}, not a number")


def _check_corners(corners: Any, problems: list[str]) -> None:
    if not isinstance(corners, list):
        _fail(problems, "corners is not an array")
        return
    numbers: set[int] = set()
    for i, c in enumerate(corners):
        if not isinstance(c, dict):
            _fail(problems, f"corners[{i}] is not an object")
            continue
        n = c.get("n")
        if not _is_int(n) or n < 1:
            _fail(problems, f"corners[{i}]: n is {n!r}, not a corner number")
        elif n in numbers:
            _fail(problems, f"corners[{i}]: corner {n} is numbered twice")
        else:
            numbers.add(n)
        if not _point(c.get("apex")):
            _fail(problems, f"corners[{i}]: apex is not a position")
        for field in ("entry", "exit"):
            if c.get(field) is not None and not _point(c[field]):
                _fail(problems, f"corners[{i}]: {field} is neither a position "
                                "nor null")
        if c.get("direction") is not None and c["direction"] not in DIRECTIONS:
            _fail(problems, f"corners[{i}]: direction is {c['direction']!r} — "
                            f"{', '.join(DIRECTIONS)} or null")
        for field in ("name", "note"):
            if not isinstance(c.get(field, ""), str):
                _fail(problems, f"corners[{i}]: {field} is not text")


def _check_sections(sections: Any, problems: list[str]) -> None:
    # Thinner than the rest on purpose: no bundle here carries a section yet,
    # and inventing constraints for records nobody has written would reject
    # the first real one. What canonical form needs is checked; no more.
    if not isinstance(sections, list):
        _fail(problems, "sections is not an array")
        return
    for i, s in enumerate(sections):
        if not isinstance(s, dict):
            _fail(problems, f"sections[{i}] is not an object")
            continue
        if not _is_int(s.get("n")) or s["n"] < 1:
            _fail(problems, f"sections[{i}]: n is {s.get('n')!r}, not a "
                            "section number")
        if not isinstance(s.get("name", ""), str):
            _fail(problems, f"sections[{i}]: name is not text")


def validate_document(doc: Any) -> dict[str, Any]:
    """Return the document if it is a well-formed v4 bundle, else raise.

    Raises `ValueError` naming what is wrong, in the terms a contributor can
    act on. Structural failures raise on their own: there is nothing useful
    to say about the records of a file that is not a bundle at all.
    """
    if not isinstance(doc, dict):
        raise ValueError(f"not a bundle document (found {type(doc).__name__})")
    if doc.get("format") != BUNDLE_FORMAT:
        raise ValueError(f"format is {doc.get('format')!r}, "
                         f"not {BUNDLE_FORMAT!r}")

    version = doc.get("version")
    if not _is_int(version):
        raise ValueError(f"version is {version!r}, not a format version")
    if version > BUNDLE_VERSION:
        raise ValueError(f"is format v{version}; this repository stores "
                         f"v{BUNDLE_VERSION} and will not guess at fields it "
                         "does not know")
    if version < BUNDLE_VERSION:
        # No upgrade path here on purpose. v1-v3 count votes per run with no
        # source id, and there is no honest way to invent the id those counts
        # belong to — a wrong one would merge two people's evidence as if it
        # were one person's.
        raise ValueError(f"is format v{version}; this repository stores "
                         f"v{BUNDLE_VERSION}. v{version} has no source id on "
                         "its votes, so it cannot be upgraded here")

    problems: list[str] = []
    meta = doc.get("meta")
    _check_meta(meta, problems)
    sources = meta.get("source_runs") if isinstance(meta, dict) else None
    _check_edges(doc.get("edges"),
                 sources if isinstance(sources, dict) and sources else None,
                 problems)
    _check_finish(doc.get("finish_crossings", []), problems)
    _check_corners(doc.get("corners", []), problems)
    _check_sections(doc.get("sections", []), problems)

    if problems:
        shown = problems[:MAX_REPORTED]
        if len(problems) > MAX_REPORTED:
            shown.append("... and more")
        raise ValueError("; ".join(shown))
    return doc
