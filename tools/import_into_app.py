"""Load this pack's bundles into a running GT7 Datalogger.

    python import_into_app.py                       # -> http://localhost:8000
    python import_into_app.py http://gt7.local:8000
    python import_into_app.py http://gt7.local:8000 --only dragon-trail-gardens

This goes through the app's import endpoint, which **merges**. Copying the
files into `data/track-bundles/` instead would overwrite whatever you have
surveyed yourself — your runs and this pack's runs are different evidence of
the same metres, and merging is what keeps both.

Your own hand-labelled corners and your confirmed layout matches are never
replaced by an import.

Needs the app's admin token if one is set: pass --token, or set GT7_ADMIN_TOKEN.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """Return the pack bundle directory, or this repository's tracks directory."""
    packed = HERE / "tracks"
    if packed.is_dir():
        return packed
    return HERE.parent / "tracks"


def post(base: str, doc: bytes, token: str) -> dict:
    request = urllib.request.Request(
        f"{base}/api/track-bundles/import",
        data=doc,
        headers={"Content-Type": "application/json",
                 **({"X-API-Key": token} if token else {})},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        result: dict = json.load(response)
        return result


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    base = (args[0] if args else "http://localhost:8000").rstrip("/")
    only = ""
    token = os.environ.get("GT7_ADMIN_TOKEN", "")
    for i, arg in enumerate(argv):
        if arg == "--only" and i + 1 < len(argv):
            only = argv[i + 1]
        if arg == "--token" and i + 1 < len(argv):
            token = argv[i + 1]

    tracks = sorted(bundle_dir().glob("*.json"))
    if only:
        tracks = [p for p in tracks if only in p.stem]
    if not tracks:
        print("no bundles found next to this script", file=sys.stderr)
        return 1

    failed = 0
    for path in tracks:
        try:
            result = post(base, path.read_bytes(), token)
        except urllib.error.HTTPError as exc:
            print(f"{path.stem}: {exc.code} {exc.read().decode()[:200]}", file=sys.stderr)
            failed += 1
            continue
        except OSError as exc:
            print(f"cannot reach {base}: {exc}", file=sys.stderr)
            return 1
        kept = " (kept your own corner labels)" if result.get("corners_kept") else ""
        print(f"{result['track']}: +{result['added_points']:,} m of border "
              f"({result['points']:,} total, {result['sources']} source(s)){kept}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
