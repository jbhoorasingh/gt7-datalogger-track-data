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
| `site/` | the inspection page published to GitHub Pages |
| `tools/` | add a bundle, rebuild the index and the signatures, validate everything |

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

## Contributing a track

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

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

## Repairing recorded points

To inspect and correct bad edge records without re-surveying the circuit, run:

```bash
python tools/track_editor.py
```

The local editor can open any bundle in `tracks/` or import another v4 bundle.
It supports visual selection, deletion and edge/wall/run-off relabelling, then
downloads a corrected copy without overwriting the source file.

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
