"""Add (or update) a bundle in this repository from an app export.

    python tools/add_bundle.py ~/Downloads/dragon-trail-gardens.json
    python tools/add_bundle.py --from-app http://gt7.local:8000

The file is validated, named after its confirmed official configuration, and
written in canonical form. If a bundle for that configuration is already here,
the two are **merged** rather than one replacing the other — that is the whole
point of the format's per-source vote counting, and it means a second person's
evidence adds to the first's instead of overwriting it.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import canonical  # noqa: E402
from build_index import configurations, slugify  # noqa: E402
from bundle_format import merge_edges, merge_finish, validate_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TRACKS = ROOT / "tracks"
CATALOG = ROOT / "catalog" / "tracks.json"


def target_name(doc: dict) -> str:
    official = doc["meta"].get("official") or {}
    by_id = {c["official_id"]: c
             for c in configurations(json.loads(CATALOG.read_text(encoding="utf-8")))}
    cfg = by_id.get(official.get("official_id", ""))
    if cfg is None:
        raise SystemExit(
            "This bundle names no official GT7 configuration, so there is nowhere to "
            "file it. Confirm the layout in the app's Tracks view and export again."
        )
    return slugify(cfg["official_name"]) + ".json"


def merge_into(existing: dict, incoming: dict) -> dict:
    """Same rules the app applies: evidence adds up, authored work is kept."""
    out = dict(existing)
    out["edges"] = merge_edges(existing["edges"], incoming["edges"])
    out["finish_crossings"] = merge_finish(
        existing["finish_crossings"], incoming["finish_crossings"]
    )
    runs = dict(existing["meta"]["source_runs"])
    for source, count in incoming["meta"]["source_runs"].items():
        # Each source's own highest run count — adding them would count the
        # same runs again every time the same file is contributed twice.
        runs[source] = max(runs.get(source, 0), count)
    out["meta"] = {
        **existing["meta"],
        "source_runs": dict(sorted(runs.items())),
        "runs": sum(runs.values()),
        "updated_at": max(existing["meta"].get("updated_at", ""),
                          incoming["meta"].get("updated_at", "")),
    }
    out["corners"] = existing["corners"] or incoming["corners"]
    out["sections"] = existing["sections"] or incoming["sections"]
    return out


def add(doc: dict) -> Path:
    path = TRACKS / target_name(doc)
    if path.exists():
        before = len(json.loads(path.read_text(encoding="utf-8"))["edges"])
        merged = merge_into(validate_document(
            json.loads(path.read_text(encoding="utf-8"))), doc)
        print(f"merging into existing {path.name}: {before:,} -> "
              f"{len(merged['edges']):,} m of border, "
              f"{len(merged['meta']['source_runs'])} source(s)")
        doc = merged
    TRACKS.mkdir(exist_ok=True)
    path.write_text(canonical.dumps(doc), encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    docs: list[dict] = []
    if argv[0] == "--from-app":
        base = argv[1].rstrip("/") if len(argv) > 1 else "http://localhost:8000"
        listing = json.load(urllib.request.urlopen(f"{base}/api/track-bundles"))
        for row in listing:
            with urllib.request.urlopen(f"{base}/api/track-bundles/{row['slug']}") as r:
                docs.append(json.load(r))
        print(f"fetched {len(docs)} bundle(s) from {base}")
    else:
        docs = [json.loads(Path(a).read_text(encoding="utf-8")) for a in argv]

    added = 0
    for raw in docs:
        try:
            doc = validate_document(raw)
        except ValueError as exc:
            print(f"skipped: {exc}", file=sys.stderr)
            continue
        if not (doc["meta"].get("official") or {}).get("official_id"):
            print(f"skipped {doc['meta']['track']!r}: no confirmed official layout",
                  file=sys.stderr)
            continue
        print("wrote", add(doc).relative_to(ROOT))
        added += 1
    if added:
        print("\nnext: gt7-tracks build-index, then gt7-tracks build-signatures\n"
              "      (or python tools/build_index.py, python tools/build_signatures.py)")
    return 0 if added else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
