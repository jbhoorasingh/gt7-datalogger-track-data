"""Generate index.json: every GT7 configuration, and what we have for it.

The index lists all 121 official configurations whether or not anybody has
surveyed them — the empty rows are the point. A list of only the tracks we
have says nothing about what is missing, and "what is missing" is the whole
question this repository exists to answer.

It carries no timestamp on purpose: the index is a pure function of
catalog/tracks.json and tracks/*.json, so CI can regenerate it and fail the
build when the committed copy is stale, and a rebuild never produces a diff of
its own.

    python tools/build_index.py [--check]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "tracks.json"
TRACKS = ROOT / "tracks"
INDEX = ROOT / "index.json"

MANUAL_KINDS = ("wall", "runoff", "edge")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unnamed"


def configurations(catalog: dict) -> list[dict]:
    """Every drivable configuration, reverse layouts included, flattened.

    A reverse layout is a separate configuration: its own official id and turn
    count, and — because the car drives the other way round — its own borders,
    so its own bundle.
    """
    out: list[dict] = []
    for track in catalog.get("tracks", []):
        for layout in track.get("layouts", []):
            base = {
                "official_id": layout.get("official_id", ""),
                "track": track["name"],
                "layout": layout["name"],
                "official_name": layout.get("official_name", layout["name"]),
                "country": track.get("country_name", ""),
                "turns": layout.get("turns", 0) or 0,
                "length_m": layout.get("length_m", 0) or 0,
                "elevation_m": layout.get("elevation_m"),
                "type": layout.get("type", ""),
                "reverse": False,
            }
            out.append(base)
            reverse = layout.get("reverse")
            if reverse:
                out.append({
                    **base,
                    "official_id": reverse.get("official_id", ""),
                    "official_name": f"{base['official_name']} (Reverse)",
                    "turns": reverse.get("turns", base["turns"]) or base["turns"],
                    "reverse": True,
                })
    return out


def bundle_summary(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    edges = doc.get("edges", [])
    with_y = sum(1 for e in edges if e.get("y") is not None)
    return {
        "file": f"tracks/{path.name}",
        "track": doc["meta"]["track"],
        "official_id": (doc["meta"].get("official") or {}).get("official_id", ""),
        "points": len(edges),
        "manual_points": sum(1 for e in edges if e.get("kind") in MANUAL_KINDS),
        "elevation_pct": round(100 * with_y / len(edges), 1) if edges else 0.0,
        "runs": doc["meta"].get("runs", 0),
        "sources": len(doc["meta"].get("source_runs", {})),
        "finish_crossings": len(doc.get("finish_crossings", [])),
        "corners": len(doc.get("corners", [])),
        "sections": len(doc.get("sections", [])),
        "updated_at": doc["meta"].get("updated_at", ""),
        "bytes": path.stat().st_size,
    }


def build() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    configs = configurations(catalog)
    bundles = [bundle_summary(p) for p in sorted(TRACKS.glob("*.json"))]

    # Bundles are matched to a configuration by the OFFICIAL ID a human
    # confirmed, never by name: a name is typed, and "Lago Maggiore - East"
    # versus "- East End" is exactly the ambiguity the id exists to remove.
    by_id = {b["official_id"]: b for b in bundles if b["official_id"]}
    unmatched = [b for b in bundles if not b["official_id"] or b["official_id"] not in
                 {c["official_id"] for c in configs}]

    rows = []
    for cfg in configs:
        bundle = by_id.get(cfg["official_id"])
        rows.append({
            **cfg,
            "slug": slugify(cfg["official_name"]),
            "bundle": {k: v for k, v in bundle.items() if k != "official_id"}
            if bundle else None,
        })

    surveyed = [r for r in rows if r["bundle"]]
    return {
        "format": "gt7-datalogger-track-index",
        "version": 1,
        "bundle_format_version": 4,
        "counts": {
            "configurations": len(rows),
            "surveyed": len(surveyed),
            "points": sum(r["bundle"]["points"] for r in surveyed),
            "corners_labelled": sum(r["bundle"]["corners"] for r in surveyed),
        },
        "unmatched_bundles": [b["file"] for b in unmatched],
        "configurations": rows,
    }


def main(argv: list[str]) -> int:
    index = build()
    text = json.dumps(index, indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        current = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
        if current != text:
            print("index.json is stale — run: python tools/build_index.py")
            return 1
        print("index.json is up to date")
        return 0
    INDEX.write_text(text, encoding="utf-8")
    c = index["counts"]
    print(f"index.json: {c['surveyed']}/{c['configurations']} configurations surveyed, "
          f"{c['points']:,} m of border, {c['corners_labelled']} corners labelled")
    if index["unmatched_bundles"]:
        print("unmatched bundles (no confirmed official id):",
              ", ".join(index["unmatched_bundles"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
