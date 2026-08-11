# Contributing a surveyed track

## 1. Survey it

In GT7 Datalogger, open **Survey**, name the circuit, and drive. Borders the
surface data can see trace themselves; walls and paved run-off limits need
manual marking, because the game reports both as plain tarmac. A few laps
gives you the shape; the Survey view's completeness card tells you where the
gaps still are.

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

```bash
pip install "gt7-datalogger @ git+https://github.com/jbhoorasingh/gt7-datalogger@main#subdirectory=backend"

python tools/add_bundle.py ~/Downloads/deep-forest-raceway.json
# ...or pull everything straight out of a running app:
python tools/add_bundle.py --from-app http://gt7.local:8000

python tools/build_index.py
```

`add_bundle.py` validates the file, names it after its configuration, and
writes it in this repository's canonical form. If a bundle for that
configuration is already here, the two are **merged**.

Then open a pull request.

## 4. What CI checks

- The app's own validator accepts the document (`tools/validate.py`). The
  validator is imported from the app rather than copied, so it cannot drift.
- It is format v4 and names a configuration that exists in the catalog.
- The filename matches that configuration.
- The file is in canonical form — `python tools/validate.py --fix` writes it.
- `index.json` matches the bundles — `python tools/build_index.py` rebuilds it.

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
```

The merge is defined by the format (each source's own highest run count wins,
hand-marked kinds outrank inferred ones) and it is idempotent, so replaying
your export onto the updated file is always correct and never double-counts.

## Reviewing

The [site](https://jbhoorasingh.github.io/gt7-datalogger-track-data/) draws any
bundle in the repository. For a pull request, the quick checks are: does the
outline look like the circuit, are the borders continuous, do the wall and
run-off marks sit where walls and run-off actually are, and is the finish line
on the finish line.
