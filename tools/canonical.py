"""The on-disk form a bundle takes in THIS repository.

The app writes bundles minified — one 700 kB line — which is right for a file
rewritten every 60 seconds by a running survey and wrong for a file living in
git. A single line means git stores a whole new blob for every re-survey, no
delta, and a pull request nobody can read.

Canonical form fixes both without changing the format: the same document, the
same bytes to within newlines, but **one record per line** and **records sorted
by position**, so

  * a diff shows the metres that actually changed,
  * git can delta successive versions,
  * two people who surveyed the same circuit produce files that interleave
    predictably instead of differing everywhere from the first metre.

It is still ordinary JSON — the app loads a canonical file with no conversion,
and re-minifies it the next time it saves.
"""

from __future__ import annotations

import json
from typing import Any

# Key order for the record types, so a rewrite never reorders anything.
EDGE_KEYS = ("x", "z", "y", "hx", "hz", "side", "kind", "votes", "run", "tw")
FINISH_KEYS = ("x", "z", "hx", "hz", "lap")
CORNER_KEYS = ("n", "name", "direction", "apex", "entry", "exit", "note")
SECTION_KEYS = ("n", "name", "start", "end")
META_KEYS = ("track", "runs", "source_runs", "updated_at", "official")


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _ordered(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    """One record on one line, keys in a fixed order, unknown keys last."""
    out = {k: record[k] for k in keys if k in record}
    out.update({k: v for k, v in record.items() if k not in out})
    return _compact(out)


def _edge(record: dict[str, Any]) -> str:
    edge = dict(record)
    # Votes are a nested dict; sort both levels or two writers of the same
    # evidence produce different bytes.
    votes = edge.get("votes") or {}
    edge["votes"] = {
        kind: {src: votes[kind][src] for src in sorted(votes[kind])}
        for kind in sorted(votes)
    }
    return _ordered(edge, EDGE_KEYS)


def _records(items: list[dict[str, Any]], render) -> str:
    if not items:
        return "[]"
    body = ",\n  ".join(render(item) for item in items)
    return "[\n  " + body + "\n ]"


def dumps(doc: dict[str, Any]) -> str:
    """A bundle document as this repository stores it."""
    edges = sorted(
        doc.get("edges", []),
        # Sorted by POSITION, not by when it was first driven. Insertion order
        # is an accident of one person's laps; position is a property of the
        # circuit, so everybody's file agrees on where a metre belongs.
        key=lambda e: (e["side"], round(e["x"], 3), round(e["z"], 3)),
    )
    meta = doc["meta"]
    parts = [
        f' "format": {_compact(doc["format"])}',
        f' "version": {doc["version"]}',
        " \"meta\": {\n  "
        + ",\n  ".join(
            f"{_compact(k)}: {_compact(meta[k])}" for k in META_KEYS if k in meta
        )
        + "\n }",
        f' "edges": {_records(edges, _edge)}',
        " \"finish_crossings\": "
        + _records(doc.get("finish_crossings", []), lambda r: _ordered(r, FINISH_KEYS)),
        " \"corners\": "
        + _records(doc.get("corners", []), lambda r: _ordered(r, CORNER_KEYS)),
        " \"sections\": "
        + _records(doc.get("sections", []), lambda r: _ordered(r, SECTION_KEYS)),
    ]
    return "{\n" + ",\n".join(parts) + "\n}\n"


def loads(text: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(text)
    return doc
