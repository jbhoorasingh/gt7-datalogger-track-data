"""Pull surveyed tracks out of a running GT7 Datalogger into this repository.

    python tools/pull_from_app.py --list                 # what has the app got?
    python tools/pull_from_app.py                        # pull all of it
    python tools/pull_from_app.py --only deep-forest     # pull one
    python tools/pull_from_app.py http://gt7.local:8000

This is the direction `import_into_app.py` is not: the app is where surveying
happens, and this brings that work back here so it can be reviewed and shared.
Each bundle is merged into `tracks/` on the same terms as `add_bundle.py` —
nobody's evidence replaces anybody else's — so pulling the same track twice
after two more laps adds the two laps rather than starting again.

`--list` writes nothing and is the safe thing to run first. A bundle whose
layout the app has not confirmed is named in the listing but refused by a
pull, because there is no reliable way to file it: confirm the match in the
app's Tracks view first.

Needs the app's admin token if one is set: pass --token, or set
GT7_ADMIN_TOKEN.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_bundle import ROOT, add  # noqa: E402
from app_client import DEFAULT_BASE, AppError, fetch_bundle, list_bundles, normalise_base  # noqa: E402
from bundle_format import validate_document  # noqa: E402


def describe(row: dict) -> str:
    name = row["official_name"] or row["track"]
    parts = [f"{row['points']:,} m" if row["points"] else "no border yet"]
    if row["runs"]:
        parts.append(f"{row['runs']} run(s)")
    if row["updated_at"]:
        parts.append(f"last surveyed {row['updated_at'][:10]}")
    if not row["official_id"]:
        parts.append("layout not confirmed")
    return f"  {row['slug']:<38} {name}  ({', '.join(parts)})"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pull-from-app",
        description="Pull surveyed track bundles out of a running datalogger.",
    )
    parser.add_argument("base", nargs="?", default=DEFAULT_BASE,
                        help=f"app base URL (default: {DEFAULT_BASE})")
    parser.add_argument("--list", action="store_true", dest="listing",
                        help="show what the app has and write nothing")
    parser.add_argument("--only", metavar="SLUG", default="",
                        help="pull only bundles whose slug contains this")
    parser.add_argument("--token", metavar="TOKEN", default="",
                        help="admin API token (or set GT7_ADMIN_TOKEN)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv) if argv is not None else sys.argv[1:])
    token = args.token or os.environ.get("GT7_ADMIN_TOKEN", "")

    try:
        base = normalise_base(args.base)
        rows = list_bundles(base, token)
    except AppError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not rows:
        print(f"{base} has no track bundles yet.")
        return 1

    if args.only:
        rows = [row for row in rows if args.only in row["slug"]]
        if not rows:
            print(f"no bundle on {base} has a slug containing {args.only!r}", file=sys.stderr)
            return 1

    print(f"{base} — {len(rows)} bundle(s)")
    for row in rows:
        print(describe(row))
    if args.listing:
        print("\nNothing was written. Drop --list to pull these into tracks/.")
        return 0

    print()
    pulled = 0
    skipped = 0
    for row in rows:
        try:
            document = validate_document(fetch_bundle(base, row["slug"], token))
        except AppError as exc:
            print(f"{row['slug']}: {exc}", file=sys.stderr)
            skipped += 1
            continue
        except ValueError as exc:
            print(f"{row['slug']}: the app's copy is not a valid bundle: {exc}", file=sys.stderr)
            skipped += 1
            continue
        if not (document["meta"].get("official") or {}).get("official_id"):
            print(f"{row['slug']}: no confirmed official layout, so there is nowhere "
                  "to file it. Confirm the match in the app's Tracks view.", file=sys.stderr)
            skipped += 1
            continue
        print("wrote", add(document).relative_to(ROOT))
        pulled += 1

    if pulled:
        print(f"\npulled {pulled} bundle(s).\n"
              "next: gt7-tracks build-index, then gt7-tracks build-signatures\n"
              "      (or python tools/build_index.py, python tools/build_signatures.py)")
    return 1 if skipped and not pulled else 0


if __name__ == "__main__":
    raise SystemExit(main())
