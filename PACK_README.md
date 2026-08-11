# GT7 track data pack

Surveyed border geometry for Gran Turismo 7 circuits, for use with
[GT7 Datalogger](https://github.com/jbhoorasingh/gt7-datalogger).

## Load it into the app

```bash
python import_into_app.py http://gt7.local:8000
```

(Default is `http://localhost:8000`. If the app has an admin token set, pass
`--token <token>` or set `GT7_ADMIN_TOKEN`.)

This goes through the app's import endpoint, which **merges**: your own runs
and this pack's runs are different evidence of the same metres, and both are
kept. Your hand-labelled corners and confirmed layout matches are never
replaced by an import.

**Do not just copy `tracks/*.json` into `data/track-bundles/`** unless you have
nothing surveyed for those circuits — that overwrites your own work instead of
adding to it.

## What is in here

| file | what |
|---|---|
| `tracks/*.json` | one bundle per surveyed configuration (format v4) |
| `index.json` | every GT7 configuration, and which of them this pack covers |
| `tracks.json` | the official GT7 track/layout catalog |
| `MANIFEST.json` | which release this pack is, and what it contains |

Licence: CC0 1.0 (public domain). Source:
https://github.com/jbhoorasingh/gt7-datalogger-track-data
