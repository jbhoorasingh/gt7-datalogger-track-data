# Contributing a surveyed track

## 1. Survey it

In GT7 Datalogger, open **Survey**, name the circuit, and drive. Borders the
surface data can see trace themselves; walls and paved run-off limits need
manual marking, because the game reports both as plain tarmac. A few laps
gives you the shape; the Survey view's completeness card tells you where the
gaps still are.

Start from what is already shared rather than from zero: newer dataloggers
list this repository in the Tracks view's **Shared bundles** panel and pull a
circuit's bundle straight in (older ones: **Import bundle…** with a file from
the [site](https://jbhoorasingh.github.io/gt7-datalogger-track-data/)). Your
laps then extend the shared record, and contributing back
sends only what you added.

## 2. Confirm the official layout

Open **Tracks**, find the circuit, and confirm the suggested official layout.

This is not optional here. GT7 broadcasts no track identifier, so a bundle's
only self-description is the name somebody typed — and a typed name cannot
place a file reliably. `Lago Maggiore - East` and `Lago Maggiore - East End`
are one circuit or two depending on who typed them. The confirmed
`official_id` is what this repository files bundles by, and CI rejects a
bundle without one.

Labelling the corners while you are there is welcome and is the highest-value
thing in a bundle after the borders themselves.

## 3. Add it

Nothing to install — the tools are standard-library Python 3.12.

```bash
# See what your running app has, without writing anything:
python tools/pull_from_app.py http://gt7.local:8000 --list

# Then take one, or all of them:
python tools/pull_from_app.py http://gt7.local:8000 --only deep-forest
# ...or start from a file you exported:
python tools/add_bundle.py ~/Downloads/deep-forest-raceway.json

python tools/build_index.py
python tools/build_signatures.py
```

Either route validates the file, names it after its configuration, and writes
it in this repository's canonical form. If a bundle for that configuration is
already here, the two are **merged**.

`pull_from_app.py` only ever reads your app. It is the mirror of
`import_into_app.py`, which is the one that writes to it.

Then open a pull request.

## 4. What CI checks

- The document is a well-formed bundle (`tools/validate.py`). The format is
  defined by `tools/bundle_format.py` — this repository's own
  standard-library copy of v4, which the app (datalogger 0.5+) reads and
  writes too; see that module's header for how the two relate.
- It is format v4 and names a configuration that exists in the catalog.
- The filename matches that configuration.
- The file is in canonical form — `python tools/validate.py --fix` writes it.
- `index.json` matches the bundles — `python tools/build_index.py` rebuilds it.
- `signatures.json` matches the bundles and `vendor/circuits.json` —
  `python tools/build_signatures.py` rebuilds it. A new bundle changes it:
  a surveyed configuration outranks the recorded lap that stood in for it, so
  the row's bounding box becomes the road you surveyed rather than one line
  through it. Its `path` is still borrowed from the recording — a bundle is
  edge records sorted by position, not a line down the road — and the build
  checks the borrowed line against your survey's own `hx`/`hz` headings before
  trusting it, so a recording of the *reverse* layout cannot be attached to a
  forward row. The build prints what it dropped, flagged and could not tell
  apart on every run; `tools/test_build_signatures.py` covers the rules.

A separate `vendor` workflow refreshes `vendor/circuits.json` from upstream
weekly, and merges the refresh itself when every check passes. It opens a draft
pull request instead when a capture matches no configuration in the catalog, or
when a check fails — see "How this stays current" in the README. It does not run
on your pull request and cannot affect it.

A separate `app-agrees` job installs the datalogger and checks it still
accepts every bundle here unchanged. If only that job is red, nothing is
wrong with your pull request: the format has moved in the app and this
repository has not caught up yet.

## Canonical form, and why

The app writes bundles minified: one 700 kB line. That is right for a file a
running survey rewrites every sixty seconds, and wrong for a file in git — no
delta between versions, and a pull request nobody can read.

In this repository the same document is stored one record per line, sorted by
position. Same format, same bytes to within newlines, but a diff shows the
metres that actually changed and successive versions delta properly. The app
loads a canonical file unchanged.

Sorting by position rather than by when a metre was first driven matters for
the same reason: insertion order is an accident of one person's laps, while
position is a property of the circuit, so two contributors' files agree on
where a record belongs instead of differing from the first line.

## Merge conflicts

Two pull requests touching one track will conflict textually — they are both
rewriting the same records. Do not hand-resolve it. Rebase and re-run:

```bash
python tools/add_bundle.py <your export>   # merges into whatever is now on main
python tools/build_index.py
python tools/build_signatures.py
```

The merge is defined by the format (each source's own highest run count wins,
hand-marked kinds outrank inferred ones) and it is idempotent, so replaying
your export onto the updated file is always correct and never double-counts.

## Updating a track that is already here

Same commands — there is no separate update path. `add_bundle.py` merges your
document into the file on `main`: the voting merge keeps each source's own
highest run count, so it never double-counts your earlier contributions, and
hand-labelled corners already in the repository are kept unless the file has
none. The round trip is the intended workflow:

1. Pull the circuit's shared bundle in the app (Tracks → **Shared bundles**),
   or import it from the pack.
2. Drive — more laps, missing borders, corner labels.
3. `python tools/pull_from_app.py http://gt7.local:8000 --only <slug>`, rebuild
   the index, open a pull request. The diff is only the metres and votes you
   added, which is what makes it reviewable.

## Drawn metres

The track editor (`python tools/track_editor.py`) can *draw* border geometry —
pen, curve, freehand and connect tools that lay records down every metre along
a path.
That is a different kind of thing from the rest of a bundle: an edge record is
normally evidence that somebody drove past that metre, and a drawn one is
somebody's opinion about where the road is.

So drawn points are filed under a source id of their own, `drawn-` and eight
hex digits, which no installation id looks like. They are legal v4 records and
CI accepts them, but they are visible as drawn in the diff and they are counted
separately in the run total. Use them to repair a gap you cannot re-drive, say
so in the pull request, and prefer another lap where a lap is possible — the
road only really gets better by being driven.

Drawing never overwrites a surveyed metre; a drawn point landing on one is
dropped — including the two records a **Connect** bridge is anchored to.

**Connect** is the one to reach for first. It bridges a hole in a border from
the two surveyed records either side of it, curving along their recorded
headings rather than cutting a chord, and you can push the curve into shape
before committing. It infers far less than tracing the gap freehand does,
because both of its ends are real measurements.

Run the editor from `gt7-tracks gui` and **Save into tracks/** merges your
corrections straight in, on the same terms as `add_bundle.py` — there is no
download-then-run-a-script step. Rebuild the index and the signatures
afterwards, as for any other change.

## Reviewing

The [site](https://jbhoorasingh.github.io/gt7-datalogger-track-data/) draws any
bundle in the repository. For a pull request, the quick checks are: does the
outline look like the circuit, are the borders continuous, do the wall and
run-off marks sit where walls and run-off actually are, and is the finish line
on the finish line. If `meta.source_runs` gained a `drawn-…` entry, some of
those metres were drawn rather than driven — worth a look at where, and worth
asking whether a lap would have done instead.
