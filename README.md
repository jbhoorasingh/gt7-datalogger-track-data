# GT7 track data

Surveyed border geometry for Gran Turismo 7 circuits — where the track edges
are, where the walls and paved run-off are, where the start/finish line is, and
what each corner is called.

**[Browse the tracks →](https://jbhoorasingh.github.io/gt7-datalogger-track-data/)**
· **[Download the latest pack →](https://github.com/jbhoorasingh/gt7-datalogger-track-data/releases/latest)**

Produced by, and consumed by,
[GT7 Datalogger](https://github.com/jbhoorasingh/gt7-datalogger). The data is
separate from the app on purpose: it changes every time somebody drives, and a
corrected corner label should not have to wait for a software release.

## What is in here

| path | what |
|---|---|
| `index.json` | **all 121 GT7 configurations**, with their official name, country, turn count and length — and, where one exists, the bundle we have |
| `tracks/<slug>.json` | one surveyed circuit, in the app's [track bundle format](https://jbhoorasingh.github.io/gt7-datalogger/reference/track-bundle-format/) (v4) |
| `signatures.json` | enough geometry — length, bounding box and the racing line in driving order — for the app to name a circuit from one lap, before anybody has named it by hand |
| `catalog/tracks.json` | the official GT7 track/layout metadata the index is built from |
| `vendor/` | third-party measurements the signatures lean on, and their licence |
| `site/` | the inspection page published to GitHub Pages — surveyed circuits draw their borders, the rest draw the one recorded lap behind their signature |
| `tools/` | add a bundle, rebuild the index and the signatures, validate everything — standard-library scripts, each runnable on its own |
| `gt7_track_tools/` | those same tools as one `gt7-tracks` command and a local GUI, built from one shared description of each tool |

The index lists **every** configuration, surveyed or not. A list of only what
we have would say nothing about what is missing, and what is missing is most of
the point.

`signatures.json` is the other way round: only the configurations we can
recognise. It exists because the app could not name a circuit until a human
named one, so a fresh install identified nothing and everything hanging off the
circuit name stayed empty. A surveyed bundle gives the best row; where there is
no survey, a vendored recording of a lap does.

Each row also carries the racing line, thinned to a point every 20 m and kept
**in the order it was driven**. That order is load-bearing. A length and a box
recognise a circuit but cannot tell a layout from its reverse, which has
exactly the same box and exactly the same length — and against 896 real laps
that misfiled 10 Deep Forest Reverse laps as Deep Forest Raceway, where they
pooled with the forward laps and competed for the same personal best. Walking a
lap along the line answers which way round it went. A reverse layout gets no row
of its own: its forward row names it, in `reverse`.

## Using it

Download the pack from the [latest release][latest], unzip it, and load it into
a running datalogger:

```bash
python import_into_app.py http://gt7.local:8000
```

That goes through the app's import endpoint, which **merges**: your own runs
and the pack's runs are different evidence of the same metres, and both are
kept. Your hand-labelled corners and your confirmed layout matches are never
replaced.

> Copying the files straight into `data/track-bundles/` instead would
> *overwrite* whatever you have surveyed yourself. Only do that for circuits
> you have nothing for.

[latest]: https://github.com/jbhoorasingh/gt7-datalogger-track-data/releases/latest

## The tools

Every script in `tools/` is also a subcommand of one CLI, and most are also a
form in a local GUI. That is not three implementations: the CLI, the GUI and
the scripts all read one registry of tool descriptions
(`gt7_track_tools/registry.py`), so a flag cannot exist in one place and be
quietly missing from another, and a run started from a browser form builds the
same argv you would have typed.

```bash
pip install -e .
```

That puts `gt7-tracks` on your path, along with the three dependencies the CLI
and GUI need. The scripts under `tools/` are unaffected by this and stay
standard-library only — if you would rather install nothing, everything below
still works in its `python tools/…` form, and CI runs it that way.

| command | what it does | script |
|---|---|---|
| `gt7-tracks pull-from-app [BASE]` | list what a running datalogger has surveyed, and merge the ones you want into `tracks/` | `pull_from_app.py` |
| `gt7-tracks add-bundle <file>…` | validate an exported bundle, name it after its configuration, merge it into `tracks/` | `add_bundle.py` |
| `gt7-tracks build-index` | rebuild `index.json` from `catalog/` and `tracks/` | `build_index.py` |
| `gt7-tracks build-signatures` | rebuild `signatures.json` from the surveys and the vendored captures | `build_signatures.py` |
| `gt7-tracks validate` | check every bundle's format, name, official id and canonical form | `validate.py` |
| `gt7-tracks vendor-captures` | refresh `vendor/circuits.json` from upstream gt-telemetry | `vendor_captures.py` |
| `gt7-tracks import-into-app [BASE]` | POST every bundle here into a running datalogger | `import_into_app.py` |
| `gt7-tracks check-app-agrees` | ask the app's own validator whether it still accepts every bundle unchanged | `check_app_agrees.py` |
| `gt7-tracks track-editor` | open the local bundle editor | `track_editor.py` |
| `gt7-tracks gui` | open the dashboard described below | — |

The options, which are the same on the script:

- `build-index`, `build-signatures`, `vendor-captures` take `--check` — compare
  against what is committed and exit non-zero if it is stale, writing nothing.
  This is what CI runs.
- `validate` takes `--fix`, which rewrites bundles into canonical form.
- `pull-from-app` takes `--list`, which shows what the app has and writes
  nothing; `--only SLUG`; and `--token TOKEN`. `BASE` defaults to
  `http://localhost:8000`. Run it with `--list` first — it is the only command
  here that tells you what is on the other end before it does anything.
- `add-bundle` takes `--from-app [BASE]`, which pulls every bundle out of a
  running app without listing them first. `pull-from-app` is the same job with
  a look before the leap.
- `vendor-captures` takes `--ref REF` to vendor a specific upstream git ref.
- `import-into-app` takes `--only SLUG` and `--token TOKEN`; `BASE` defaults to
  `http://localhost:8000`.
- `track-editor` and `gui` take `--port PORT` and `--no-browser`, which prints
  the URL rather than opening one. `--port 0` picks a free port, which is
  already what the editor does if you do not ask for one; the GUI defaults to
  8766 so the tab you left open yesterday still points at it.

### The GUI

```bash
gt7-tracks gui
```

Serves a dashboard on `http://127.0.0.1:8766/`, bound to loopback and nothing
else, and opens a browser at it. Each tool is a form generated from that same
registry — arguments, flags, defaults and all, with the admin token rendered as
a password field — and every run is recorded with its exact argv, streaming
stdout and stderr, exit code and duration while it runs. So the thing that goes
wrong at three in the morning is a run you can read afterwards rather than
scrollback you have already lost.

The forms are grouped in the order the work happens — get track data, rebuild
what is derived from it, check it, send it back to your app — rather than
alphabetically, and each field is labelled in words with the flag it becomes
shown beside it, so a GUI run and a typed run are visibly the same run. When a
command finishes, the card offers the commands it just made stale: adding a
bundle offers to rebuild the index, the signatures and then validate, because
that ordering is a property of the tools and the tools may as well say it.

Above the forms is **Your datalogger**: type its address, connect, and pick
from a list of what it has surveyed, with the point count, the run count and
the date of the last survey. A bundle whose layout the app has not confirmed is
listed and disabled with the reason, rather than quietly missing. Pulling the
ones you ticked starts one `pull-from-app` run each, with the argv you would
have typed — the panel is a nicer way to choose, not a second implementation.

The track editor is deliberately absent from that list of forms: it is a page
in its own right rather than a command with output to stream, so the dashboard
serves it rather than wrapping it.

## Contributing a track

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

```bash
gt7-tracks add-bundle ~/Downloads/deep-forest-raceway.json
gt7-tracks build-index
gt7-tracks build-signatures
```

...or, with nothing installed:

```bash
python tools/add_bundle.py ~/Downloads/deep-forest-raceway.json
python tools/build_index.py
python tools/build_signatures.py
```

Your bundle must name the official GT7 configuration it belongs to — confirm
the layout in the app's Tracks view before exporting. Without it there is no
reliable way to file the bundle, because a typed track name is not an
identifier and "Lago Maggiore - East" versus "- East End" is a real ambiguity.

If a bundle for that configuration already exists, yours is **merged** into it.
Nobody's evidence replaces anybody else's: every observation is stamped with
the installation that made it, so two people who each drove a metre once have
seen it twice between them.

## How this stays current

Data arrives here two ways.

**People surveying.** A pull request, reviewed, merged — the section above.
This is the only way a bundle is ever created, and it is the only way the road
itself gets better.

**The vendored captures, refreshed on a schedule.** The 69 configurations
nobody has surveyed have a signature only because
[gt-telemetry](https://github.com/zetetos/gt-telemetry) published a recording
of a lap of each. Those are vendored rather than fetched at build time, so a
build is reproducible offline — which is right, and which used to mean the data
only moved when somebody remembered to move it.

`.github/workflows/vendor.yml` now does the remembering. Weekly, it re-fetches
upstream, distils it, rebuilds `signatures.json`, runs the full check suite, and
**merges the result itself when everything is clean**. Nothing in that path is a
judgement, so nothing in it needs a person. It then asks the pack and the site
to republish, because a merge made by a workflow does not start one.

One case stops and waits: a capture whose name matches no configuration in
`catalog/tracks.json`. That is either a circuit worth a row or an upstream
rename worth a line in the generator's mapping table, and the file cannot tell
which. The build refuses it rather than skipping it quietly, and the refresh
opens a **draft pull request** with the new captures already on its branch, so
the decision is the only work left. Any failing check does the same.

So a silent week means upstream did not move, or moved and was fine. A pull
request from the refresh means it is asking you something.

Run it by hand with `gh workflow run vendor.yml`, or check upstream without
changing anything:

```bash
gt7-tracks vendor-captures --check
```

## Repairing recorded points

To inspect and correct bad edge records without re-surveying the circuit, run:

```bash
gt7-tracks track-editor
```

The local editor opens a bundle three ways: any circuit in `tracks/`, a
**running datalogger** — type its address, connect, and pick from what it has
surveyed — or a v4 bundle file from anywhere. It is also served from the GUI,
so `gt7-tracks gui` gets you both from one process.

The layout is two thin strips and then nothing but canvas. Everything that used
to sit in a permanent sidebar is either contextual — only the active tool's own
options are on screen, and the selection actions appear when there is a
selection — or a popover behind **Open** and **Layers**. The sidebar held more
than a screenful, which put the tool palette below the fold.

**Saving.** Run the editor from the GUI and it offers **Save into tracks/**,
which merges the edited document straight in. That is not a second
implementation of the merge: the server hands the document to the registered
`add-bundle` tool, so saving from the editor and typing
`gt7-tracks add-bundle` are one code path with one set of rules, and the save
appears in the run log next to everything else. Run the editor from
`gt7-tracks track-editor` instead and the button is absent — that server has no
write endpoints at all, and the page asks which one is behind it rather than
shipping two editors. **Download** is always there either way, and no source
file is ever overwritten in place.

The app is read through the local server rather than from the page, because a
browser will not let a page on loopback read `http://gt7.local:8000` unless the
datalogger opens itself to any local page, which is not a trade worth asking
for. Those two routes only ever GET: nothing in the editor can change your live
survey, and pushing back is still `import-into-app`, which you have to choose.
If your app has an admin token, set `GT7_ADMIN_TOKEN` before starting the
server — it is deliberately not a field in the page, because a token in a URL
ends up in logs, history and referrers.

### Selecting

Click a point, drag a **lasso** around a group of them, or paint with the
**brush**; hold Shift to invert what any of those does. Selected points can be
relabelled edge/wall/run-off or deleted, with undo.

The brush radius is **metres of road**, not pixels of screen. A screen radius
means the brush grabs a different amount of circuit at every zoom, and at "fit
the whole track" an 18 px brush was an 18 m one — it swallowed both borders and
twelve metres of run-off either side when you meant to touch one edge. Metres
are what the rest of the editor already speaks: the scale bar, the draw
spacing, the dedup grid.

### Telling the sides apart

Colour is already spoken for. A wall is red and paved run-off is purple on
either side of the road, so only a plain `edge` ever falls through to the
side's own blue or pink — which meant that zoomed in on a repair, the two
borders looked the same.

Side is drawn as a **shape** instead: squares on the left, circles on the
right. That survives every kind, and it reads at any zoom where the points are
big enough to see at all. On top of that, while a tool that writes to a
particular side is active, everything on the other side steps back to a
quarter opacity — so there is no doubt which border you are about to add
metres to.

### Moving around

Zoom is measured in notches, not in the browser's `deltaY`. Chrome reports
pixels, Firefox reports lines, and a trackpad reports single digits where a
mouse reports 120 — zooming by the raw number is why the same gesture crawled
in one browser and lurched in another. One notch is 1.25× everywhere, whatever
sent it, and the `+`/`−` buttons and the `+`/`-` keys do exactly one notch too.
A momentum flick is capped at three notches so it cannot cross the whole range
in one event. The metre under the cursor stays under the cursor, panning cannot
lose the circuit off the edge, and a scale bar in metres says what you are
looking at. `0` fits the track; **To selection** zooms to what you have picked.

### Drawing

Four tools create border geometry rather than select it: **Pen** for straight
runs, **Curve** for a spline through the points you click, **Freehand** for
tracing, and **Connect** for bridging a gap. Each lays down records every metre
along the path, taking the heading from the path's own tangent, on the side and
of the kind you chose.

**Connect** is the one for the commonest repair there is. A surveyed border is
not a continuous line — it has holes wherever nobody drove — and bridging one
should not mean tracing it by hand. Click a record either side of the gap and
the editor draws the join, then tells you how many metres it spans.

It never asks which side of the road you are on. A connector can only join a
border to itself, and both of its anchors are surveyed records that already
say which side they are: it reports the side it inherited rather than offering
a choice that has already been made.

The join is not a chord. Every edge record carries `hx`/`hz`, the heading of
the car when that metre was seen, so the bridge is a cubic Hermite using those
headings as its end tangents: it leaves the first record along the road and
arrives at the second along the road, and curves the way the circuit curves.
**Curve** scales that from 0 (the straight line) to 100 % (following the
headings out as far as the gap is wide) — on a 75 m gap whose records point 75°
off the chord, that is the difference between a 75 m line and an 89 m arc. A
heading square across the gap says nothing useful about how to leave it, so
that case falls back to the straight line rather than looping.

Then **push** it: drag on the bridge and it deforms under the cursor, like a
smudge brush, with the reach set in metres. Both ends stay pinned, because they
sit on real surveyed records and moving them would break the join. The two
records the bridge is anchored to are never overwritten — like any drawn point
landing on a surveyed metre, they are skipped.

Both records must be on the same side of the road; joining the left border to
the right would draw a line across the track and file it as one border. The
bridge inherits its side and kind from what it joins, and a record whose kind
was inferred rather than marked becomes a plain edge.

Drawn metres are not evidence, and the format has nowhere to say so. What it
does have is per-source vote counting, so they are filed under a source of
their own — `drawn-` and eight hex digits, which no installation id looks
like. A reviewer reading the diff can see which metres were driven and which
were drawn; a merge treats them as one contributor's view rather than folding
them into anybody's laps; and the bundle's run count goes up by one, because
it really does now contain something that is not a lap. Drawing over a metre
the bundle already holds is skipped rather than replacing it: a surveyed metre
is a measurement and a drawn one is not.

## What this data is not

- **Not a racing line.** These are the edges of the road, not the way round it.
- **Not complete.** Elevation in particular only fills in by re-driving, so
  circuits mapped before the app recorded it sit near 0 % until somebody
  drives them again. The site shows this per track rather than hiding it.
- **Not personal.** The `source` ids stamped on the evidence are random per
  installation. They exist so two people's run counts can be told apart, and
  they identify nobody.

## Licence

Data: [CC0 1.0](LICENSE) — public domain. Tooling and the site:
[MIT](LICENSE-MIT).

`catalog/tracks.json` is factual metadata about Gran Turismo 7 (a Polyphony
Digital / Sony Interactive Entertainment product) and is included for
identification only. This project is not affiliated with either.
