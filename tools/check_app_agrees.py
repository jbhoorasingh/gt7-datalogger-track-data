"""Assert the app still accepts every bundle this repository ships.

`bundle_format.py` defines v4 here so that the tools run without installing
the app. The app implements v4 as well, which means there are two
definitions of one format and they can drift apart — the exact failure the
original "import the validator" plan existed to prevent.

This is the guard. It installs nothing and decides nothing on its own: it
hands each committed bundle to `gt7-datalogger`'s own `validate_document`
and checks that the app takes it as-is.

"As-is" is the part that matters. A bundle the app *upgrades* has been
accepted, but it has also been changed, and a repository whose files the app
silently rewrites on load is a repository of stale files. So a version bump,
a dropped record, a renumbered corner and a rewritten source id all fail
here, and each says which file and what moved.

This runs in CI against the app's default branch, so it is a report about
the app as it is today rather than a check a contributor has to satisfy.
Failure means the format moved and this repository has not followed yet — it
does not mean the bundle under review is bad.

    python tools/check_app_agrees.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bundle_format  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TRACKS = ROOT / "tracks"

try:
    from app.processing import track_bundle
except ImportError:
    print(
        "This check needs the app, which the repository's own tools do not:\n"
        "  pip install "
        '"gt7-datalogger @ git+https://github.com/jbhoorasingh/gt7-datalogger'
        '@main#subdirectory=backend"',
        file=sys.stderr,
    )
    raise SystemExit(2) from None


def compare(name: str, ours, theirs) -> str | None:
    if ours == theirs:
        return None
    return f"{name}: we ship {ours!r}, the app makes it {theirs!r}"


def check(path: Path) -> list[str]:
    """What the app changed about one bundle, if anything."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    try:
        got = track_bundle.validate_document(doc)
    except ValueError as exc:  # BundleError subclasses ValueError
        return [f"the app rejects it: {exc}"]

    # Read both sides with .get: a committed file that is somehow not v4 is
    # something to report, not something to crash on.
    ours_meta = doc.get("meta") or {}
    theirs_meta = got.get("meta") or {}

    def count(where: dict, key: str) -> int:
        return len(where.get(key) or [])

    drift = [
        compare("version", doc.get("version"), got.get("version")),
        compare("edge count", count(doc, "edges"), count(got, "edges")),
        compare("finish crossings", count(doc, "finish_crossings"),
                count(got, "finish_crossings")),
        compare("corner count", count(doc, "corners"), count(got, "corners")),
        compare("section count", count(doc, "sections"), count(got, "sections")),
        compare("meta.source_runs", ours_meta.get("source_runs"),
                theirs_meta.get("source_runs")),
        compare("meta.runs", ours_meta.get("runs"), theirs_meta.get("runs")),
        # Corner numbering is authored, and the app renumbers on import; if it
        # renumbers ours, the numbers a contributor typed are not the numbers
        # a reader would see.
        compare("corner numbering",
                [c.get("n") for c in doc.get("corners") or []],
                [c.get("n") for c in got.get("corners") or []]),
    ]
    return [d for d in drift if d]


def main() -> int:
    app_version = getattr(track_bundle, "BUNDLE_VERSION", None)
    print(f"this repository stores v{bundle_format.BUNDLE_VERSION}; "
          f"the installed app reads v{app_version}")

    if not hasattr(track_bundle, "validate_document"):
        # The app predates having a validator at all, which is where this
        # repository's copy of the format came from in the first place.
        print(f"\nThe installed app (v{app_version}) has no validate_document, "
              "so there is nothing to compare against. It predates the "
              "shared format; there is no drift to report and nothing here "
              "is verified.", file=sys.stderr)
        return 1

    failures: list[str] = []
    if app_version != bundle_format.BUNDLE_VERSION:
        # Reported, not fatal on its own: what settles it is whether the app
        # still takes the files. A newer app that reads v4 happily is fine.
        print(f"note: the app is on v{app_version} — the checks below are "
              "what decides whether that matters")

    files = sorted(TRACKS.glob("*.json"))
    if not files:
        print("no bundles yet — nothing to check")
        return 0

    for path in files:
        problems = check(path)
        if problems:
            failures.extend(f"{path.name}: {p}" for p in problems)
            print(f"{path.name}: DRIFT")
            for problem in problems:
                print(f"    {problem}")
        else:
            print(f"{path.name}: ok — the app takes it unchanged")

    if failures:
        print(
            f"\nThe app and tools/bundle_format.py no longer agree about "
            f"{len(failures)} thing(s).\n"
            "This is not a problem with the bundle under review. The format "
            "moved in the app and this repository has not followed: reconcile "
            "tools/bundle_format.py with the app's track_bundle.py, and "
            "re-export the bundles if the on-disk shape changed.",
            file=sys.stderr,
        )
        return 1
    print(f"\n{len(files)} bundle(s) — the app accepts every one unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
