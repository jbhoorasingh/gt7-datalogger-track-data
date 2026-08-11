"""Check every bundle in tracks/ before it can be merged.

The format itself is checked by `bundle_format.validate_document`, which is
where v4 is defined — see that module for why the definition lives here and
not in the app.

On top of the format, this repository asks for three things the format does
not:

1. **A confirmed official configuration.** A bundle whose `meta.official` is
   null cannot be placed in the index, and its name alone can't be trusted to
   place it — that ambiguity is what the official id exists to remove.
2. **Canonical on-disk form.** One record per line, sorted by position, so
   diffs are reviewable and git can delta successive versions.
3. **A filename matching the configuration**, so a contributor and a reviewer
   are looking at the same track without opening the file.

    python tools/validate.py [--fix]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import canonical  # noqa: E402
from build_index import configurations, slugify  # noqa: E402
from bundle_format import validate_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TRACKS = ROOT / "tracks"
CATALOG = ROOT / "catalog" / "tracks.json"


def main(argv: list[str]) -> int:
    fix = "--fix" in argv
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_id = {c["official_id"]: c for c in configurations(catalog)}
    files = sorted(TRACKS.glob("*.json"))
    if not files:
        print("no bundles yet — nothing to validate")
        return 0

    failures: list[str] = []
    for path in files:
        raw = path.read_text(encoding="utf-8")
        try:
            doc = validate_document(json.loads(raw))
        except ValueError as exc:
            failures.append(f"{path.name}: {exc}")
            continue

        official = doc["meta"].get("official")
        if not official or not official.get("official_id"):
            failures.append(
                f"{path.name}: no confirmed official layout. Open the track in the "
                "app's Tracks view and confirm the match, then re-export."
            )
        elif official["official_id"] not in by_id:
            failures.append(f"{path.name}: official_id {official['official_id']!r} "
                            "is not in the catalog")
        else:
            want = slugify(by_id[official["official_id"]]["official_name"]) + ".json"
            if path.name != want:
                failures.append(f"{path.name}: should be named {want}")

        expected = canonical.dumps(doc)
        if raw != expected:
            if fix:
                path.write_text(expected, encoding="utf-8")
                print(f"{path.name}: rewritten in canonical form")
            else:
                failures.append(f"{path.name}: not in canonical form — "
                                "run: python tools/validate.py --fix")

        edges = doc["edges"]
        print(f"{path.name}: ok — {len(edges):,} m of border, "
              f"{doc['meta']['runs']} run(s) from "
              f"{len(doc['meta']['source_runs'])} source(s), "
              f"{len(doc['corners'])} corner(s)")

    if failures:
        print("\nFAILED:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"\n{len(files)} bundle(s) valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
